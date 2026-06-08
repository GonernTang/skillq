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
