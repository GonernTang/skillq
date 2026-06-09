"""paper.paper_mode — four-layer LQRL paper method on top of Harbor.

Public API:

- :class:`MethodConfig` — Pydantic hyperparameter config.
- :class:`PaperClaudeCodeAgent` — agent subclass that calls the
  :func:`paper.paper_mode.retrieval_step.rerank_with_ucb` step before
  delegating to lqrl's ``SkillsVoteClaudeCode.run``.
- :func:`paper.paper_mode.bridge.attach_paper_registers` — register the
  single ``on_trial_ended`` hook on a Harbor ``Job``.
- :func:`paper.paper_mode.bridge.run_paper_job_sync` — high-level
  entrypoint used by ``paper paper run``.
"""

from paper.paper_mode.agent import PaperClaudeCodeAgent
from paper.paper_mode.bridge import (
    attach_paper_registers,
    run_paper_job,
    run_paper_job_sync,
)
from paper.paper_mode.config import MethodConfig, PaperRetrievalArgs
from paper.paper_mode.entrypoint import main
from paper.paper_mode.retrieval_step import rerank_with_ucb

__all__ = [
    "MethodConfig",
    "PaperRetrievalArgs",
    "PaperClaudeCodeAgent",
    "attach_paper_registers",
    "run_paper_job",
    "run_paper_job_sync",
    "rerank_with_ucb",
    "main",
]
