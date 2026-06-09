"""mg.skillsvote_mode — pass-through to upstream SkillsVote baseline.

This package contains no implementation code. It exists so that:

- The ``mg skillsvote ...`` CLI surface mirrors ``mg paper ...``.
- The boundary between the SkillsVote baseline and the LQRL paper
  method is explicit at the package level.

All agent / hook / prompt / evolve logic is imported from
``skills_vote.*`` (the upstream SkillsVote package).
"""

from mg.skillsvote_mode.entrypoint import main

__all__ = ["main"]
