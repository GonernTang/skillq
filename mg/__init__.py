"""mg — branch-style entrypoint for lqrl and the LQRL paper method.

Two run modes, mutually exclusive at the Job level:

- ``mg.lqrl_mode.entrypoint.main`` — pass-through to upstream lqrl's
  ``attach_registers`` / ``run_job``. No implementation code in
  ``mg.lqrl_mode``.
- ``mg.paper_mode.entrypoint.main`` — runs the four-layer paper method
  (TwoStageRanker → BetaLayeredQ → LibManager → NearMissRefiner) via
  a single ``on_trial_ended`` hook.

The :mod:`mg.cli` module dispatches between them.
"""

from mg.lqrl_mode.entrypoint import main as lqrl_main
from mg.paper_mode.entrypoint import main as paper_main

__all__ = ["lqrl_main", "paper_main"]
__version__ = "0.1.0"
