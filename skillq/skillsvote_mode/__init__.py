"""paper.skillsvote_mode — pass-through to upstream SkillsVote baseline.

This package contains no implementation code. It exists so that:

- The ``paper skillsvote ...`` CLI surface mirrors ``paper paper ...``.
- The boundary between the SkillsVote baseline and the SkillQ paper
  method is explicit at the package level.

All agent / hook / prompt / evolve logic is imported from
``skills_vote.*`` (the upstream SkillsVote package).
"""

from skillq.skillsvote_mode.entrypoint import main

__all__ = ["main"]
