"""Persistent state for the SkillQ paper method (global-Q refactor).

The :class:`QlibState` serialises everything the four-layer method needs
to survive a Job resume:

- the bounded :class:`~paper.method.types.Qlib` (skill bodies, n_retrievals,
  n_uses, n_success, metadata);
- the :class:`~paper.method.library.LibManager` **global** Q-table and
  per-skill probation / eviction queues (no per-intent dimension in the
  global-Q refactor);
- the current :attr:`step` counter used to gate staleness;
The state file lives at a path that does **not** collide with the
upstream ``lqrl`` package's ``skills_vote_evolve_state.json`` — by
default we write to ``<library_root>/.state/method_state.json``.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from skillq.method.library import LibManager
from skillq.method.types import Qlib, Skill

# YAML frontmatter: `--- \n key: value \n ... \n--- \n body`
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass
class QlibState:
    """Persistent serialisation of the four-layer method's working set.

    State file JSON keys (post-simplification 2026-06-18):
        step:                 int
        q_table:              [[skill_id: str, q: float], ...]   ← global
        library:              {b_max: int, skills: {skill_id: {...}}}
        seed_initial_q:       float
        library_root:         str (path, optional)

    Backward-compat note: older state files written by the
    admission/eviction-aware code path may also carry
    ``probation``, ``deprecation_list``, ``evict_candidates``, and
    ``last_retrieval_step`` keys. ``load_into`` silently ignores them
    (no consumer in the simplified LibManager); the legacy
    ``{sid: {intent: int}}`` probation-count shape is also accepted for
    backward compat.
    """

    state_path: Path
    step: int = 0
    # Set to True once the first ``save()`` has been called; saves us
    # from accidentally clobbering a state file we did not own.
    _written: bool = field(default=False, init=False, repr=False)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def save(
        self,
        lib: Qlib,
        mgr: LibManager,
        lib_root: Path | None = None,
        seed_initial_q: float = 0.5,
    ) -> None:
        """Persist the library, Q-table, and step counter to JSON."""
        payload: dict[str, Any] = {
            "step": self.step,
            "q_table": [
                [skill_id, q] for skill_id, q in mgr.q_table.items()
            ],
            "library": {
                "b_max": lib.b_max,
                "skills": {
                    sid: _skill_to_dict(skill) for sid, skill in lib.skills.items()
                },
            },
            "seed_initial_q": float(seed_initial_q),
        }
        if lib_root is not None:
            payload["library_root"] = str(lib_root)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._written = True

    def load_into(
        self,
        lib: Qlib,
        mgr: LibManager,
        lib_root: Path | None = None,
    ) -> bool:
        """Load the state file (if it exists) into ``lib`` and ``mgr``.

        Returns ``True`` if a state file was found and loaded; ``False``
        otherwise (in which case the in-memory state is unchanged).

        Backwards compatible with the old ``(intent, skill_id, q)`` row
        format from the per-intent-Q refactor; any 3-element rows are
        silently coerced to the new global-Q 2-element form by keeping
        the q value (per-skill; later rows with the same skill_id
        overwrite).
        """
        if not self.state_path.exists():
            return False
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.step = int(data.get("step", 0))

        # Q-table — accept both new 2-tuple and legacy 3-tuple format.
        mgr.q_table.clear()
        for row in data.get("q_table", []):
            if len(row) == 2:
                skill_id, q = str(row[0]), float(row[1])
            elif len(row) == 3:
                # Legacy: [intent, skill_id, q] — drop the intent dim
                _intent, skill_id, q = row[0], str(row[1]), float(row[2])
            else:
                continue
            mgr.q_table[skill_id] = q

        # Probation bookkeeping (telemetry only; no decision consumer).
        # probation_count may be {sid: int} (new) or {sid: {intent: int}}
        # (legacy). Use defaultdict(int) so :meth:`LibManager.update_q`
        # can implicitly insert a 0 the first time a skill gets updated.
        # Older state files may carry a "probation" envelope; its
        # "count" subkey is accepted for backward compat.
        mgr.probation_count = defaultdict(int)
        prob = data.get("probation", {})
        raw_count = prob.get("count", {}) if isinstance(prob, dict) else {}
        for sid, val in raw_count.items():
            if isinstance(val, dict):
                # legacy per-intent count — sum across intents
                mgr.probation_count[sid] = sum(int(n) for n in val.values())
            else:
                mgr.probation_count[sid] = int(val)

        # Library
        lib_data = data.get("library", {})
        lib.b_max = int(lib_data.get("b_max", lib.b_max))
        lib.skills.clear()
        for sid, raw in lib_data.get("skills", {}).items():
            lib.add(_skill_from_dict(sid, raw))

        # Seed skills: pre-populate Q=seed_initial_q for any skill that
        # has NO q_table entry yet. The seed value is configurable via
        # the MethodConfig.seed_initial_q field (default 0.5). This is
        # the "optimistic prior" pattern; resume from an existing state
        # file is idempotent (we only fill missing entries).
        seed_initial_q = float(data.get("seed_initial_q", 0.5))
        if seed_initial_q != 0.0:
            for sid in lib.skills:
                if sid not in mgr.q_table:
                    mgr.q_table[sid] = seed_initial_q

        self._written = True
        return True

    # ------------------------------------------------------------------
    # Seed-from-disk (Plan D fix)
    # ------------------------------------------------------------------
    @staticmethod
    def scan_seed_dir(
        seed_dir: Path,
        *,
        q_initial: float = 0.5,
    ) -> tuple[dict[str, dict[str, Any]], list[list[float]]]:
        """Walk ``seed_dir`` and build a (skills, q_table) pair from
        every ``<seed_dir>/<skill_name>/SKILL.md`` it finds.

        This is the Plan D entry point: when the paper method boots and
        ``method_state.json`` does not yet exist (or its
        ``library.skills`` is empty), the bridge calls this to populate
        the in-memory lib from the on-disk seed library. The seed
        directory is the same one the smoke config bind-mounts at
        ``/skills`` inside the container, so the agent sees the same
        32 skills the paper method's library knows about.

        Parameters
        ----------
        seed_dir : Path
            Root directory; each immediate subdir containing a
            ``SKILL.md`` is treated as one skill. The skill_id comes
            from the frontmatter ``name:`` field if present, else the
            directory name. Subdirs without a SKILL.md are silently
            skipped (so the seed-stub pattern still works).
        q_initial : float
            The Q value to give each freshly-seeded skill. Matches
            :data:`MethodConfig.seed_initial_q`.

        Returns
        -------
        (skills, q_table) : tuple
            ``skills`` is a dict ready to drop into
            ``state["library"]["skills"]``; ``q_table`` is a list of
            ``[skill_id, q]`` rows ready for ``state["q_table"]``.

            **Skill-id policy:** each skill's primary id is the
            DIRECTORY name (``skill_dir.name``), not the YAML
            frontmatter ``name:`` field. The agent invokes
            ``Skill("<name>")`` and the directory name is what Claude
            Code's Skill tool registers (the init event's
            ``skills: [...]`` list is keyed by directory name —
            see ``affaan-m-security-review`` not the frontmatter
            ``security-review``). Using the frontmatter name here
            would silently drop the second/later dirs that share
            a frontmatter name and leave the agent unable to find
            any of the skills it can see — exactly the bug the
            earlier version of this code caused. Dedup still
            applies but on directory names, which are unique by
            filesystem invariant.
        """
        if not isinstance(seed_dir, Path):
            seed_dir = Path(seed_dir)
        if not seed_dir.is_dir():
            return {}, []

        skills: dict[str, dict[str, Any]] = {}
        q_table: list[list[float]] = []

        for skill_dir in sorted(p for p in seed_dir.iterdir() if p.is_dir()):
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                continue
            try:
                body = skill_md.read_text(encoding="utf-8")
            except OSError:
                continue
            # Directory name = primary id (matches what Claude Code's
            # Skill tool registers in its init event). Frontmatter
            # name is preserved in the body's frontmatter block and
            # accessible via the agent reading the file.
            skill_id = skill_dir.name
            skills[skill_id] = {
                "body": body,
                "n_retrievals": 0,
                "n_uses": 0,
                "n_success": 0,
                "metadata": {
                    "source": "seed_dir",
                    "seed_dir": skill_dir.name,
                },
            }
            q_table.append([skill_id, float(q_initial)])
        return skills, q_table

    def ensure_seeded(
        self,
        lib: Qlib,
        mgr: LibManager,
        seed_dir: Path | None,
        *,
        seed_initial_q: float = 0.5,
    ) -> bool:
        """If ``lib.skills`` is empty and ``seed_dir`` exists, populate
        the in-memory lib + Q-table from disk and persist to
        ``self.state_path``.

        Called by the bridge on first run of a Job (when no prior
        ``method_state.json`` exists). Returns ``True`` if seeding
        happened, ``False`` otherwise (state file already had skills,
        or ``seed_dir`` was not set / not a directory).

        Idempotent: if the in-memory lib already has skills, this is a
        no-op even when called multiple times.
        """
        if lib.skills:
            return False
        if seed_dir is None:
            return False
        if not isinstance(seed_dir, Path):
            seed_dir = Path(seed_dir)
        if not seed_dir.is_dir():
            return False
        skills, q_table = self.scan_seed_dir(
            seed_dir, q_initial=seed_initial_q
        )
        if not skills:
            return False
        for sid, raw in skills.items():
            lib.add(_skill_from_dict(sid, raw))
        for row in q_table:
            mgr.q_table[row[0]] = float(row[1])
        # Persist so a subsequent ``load_into`` sees the same library
        # and we don't re-seed on every on_trial_started.
        self.save(
            lib=lib,
            mgr=mgr,
            lib_root=None,
            seed_initial_q=seed_initial_q,
        )
        return True


# ---------------------------------------------------------------------------
# Skill (de)serialisation helpers
# ---------------------------------------------------------------------------
def _skill_to_dict(skill: Skill) -> dict[str, Any]:
    return {
        "body": skill.body,
        "n_retrievals": skill.n_retrievals,
        "n_uses": skill.n_uses,
        "n_success": skill.n_success,
        "metadata": skill.metadata,
    }


def _skill_from_dict(skill_id: str, raw: dict[str, Any]) -> Skill:
    return Skill(
        skill_id=skill_id,
        body=str(raw.get("body", "")),
        n_retrievals=int(raw.get("n_retrievals", 0)),
        n_uses=int(raw.get("n_uses", 0)),
        n_success=int(raw.get("n_success", 0)),
        metadata=dict(raw.get("metadata", {})),
    )


def _frontmatter_name(body: str) -> str:
    """Extract ``name:`` from a SKILL.md's YAML frontmatter, else ''.

    Matches the same regex the AgenticSearchWriter's
    ``_read_existing_body`` uses, so a skill that the writer reads
    back gets the same ``skill_id`` it would have when seeded from
    the original disk file. This keeps the paper method's library
    and the agent's Skill tool aligned on the same identifiers.
    """
    m = _FRONTMATTER_RE.match(body)
    if not m:
        return ""
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        if k.strip() == "name":
            v = v.strip().strip('"').strip("'").strip()
            return v
    return ""
