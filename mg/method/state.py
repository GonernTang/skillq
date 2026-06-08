"""Persistent state for the LQRL paper method.

The :class:`QlibState` serialises everything the four-layer method needs
to survive a Job resume:

- the bounded :class:`~mg.method.types.Qlib` (skill bodies, n_retrievals,
  n_uses, n_success, metadata);
- the :class:`~mg.method.library.LibManager` Q-table and probation /
  eviction queues;
- the current :attr:`step` counter used to gate staleness.

The state file lives at a path that does **not** collide with the
upstream ``lqrl`` package's ``skills_vote_evolve_state.json`` — by
default we write to ``<library_root>/.state/method_state.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mg.method.library import LibManager
from mg.method.types import Qlib, Skill


@dataclass
class QlibState:
    """Persistent serialisation of the four-layer method's working set.

    The state file format is JSON with three top-level keys: ``step``,
    ``q_table``, ``probation``, and ``library``. Backwards-compatible
    loaders should default missing fields to the right zero values.
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
        payload = {
            "step": self.step,
            "q_table": [
                [intent, skill_id, q]
                for (intent, skill_id), q in mgr.q_table.items()
            ],
            "probation": {
                "avg_q": dict(mgr.probation_avg_q),
                "count": {
                    sid: {str(intent): n for intent, n in counts.items()}
                    for sid, counts in mgr.probation_count.items()
                },
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
        """
        if not self.state_path.exists():
            return False
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.step = int(data.get("step", 0))

        # Q-table
        mgr.q_table.clear()
        for row in data.get("q_table", []):
            intent, skill_id, q = int(row[0]), str(row[1]), float(row[2])
            mgr.q_table[(intent, skill_id)] = q

        # Probation bookkeeping
        prob = data.get("probation", {})
        mgr.probation_avg_q = {k: float(v) for k, v in prob.get("avg_q", {}).items()}
        mgr.probation_count = {
            sid: {int(intent): int(n) for intent, n in counts.items()}
            for sid, counts in prob.get("count", {}).items()
        }

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

        # Seed skills: pre-populate a single Q-table entry at
        # intent_hash=0 with Q=0.5 so they behave identically to
        # freshly extracted skills on first retrieve. This is a
        # minimal "optimistic prior" — the Q-table is still keyed
        # by (intent_hash, skill_id) and grows naturally per-intent
        # once the skill is actually used.
        #
        # The (intent_hash=0) key is a sentinel — bridge.py will
        # use a *real* intent_hash on first retrieve and the
        # natural Q update will overwrite / augment this entry.
        # We only do this for skills that have *no* Q-table entry
        # yet, so resume from an existing state file is not
        # affected.
        seed_initial_q = float(data.get("seed_initial_q", 0.5))
        if seed_initial_q != 0.0:
            for sid in lib.skills:
                # Only seed skills that have NO Q-table entry yet
                # (don't overwrite an existing Q — resume must be
                # idempotent).
                if not any(
                    skill_id == sid for (_intent, skill_id) in mgr.q_table.keys()
                ):
                    mgr.q_table[(0, sid)] = seed_initial_q

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
