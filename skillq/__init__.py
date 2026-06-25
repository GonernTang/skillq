"""mg — branch-style entrypoint exposing two run modes:

- ``paper.skillsvote_mode.entrypoint.main`` — pass-through to the upstream
  ``skills_vote`` package (the **SkillsVote baseline**, the comparison
  method for the SkillQ paper). ``paper skillsvote run -c X`` runs the
  baseline verbatim. No implementation code in
  ``paper.skillsvote_mode``.
- ``skillq.skillq_runtime.entrypoint.main`` — runs the **SkillQ paper's**
  four-layer method (TwoStageRanker → BetaLayeredQ → LibManager →
  EditRefiner) via a single ``on_trial_ended`` hook. ``paper paper
  run -c X`` runs the SkillQ method.

The :mod:`paper.cli` module dispatches between them.
"""

# Importing the resolver module registers the ``${now:...}`` and
# ``${abspath:...}`` OmegaConf resolvers that the existing paper
# configs depend on. Must come before any submodule that may load a
# JobConfig YAML.
from skillq import _resolvers  # noqa: F401  (side-effect import)

from skillq.skillq_runtime.entrypoint import main as paper_main
from skillq.skillsvote_mode.entrypoint import main as skillsvote_main

__all__ = ["skillsvote_main", "paper_main"]
__version__ = "0.1.0"
