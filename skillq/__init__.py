"""mg — branch-style entrypoint exposing two run modes:

- ``paper.skillsvote_mode.entrypoint.main`` — pass-through to the upstream
  ``skills_vote`` package (the **SkillsVote baseline**, the comparison
  method for the SkillQ paper). ``paper skillsvote run -c X`` runs the
  baseline verbatim. No implementation code in
  ``paper.skillsvote_mode``.
- ``skillq.runtime.entrypoint.main`` — runs the **SkillQ paper's**
  four-layer method (L1 retrieval + L2 Q-learning + L3 Lib/Edit + L4
  extraction) via the new closure-free 8-step pipeline. ``paper paper
  run -c X`` runs the SkillQ method. Step 4 of the refactor
  (2026-06-26) replaced the legacy closure with this new pipeline;
  Step 7 (2026-06-27) deleted the legacy module entirely.

The :mod:`paper.cli` module dispatches between them.

The :func:`paper_main` symbol is the entrypoint
(:mod:`skillq.runtime.entrypoint`). Step 7 removed the legacy
``legacy_paper_main`` alias — the ``MethodConfig.runtime`` field
remains (``Literal["new", "legacy"]``) but its ``"legacy"`` value
now raises a friendly migration error from
:mod:`skillq.runtime.cli`.
"""

# Importing the resolver module registers the ``${now:...}`` and
# ``${abspath:...}`` OmegaConf resolvers that the existing paper
# configs depend on. Must come before any submodule that may load a
# JobConfig YAML.
from skillq import _resolvers  # noqa: F401  (side-effect import)

from skillq.runtime.entrypoint import main as paper_main
from skillq.skillsvote_mode.entrypoint import main as skillsvote_main

__all__ = ["skillsvote_main", "paper_main"]
__version__ = "0.1.0"
