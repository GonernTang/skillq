"""mg — branch-style entrypoint exposing two run modes:

- ``mg.skillsvote_mode.entrypoint.main`` — pass-through to the upstream
  ``skills_vote`` package (the **SkillsVote baseline**, the comparison
  method for the LQRL paper). ``mg skillsvote run -c X`` runs the
  baseline verbatim. No implementation code in
  ``mg.skillsvote_mode``.
- ``mg.paper_mode.entrypoint.main`` — runs the **LQRL paper's**
  four-layer method (TwoStageRanker → BetaLayeredQ → LibManager →
  NearMissRefiner) via a single ``on_trial_ended`` hook. ``mg paper
  run -c X`` runs the LQRL method.

The :mod:`mg.cli` module dispatches between them.
"""

from mg.paper_mode.entrypoint import main as paper_main
from mg.skillsvote_mode.entrypoint import main as skillsvote_main

__all__ = ["skillsvote_main", "paper_main"]
__version__ = "0.1.0"
