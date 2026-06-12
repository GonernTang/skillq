"""Bridge between Harbor's trial-event stream and the four-layer method
(per-subtask hook refactor, 2026-06-11).

Two public functions:

- :func:`attach_paper_registers` — wires Harbor's per-trial lifecycle
  hooks for the paper method: ``on_trial_started`` (container
  wiring — see :mod:`paper.paper_mode.container_wiring`) and
  ``on_trial_ended`` (per-subtask Q-update + library maintenance).
- :func:`run_paper_job` — high-level orchestrator that creates a Harbor
  :class:`Job`, starts the host-side embedding daemon, attaches both
  hooks, runs the job, and tears down the daemon in a try/finally.

**Global-Q + per-subtask refactor**:

- The Q-table is keyed by ``skill_id`` (single global value per
  skill). Eq. 4 reads it as ``mgr.q_table[skill_id]``; Eq. 6 (the
  Q-update) writes to the same key.
- Per-subtask verdicts come from the container's PreToolUse hook
  log (``mg_skill_calls.jsonl``). The bridge aggregates by
  ``(skill_id, trial)`` (mean ``r_subtask`` over all calls in the
  trial), then applies::

      Q(skill) += alpha * (w_subtask * r_subtask_mean
                           + w_task    * r_task
                           - Q(skill))

**Container wiring lifecycle** (issue #2 fix):

- :func:`run_paper_job` calls :func:`start_container_wiring` BEFORE
  ``Job.create`` to spin up the FastAPI embed daemon.
- :func:`attach_paper_registers` registers an ``on_trial_started``
  hook that calls :func:`wire_one_trial` — re-dumps state, injects
  ``MG_*`` env vars, bind-mounts hook script + settings.json into
  the container.
- :func:`run_paper_job`'s try/finally calls
  :func:`stop_container_wiring` to stop the daemon cleanly.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from harbor.job import Job
from harbor.models.trial.result import TrialResult
from harbor.trial.hooks import TrialHookEvent
from omegaconf import OmegaConf

from paper.method.attribution import (
    Attribution,
    AttributionAnalyzer,
    LiteLLMAttributionBackend,
)
from paper.method.editor_backend import LiteLLMEditBackend
from paper.method.extractor import SkillExtractor
from paper.method.library import LibManager
from paper.method.near_miss import NearMissRefiner
from paper.method.retrieval import LiteLLMEmbedder
from paper.method.state import QlibState
from paper.method.sub_task_verifier import (
    LiteLLMSubTaskVerifierBackend,
    StubSubTaskVerifierBackend,
    SubTaskVerifier,
    mean_r_subtask,
)
from paper.method.types import Qlib, Skill
from paper.method.vector_table import VectorTable
from paper.method.verifier import IndependentVerifier, LiteLLMVerifierBackend
from paper.paper_mode.config import MethodConfig
from paper.paper_mode.container_wiring import (
    ContainerWiringHandle,
    start_container_wiring,
    stop_container_wiring,
    wire_one_trial,
)

logger = logging.getLogger("paper.paper.bridge")


# ---------------------------------------------------------------------------
# Trial-level helpers
# ---------------------------------------------------------------------------
def _harbor_r_task(result: TrialResult) -> float:
    """Extract the scalar reward from a Harbor TrialResult.

    Returns ``0.0`` if the result has no verifier reward yet (e.g. the
    trial was cancelled).
    """
    if result.verifier_result is None or not result.verifier_result.rewards:
        return 0.0
    rewards = result.verifier_result.rewards
    reward = rewards.get("reward")
    if reward is None:
        if len(rewards) == 1:
            reward = next(iter(rewards.values()))
        else:
            return 0.0
    try:
        return float(reward)
    except (TypeError, ValueError):
        return 0.0


def _is_retryable_failure(event: TrialHookEvent, retry_config) -> bool:
    """Equivalent semantics to lqrl's ``_will_harbor_retry`` helper.

    We do **not** import lqrl's helper — keep the dependency surface
    minimal and the semantics easy to audit in one place.
    """
    if event.result is None or event.result.exception_info is None:
        return False
    exception_type = event.result.exception_info.exception_type
    if (
        retry_config.exclude_exceptions is not None
        and exception_type in retry_config.exclude_exceptions
    ):
        return False
    if (
        retry_config.include_exceptions is not None
        and exception_type not in retry_config.include_exceptions
    ):
        return False
    return True


def _trial_dir(event: TrialHookEvent) -> Path:
    return Path(urlparse(event.result.trial_uri).path)  # type: ignore[union-attr]


def _find_skills_dir(event: TrialHookEvent) -> Path | None:
    """Locate the directory lqrl's ``step_recommend`` copied skills into.

    See comments in the prior revision of this module. The per-subtask
    hook does not need this; we still surface it for the attribution
    analyzer.
    """
    config = event.config
    if config is None:
        return None
    env = getattr(config.agent, "env", None) or {}
    for var in ("CLAUDE_CONFIG_DIR", "CODEX_HOME"):
        val = env.get(var) if isinstance(env, dict) else None
        if val:
            candidate = Path(val) / "skills"
            if candidate.exists():
                return candidate
    return None


# ---------------------------------------------------------------------------
# Auto-extract buffer (batched-evolve, mirrors lqrl's evolve_every_n_trials)
# ---------------------------------------------------------------------------
@dataclass
class _ExtractBuffer:
    """Buffer of (task, knowledge) records awaiting a batched-extract flush."""

    n_trials_threshold: int
    pending: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        *,
        task: str,
        knowledge: str,
    ) -> list[dict[str, Any]]:
        if not knowledge.strip():
            return []
        self.pending.append({"task": task, "knowledge": knowledge})
        if len(self.pending) >= self.n_trials_threshold:
            return list(self.pending)
        return []

    def flush(self) -> list[dict[str, Any]]:
        if not self.pending:
            return []
        batch = self.pending
        self.pending = []
        return batch

    def __len__(self) -> int:
        return len(self.pending)


# ---------------------------------------------------------------------------
# Sub-task log reader — parses the container's hook JSONL
# ---------------------------------------------------------------------------
@dataclass
class _SubTaskCallRecord:
    skill_id: str
    requested: str
    top_k: list[dict[str, Any]]
    approved: bool
    ts: float
    intent_text: str


def _read_skill_calls_log(log_path: Path) -> list[_SubTaskCallRecord]:
    """Parse the JSONL the hook wrote during a trial.

    Returns [] on any structural failure (missing file, bad JSON).
    Per the per-subtask design, we aggregate by skill_id downstream
    and take the mean of r_subtask over all calls in the trial.
    """
    if not log_path.exists():
        return []
    out: list[_SubTaskCallRecord] = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.append(
                _SubTaskCallRecord(
                    skill_id=str(rec.get("requested", "")),
                    requested=str(rec.get("requested", "")),
                    top_k=list(rec.get("top_k", [])),
                    approved=bool(rec.get("approved", False)),
                    ts=float(rec.get("ts", 0.0)),
                    intent_text=str(rec.get("intent_text", "")),
                )
            )
    return out


def _slice_sub_task_trace(trial_dir: Path, ts: float) -> str:
    """Read a slice of the agent's session log around ``ts`` seconds.

    Used by :class:`SubTaskVerifier` to build its judgment context.
    Best-effort — returns whatever we can parse; if the session log
    is missing we return a stub note so the verifier can still
    produce a (likely "uncertain") verdict rather than crashing.
    """
    # Sessions live under <trial_dir>/agent/sessions/projects/*/; the
    # latest .jsonl is the agent's run log.
    sessions_root = trial_dir / "agent" / "sessions" / "projects"
    if not sessions_root.exists():
        return "<no agent session log found>"

    jsonls = sorted(
        sessions_root.glob("*/*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not jsonls:
        return "<no agent session log found>"

    # Approximate: extract the last ~50 records (all of them for short
    # runs; a budget-capped subset for long ones). The verifier's
    # judgment is about the sub-task's *last* state, so the most
    # recent activity is the most informative.
    out_lines: list[str] = []
    try:
        with open(jsonls[0], "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Compact representation: type + content snippet
                rtype = rec.get("type", "?")
                content = rec.get("message", {}).get("content", "")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                content = block.get("text", "")
                                break
                            if block.get("type") == "tool_use":
                                content = (
                                    f"[tool_use:{block.get('name','?')}] "
                                    f"{json.dumps(block.get('input', {}))[:200]}"
                                )
                                break
                if isinstance(content, str):
                    out_lines.append(f"{rtype}: {content[:300]}")
    except Exception:  # noqa: BLE001
        return "<agent session log read failed>"
    return "\n".join(out_lines[-50:])


# ---------------------------------------------------------------------------
# Public: hook registration
# ---------------------------------------------------------------------------
def attach_paper_registers(
    job: Job,
    method: MethodConfig,
    wiring: ContainerWiringHandle | None = None,
) -> None:
    """Wire the per-subtask hook and the per-trial Q-update.

    Registers two Harbor lifecycle hooks on the job:

    - ``on_trial_started`` (only if ``wiring`` is provided) — calls
      :func:`wire_one_trial` to dump fresh state to the trial
      directory, inject the ``MG_*`` env vars into the agent
      config, and bind-mount the hook script + ``settings.json``
      into the container.
    - ``on_trial_ended`` — reads the per-subtask hook log, calls
      :class:`SubTaskVerifier` per unique (skill, trial) pair,
      applies Eq. 6 (global Q variant) with ``w_subtask * r_subtask
      + w_task * r_task`` as the target, and maintains the lib.

    Both callbacks swallow exceptions (the bridge's safety net so a
    bug in the method never aborts the trial).

    ``wiring=None`` is the legacy / unit-test mode: per-subtask hook
    is not registered, so on_trial_started is skipped. The
    end-of-trial Q-update still runs, but the Q-table won't
    observe per-Skill-call outcomes (it'll only see the trial's
    overall reward via r_task).
    """
    lib = Qlib(b_max=method.b_max)
    mgr = LibManager(
        b_max=method.b_max,
        theta_admit=method.theta_admit,
        theta_evict=method.theta_evict,
        n_explore=method.n_explore,
        n_stale=method.n_stale,
    )
    # State + emb_cache load
    state = QlibState(method.resolved_state_path())
    state.load_into(lib, mgr, lib_root=method.library_root)
    emb_cache = VectorTable(method.resolved_state_path().parent / "emb_cache.json")
    emb_cache.load()

    # IndependentVerifier (still used for r_learning on near-miss
    # edits — Eq. 6's `r_learning` term, which is per-skill-content
    # delta and is computed only when a near-miss edit actually
    # fires).
    verifier = IndependentVerifier(
        backend=LiteLLMVerifierBackend(model=method.verifier_model),
        model=method.verifier_model,
    )
    refiner = NearMissRefiner(
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
        )
        if method.enable_auto_extract
        else None
    )
    extract_buffer = _ExtractBuffer(n_trials_threshold=method.extract_every_n_trials)

    # Sub-task verifier
    sub_task_verifier = SubTaskVerifier(
        backend=LiteLLMSubTaskVerifierBackend(
            model=method.q_subtask_verifier_model
        ),
        model=method.q_subtask_verifier_model,
    )

    # Track which lib mutates fired this on_ended call (so we can
    # batch emb_cache refresh at the end).
    lib_changes_this_trial: list[tuple[str, str, str]] = []  # (action, sid, body)

    expected_terminal_trials = len(job)

    async def _flush_buffer() -> None:
        batch = extract_buffer.flush()
        if not batch:
            return
        try:
            new_skill = await extractor.extract_batch(  # type: ignore[union-attr]
                trials=batch,
                available_skill_names=[s.skill_id for s in lib.skills.values()],
            )
        except Exception:
            logger.exception("extract_batch subprocess crashed; batch discarded.")
            return
        if new_skill is None:
            logger.info(
                "extract_batch returned no skill (LLM skipped or LLM "
                "output failed); batch of %d records discarded.",
                len(batch),
            )
            return
        if new_skill.skill_id in lib:
            logger.warning(
                "extract_batch produced skill %s which is already in lib; "
                "skipping lib.add.",
                new_skill.skill_id,
            )
            return
        new_skill.admission_exempt = True
        lib.add(new_skill)
        # Seed Q on the new skill (global, no per-intent).
        mgr.set_q(new_skill.skill_id, method.new_skill_initial_q)
        # Schedule emb_cache refresh for the new skill.
        lib_changes_this_trial.append(("add", new_skill.skill_id, new_skill.body))
        logger.info(
            "Batched extract created skill %s (Q_init=%.2f) from %d trials",
            new_skill.skill_id,
            method.new_skill_initial_q,
            len(batch),
        )

    async def on_ended(event: TrialHookEvent) -> None:
        nonlocal lib_changes_this_trial

        if event.result is None:
            return
        if event.result.exception_info is not None:
            return
        if _is_retryable_failure(event, job.config.retry):
            logger.debug(
                "Skipping paper method for retryable failed trial %s",
                event.trial_id,
            )
            return

        try:
            r_task = _harbor_r_task(event.result)
            intent_text = event.task_name or _trial_dir(event).name
            trial_dir = _trial_dir(event)

            # ---- Per-subtask Q-update (new) ----
            # 1. Read the hook's calls log (one record per Skill
            #    invocation the agent made during this trial).
            # 2. For each unique (skill, trial) pair, slice the
            #    session log around the call's ts and ask the
            #    sub-task verifier whether the sub-task completed.
            # 3. Aggregate by mean and apply Eq. 6 (global-Q
            #    variant).
            calls_log = _read_skill_calls_log(
                trial_dir / "mg_skill_calls.jsonl"
            )
            by_skill: dict[str, list[_SubTaskCallRecord]] = defaultdict(list)
            for c in calls_log:
                if not c.skill_id:
                    continue
                by_skill[c.skill_id].append(c)

            sub_task_log_entries: list[dict[str, Any]] = []
            if not by_skill:
                # No Skill calls in this trial — Q-table unchanged.
                # Still log this as a no-op for debug.
                if method.debug_keep_subtask_log:
                    sub_task_log_entries.append(
                        {
                            "trial": event.trial_id,
                            "skill": "<none>",
                            "calls": 0,
                            "verdicts": [],
                            "r_subtask_mean": 0.0,
                            "r_task": r_task,
                            "q_delta": 0.0,
                        }
                    )
            else:
                for skill_id, calls in by_skill.items():
                    if skill_id not in lib:
                        # Skill was in the agent's view at call time
                        # but has since been evicted. Skip — we don't
                        # Q-update a skill that no longer exists.
                        continue
                    verdicts = []
                    for call in calls:
                        trace = _slice_sub_task_trace(trial_dir, call.ts)
                        skill = lib.get(skill_id)
                        # We pass the description, not the body. The
                        # judge evaluates goal completion, not body
                        # quality.
                        from paper.method.vector_table import _description_of

                        desc = _description_of(skill.body) if skill else ""
                        verdict = sub_task_verifier.score(
                            task=intent_text,
                            skill_id=skill_id,
                            skill_description=desc,
                            sub_task_trace=trace,
                        )
                        verdicts.append(verdict)
                    r_subtask_mean = mean_r_subtask(verdicts)
                    # Eq. 6 (global-Q variant):
                    q_old = mgr.q_for(skill_id)
                    target = method.q_w_subtask * r_subtask_mean + method.q_w_task * r_task
                    delta = method.q_alpha * (target - q_old)
                    mgr.update_q(skill_id, delta)
                    # Bump per-skill counters
                    skill_obj = lib.get(skill_id)
                    if skill_obj is not None:
                        skill_obj.n_uses += 1
                        if r_task > 0.5:
                            skill_obj.n_success += 1
                    # Debug log
                    if method.debug_keep_subtask_log:
                        sub_task_log_entries.append(
                            {
                                "trial": event.trial_id,
                                "skill": skill_id,
                                "calls": len(calls),
                                "verdicts": [
                                    {
                                        "ts": v.confidence,
                                        "success": v.success,
                                        "confidence": v.confidence,
                                        "rationale": v.rationale,
                                    }
                                    for v in verdicts
                                ],
                                "r_subtask_mean": r_subtask_mean,
                                "r_task": r_task,
                                "q_delta": delta,
                            }
                        )
                    logger.info(
                        "Q-update skill=%s calls=%d r_subtask_mean=%+.2f "
                        "r_task=%.2f q_old=%+.3f -> q_new=%+.3f",
                        skill_id,
                        len(calls),
                        r_subtask_mean,
                        r_task,
                        q_old,
                        q_old + delta,
                    )

            # ---- Auto-extract (create_skill path) — unchanged ----
            attribution = attribution_analyzer.analyze(
                task=intent_text,
                trial_dir=trial_dir,
                skills_root=_find_skills_dir(event),
            )
            if (
                extractor is not None
                and r_task > 0.5
                and attribution.overall_attribution
                in (
                    Attribution.SUCCESS_VIEWED_SKILL_BUT_NOT_USED,
                    Attribution.SUCCESS_NO_SKILL_SEEN,
                )
                and not any(
                    mgr.q_for(s) > method.theta_consider_used for s in lib.skills
                )
                and attribution.knowledge_to_extract.strip()
            ):
                batch = extract_buffer.add(
                    task=intent_text,
                    knowledge=attribution.knowledge_to_extract,
                )
                if batch:
                    await _flush_buffer()
                if (
                    extract_buffer
                    and (state.step + 1) >= expected_terminal_trials
                ):
                    await _flush_buffer()

            # ---- Library maintenance ----
            # Detect lib changes so we can refresh emb_cache after
            # maintain() runs (it may evict skills).
            skills_before = set(lib.skills.keys())
            mgr.maintain(lib, current_step=state.step + 1)
            skills_after = set(lib.skills.keys())
            evicted = skills_before - skills_after
            for sid in evicted:
                lib_changes_this_trial.append(("remove", sid, ""))
                if sid in mgr.q_table:
                    del mgr.q_table[sid]

            # Refresh emb_cache in response to lib changes from
            # this trial. Done once at the end (not per change) to
            # batch embedding API calls.
            if lib_changes_this_trial:
                try:
                    from paper.method.retrieval import LiteLLMEmbedder

                    embedder = LiteLLMEmbedder(
                        model=method.embedder_model,
                        dim=int(getattr(method, "embedder_dim", 1536)),
                    )
                    added = [
                        (sid, body) for action, sid, body in lib_changes_this_trial
                        if action == "add" and body
                    ]
                    removed = [
                        sid for action, sid, _ in lib_changes_this_trial
                        if action == "remove"
                    ]
                    from paper.method.vector_table import sync_lib_to_vector_table

                    sync_lib_to_vector_table(
                        added=added,
                        removed=removed,
                        vector_table=emb_cache,
                        embedder=embedder,
                    )
                    emb_cache.save()
                except Exception:  # noqa: BLE001
                    logger.exception("emb_cache refresh failed; continuing.")

            state.step += 1
            state.save(
                lib,
                mgr,
                lib_root=method.library_root,
                seed_initial_q=method.seed_initial_q,
                sub_task_log=sub_task_log_entries,
                debug_keep_subtask_log=method.debug_keep_subtask_log,
            )

            # ---- Near-miss refine (Layer 4) ----
            if r_task == 0.0 and lib.skills:
                # Pick the skill with the highest Q for this trial's
                # intent — closest to the paper's "best skill" notion
                # in the global-Q world.
                top = max(
                    lib.skills.values(),
                    key=lambda s: mgr.q_for(s.skill_id),
                    default=None,
                )
                if top is not None:
                    current_q = mgr.q_for(top.skill_id)
                    if refiner.is_near_miss(r_task, current_q, method.theta_near_miss):
                        new_skill = refiner.propose_edit(
                            skill=top,
                            task=intent_text,
                            failure_trace=str(trial_dir),
                        )
                        if new_skill is not top:
                            lib.replace(new_skill)
                            # Near-miss edit triggers a description
                            # re-embed if the description changed.
                            from paper.method.vector_table import (
                                _description_of,
                                sync_lib_to_vector_table,
                            )
                            old_desc = _description_of(top.body)
                            new_desc = _description_of(new_skill.body)
                            if old_desc != new_desc:
                                try:
                                    from paper.method.retrieval import LiteLLMEmbedder
                                    embedder = LiteLLMEmbedder(
                                        model=method.embedder_model,
                                        dim=int(getattr(method, "embedder_dim", 1536)),
                                    )
                                    sync_lib_to_vector_table(
                                        replaced=[(new_skill.skill_id, top.body, new_skill.body)],
                                        vector_table=emb_cache,
                                        embedder=embedder,
                                    )
                                    emb_cache.save()
                                except Exception:  # noqa: BLE001
                                    logger.exception("emb_cache refresh after near-miss failed; continuing.")
                            logger.info(
                                "Near-miss refined skill %s for trial %s",
                                new_skill.skill_id,
                                event.trial_id,
                            )
        except Exception:
            # Never let a method bug abort the trial.
            logger.exception(
                "Paper method on_ended failed for trial %s; swallowed.",
                event.trial_id,
            )

    # ---- on_trial_started: container wiring (issue #2) ----
    if wiring is not None:
        async def on_trial_started(event: TrialHookEvent) -> None:
            try:
                wire_one_trial(wiring, event)
            except Exception:
                # Fail-soft: hook env is nice-to-have, not a hard
                # dependency. The trial can still run (without the
                # per-subtask retrieval) if wiring fails.
                logger.exception(
                    "Container wiring for trial %s failed; trial will run without hook.",
                    event.trial_id,
                )

        job.on_trial_started(on_trial_started)
    job.on_trial_ended(on_ended)


# ---------------------------------------------------------------------------
# Public: high-level entry
# ---------------------------------------------------------------------------
async def run_paper_job(job_config_path: Path, method: MethodConfig) -> int:
    """Create a Harbor Job, start the embed daemon, attach the
    per-subtask hook, run, and tear down.

    Issue #2 (container wiring) lifecycle:

    1. :func:`start_container_wiring` boots the host-side FastAPI
       embed daemon. If the API key is missing we propagate the
       error.
    2. :func:`Job.create` instantiates the trial queue.
    3. :func:`attach_paper_registers` registers both
       ``on_trial_started`` (per-trial hook wiring) and
       ``on_trial_ended`` (per-subtask Q-update).
    4. ``await job.run()`` drives the trial queue.
    5. ``finally`` - :func:`stop_container_wiring` tears down the
       daemon and its thread, regardless of whether ``job.run``
       raised.
    """
    from harbor import Job
    from harbor.cli.utils import run_async  # type: ignore[attr-defined]
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

    # Start the embed daemon BEFORE creating the Job so the
    # daemon's host:port is known by the time on_trial_started
    # runs for the first trial. ``wiring`` is None when
    # EMBEDDING_API_KEY isn't set — the trial still runs, but the
    # per-subtask hook is not installed.
    wiring = start_container_wiring(method)
    job = await Job.create(job_cfg)
    try:
        attach_paper_registers(job, method, wiring)
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


def run_paper_job_sync(job_config_path: Path, method: MethodConfig) -> int:
    """Synchronous wrapper around :func:`run_paper_job`."""
    return asyncio.run(run_paper_job(job_config_path, method))
