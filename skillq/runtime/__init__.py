"""``skillq.runtime`` — Step 4 (2026-06-26) refactor.

Replaces :mod:`skillq.runtime` (now
:mod:`skillq.runtime`). The new package owns the
paper-method's per-trial orchestration:

- :mod:`.context` — ``TrialContext`` + ``MethodServices`` +
  ``StepResult`` dataclasses.
- :mod:`.steps` — 8-step closure-free pipeline
  (``ON_TRIAL_ENDED_PIPELINE``).
- :mod:`.bridge` — orchestrator that builds ``MethodServices``
  + attaches ``on_trial_started`` / ``on_trial_ended`` hooks.
  Includes the ``runtime="legacy"`` rollback delegation.
- :mod:`.env_seed` — single source of truth for the 14
  ``SKILLQ_*`` env vars pre-seeded before :func:`harbor.Job.create`.
- :mod:`.orchestrator` — high-level ``run_paper_job`` that
  owns the daemon lifecycle.
- :mod:`.entrypoint` — ``main()`` + ``run_paper_job_sync``
  re-exports.
- :mod:`.cli` — ``paper paper`` argparse subcommand.
- :mod:`.agent` — ``SkillQClaudeCodeAgent`` (Step 4: thin
  re-export from legacy; Step 5: from-scratch subclass that
  drops the obsolete bind-mount env vars).

Public surface — same names as the pre-refactor ``skillq_runtime`` package, so imports written before the 2026-06-26 refactor continue to resolve via ``skillq.runtime``.
"""

from skillq.runtime.agent import PaperClaudeCodeAgent, SkillQClaudeCodeAgent
from skillq.runtime.bridge import (
    attach_layered_registers,
    attach_legacy_registers,
    attach_registers,
    build_method_services,
)
from skillq.runtime.context import MethodServices, StepResult, TrialContext
from skillq.runtime.entrypoint import main, run_paper_job_sync
from skillq.runtime.env_seed import seed_agent_env
from skillq.runtime.orchestrator import run_paper_job
from skillq.runtime.steps import (
    ON_TRIAL_ENDED_PIPELINE,
    run_pipeline,
    step_attribute,
    step_classify_failure,
    step_dispatch_evolve,
    step_incremental_edit,
    step_maintain_lib,
    step_q_update,
    step_refresh_emb_cache,
    step_save_state,
)

__all__ = [
    # agents
    "SkillQClaudeCodeAgent",
    "PaperClaudeCodeAgent",
    # bridge
    "build_method_services",
    "attach_registers",
    "attach_legacy_registers",
    "attach_layered_registers",
    # context + steps
    "MethodServices",
    "StepResult",
    "TrialContext",
    "ON_TRIAL_ENDED_PIPELINE",
    "run_pipeline",
    "step_classify_failure",
    "step_q_update",
    "step_attribute",
    "step_maintain_lib",
    "step_refresh_emb_cache",
    "step_incremental_edit",
    "step_dispatch_evolve",
    "step_save_state",
    # env_seed
    "seed_agent_env",
    # orchestrator + entrypoint
    "run_paper_job",
    "run_paper_job_sync",
    "main",
]