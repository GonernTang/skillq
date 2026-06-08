"""Core data types for the LQRL paper method (mg/method).

Naming is intentionally distinct from both the upstream ``lqrl`` package
(``skills_vote``) and the ``implementation_guide`` skeleton. Specifically:

- A :class:`Skill` is a reusable non-parametric memory unit, stored as a
  folder of files (typically ``SKILL.md`` plus optional ``scripts/``).
- A :class:`Qlib` is the bounded library $M_t$ of size $B_t \\le B_{\\max}$.
- A :class:`Verdict` is the result of the informationally isolated verifier
  on a (old, new) skill content delta; the scalar ``r_learning`` is the
  *learning reward* used by :class:`~mg.method.layered_q.BetaLayeredQ`.
- A :class:`RetrievalResult` is one ranked skill returned by
  :class:`~mg.method.retrieval.TwoStageRanker`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Skill:
    """A reusable skill — body is typically the contents of ``SKILL.md``."""

    skill_id: str
    body: str = ""
    n_retrievals: int = 0
    n_uses: int = 0
    n_success: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Qlib:
    """The bounded library $M_t$ of skills (Eq. 2 of the paper).

    Invariant: :attr:`size` $\\le$ :attr:`b_max` at all times. Enforced
    by :class:`~mg.method.library.LibManager.maintain`.
    """

    b_max: int = 50
    skills: dict[str, Skill] = field(default_factory=dict)

    @property
    def size(self) -> int:
        """Current library size $B_t$."""
        return len(self.skills)

    def __contains__(self, skill_id: str) -> bool:
        return skill_id in self.skills

    def __iter__(self):
        return iter(self.skills.values())

    def add(self, skill: Skill) -> None:
        self.skills[skill.skill_id] = skill

    def remove(self, skill_id: str) -> None:
        self.skills.pop(skill_id, None)

    def get(self, skill_id: str) -> Skill | None:
        return self.skills.get(skill_id)

    def replace(self, skill: Skill) -> None:
        """In-place update of a skill's body / metadata, preserving identity."""
        self.skills[skill.skill_id] = skill


@dataclass
class Verdict:
    """Informationally isolated verifier verdict on a (old, new) content delta.

    ``r_learning`` is the *learning reward* used in Eq. 6 of the paper:

        r_learning = clamp(new_score - old_score, -1, 1)
    """

    old_score: float
    new_score: float
    improved: bool
    rationale: str

    @property
    def r_learning(self) -> float:
        return max(-1.0, min(1.0, self.new_score - self.old_score))


@dataclass
class RetrievalResult:
    """One ranked skill returned by :class:`TwoStageRanker`."""

    skill: Skill
    score: float
    phase_a_rank: int
    phase_b_rank: int
