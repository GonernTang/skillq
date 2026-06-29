"""Core data types for the SkillQ paper method.

Naming is intentionally distinct from the vendored ``skillsvote/`` package
(``skills_vote``). Specifically:

- A :class:`Skill` is a reusable non-parametric memory unit, stored as a
  folder of files (typically ``SKILL.md`` plus optional ``scripts/``).
- A :class:`Qlib` is the bounded library $M_t$ of size $B_t \\le B_{\\max}$.

The 2026-06-25 dead-code purge removed :class:`Verdict` (Eq. 6 information-
isolated verifier) and :class:`RetrievalResult` (paper Eq. 4 TwoStageRanker)
because the runtime path no longer executes either algorithm.

Step 1 of the 2026-06-26 refactor moved this module from
``skillq.shared.types`` to ``skillq.shared.types``. The old
import path is kept as a thin re-export shim until Step 7.
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
    by :class:`~skillq.shared.q_table.LibManager.maintain`.
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