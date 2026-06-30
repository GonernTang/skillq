"""Pre-seed agent env vars — Step 4 (2026-06-26) refactor.

Single source of truth for the 14 ``SKILLQ_*`` env vars injected
into ``cfg.agents[0].env`` before :func:`harbor.Job.create` runs.

**Why this lives in its own module**: the legacy
``_seed_agent_hook_env`` helper inside
``runtime/bridge.py:1327-1410` was bundled with the
closure body — invisible to the rest of the codebase. The new
``env_seed.py`` module exposes a single
:func:`seed_agent_env` function that:

- Is called from :mod:`skillq.runtime.entrypoint` BEFORE
  ``Job.create`` (critical timing — Harbor snapshots
  ``config.env`` into ``agent._extra_env`` at agent-construction
  time inside :class:`harbor.trial.trial.Trial.__init__`).
- Reads its knobs from :class:`MethodConfig` (single source).
- Honours the new :attr:`MethodConfig.runtime` flag — the
  14-var contract is identical for ``runtime="new"`` and
  ``runtime="legacy"`` so the container-side hook is unchanged.
- Asserts at runtime that ``SKILLQ_RANK_ENDPOINT`` is present
  in the seeded env (the contract Step 5's
  :mod:`runtime.hook` depends on); failure is loud.

The 14 env vars (post-Step-3 dedup):

=====================  ======  =================================
Variable               Set by  Notes
=====================  ======  =================================
SKILLQ_RANK_ENDPOINT   seed    NEW (replaces SKILLQ_EMBED_HOST/PORT)
SKILLQ_CALLS_LOG_PATH  wiring  Trial-scoped; per-trial write
SKILLQ_HOOK_TOP_K      seed
SKILLQ_HOOK_LAMBDA     seed
SKILLQ_HOOK_C_UCB      seed
SKILLQ_HOOK_SCORE_MODE seed
SKILLQ_HOOK_MULT_BETA  seed
SKILLQ_HOOK_MULT_GAMMA seed
SKILLQ_SIM_GATE_MIN_SCORE seed
SKILLQ_SIM_GATE_FLOOR  seed
SKILLQ_PULL_TOP_K      seed    Only when method.retrieval_mode=="pull"
SKILLQ_USER_TASK       wiring  Trial-scoped
SKILLQ_HOOK_RANK_TIMEOUT_SEC seed  NEW (default 5.0)
=====================  ======  =================================

Trial-scoped vars (``SKILLQ_CALLS_LOG_PATH`` /
``SKILLQ_USER_TASK``) are re-applied inside
:mod:`skillq.runtime.container_wiring.wire_one_trial`.
The 12 method-config vars are seeded **once** here.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harbor.models.job.config import JobConfig

    from skillq.config import MethodConfig
    from skillq.runtime.container_wiring import ContainerWiringHandle


logger = logging.getLogger("skillq.runtime.env_seed")


def seed_agent_env(
    job_cfg: "JobConfig",
    method: "MethodConfig",
    wiring: "ContainerWiringHandle | None",
) -> None:
    """Pre-seed ``cfg.agents[0].env`` with the 14 SKILLQ_* tunables.

    See the module docstring for the full list. Critical timing:
    this MUST run before :func:`harbor.Job.create`. Harbor's
    Trial.__init__ calls ``AgentFactory.create_agent_from_config``
    which calls ``resolve_env_vars(config.env)`` ONCE and copies
    the result into ``agent._extra_env``. Any later mutation of
    ``config.env`` (the one inside
    :func:`wire_one_trial`) is invisible to the agent's bash
    process. Therefore the only safe injection point is
    BEFORE :func:`Job.create`.

    Defence-in-depth: the container-side ``runtime/hook.py``
    (Step 5) reads these via ``os.environ.get`` and applies the
    scoring formula + Hard Gate params. If a required var is
    missing, the hook falls back to internal defaults — which
    silently drift from the method config. The post-conditions
    below make this drift loud.

    No-op when ``job_cfg.agents`` is empty (defensive — Harbor's
    JobConfig requires at least one today but a future variant
    might not).
    """
    if not job_cfg.agents:
        return
    agent_cfg = job_cfg.agents[0]
    if agent_cfg.env is None:
        agent_cfg.env = {}

    # ---- RANK endpoint (NEW) ----
    # The /rank endpoint replaces the legacy SKILLQ_EMBED_HOST +
    # SKILLQ_EMBED_PORT pair. Default points at the host's
    # loopback from the container's perspective; docker-compose
    # users override via .env.
    default_endpoint = (
        os.environ.get("SKILLQ_RANK_ENDPOINT", "http://host.docker.internal:8765")
    )
    if wiring is not None:
        # Prefer the wiring handle's actual host:port so the
        # container always reaches the right daemon even when
        # the port is ephemeral.
        try:
            embed = wiring.embedding  # type: ignore[attr-defined]
            host = embed.get("host", "host.docker.internal")
            port = embed.get("port", 8765)
            default_endpoint = f"http://{host}:{port}"
        except Exception:  # noqa: BLE001
            pass
    agent_cfg.env["SKILLQ_RANK_ENDPOINT"] = default_endpoint

    # ---- 5 SKILLQ_HOOK_* tunables (was 7, dropped Q_CLIP_MIN/MAX in Phase 10 Bug 1) ----
    # Names + defaults must match the container-side fallback
    # in runtime/hook.py:_read_params_from_env so the two never
    # silently disagree.
    hook_env = {
        "SKILLQ_HOOK_TOP_K": str(method.hook_top_k),
        "SKILLQ_HOOK_LAMBDA": f"{method.hook_lambda:.6f}",
        "SKILLQ_HOOK_C_UCB": f"{method.hook_c_ucb:.6f}",
        "SKILLQ_HOOK_SCORE_MODE": method.hook_score_mode,
        "SKILLQ_HOOK_MULT_BETA": f"{method.hook_multiplicative_beta:.6f}",
        "SKILLQ_HOOK_MULT_GAMMA": f"{method.hook_multiplicative_gamma:.6f}",
    }
    # 2026-06-29 (Phase 10 Bug 1): if a caller still set the old
    # SKILLQ_HOOK_Q_CLIP_MIN/MAX in their env, strip it so a stale
    # value cannot survive into the container. (The container hook
    # no longer reads these; we just want to prevent silent leaks
    # from confusing downstream audit.)
    agent_cfg.env.pop("SKILLQ_HOOK_Q_CLIP_MIN", None)
    agent_cfg.env.pop("SKILLQ_HOOK_Q_CLIP_MAX", None)
    agent_cfg.env.update(hook_env)

    # ---- 2 SIM_GATE_* params ----
    agent_cfg.env["SKILLQ_SIM_GATE_MIN_SCORE"] = (
        f"{getattr(method, 'sim_gate_min_score', 0.7):.6f}"
    )
    agent_cfg.env["SKILLQ_SIM_GATE_FLOOR"] = str(
        getattr(method, "sim_gate_floor", 0)
    )

    # ---- 1 NEW timeout (Step 3) ----
    agent_cfg.env["SKILLQ_HOOK_RANK_TIMEOUT_SEC"] = str(
        getattr(method, "hook_rank_timeout_sec", 5.0)
    )

    # ---- 2 paths that MUST be set before Job.create (Bug #2 2026-06-30) ----
    #
    # The legacy code deferred ``SKILLQ_CALLS_LOG_PATH`` /
    # ``SKILLQ_USER_TASK`` to ``_wire_hook_trial`` (fired on
    # ``on_trial_started`` post-Trial.__init__). But Harbor's
    # Trial.__init__ snapshots ``config.env`` into
    # ``agent._extra_env`` at agent-factory time — and the agent
    # is constructed LAZILY per-trial in the worker. With
    # ``n_concurrent_trials > 1`` and async scheduling, the
    # mutation-then-snapshot window is non-deterministic: in some
    # trials the late mutation wins (chess got the path), in
    # others it loses (extract-elf got "" → hook silently skips
    # writing the calls log → no L1 audit data).
    #
    # Fix: pre-seed BOTH env vars here, BEFORE ``Job.create``,
    # using a library-scoped fixed path so ``on_trial_started``
    # cannot race. The library-scoped path is a single file
    # shared by all trials of the same run (``<library_root>/
    # _calls_log/skillq_skill_calls.jsonl``). A JSONL is the right
    # format because multiple processes can append concurrently
    # without coordination — the hook already uses
    # ``open(..., "a")`` which POSIX guarantees atomic for
    # short writes.
    #
    # ``SKILLQ_USER_TASK`` is per-trial by nature, so we cannot
    # pre-seed a meaningful value here. Instead the hook falls
    # back to ``transcript_path`` (last-N assistant messages) when
    # the env var is empty — that's the line at runtime/hook.py
    # 356-357. So setting it to "" here is the same as the
    # legacy default and continues to work via the fallback.
    _library_root = Path(getattr(method, "library_root", "./.skillq_library")).resolve()
    _calls_log_dir = _library_root / "_calls_log"
    _calls_log_dir.mkdir(parents=True, exist_ok=True)
    _calls_log_path = str(_calls_log_dir / "skillq_skill_calls.jsonl")
    agent_cfg.env["SKILLQ_CALLS_LOG_PATH"] = _calls_log_path
    agent_cfg.env["SKILLQ_USER_TASK"] = ""  # hooked via transcript_path fallback

    # ---- Pull-mode top_k (default since 2026-07-01) ----
    # retrieval_mode="pull" is the paper-intent default; in this
    # mode the container-side hook needs SKILLQ_PULL_TOP_K to know
    # how many top-K to inject per UserPromptSubmit. For "hook"
    # mode we skip this — the gate fires only on Skill() tool_use
    # and the hook's TOP_K is read from SKILLQ_HOOK_TOP_K (already
    # seeded above).
    if getattr(method, "retrieval_mode", "pull") == "pull":
        agent_cfg.env["SKILLQ_PULL_TOP_K"] = str(method.hook_pull_top_k)

    n_seeded = sum(1 for k in agent_cfg.env if k.startswith("SKILLQ_"))
    logger.info(
        "Pre-seeded cfg.agents[0].env with %d SKILLQ_* vars "
        "(score_mode=%s, beta=%.3f, gamma=%.3f, rank_endpoint=%s)",
        n_seeded,
        method.hook_score_mode,
        method.hook_multiplicative_beta,
        method.hook_multiplicative_gamma,
        default_endpoint,
    )

    # Post-condition: SKILLQ_RANK_ENDPOINT must be present.
    assert "SKILLQ_RANK_ENDPOINT" in agent_cfg.env, (
        "seed_agent_env must inject SKILLQ_RANK_ENDPOINT — "
        "container-side hook reads it without a default. "
        "Check that the method config + wiring handle are valid."
    )


__all__ = ["seed_agent_env"]