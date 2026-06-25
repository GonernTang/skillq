"""skillq.skillq_runtime — four-layer SkillQ paper method on top of Harbor.

Public API:

- :class:`MethodConfig` — Pydantic hyperparameter config.
- :class:`PaperClaudeCodeAgent` — agent subclass (thin pass-through to
  lqrl's ``SkillsVoteClaudeCode``).
- :func:`skillq.skillq_runtime.bridge.attach_paper_registers` — register the
  single ``on_trial_ended`` hook on a Harbor ``Job``.
- :func:`skillq.skillq_runtime.bridge.run_paper_job_sync` — high-level
  entrypoint used by ``paper paper run``.

Container-side retrieval is done by the PreToolUse hook in
:mod:`skillq.skillq_runtime.hook`. The bridge writes the per-trial
state dump + env vars + bind mounts via
:mod:`skillq.skillq_runtime.container_wiring`.
"""

from skillq.skillq_runtime.agent import PaperClaudeCodeAgent
from skillq.skillq_runtime.bridge import (
    attach_paper_registers,
    run_paper_job,
    run_paper_job_sync,
)
from skillq.skillq_runtime.config import MethodConfig
from skillq.skillq_runtime.entrypoint import main

__all__ = [
    "MethodConfig",
    "PaperClaudeCodeAgent",
    "attach_paper_registers",
    "run_paper_job",
    "run_paper_job_sync",
    "main",
]
