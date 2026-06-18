"""Q-driven library management (Sec. 3.3 of the paper, global-Q refactor).

**Simplification (2026-06-18):** admission, stale-queue, low-Q-queue,
deprecation list, rejuvenate path are all gone. The single rule is
hard-bounded eviction: when ``len(library) > b_max``, the lowest-Q
skill is removed. Per-skill call counts (``update_count``) and
per-skill subtask-success counts (``probation_count``) are kept as
telemetry but never influence any decision.

This module is the mg-side rewrite of
``skillsvote/src/skills_vote/library.py:LibraryManager``, renamed to
``LibManager``. Q-table is keyed by ``skill_id`` only (global-Q
refactor): one Q per skill that the paper's Eq. 4 retrieval reads.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Optional

from skillq.method.types import Qlib


@dataclass
class LibManager:
    """Q-value-driven library management (Sec. 3.3, Layer 3).

    Q-table is keyed by ``skill_id`` (global, per-skill). The only
    eviction rule is hard-bounded: when ``len(library) > b_max`` the
    lowest-Q skill is removed.

    Telemetry fields (read for observability, never consumed by any
    decision):

    - ``update_count``: per-skill call count (``+= 1`` every
      :meth:`update_q`).
    - ``probation_count``: per-skill subtask-success count (same
      increment as ``update_count``; kept distinct so future logic
      can split the two without re-introducing a write path).
    """

    b_max: int
    # Bug 5: optional bilateral Q-value clip. Default (None, None)
    # = no clip = existing behaviour preserved. See
    # ``MethodConfig.q_clip_floor`` / ``q_clip_ceiling`` for the
    # user-facing knobs.
    q_clip_floor: Optional[float] = None
    q_clip_ceiling: Optional[float] = None

    # Q-table: skill_id -> Q-value (single global value per skill)
    q_table: Dict[str, float] = field(default_factory=dict)
    # Telemetry: skill_id -> update count
    update_count: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    # Telemetry: skill_id -> subtask-success count (one per update_q)
    probation_count: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # ------------------------------------------------------------------
    # Q-table mutation
    # ------------------------------------------------------------------
    def update_q(self, skill_id: str, delta: float) -> None:
        """Apply a Q-value increment (or decrement) to one skill.

        If ``q_clip_floor`` / ``q_clip_ceiling`` are set, the resulting
        Q is clipped to ``[q_clip_floor, q_clip_ceiling]`` (Bug 5).
        Default None: no clip = existing behaviour preserved.
        """
        new_q = self.q_table.get(skill_id, 0.0) + delta
        if self.q_clip_floor is not None:
            new_q = max(self.q_clip_floor, new_q)
        if self.q_clip_ceiling is not None:
            new_q = min(self.q_clip_ceiling, new_q)
        self.q_table[skill_id] = new_q
        self.update_count[skill_id] += 1
        # Telemetry: same increment that feeds update_count, kept as a
        # separate counter so a future per-skill success metric can be
        # distinguished from raw call count without re-introducing a
        # write path.
        self.probation_count[skill_id] += 1

    def set_q(self, skill_id: str, q_value: float) -> None:
        """Set the Q value of a skill directly (used for seed/initial).

        If ``q_clip_floor`` / ``q_clip_ceiling`` are set, the value is
        clipped to ``[q_clip_floor, q_clip_ceiling]`` (Bug 5).
        Default None: no clip = existing behaviour preserved.
        """
        if self.q_clip_floor is not None:
            q_value = max(self.q_clip_floor, q_value)
        if self.q_clip_ceiling is not None:
            q_value = min(self.q_clip_ceiling, q_value)
        self.q_table[skill_id] = q_value

    def q_for(self, skill_id: str) -> float:
        """Public Q-table getter used by retrieval glue and the bridge."""
        return self.q_table.get(skill_id, 0.0)

    # ------------------------------------------------------------------
    # Maintenance pass
    # ------------------------------------------------------------------
    def maintain(self, library: Qlib, current_step: int) -> list[str]:
        """Enforce ``len(library) <= b_max`` by evicting the lowest-Q
        skill until the library fits. Returns ``["evict:<skill_id>", ...]``
        event strings for logging.
        """
        events: list[str] = []
        while library.size > self.b_max:
            victim = self._pick_eviction_victim(library)
            if victim is None:
                break
            library.remove(victim)
            events.append(f"evict:{victim}")
        return events

    def _pick_eviction_victim(self, library: Qlib) -> str | None:
        """Return the skill_id with the lowest Q in ``library``."""
        if library.size == 0:
            return None
        return min(library, key=lambda s: self.q_for(s.skill_id)).skill_id


# ---------------------------------------------------------------------------
# Theoretical helpers (used in experiments; Theorems 1 + 2 of the paper).
# ---------------------------------------------------------------------------
def forgetting_rate_upper_bound(
    alpha: float,
    var_task: float,
    q_max: float,
    q_min: float,
) -> float:
    """Upper bound on the forgetting rate from Theorem 2."""
    denom = (q_max - q_min) ** 2
    if denom <= 0:
        return float("inf")
    return alpha * var_task / ((2.0 - alpha) * denom)
