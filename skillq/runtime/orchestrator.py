"""``run_paper_job`` orchestrator — Step 5 (2026-06-26) refactor.

Replaces the Step-4 orchestrator with one that uses the new
ranking service (Step 3) + new container wiring (Step 5) +
new agent (Step 5).

Flow:

1. Load the job YAML into a :class:`harbor.JobConfig`.
2. Pre-flight the environment.
3. Build :class:`MethodServices` via
   :func:`skillq.runtime.bridge.build_method_services`.
4. Boot the host-side ranking daemon via
   :func:`skillq.runtime.container_wiring.start_container_wiring`,
   injecting the MethodServices snapshot into
   ``app.state.{lib, mgr, emb_cache, method}``.
5. Pre-seed ``cfg.agents[0].env`` via
   :func:`skillq.runtime.env_seed.seed_agent_env` — 14
   SKILLQ_* vars, **must** happen before :func:`harbor.Job.create`.
6. :func:`harbor.Job.create`.
7. Attach per-trial hooks via
   :func:`skillq.runtime.bridge.attach_layered_registers`,
   passing the pre-built ``MethodServices`` so the bridge
   doesn't rebuild it (and so the daemon's ``app.state``
   stays in sync with the lib the steps mutate).
8. ``await job.run()``.
9. Tear down the daemon in a try/finally.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from omegaconf import OmegaConf

from skillq.runtime.bridge import (
    MethodServices,
    attach_layered_registers,
    build_method_services,
)
from skillq.runtime.container_wiring import (
    start_container_wiring,
    stop_container_wiring,
)
from skillq.runtime.env_seed import seed_agent_env

if TYPE_CHECKING:
    from harbor.models.job.config import JobConfig

    from skillq.config import MethodConfig


logger = logging.getLogger("skillq.runtime.orchestrator")


async def run_paper_job(
    job_config_path: Path,
    method: "MethodConfig",
) -> int:
    """Run a Harbor job with the SkillQ paper method.

    Replaces :func:`skillq.runtime.bridge.run_paper_job`
    for the new pipeline (Step 4) + new container wiring (Step 5).
    """
    from harbor import Job
    from harbor.environments.factory import EnvironmentFactory
    from harbor.models.job.config import JobConfig

    cfg = OmegaConf.load(str(job_config_path))
    cfg_container = OmegaConf.to_container(cfg, resolve=True)
    if not isinstance(cfg_container, dict):
        raise TypeError("Job config must be a mapping.")
    job_cfg = JobConfig.model_validate(cfg_container)

    EnvironmentFactory.run_preflight(
        type=job_cfg.environment.type,
        import_path=job_cfg.environment.import_path,
    )

    # 1. Build MethodServices BEFORE the daemon so we can inject
    #    the lib/mgr/emb_cache/method snapshot into the daemon's
    #    app.state. The bridge's on_trial_ended callback will
    #    refresh app.state via inject_ranking_state after every
    #    trial's step_save_state.
    services: MethodServices = build_method_services(
        method,
        expected_terminal_trials=0,  # patched after Job.create
        retry_config=job_cfg.retry,
    )

    # 2. Boot the ranking daemon BEFORE seeding env vars so the
    #    wiring handle's port is known.
    wiring = start_container_wiring(method, services=services)

    # 3. Pre-seed env vars. **Must** run before Job.create.
    seed_agent_env(job_cfg, method, wiring)

    # 4. Create the Job.
    job = await Job.create(job_cfg)
    try:
        # Patch the expected_terminal_trials now that we know the
        # real job length.
        services.expected_terminal_trials = len(job)

        # Attach per-trial hooks. Pass the pre-built services so
        # the bridge reuses our snapshot (instead of rebuilding
        # from disk and missing the in-memory mutations done by
        # the daemon's /rank path).
        attach_layered_registers(
            job,
            method,
            wiring,
            services=services,
            retry_config=job_cfg.retry,
        )
        result = await job.run()
    finally:
        if wiring is not None:
            stop_container_wiring(wiring)

    logger.info(
        "Paper method finished: %s trials, %s successes",
        getattr(result, "n_trials", "?"),
        getattr(result, "n_succeeded", "?"),
    )
    return 0


def run_paper_job_sync(job_config_path: Path, method: "MethodConfig") -> int:
    """Synchronous wrapper around :func:`run_paper_job`."""
    return asyncio.run(run_paper_job(job_config_path, method))


__all__ = ["run_paper_job", "run_paper_job_sync"]