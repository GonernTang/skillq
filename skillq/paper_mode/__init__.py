"""paper.paper_mode — four-layer SkillQ paper method on top of Harbor.

Public API:

- :class:`MethodConfig` — Pydantic hyperparameter config.
- :class:`PaperClaudeCodeAgent` — agent subclass (thin pass-through to
  lqrl's ``SkillsVoteClaudeCode``).
- :func:`paper.paper_mode.bridge.attach_paper_registers` — register the
  single ``on_trial_ended`` hook on a Harbor ``Job``.
- :func:`paper.paper_mode.bridge.run_paper_job_sync` — high-level
  entrypoint used by ``paper paper run``.

Container-side retrieval is done by the PreToolUse hook in
:mod:`paper.paper_mode.hook`. The bridge writes the per-trial
state dump + env vars + bind mounts via
:mod:`paper.paper_mode.container_wiring`.
"""

from skillq.paper_mode.agent import PaperClaudeCodeAgent
from skillq.paper_mode.bridge import (
    attach_paper_registers,
    run_paper_job,
    run_paper_job_sync,
)
from skillq.paper_mode.config import MethodConfig
from skillq.paper_mode.entrypoint import main

__all__ = [
    "MethodConfig",
    "PaperClaudeCodeAgent",
    "attach_paper_registers",
    "run_paper_job",
    "run_paper_job_sync",
    "main",
]
