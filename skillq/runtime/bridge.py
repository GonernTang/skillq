"""Closure-free bridge orchestrator — Step 4 (2026-06-26) refactor.

Public surface (Step 4 deliverable, §7 of the plan):

- :func:`attach_registers` — wires Harbor's per-trial lifecycle
  hooks for the **new** method (Step 2's pipeline). Replaces the
  980-line ``attach_paper_registers`` closure in
   ``runtime/bridge.py`` with a ~50-line top-level function.
- :func:`attach_legacy_registers` — same name, **legacy** closure.
  Kept as a thin delegation to the original implementation so
  ``MethodConfig.runtime="legacy"`` still works as a rollback
  escape hatch. Will be removed in v1.5.
- :func:`build_method_services` — constructs the long-lived
  :class:`MethodServices` bag that :class:`TrialContext` carries.
  Lifts the legacy closure's setup code (lib + mgr + state +
  emb_cache load + analyzer + refiner + extractor) into a
  standalone function so Step 5's ``runtime/container_wiring``
  can re-use it for daemon state injection.

The feature flag lives on :class:`MethodConfig.runtime`
(``Literal["new", "legacy"]``, default ``"new"``). The
dispatch happens in :mod:`skillq.runtime.entrypoint`.

**Why the legacy path is preserved**:

The 290-test suite currently passes against the legacy
``runtime/bridge.py``. Moving to the new pipeline in one
step is risky — the closure has 8 nested helpers + 3
``nonlocal`` variables, and the surface (retry config plumbing,
``_find_skills_dir`` env-var lookup, ``extractor_for_mode``
factory) all needs to be wired correctly. Keeping the legacy
path allows:

1. **Gradual rollout**: ``runtime="legacy"`` users see no
   behaviour change. New users get the cleaner pipeline.
2. **Diff testing**: Step 6's import-replacement can run both
   paths against the same inputs and verify Q-table + calls_log
   parity (this is the L1-parity test, applied to L2-L4).
3. **Rollback**: if a Step-4 bug surfaces in production,
   flipping ``runtime`` back to ``"legacy"`` reverts to the
   known-good implementation without redeployment.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from harbor.job import Job
from harbor.trial.hooks import TrialHookEvent

from skillq.layers.l3_attribution.analyzer import AttributionAnalyzer
from skillq.layers.l3_attribution.edit import EditRefiner
from skillq.layers.l3_attribution.models import LiteLLMAttributionBackend
from skillq.layers.l4_evolve.create import SkillExtractor
from skillq.layers.l4_evolve.extract_buffer import ExtractBuffer
from skillq.runtime.context import MethodServices, StepResult, TrialContext
from skillq.runtime.steps import run_pipeline
from skillq.shared.backends.litellm import LiteLLMEditBackend, LiteLLMEmbedder
from skillq.shared.chown import chown_agent_sessions_to_host_user
from skillq.shared.embeddings import VectorTable, sync_lib_to_vector_table
from skillq.shared.library import QlibState
from skillq.shared.q_table import LibManager
from skillq.shared.types import Qlib

if TYPE_CHECKING:
    from harbor.models.job.config import JobConfig
    from harbor.models.trial.result import TrialResult

    from skillq.config import MethodConfig
    from skillq.runtime.container_wiring import ContainerWiringHandle


logger = logging.getLogger("skillq.runtime.bridge")


# ---------------------------------------------------------------------------
# Per-trial helpers (small, pure, lifted from runtime/bridge.py)
# ---------------------------------------------------------------------------
def _harbor_r_task(result: "TrialResult") -> int:
    """Binarise the trial-level verifier reward.

    Returns ``0`` when the verifier reported no reward (e.g.
    cancelled, exception). ``1`` when the verifier passed,
    ``0`` when it failed. Mirrors the legacy ``_harbor_r_task``
    helper exactly.
    """
    if result.verifier_result is None or not result.verifier_result.rewards:
        return 0
    rewards = result.verifier_result.rewards
    reward = rewards.get("reward")
    if reward is None:
        if len(rewards) == 1:
            reward = next(iter(rewards.values()))
        else:
            return 0
    try:
        return int(round(float(reward)))
    except (TypeError, ValueError):
        return 0


def _trial_dir(event: TrialHookEvent) -> Path:
    """Resolve the host-side trial directory from the event."""
    return Path(urlparse(event.result.trial_uri).path)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# MethodServices construction — moved out of the legacy closure
# ---------------------------------------------------------------------------
def build_method_services(
    method: "MethodConfig",
    *,
    expected_terminal_trials: int,
    retry_config: Any = None,
) -> MethodServices:
    """Construct the long-lived :class:`MethodServices` bag.

    Lifts the setup code from the legacy ``attach_paper_registers``
    closure (lib + mgr + state + emb_cache load + analyzer +
    refiner + extractor + Plan-D seed). Pure function: same
    ``method`` + ``expected_terminal_trials`` always produce the
    same ``MethodServices`` instance.

    Plan D (auto-seed from ``seed_skills_dir``) is honoured here.
    Plan D's pre-compute pass also lives here — pre-embed every
    seeded skill's description into ``emb_cache`` so the L1
    Hard Gate has cosine signals from trial 1 onwards.

    Step 5's :mod:`runtime.container_wiring` calls this from the
    host side BEFORE :func:`start_container_wiring` so the
    resulting ``MethodServices`` can be injected into the
    ranking service daemon's ``app.state`` snapshot.
    """
    lib = Qlib(b_max=method.b_max)
    mgr = LibManager(
        b_max=method.b_max,
        q_clip_floor=method.q_clip_floor,
        q_clip_ceiling=method.q_clip_ceiling,
    )
    state = QlibState(method.resolved_state_path())
    state.load_into(
        lib, mgr, lib_root=method.library_root, overwrite_q=method.reuse_q_table
    )
    if not method.reuse_q_table:
        mgr.q_table.clear()
        logger.info(
            "reuse_q_table=False: cleared in-memory Q-table; Plan D "
            "will re-seed with seed_initial_q at %s",
            method.resolved_state_path(),
        )
    if not lib.skills and method.seed_skills_dir is not None:
        seeded = state.ensure_seeded(
            lib=lib,
            mgr=mgr,
            seed_dir=method.seed_skills_dir,
            seed_initial_q=method.seed_initial_q,
        )
        if seeded:
            logger.info(
                "Plan D: seeded %d skills from %s into %s",
                len(lib.skills),
                method.seed_skills_dir,
                method.resolved_state_path(),
            )

    emb_cache = VectorTable(method.resolved_emb_cache_path())
    emb_cache.load()
    if not method.reuse_embedding_cache:
        emb_cache.clear()
        logger.info(
            "reuse_embedding_cache=False: cleared emb_cache; "
            "Plan D will re-embed every skill → %s",
            emb_cache.cache_path,
        )

    # Plan D pre-embed pass.
    if lib.skills and len(emb_cache) < len(lib.skills):
        try:
            missing = [sid for sid in lib.skills if sid not in emb_cache]
            if missing:
                embedder = LiteLLMEmbedder(
                    model=method.embedder_model,
                    dim=int(getattr(method, "embedder_dim", 1536)),
                )
                added = [(sid, lib.skills[sid].body) for sid in missing]
                sync_lib_to_vector_table(
                    added=added,
                    removed=[],
                    replaced=[],
                    vector_table=emb_cache,
                    embedder=embedder,
                )
                emb_cache.save()
                logger.info(
                    "Plan D (cont.): pre-computed emb_cache for %d skills "
                    "(%d already cached) → %s",
                    len(added),
                    len(emb_cache) - len(added),
                    emb_cache.cache_path,
                )
        except Exception:  # noqa: BLE001
            logger.exception(
                "emb_cache pre-compute failed; continuing with Q+UCB-only "
                "ranking. The hook will still work but cosine will be 0."
            )

    refiner = EditRefiner(
        backend=LiteLLMEditBackend(model=method.editor_model),
        model=method.editor_model,
    )
    attribution_analyzer = AttributionAnalyzer(
        backend=LiteLLMAttributionBackend(model=method.attribution_model),
        model=method.attribution_model,
    )
    extractor: SkillExtractor | None = (
        SkillExtractor(
            claude_cli=method.extractor_claude_cli,
            timeout_sec=method.extract_timeout_sec,
            model=method.extractor_model,
        )
        if method.enable_auto_extract
        else None
    )
    extract_buffer = ExtractBuffer(n_trials_threshold=method.extract_every_n_trials)

    services = MethodServices(
        lib=lib,
        mgr=mgr,
        emb_cache=emb_cache,
        state=state,
        method=method,
        attribution_analyzer=attribution_analyzer,
        refiner=refiner,
        extractor=extractor,
        extract_buffer=extract_buffer,
        expected_terminal_trials=expected_terminal_trials,
    )
    # ``retry_config`` is read by ``step_classify_failure`` via
    # ``getattr(ctx.services, 'retry_config', None)``. Stash it
    # on the services bag rather than threading it through the
    # frozen ``MethodServices`` dataclass (which would force
    # ``__post_init__`` plumbing everywhere).
    object.__setattr__(services, "retry_config", retry_config)
    return services


# ---------------------------------------------------------------------------
# New pipeline (closure-free)
# ---------------------------------------------------------------------------
def _aggregate_results(output_dir: Path) -> None:
    """Read skillq_results.jsonl and write a Harbor-compatible result.json."""
    results_path = output_dir / "skillq_results.jsonl"
    if not results_path.exists():
        return
    try:
        results: list[dict[str, Any]] = []
        with open(results_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                results.append(json.loads(line))
        if not results:
            return
        mean = sum(r["reward"] for r in results) / len(results)
        harbor_result_path = output_dir / "result.json"
        with open(harbor_result_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "mean": round(mean, 3),
                    "results": [
                        {
                            "task_name": r["task_name"],
                            "reward": r["reward"],
                            "trial_id": r["trial_id"],
                        }
                        for r in results
                    ],
                },
                f,
                indent=2,
                ensure_ascii=False,
            )
        logger.info(
            "aggregated %d trial results → result.json (mean=%.3f)",
            len(results),
            mean,
        )
    except Exception:
        logger.exception("result.json aggregation failed")


def _write_trial_result(
    trial_dir: Path,
    trial_id: str,
    task_name: str,
    reward: int,
) -> None:
    """Append a per-trial result line to the job-level results log."""
    results_path = trial_dir.parent / "skillq_results.jsonl"
    try:
        with open(results_path, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "ts": time.time(),
                        "trial_id": trial_id,
                        "task_name": task_name,
                        "reward": reward,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except OSError:
        pass  # best-effort; Harbor result.json is the authority


async def _on_trial_ended_new(
    event: TrialHookEvent,
    services: MethodServices,
) -> None:
    """Per-trial Q-update + library maintenance (new pipeline).

    Replaces the 980-line ``on_ended`` closure inside the legacy
    ``attach_paper_registers``. The body is just:

    1. chown agent sessions back to host user (best-effort, pre-classify)
    2. early-return on ``event.result is None``
    3. build :class:`TrialContext` + fresh :class:`StepResult`
    4. run :func:`skillq.runtime.steps.run_pipeline`
    5. on exception, write a per-trial ``method_errors.jsonl``
       record so users can diagnose what broke

    The 8 step functions in :mod:`runtime.steps` do all the
    work; this function is just plumbing.
    """
    # 1. Chown (best-effort, pre-classify).
    if event.result is not None:
        try:
            chown_agent_sessions_to_host_user(
                _trial_dir(event) if event.result.trial_uri else None
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("post-trial chown failed: %s", exc)

    # 2. No result → nothing to do.
    if event.result is None:
        return
    trial_dir = _trial_dir(event)

    # 3. Build context + accumulator.
    r_task = _harbor_r_task(event.result)
    intent_text = event.task_name or trial_dir.name
    ctx = TrialContext(
        trial_id=event.trial_id,
        trial_dir=trial_dir,
        intent_text=intent_text,
        r_task=r_task,
        failure=None,
        services=services,
        event=event,
    )
    result = StepResult()

    # 4. Run the pipeline.
    try:
        await run_pipeline(ctx, result)
        # Per-trial incremental result: append to results.jsonl so
        # a mid-run crash doesn't lose all accumulated rewards.
        _write_trial_result(trial_dir, event.trial_id, intent_text, r_task)
    except Exception as exc:
        # Never let a method bug abort the trial. Write a per-trial
        # record so users can diagnose what broke (Bug 5 fix).
        logger.exception(
            "Paper method on_ended failed for trial %s; swallowed.",
            event.trial_id,
        )
        try:
            err_path = trial_dir / "skillq_state" / "method_errors.jsonl"
            err_path.parent.mkdir(parents=True, exist_ok=True)
            with open(err_path, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "ts": time.time(),
                            "trial_id": event.trial_id,
                            "phase": "on_ended",
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception:  # noqa: BLE001
            pass

    # 5. Last-trial aggregation: read all per-trial results and
    #    write a proper result.json so downstream tools work even
    #    if Harbor never wrote its own.
    if services.state.step >= services.expected_terminal_trials:
        _aggregate_results(trial_dir.parent)


def _make_on_trial_started_new(
    wiring: "ContainerWiringHandle | None",
):
    """Construct the ``on_trial_started`` hook (new pipeline).

    Container wiring is unchanged from the legacy implementation
    in this Step — Step 5 will replace ``wire_one_trial`` to
    drop the 4 redundant bind-mounts (``lib.json`` /
    ``q_table.json`` / ``emb_cache.json`` / ``settings.json``)
    since the host now owns those via ``/rank`` and ``app.state``.
    """
    from skillq.runtime.container_wiring import wire_one_trial

    async def on_trial_started(event: TrialHookEvent) -> None:
        if wiring is None:
            return
        try:
            wire_one_trial(wiring, event)
        except Exception:
            logger.exception(
                "Container wiring for trial %s failed; trial will run without hook.",
                event.trial_id,
            )

    return on_trial_started


def attach_registers(
    job: Job,
    method: "MethodConfig",
    wiring: "ContainerWiringHandle | None" = None,
    *,
    services: MethodServices | None = None,
    retry_config: Any = None,
) -> MethodServices:
    """Wire Harbor's per-trial lifecycle hooks for the **new** method.

    Replaces the 980-line ``attach_paper_registers`` closure with
    a 50-line top-level function. The closure's nested helpers
    (``_q_update`` / ``_attribution_and_extract_dispatch`` /
    ``_maintain_lib`` / ``_refresh_emb_cache`` /
    ``_incremental_edit_on_failure`` / ``_flush_buffer`` /
    ``_extractor_for_mode`` / ``_find_skills_dir``) are now
    top-level :func:`step_xxx` functions in
    :mod:`skillq.runtime.steps`.

    Parameters
    ----------
    job
        The Harbor :class:`Job` to attach hooks to. Created by
        ``await Job.create(job_cfg)``.
    method
        The parsed :class:`MethodConfig`.
    wiring
        Container wiring handle from
        :func:`skillq.runtime.container_wiring.start_container_wiring`.
        ``None`` means no API key → no per-subtask hook installed;
        the agentic-search path is still active.
    services
        Optional pre-built :class:`MethodServices`. When ``None``
        (the common case), :func:`build_method_services` is
        called. When provided, we re-use it — this lets Step 5's
        :mod:`runtime.container_wiring` inject a services bag
        that has already been seeded into the ranking daemon's
        ``app.state``.
    retry_config
        Optional :class:`harbor.models.job.config.RetryConfig`
        from the job config. Threaded through to
        :func:`step_classify_failure` via
        ``ctx.services.retry_config``.

    Returns
    -------
    MethodServices
        The services bag. Step 5's container wiring uses it to
        inject state into the ranking daemon. Step 6's tests use
        it as a fixture.
    """
    if services is None:
        services = build_method_services(
            method,
            expected_terminal_trials=len(job),
            retry_config=retry_config,
        )
    else:
        # Caller provided a services bag. Make sure ``retry_config``
        # is updated if a fresh one was passed.
        if retry_config is not None:
            object.__setattr__(services, "retry_config", retry_config)

    async def on_ended(event: TrialHookEvent) -> None:
        await _on_trial_ended_new(event, services)

    on_started = _make_on_trial_started_new(wiring)
    job.on_trial_started(on_started)
    job.on_trial_ended(on_ended)
    return services


# ---------------------------------------------------------------------------
# Legacy rollback path
# ---------------------------------------------------------------------------
def attach_legacy_registers(
    job: Job,
    method: "MethodConfig",
    wiring: "ContainerWiringHandle | None" = None,
) -> None:
    """Stub for the legacy closure-based path.

    Step 7 (2026-06-27) deleted ``skillq._legacy_runtime.*`` entirely,
    so the ``MethodConfig.runtime="legacy"`` rollback path is no
    longer reachable. Calling this function raises a clear error so
    old YAMLs that still set ``runtime: legacy`` fail loudly with a
    migration message instead of an opaque ImportError.

    To roll back to the pre-Step-7 behaviour, check out the v0.x tag
    and use the corresponding ``MethodConfig.runtime="legacy"``
    bridge. The new path (``runtime="new"`` — the default) is the
    supported one and is bit-equivalent on the smoke config.
    """
    raise RuntimeError(
        "MethodConfig.runtime='legacy' is no longer supported — the "
        "legacy closure-based bridge was deleted in Step 7 "
        "(2026-06-27). Set method.runtime='new' (or omit it; 'new' "
        "is the default) to use the closure-free 8-step pipeline at "
        "skillq.runtime.bridge.attach_layered_registers. The two "
        "implementations are bit-equivalent on the smoke config and "
        "the e2e 3-task config."
    )


# ---------------------------------------------------------------------------
# Feature-flag dispatch (called from runtime.entrypoint)
# ---------------------------------------------------------------------------
def attach_layered_registers(
    job: Job,
    method: "MethodConfig",
    wiring: "ContainerWiringHandle | None" = None,
    *,
    services: MethodServices | None = None,
    retry_config: Any = None,
) -> MethodServices | None:
    """Attach per-trial hooks under the user's chosen runtime.

    Dispatches on :attr:`MethodConfig.runtime` (``Literal["new",
    "legacy"]``):

    - ``"new"`` (default) → :func:`attach_registers` (the new
      closure-free pipeline).
    - ``"legacy"`` → :func:`attach_legacy_registers` (rollback).

    Returns the :class:`MethodServices` bag (or ``None`` when the
    legacy path is taken — the legacy path doesn't return
    services, so the caller has to fish them out of the closure).
    """
    runtime = getattr(method, "runtime", "new")
    if runtime == "legacy":
        attach_legacy_registers(job, method, wiring)
        return None
    return attach_registers(
        job, method, wiring, services=services, retry_config=retry_config
    )


__all__ = [
    "build_method_services",
    "attach_registers",
    "attach_legacy_registers",
    "attach_layered_registers",
]