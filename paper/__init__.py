"""mg — branch-style entrypoint exposing two run modes:

- ``paper.skillsvote_mode.entrypoint.main`` — pass-through to the upstream
  ``skills_vote`` package (the **SkillsVote baseline**, the comparison
  method for the LQRL paper). ``paper skillsvote run -c X`` runs the
  baseline verbatim. No implementation code in
  ``paper.skillsvote_mode``.
- ``paper.paper_mode.entrypoint.main`` — runs the **LQRL paper's**
  four-layer method (TwoStageRanker → BetaLayeredQ → LibManager →
  NearMissRefiner) via a single ``on_trial_ended`` hook. ``paper paper
  run -c X`` runs the LQRL method.

The :mod:`paper.cli` module dispatches between them.
"""

from paper.paper_mode.entrypoint import main as paper_main
from paper.skillsvote_mode.entrypoint import main as skillsvote_main

__all__ = ["skillsvote_main", "paper_main"]
__version__ = "0.1.0"
