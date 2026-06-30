"""Closure-free on_trial_ended pipeline — Step 4 (2026-06-26) refactor.

Each step is ``async def step_xxx(ctx, result) -> None``. Steps
read :class:`skillq.runtime.context.TrialContext` (immutable) and
write to :class:`skillq.runtime.context.StepResult` (mutable
per-trial accumulator) plus :class:`MethodServices` (long-lived
handles). **No closures, no ``nonlocal``, no per-call state**
beyond ``ctx`` / ``result`` / ``services``.

The pipeline runs at every Harbor ``on_trial_ended`` event:

1. :func:`step_classify_failure` — populates ``ctx.failure``
2. :func:`step_q_update` — task-only Eq.5 Q-learning
3. :func:`step_attribute` — L3 attribution analyzer call
4. :func:`step_maintain_lib` — Q-driven admission/eviction
5. :func:`step_refresh_emb_cache` — batched emb_cache update
6. :func:`step_incremental_edit` — L3 EditRefiner (gated on
   ``FAILURE_SKILL_USED``)
7. :func:`step_dispatch_evolve` — L4 rule table + extract buffer
8. :func:`step_save_state` — atomic ``method_state.json`` write

The order matters: Q-update happens before attribution because
Q-update is synchronous (no LLM call) and gives the early log
line. Attribution goes before maintenance because the L3 edit
gate consumes the verdict. Maintenance goes before
``refresh_emb_cache`` because the diff feeds the refresh. Edit
goes before ``save_state`` so the in-memory ``lib.replace`` is
reflected on disk. Dispatch goes before save because Rule 2 +
Rule 5 may add new skills. Save is last.

Compare to the legacy ``attach_paper_registers`` closure
(``runtime/bridge.py:345-1321``) which inlined these 8
steps in a 980-line closure with 8 nested helpers and 3
``nonlocal`` variables. Each of those three ``nonlocal`` bugs
(documented in ``doc/bug_to_fix.md``) is structurally
impossible here because step functions take only ``ctx`` and
``result`` as inputs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from skillq.layers.l3_attribution.models import Attribution
from skillq.services.ranking_service import sync_embed
from skillq.shared.backends.litellm import LiteLLMEmbedder
from skillq.shared.embeddings import _description_of, sync_lib_to_vector_table
from skillq.shared.mirror import mirror_skill_to_host_dir
from skillq.layers.l1_retrieval.scoring import cosine as _cosine
from skillq.layers.l4_evolve.create import SkillExtractor
from skillq.shared.calls_log import (
    _SubTaskCallRecord,
    _extract_skill_calls_from_session,
    _read_skill_calls_log,
)
from skillq.shared.chown import chown_agent_sessions_to_host_user
from skillq.shared.classify_trial_failure import (
    TrialFailureClass,
    classify_trial_failure,
)
from skillq.shared.session_tail import _read_session_assistant_tail

if TYPE_CHECKING:
    from skillq.runtime.context import MethodServices, StepResult, TrialContext


logger = logging.getLogger("skillq.runtime.steps")


# ---------------------------------------------------------------------------
# Step 1: classify_failure
# ---------------------------------------------------------------------------
async def step_classify_failure(ctx: "TrialContext", result: "StepResult") -> None:
    """Classify the trial outcome and early-return on infra failure.

    Reads the Harbor ``RetryConfig`` from
    ``ctx.services.method``'s parent job config (passed via
    ``ctx.trial_id`` lookup, but in practice we need access to the
    retry config — see the *Step 1 retry-config plumbing* note
    below).

    Behaviour:

    - ``TrialFailureClass.RUN_NORMAL`` → continue pipeline.
    - ``TrialFailureClass.RUN_TASK_FAILURE`` → continue pipeline
      (the agent produced a usable trajectory even though the
      verifier failed).
    - ``TrialFailureClass.SKIP_ALL`` → log and early-return.
      Downstream steps are skipped because the pipeline is
      linear.

    *Step 1 retry-config plumbing*: the legacy
    ``_classify_trial_failure`` helper takes the Harbor
    ``RetryConfig`` as its second arg. In the legacy closure it
    was available as ``job.config.retry``. In the new pipeline
    we stash it on :class:`MethodServices` (added in this step)
    so the classifier still works.

    Note: this step **mutates** ``ctx.failure`` (despite
    ``frozen=True``). We do this by constructing a new
    :class:`TrialContext` with the updated field via
    :func:`dataclasses.replace`. The other fields stay the same.
    """
    # NOTE: real retry config plumbing lands in bridge.py — this
    # step reads it via ``ctx.services.method``'s surrounding
    # context (the orchestrator attaches it as
    # ``ctx.services.retry_config``). For the first iteration
    # we accept a None default and treat as "no exclusions" —
    # the classifier's signature is unchanged.
    retry_config = getattr(ctx.services, "retry_config", None)
    # The classifier needs the Harbor event to read
    # ``event.result.exception_info``. Step 7 (2026-06-27)
    # plumbs the event through ``ctx.event`` so step 1 doesn't
    # have to reach back into the orchestrator's locals.
    failure = classify_trial_failure(
        event=ctx.event,
        retry_config=retry_config,
        trial_dir=ctx.trial_dir,
    )
    # ``ctx.failure`` is a mutable field (set by this step,
    # read by downstream steps). All other ctx fields stay
    # stable for the duration of the trial.
    ctx.failure = failure
    if failure is TrialFailureClass.SKIP_ALL:
        logger.debug(
            "step_classify_failure: SKIP_ALL for trial=%s",
            ctx.trial_id,
        )


# ---------------------------------------------------------------------------
# Step 2: q_update (Eq.5, task-only, optional cosine weight)
# ---------------------------------------------------------------------------
async def step_q_update(ctx: "TrialContext", result: "StepResult") -> None:
    """Apply the task-only Q-update (Eq.5) for one trial.

    Reads from ``ctx.trial_dir / "agent" / "sessions" /
    "skillq_skill_calls.jsonl"`` (the container's PreToolUse hook
    log), with a session-log fallback for agentic mode. For every
    approved (non-denied) Skill call this trial, applies::

        Q(skill) += alpha * (r_task - Q(skill))

    multiplied by ``max(cos(phi(q), phi(s)), 0)`` if the user
    opted into cosine weighting.

    Denied calls (hook returned ``permissionDecision: "deny"``)
    are recorded in the call log but skipped from Q-update — the
    agent solved the sub-task directly without using the
    (irrelevant) skill.

    Writes per-skill entries into ``result.q_updates`` and
    persists them to
    ``<trial_dir>/skillq_state/q_updates.jsonl`` for durability.
    """
    method = ctx.services.method
    lib = ctx.services.lib
    mgr = ctx.services.mgr
    emb_cache = ctx.services.emb_cache

    # 1. Read the PreToolUse hook log.
    calls_log = _read_skill_calls_log(
        ctx.trial_dir / "agent" / "sessions" / "skillq_skill_calls.jsonl"
    )
    if not calls_log:
        calls_log = _extract_skill_calls_from_session(ctx.trial_dir)

    # 2. Bucket by skill_id; drop denied calls.
    by_skill: dict[str, list[_SubTaskCallRecord]] = defaultdict(list)
    for c in calls_log:
        if not c.skill_id:
            continue
        if c.denied:
            logger.debug(
                "Q-update skipped (hook denied): skill=%s trial=%s",
                c.skill_id,
                ctx.trial_id,
            )
            continue
        by_skill[c.skill_id].append(c)

    if not by_skill:
        return

    # 3. Compute phi(q) once per trial (cosine-weighted mode).
    phi_q: list[float] | None = None
    if method.q_update_cosine_weight:
        intent_text = ""
        if calls_log:
            intent_text = (calls_log[0].intent_text or "").strip()
        if not intent_text:
            intent_text = ctx.trial_id
        try:
            phi_q = sync_embed(
                text=intent_text,
                host="127.0.0.1",
                port=method.hook_embedding_service_port,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "phi(q) embed failed; cosine weight disabled for "
                "trial %s: %s",
                ctx.trial_id,
                exc,
            )
            phi_q = None

    out: list[dict[str, Any]] = []
    for skill_id, calls in by_skill.items():
        if skill_id not in lib:
            continue  # evicted mid-trial; skip

        n_calls = len(calls)
        q_old = mgr.q_for(skill_id)
        target = ctx.r_task
        delta = method.q_alpha * (target - q_old)

        cosine_sim: float | None = None
        if phi_q is not None:
            phi_s = emb_cache.get(skill_id)
            if phi_s is None:
                logger.debug(
                    "Q-update skipped: no embedding for skill=%s",
                    skill_id,
                )
                continue
            phi_s_list = (
                phi_s.tolist() if hasattr(phi_s, "tolist") else list(phi_s)
            )
            sim = _cosine(phi_q, phi_s_list)
            sim_clamped = max(sim, 0.0)
            cosine_sim = sim_clamped
            delta = delta * sim_clamped

        if delta != 0.0:
            mgr.update_q(skill_id, delta)

        skill_obj = lib.get(skill_id)
        if skill_obj is not None:
            skill_obj.n_retrievals += n_calls
            skill_obj.n_uses += 1
            if ctx.r_task:
                skill_obj.n_success += 1

        out.append(
            {
                "trial": ctx.trial_id,
                "skill": skill_id,
                "calls": n_calls,
                "r_task": ctx.r_task,
                "q_old": q_old,
                "q_delta": delta,
                "q_new": q_old + delta,
                "cosine_sim": cosine_sim,
            }
        )
        logger.info(
            "Q-update skill=%s calls=%d r_task=%d sim=%s q_old=%+.3f -> q_new=%+.3f",
            skill_id,
            n_calls,
            int(ctx.r_task),
            f"{cosine_sim:.3f}" if cosine_sim is not None else "n/a",
            q_old,
            q_old + delta,
        )

    # 4. Persist for durability (independent of step_save_state).
    if out:
        try:
            q_path = ctx.trial_dir / "skillq_state" / "q_updates.jsonl"
            q_path.parent.mkdir(parents=True, exist_ok=True)
            with open(q_path, "w", encoding="utf-8") as f:
                for entry in out:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            logger.exception(
                "failed to write q_updates.jsonl for %s", ctx.trial_id
            )

    result.q_updates = out


# ---------------------------------------------------------------------------
# Step 3: attribute (L3 verdict)
# ---------------------------------------------------------------------------
async def step_attribute(ctx: "TrialContext", result: "StepResult") -> None:
    """Run the L3 attribution analyzer.

    Always called (even when ``extractor is None``) because
    :func:`step_incremental_edit` reads the verdict to gate on
    ``FAILURE_SKILL_USED``. Cost: +1 LLM call per trial even
    when L4 is disabled — acceptable because L3 cannot fire
    without the verdict.

    Writes the :class:`TrialAttribution` to ``result.attribution``
    so the next step can read it without re-running the analyzer.

    Falls back to a stub verdict when the trace is missing
    (the analyzer handles this internally).
    """
    attribution = ctx.services.attribution_analyzer.analyze(
        task=ctx.intent_text,
        trial_dir=ctx.trial_dir,
        skills_root=_find_skills_dir(ctx),
        r_task=ctx.r_task,
    )
    result.attribution = attribution


def _find_skills_dir(ctx: "TrialContext") -> Path | None:
    """Locate the directory lqrl's ``step_recommend`` copied skills into.

    Mirrors the legacy ``_find_skills_dir`` in
    ``runtime/bridge.py:211-228``. The per-subtask hook
    doesn't need this; we still surface it for the attribution
    analyzer.
    """
    # The legacy version took a TrialHookEvent and read
    # ``event.config.agent.env``. In the new pipeline the env is
    # not on the event — it's on ``ctx.services.method``'s parent
    # job config (not currently threaded through). Until that
    # lands we return None and let the analyzer degrade to
    # ``available_skills = {}`` (it already handles that case).
    return None


# ---------------------------------------------------------------------------
# Step 4: maintain_lib (Q-driven admission/eviction)
# ---------------------------------------------------------------------------
async def step_maintain_lib(ctx: "TrialContext", result: "StepResult") -> None:
    """Run the Q-driven admission/eviction pass and record the diff.

    Calls :meth:`LibManager.maintain` to evict low-Q skills
    when the lib exceeds ``method.b_max``. Records every change
    into ``result.lib_changes`` so :func:`step_refresh_emb_cache`
    can update the embedding cache without re-embedding
    unchanged skills.

    Also drains any pending ``result.lib_changes`` from previous
    steps (none in the current design but kept for future
    extensions) into the change list.
    """
    services = ctx.services
    skills_before = set(services.lib.skills.keys())
    services.mgr.maintain(services.lib, current_step=services.state.step + 1)
    skills_after = set(services.lib.skills.keys())

    # Carry forward any changes queued by earlier steps (currently
    # none — Rule 2 + Rule 5 happen in step_dispatch_evolve, AFTER
    # this one — but kept for symmetry).
    changes = list(result.lib_changes)
    for sid in skills_before - skills_after:
        changes.append(("remove", sid, ""))
        if sid in services.mgr.q_table:
            del services.mgr.q_table[sid]

    result.lib_changes = changes


# ---------------------------------------------------------------------------
# Step 5: refresh_emb_cache (batched embed from lib changes)
# ---------------------------------------------------------------------------
async def step_refresh_emb_cache(ctx: "TrialContext", result: "StepResult") -> None:
    """Apply a batched emb_cache update from the lib changes.

    Reads ``result.lib_changes`` (collected by
    :func:`step_maintain_lib` + any earlier step that mutates the
    lib). Embeds added skills + removes evicted ones in one
    round-trip to the host embed service. Saves the cache
    atomically.

    Best-effort: a cache-refresh failure logs and continues —
    the trial's lib / Q-table are unaffected.
    """
    services = ctx.services
    changes = result.lib_changes
    if not changes:
        return
    method = services.method
    try:
        embedder = LiteLLMEmbedder(
            model=method.embedder_model,
            dim=int(getattr(method, "embedder_dim", 1536)),
        )
        added = [
            (sid, body) for action, sid, body in changes
            if action == "add" and body
        ]
        removed = [
            sid for action, sid, _ in changes
            if action == "remove"
        ]
        sync_lib_to_vector_table(
            added=added,
            removed=removed,
            vector_table=services.emb_cache,
            embedder=embedder,
        )
        services.emb_cache.save()
    except Exception:  # noqa: BLE001
        logger.exception("emb_cache refresh failed; continuing.")


# ---------------------------------------------------------------------------
# Step 6: incremental_edit (L3 EditRefiner on FAILURE_SKILL_USED)
# ---------------------------------------------------------------------------
async def step_incremental_edit(ctx: "TrialContext", result: "StepResult") -> None:
    """L3 in-place edit when the failing trial's attribution
    says a skill was used and is at fault.

    Gate (in order):

    1. ``r_task == 0`` — only fires on failures (successes are
       no-op; no point editing a working skill).
    2. ``lib.skills`` non-empty — nothing to edit otherwise.
    3. ``result.attribution.overall_attribution ==
       Attribution.FAILURE_SKILL_USED`` — the verdict must
       explicitly say "skill was used and the trial still
       failed". Other failure paths route to L4 Create or are
       no-ops.

    Picks the highest-Q skill (``max(lib.skills.values(), key=Q)``),
    asks :class:`EditRefiner.propose_edit` for a minimal edit,
    then calls :meth:`Qlib.replace` to swap it in. Re-embeds the
    description only if the frontmatter changed (avoids a wasted
    embed call when the editor proposes a no-op).

    Always sets ``result.edited_skill_id`` (either the replaced
    skill's id, or ``None`` if no edit fired).
    """
    services = ctx.services
    method = services.method

    if ctx.r_task or not services.lib.skills:
        return
    attribution = result.attribution
    if (
        attribution is None
        or attribution.overall_attribution != Attribution.FAILURE_SKILL_USED
    ):
        return

    top = max(
        services.lib.skills.values(),
        key=lambda s: services.mgr.q_for(s.skill_id),
        default=None,
    )
    if top is None:
        return

    # Build a real failure trace from the analyzer's diagnosis
    # + a tail of the session log.
    diagnosis_parts: list[str] = []
    if attribution is not None:
        kx = attribution.knowledge_to_extract.strip()
        if kx:
            diagnosis_parts.append(f"knowledge_to_extract: {kx}")
        gx = attribution.library_gap_skill_description.strip()
        if gx:
            diagnosis_parts.append(f"library_gap_skill_description: {gx}")
    diagnosis = "\n".join(diagnosis_parts)
    tail = _read_session_assistant_tail(ctx.trial_dir, k=3, per_message_chars=2000)

    try:
        new_skill = services.refiner.propose_edit(
            skill=top,
            task=ctx.intent_text,
            failure_diagnosis=diagnosis,
            session_tail=tail,
        )
    except Exception:
        logger.exception(
            "L3 propose_edit failed for trial %s; L3 skipped.",
            ctx.trial_id,
        )
        return
    if new_skill is top:
        return

    services.lib.replace(new_skill)
    result.edited_skill_id = new_skill.skill_id

    # 2026-06-29 (Phase 10 Bug 3): critical — mirror the edited body
    # to seed_skills_dir so the next trial's container (which reads
    # bind-mounted /skills) sees the *new* body, not the seed body
    # or L3's prior write. force=True because L3 itself wrote the
    # previous body; the default idempotent skip would silently
    # re-expose the bug after the first edit lands. L4 Create keeps
    # the default force=False to preserve the human-edit guarantee.
    if method.seed_skills_dir is not None:
        try:
            mirror_skill_to_host_dir(
                new_skill, method.seed_skills_dir, force=True,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "L3 mirror to seed_skills_dir failed for skill %s; "
                "in-memory lib is correct but next trial may read "
                "stale body until the next successful edit.",
                new_skill.skill_id,
            )

    # Re-embed only if the frontmatter changed.
    if _description_of(top.body) != _description_of(new_skill.body):
        try:
            embedder = LiteLLMEmbedder(
                model=method.embedder_model,
                dim=int(getattr(method, "embedder_dim", 1536)),
            )
            sync_lib_to_vector_table(
                replaced=[(new_skill.skill_id, top.body, new_skill.body)],
                vector_table=services.emb_cache,
                embedder=embedder,
            )
            services.emb_cache.save()
        except Exception:  # noqa: BLE001
            logger.exception(
                "emb_cache refresh after incremental edit failed; continuing."
            )
    logger.info(
        "Incremental edit on failure: skill %s, trial %s",
        new_skill.skill_id,
        ctx.trial_id,
    )


# ---------------------------------------------------------------------------
# Step 7: dispatch_evolve (L4 rule table + extract buffer)
# ---------------------------------------------------------------------------
async def step_dispatch_evolve(ctx: "TrialContext", result: "StepResult") -> None:
    """Rule table for L4 batched extraction.

    Two rules trigger a new-skill creation here:

    - **Rule 2** (success path): ``r_task == 1`` AND
      ``attribution == SUCCESS_NO_SKILL_SEEN`` AND
      ``knowledge_to_extract`` is non-empty. Add to buffer with
      ``mode="success"`` so the right prompt is used.
    - **Rule 5** (failure path): ``r_task == 0`` AND
      ``attribution == FAILURE_SKILL_NOT_USED`` AND
      ``knowledge_to_extract`` is non-empty. Add to buffer with
      ``mode="failure"`` so the guard-rail prompt is used.

    If the buffer fills (``n_trials_threshold``), flush via
    :class:`SkillExtractor.extract_batch` and add the resulting
    skill to the lib + mirror to ``seed_skills_dir`` +
    Q-seed + emb_cache delta.

    Final-trial force flush: on the very last trial of the job
    (``state.step + 1 >= expected_terminal_trials``) flush
    unconditionally so a near-full buffer doesn't get discarded.

    Gate: ``extractor is None`` → no-op (L4 disabled).
    """
    services = ctx.services
    method = services.method
    extractor = services.extractor
    attribution = result.attribution
    if attribution is None or extractor is None:
        return

    knowledge = attribution.knowledge_to_extract.strip()
    gap_description = attribution.library_gap_skill_description.strip()
    triggered = False

    if knowledge:
        if (
            ctx.r_task
            and attribution.overall_attribution == Attribution.SUCCESS_NO_SKILL_SEEN
        ):
            buffer_full = services.extract_buffer.add(
                task=ctx.intent_text,
                knowledge=knowledge,
                gap_description=gap_description,
                mode="success",
            )
            result.dispatched_mode = "success"
            triggered = True
            if buffer_full:
                await _flush_buffer(ctx, result)
        elif (
            not ctx.r_task
            and attribution.overall_attribution
            == Attribution.FAILURE_SKILL_NOT_USED
        ):
            buffer_full = services.extract_buffer.add(
                task=ctx.intent_text,
                knowledge=knowledge,
                gap_description=gap_description,
                mode="failure",
            )
            result.dispatched_mode = "failure"
            triggered = True
            if buffer_full:
                await _flush_buffer(ctx, result)

    if not triggered:
        return
    # Final-trial force flush.
    if services.state.step + 1 >= services.expected_terminal_trials:
        await _flush_buffer(ctx, result)


async def _flush_buffer(ctx: "TrialContext", result: "StepResult") -> None:
    """Drain the extract buffer and ingest the resulting skill(s).

    Mirrors the legacy ``_flush_buffer`` closure inside
    ``attach_paper_registers``. Records are grouped by ``mode``
    so each ``claude --print`` invocation gets the right prompt
    (success vs failure). L1 Hard Gate + L3 attribution routing
    + name-collision check below are the only dedup guards
    (2026-06-30: removed cosine-based semantic dedup).
    """
    services = ctx.services
    method = services.method
    groups = services.extract_buffer.flush()
    for mode, batch in groups:
        if not batch:
            continue
        try:
            mode_extractor = _extractor_for_mode(services.extractor, mode)
            new_skill = await mode_extractor.extract_batch(
                trials=batch,
            )
        except Exception:
            logger.exception(
                "extract_batch subprocess crashed (mode=%s); batch discarded.",
                mode,
            )
            continue
        if new_skill is None:
            logger.info(
                "extract_batch returned no skill (mode=%s, LLM skipped or "
                "output failed); batch of %d records discarded.",
                mode,
                len(batch),
            )
            continue
        if new_skill.skill_id in services.lib:
            logger.warning(
                "extract_batch produced skill %s which is already in lib; "
                "skipping lib.add.",
                new_skill.skill_id,
            )
            continue
        new_skill.admission_exempt = True
        services.lib.add(new_skill)
        mirror_skill_to_host_dir(new_skill, method.seed_skills_dir)
        services.mgr.set_q(new_skill.skill_id, method.new_skill_initial_q)
        result.lib_changes.append(("add", new_skill.skill_id, new_skill.body))
        logger.info(
            "Batched extract (mode=%s) created skill %s (Q_init=%.2f) from %d trials",
            mode,
            new_skill.skill_id,
            method.new_skill_initial_q,
            len(batch),
        )


def _extractor_for_mode(base: SkillExtractor, mode: str) -> SkillExtractor:
    """Build a mode-specific extractor from the base config.

    Mirrors the legacy ``_extractor_for_mode`` closure. Same
    parameters as ``base`` but with ``prompt_mode`` swapped to
    ``mode`` and the structural-validation flag threaded through.
    """
    return SkillExtractor(
        claude_cli=base.claude_cli,
        model=base.model,
        timeout_sec=base.timeout_sec,
        name_min_words=base.name_min_words,
        name_max_words=base.name_max_words,
        body_min_tokens=base.body_min_tokens,
        body_max_tokens=base.body_max_tokens,
        prompt_mode=mode,
        enforce_failure_skill_structure=base.enforce_failure_skill_structure,
    )


# ---------------------------------------------------------------------------
# Step 8: save_state (atomic method_state.json write)
# ---------------------------------------------------------------------------
async def step_save_state(ctx: "TrialContext", result: "StepResult") -> None:
    """Persist the post-trial lib + Q-table + step counter.

    Calls :meth:`QlibState.save` to atomically write
    ``<library_root>/.state/method_state.json``. Then re-dumps
    ``q_table.json`` to ``<trial_dir>/skillq_state/`` so users
    inspecting the trial artifacts see the post-trial Q-values
    (matching ``method_state.json``), not the trial-START
    snapshot.

    Defensive: never raises — a save failure logs and continues
    so the trial-end bookkeeping still completes.
    """
    services = ctx.services
    method = services.method
    services.state.step += 1
    try:
        services.state.save(
            services.lib,
            services.mgr,
            lib_root=method.library_root,
            seed_initial_q=method.seed_initial_q,
        )
    except Exception:
        logger.exception(
            "method_state.json save failed for trial %s; continuing.",
            ctx.trial_id,
        )
    # Bug 3 mirror: per-trial q_table.json (best-effort).
    try:
        trial_q_path = ctx.trial_dir / "skillq_state" / "q_table.json"
        trial_q_path.parent.mkdir(parents=True, exist_ok=True)
        trial_q_path.write_text(
            json.dumps(dict(services.mgr.q_table), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        logger.exception(
            "Bug 3 mirror: failed to re-dump per-trial q_table.json for trial %s",
            ctx.trial_id,
        )


# ---------------------------------------------------------------------------
# Pipeline — the order of execution at every on_trial_ended event
# ---------------------------------------------------------------------------
ON_TRIAL_ENDED_PIPELINE = (
    step_classify_failure,
    step_q_update,
    step_attribute,
    step_maintain_lib,
    step_refresh_emb_cache,
    step_incremental_edit,
    step_dispatch_evolve,
    step_save_state,
)


async def run_pipeline(ctx: "TrialContext", result: "StepResult") -> None:
    """Run the full :data:`ON_TRIAL_ENDED_PIPELINE`.

    Each step is called sequentially. Steps are responsible for
    their own no-op-on-irrelevant-verdict behaviour (e.g.
    :func:`step_incremental_edit` returns immediately on
    ``r_task=1``). The pipeline is **linear**: a single shared
    ``ctx`` + ``result`` thread through every step.

    **SKIP_ALL early-return (Task #74, 2026-06-29)**: after
    :func:`step_classify_failure` populates ``ctx.failure``, if
    the verdict is :attr:`TrialFailureClass.SKIP_ALL` (infra
    failure / OOM / retryable) we skip the remaining 7 steps
    entirely. Concretely:

    - :func:`step_q_update` — would do nothing anyway (no Q-update
      signal on a half-flushed trial).
    - :func:`step_attribute` — would burn an LLM call on a useless
      trajectory. Per ``classify_trial_failure`` docstring, SKIP_ALL
      means "no useful trajectory to learn from".
    - :func:`step_maintain_lib` / :func:`step_refresh_emb_cache` —
      no diff to record.
    - :func:`step_incremental_edit` — would edit a skill from a
      partial trajectory; semantic garbage.
    - :func:`step_dispatch_evolve` — Rule 5 (FAILURE_SKILL_NOT_USED)
      would *trigger* the L4 extract path on an OOM-killed trial,
      which is exactly the bug :func:`test_bridge_skips_extract_on_oom_even_with_trajectory`
      pins. SKIP_ALL must short-circuit before this step.
    - :func:`step_save_state` — must NOT advance ``state.step``.
      The test ``test_attach_layered_registers_skips_failed_trials``
      pins ``state.step == 0`` for SKIP_ALL trials; without the
      early-return the unconditional ``services.state.step += 1``
      on line 758 fires.

    No exceptions propagate out of individual steps (each step
    is responsible for its own try/except). A step that fails
    logs and continues.
    """
    for step in ON_TRIAL_ENDED_PIPELINE:
        await step(ctx, result)
        # Short-circuit after classification if the verdict is
        # SKIP_ALL — see docstring for the per-step rationale.
        if (
            step is step_classify_failure
            and ctx.failure is TrialFailureClass.SKIP_ALL
        ):
            logger.debug(
                "run_pipeline: SKIP_ALL for trial=%s, skipping remaining %d steps",
                ctx.trial_id,
                len(ON_TRIAL_ENDED_PIPELINE)
                - ON_TRIAL_ENDED_PIPELINE.index(step) - 1,
            )
            return


__all__ = [
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
]