"""Persistent state for the SkillQ paper method (global-Q refactor).

The :class:`QlibState` serialises everything the four-layer method needs
to survive a Job resume:

- the bounded :class:`~paper.method.types.Qlib` (skill bodies, n_retrievals,
  n_uses, n_success, metadata);
- the :class:`~paper.method.library.LibManager` **global** Q-table and
  per-skill probation / eviction queues (no per-intent dimension in the
  global-Q refactor);
- the current :attr:`step` counter used to gate staleness;
- (optional, debug) a ``sub_task_log`` list of per-trial skill-call verdicts.

The state file lives at a path that does **not** collide with the
upstream ``lqrl`` package's ``skills_vote_evolve_state.json`` — by
default we write to ``<library_root>/.state/method_state.json``.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from skillq.method.library import LibManager
from skillq.method.types import Qlib, Skill


@dataclass
class QlibState:
    """Persistent serialisation of the four-layer method's working set.

    State file JSON keys (post global-Q refactor):
        step:                 int
        q_table:              [[skill_id: str, q: float], ...]   ← global
        probation:            {avg_q: {skill_id: float}, count: {skill_id: int}}
        deprecation_list:     [skill_id, ...]
        evict_candidates:     [skill_id, ...]
        last_retrieval_step:  {skill_id: int}
        library:              {b_max: int, skills: {skill_id: {...}}}
        seed_initial_q:       float
        sub_task_log:         [debug entries — only present when
                               debug_keep_subtask_log=True is set on
                               the calling bridge]
        library_root:         str (path, optional)
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
        sub_task_log: list[dict[str, Any]] | None = None,
        debug_keep_subtask_log: bool = True,
    ) -> None:
        """Persist the library, Q-table, and step counter to JSON."""
        payload: dict[str, Any] = {
            "step": self.step,
            "q_table": [
                [skill_id, q] for skill_id, q in mgr.q_table.items()
            ],
            "probation": {
                "avg_q": dict(mgr.probation_avg_q),
                "count": dict(mgr.probation_count),
            },
            "deprecation_list": list(mgr.deprecation_list),
            "evict_candidates": list(mgr.evict_candidates),
            "last_retrieval_step": dict(mgr.last_retrieval_step),
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
        if debug_keep_subtask_log and sub_task_log is not None:
            payload["sub_task_log"] = sub_task_log
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

        # Probation bookkeeping
        prob = data.get("probation", {})
        mgr.probation_avg_q = {k: float(v) for k, v in prob.get("avg_q", {}).items()}
        # probation_count may be {sid: int} (new) or {sid: {intent: int}} (legacy).
        # Use defaultdict(int) so :meth:`LibManager.update_q` can
        # implicitly insert a 0 the first time a skill gets updated
        # (the dataclass default is also defaultdict(int)).
        mgr.probation_count = defaultdict(int)
        raw_count = prob.get("count", {})
        for sid, val in raw_count.items():
            if isinstance(val, dict):
                # legacy per-intent count — sum across intents
                mgr.probation_count[sid] = sum(int(n) for n in val.values())
            else:
                mgr.probation_count[sid] = int(val)

        mgr.deprecation_list = list(data.get("deprecation_list", []))
        mgr.evict_candidates = list(data.get("evict_candidates", []))
        mgr.last_retrieval_step = {
            k: int(v) for k, v in data.get("last_retrieval_step", {}).items()
        }

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
