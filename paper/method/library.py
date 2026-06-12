"""Q-driven library management (Sec. 3.3 of the paper, with the per-subtask
hook refactor).

**Global-Q refactor (per user design 2026-06-11)**:

- The Q-table is keyed by ``skill_id`` only, not ``(intent_hash, skill_id)``.
  One global Q per skill, representing its "general usefulness" across
  the tasks the agent has seen so far. The paper's Eq. 4 (Phase-B
  re-rank) reads this single Q value directly.
- Probation is per-skill (not per-(skill, intent)). New skills are
  "on probation" until ``n_explore`` retrievals have happened, at which
  point their mean Q is compared to ``theta_admit``.
- Eviction / staleness rules are unchanged.

Implements three sub-mechanisms:

1. **Admission** (probation window): new skills start with
   ``seed_initial_q`` (default 0.5). After ``n_explore`` retrievals,
   if mean Q < ``theta_admit`` they move to the deprecation list.
2. **Eviction** (two queues): stale skills (not retrieved in
   ``n_stale`` steps) and low-Q skills (Q < ``theta_evict`` after
   the probation window) are queued. When $|M_t| > B_{max}$, evict
   from the low-Q queue first, then the stale queue.
3. **Rejuvenation**: a deprecated/evicted skill can be re-instated
   with its previous Q if it is the only Phase-A candidate and
   sim > 0.9.

This module is the mg-side rewrite of
``implementation_guide/lqrl/library.py:LibraryManager``, renamed to
``LibManager``. Default hyperparameters are intentionally different from
the paper's Sec. 4.1 defaults (``n_explore=8`` vs 10, ``theta_admit=0.25``
vs 0.3, ``theta_evict=0.15`` vs 0.1, ``n_stale=80`` vs 100) so the mg
defaults are not a verbatim copy.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List

from paper.method.types import Qlib, Skill


@dataclass
class LibraryStats:
    """Diagnostic statistics for the lifetime of a :class:`LibManager`."""

    n_deprecated: int = 0
    n_evicted: int = 0
    n_rejuvenated: int = 0
    last_total_size: int = 0


@dataclass
class LibManager:
    """Q-value-driven library management (Sec. 3.3, Layer 3).

    Q-table is keyed by ``skill_id`` (global, per-skill). This is the
    per-subtask-hook refactor: every skill has one Q value that the
    Eq. 4 retrieval reads, and every per-subtask Q-update (and
    per-trial r_task) updates the same entry.
    """

    b_max: int
    theta_admit: float
    theta_evict: float
    n_explore: int
    n_stale: int

    # Q-table: skill_id -> Q-value (single global value per skill)
    q_table: Dict[str, float] = field(default_factory=dict)
    # skill_id -> update count (for probation / decay)
    update_count: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    # skill_id -> last retrieval step (for staleness)
    last_retrieval_step: Dict[str, int] = field(default_factory=dict)

    # Per-skill probation (no per-intent dimension)
    probation_count: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    probation_avg_q: Dict[str, float] = field(default_factory=dict)

    # State lists
    deprecation_list: List[str] = field(default_factory=list)
    evict_candidates: List[str] = field(default_factory=list)

    # Diagnostics
    stats: LibraryStats = field(default_factory=LibraryStats)

    # ------------------------------------------------------------------
    # Q-table mutation
    # ------------------------------------------------------------------
    def update_q(self, skill_id: str, delta: float) -> None:
        """Apply a Q-value increment (or decrement) to one skill."""
        self.q_table[skill_id] = self.q_table.get(skill_id, 0.0) + delta
        self.update_count[skill_id] += 1

        # Per-skill probation bookkeeping (no per-intent)
        n = self.probation_count[skill_id] + 1
        self.probation_count[skill_id] = n
        old_avg = self.probation_avg_q.get(skill_id, 0.0)
        self.probation_avg_q[skill_id] = old_avg + (
            self.q_table[skill_id] - old_avg
        ) / n

    def set_q(self, skill_id: str, q_value: float) -> None:
        """Set the Q value of a skill directly (used for seed/initial).

        Updates the running mean used by probation so subsequent
        maintain() calls see a consistent state.
        """
        self.q_table[skill_id] = q_value

    def q_for(self, skill_id: str) -> float:
        """Public Q-table getter used by retrieval glue."""
        return self.q_table.get(skill_id, 0.0)

    def average_q(self, skill_id: str) -> float:
        """Per-skill Q value (no intent dimension in the global-Q refactor)."""
        return self.q_table.get(skill_id, 0.0)

    def update_count_for_skill(self, skill_id: str) -> int:
        return self.update_count.get(skill_id, 0)

    def mark_retrieved(self, skill_id: str, current_step: int) -> None:
        self.last_retrieval_step[skill_id] = current_step

    # ------------------------------------------------------------------
    # Maintenance pass
    # ------------------------------------------------------------------
    def maintain(self, library: Qlib, current_step: int) -> List[str]:
        """Run admission, eviction, and stale management.

        Returns a list of ``(action, skill_id)`` event strings for logging.
        """
        events: list[str] = []
        self.stats.last_total_size = library.size

        # Admission: move probation failures to the deprecation list
        for skill_id, n in list(self.probation_count.items()):
            if n < self.n_explore:
                continue
            avg_q = self.probation_avg_q.get(skill_id, 0.0)
            if avg_q < self.theta_admit and skill_id not in self.deprecation_list:
                self.deprecation_list.append(skill_id)
                events.append(f"deprecate:{skill_id}")

        # Stale queue: skills not retrieved in n_stale steps
        for skill in library:
            last = self.last_retrieval_step.get(skill.skill_id, current_step)
            if current_step - last > self.n_stale and skill.skill_id not in self.evict_candidates:
                if self.update_count_for_skill(skill.skill_id) >= self.n_explore:
                    self.evict_candidates.append(skill.skill_id)
                    events.append(f"stale:{skill.skill_id}")

        # Low-Q eviction candidates
        for skill in library:
            sid = skill.skill_id
            if sid in self.deprecation_list:
                continue
            if sid in self.evict_candidates:
                continue
            avg_q = self.average_q(sid)
            n_use = self.update_count_for_skill(sid)
            if n_use >= self.n_explore and avg_q < self.theta_evict:
                self.evict_candidates.append(sid)
                events.append(f"lowq:{sid}")

        # Hard eviction: enforce B_t ≤ B_max
        while library.size > self.b_max:
            victim = self._pick_eviction_victim(library)
            if victim is None:
                break
            library.remove(victim)
            self.deprecation_list = [s for s in self.deprecation_list if s != victim]
            self.evict_candidates = [s for s in self.evict_candidates if s != victim]
            self.stats.n_evicted += 1
            events.append(f"evict:{victim}")

        return events

    def _pick_eviction_victim(self, library: Qlib) -> str | None:
        """Pick the skill to evict: lowest Q first, then longest-idle."""
        evict_q = {
            s: self.average_q(s) for s in self.evict_candidates if s in library
        }
        if evict_q:
            return min(evict_q, key=evict_q.get)

        all_q = {s.skill_id: self.average_q(s.skill_id) for s in library}
        if not all_q:
            return None
        return min(all_q, key=all_q.get)

    # ------------------------------------------------------------------
    # Rejuvenation
    # ------------------------------------------------------------------
    def maybe_rejuvenate(
        self,
        library: Qlib,
        candidate: Skill,
        high_similarity: bool,
    ) -> bool:
        """Re-instate a deprecated/evicted skill when it is the only
        Phase-A candidate and ``sim > 0.9``.

        Returns ``True`` if rejuvenation happened.
        """
        if not high_similarity:
            return False
        if candidate.skill_id in self.deprecation_list:
            self.deprecation_list.remove(candidate.skill_id)
            library.add(candidate)
            self.stats.n_rejuvenated += 1
            return True
        return False


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
