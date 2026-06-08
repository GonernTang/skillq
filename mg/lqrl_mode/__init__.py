"""mg.lqrl_mode — pass-through to upstream lqrl.

This package contains no implementation code. It exists so that:

- The ``mg lqrl ...`` CLI surface mirrors ``mg paper ...``.
- The boundary between the lqrl lifecycle and the paper method is
  explicit at the package level.

All agent / hook / prompt / evolve logic is imported from
``skills_vote.*`` (the upstream lqrl package).
"""

from mg.lqrl_mode.entrypoint import main

__all__ = ["main"]
