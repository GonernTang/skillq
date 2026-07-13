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
5. :func:`step_incremental_edit` — L3 EditRefiner (gated on
   ``FAILURE_SKILL_USED``)
6. :func:`step_dispatch_evolve` — L4 rule table + extract buffer
7. :func:`step_refresh_emb_cache` — batched emb_cache update
8. :func:`step_save_state` — atomic ``method_state.json`` write
   + defensive ``emb_cache.save()``

**Pipeline invariant (2026-07-01, see
``tests/test_pipeline_emb_cache_ordering.py``)**:
``step_refresh_emb_cache`` is position 7 and must remain
AFTER every lib-mutating step (:func:`step_maintain_lib`,
:func:`step_incremental_edit`, :func:`step_dispatch_evolve`)
and BEFORE :func:`step_save_state`. The previous position-5
ordering lost L4 additions to ``emb_cache.json`` in the same
trial — see [[emb-cache-ordering-bug]].

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
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from skillq.layers.l3_attribution.models import Attribution, TrialAttribution
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
    #    2026-07-01 (Bug #51/#52 fix): the per-trial calls log now
    #    lives at ``<trial_dir>/agent/sessions/_calls_log/skillq_skill_calls.jsonl``
    #    (the bind-mounted RW dir from
    #    :func:`skillq.runtime.container_wiring._wire_hook_trial`).
    #    The old library-scoped path is gone — 4 concurrent trials
    #    sharing it caused write races / empty files.
    calls_log = _read_skill_calls_log(
        ctx.trial_dir / "agent" / "sessions" / "_calls_log" / "skillq_skill_calls.jsonl"
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
    """Run L3 attribution — always calls LLM for knowledge extraction.

    The LLM receives the full session trace plus the list of current
    library skill IDs (``available_skill_ids``) so it can reliably
    detect whether a skill was used.  After the LLM returns, the
    calls_log is used as ground truth to correct misclassified
    verdicts (``FAILURE_SKILL_NOT_USED`` / ``FAIL_ENV_ISSUE`` →
    ``FAILURE_SKILL_USED`` when a lib skill was actually called).

    knowledge_to_extract from the LLM is always preserved — even
    when the verdict is overridden — because it contains the raw
    material for L3 skill edits and L4 new-skill creation.
    """
    # Read calls_log for ground-truth skill usage check.
    _log = (
        ctx.trial_dir / "agent" / "sessions"
        / "_calls_log" / "skillq_skill_calls.jsonl"
    )
    _calls = _read_skill_calls_log(_log)
    if not _calls:
        _calls = _extract_skill_calls_from_session(ctx.trial_dir)
    _approved = [
        c for c in _calls
        if c.skill_id and not c.denied
        and c.skill_id in ctx.services.lib
    ]

    # Build available skill list from the in-memory library.
    skill_ids = list(ctx.services.lib.skills.keys())
    logger.warning(
        "step_attribute: trial=%s r_task=%d approved_calls=%d lib_skills=%d",
        ctx.trial_id, ctx.r_task, len(_approved), len(skill_ids),
    )

    try:
        attribution = ctx.services.attribution_analyzer.analyze(
            task=ctx.intent_text,
            trial_dir=ctx.trial_dir,
            available_skill_ids=skill_ids,
            r_task=ctx.r_task,
        )
    except Exception:
        logger.exception(
            "attribution call failed for trial %s; using fallback verdict",
            ctx.trial_id,
        )
        attribution = TrialAttribution(
            overall_attribution=(
                Attribution.SUCCESS_NO_SKILL_SEEN if ctx.r_task
                else Attribution.FAILURE_SKILL_USED
            ),
            overall_rationale="[attribution-fallback] model call failed",
            knowledge_to_extract="",
        )

    # If calls_log proves a lib skill was used but the LLM returned a
    # mismatch, correct the verdict.  knowledge_to_extract is preserved.
    if ctx.r_task == 0 and _approved:
        if attribution.overall_attribution not in (
            Attribution.FAILURE_SKILL_USED,
        ):
            logger.warning(
                "attribution verdict override: trial=%s LLM=%s but "
                "calls_log shows %d approved Skill() call(s) (first=%s) "
                "→ clamped to failure_skill_used",
                ctx.trial_id, attribution.overall_attribution.value,
                len(_approved), _approved[0].skill_id,
            )
            attribution = attribution.model_copy(update={
                "overall_attribution": Attribution.FAILURE_SKILL_USED,
                "overall_rationale": (
                    f"[calls-log-override] r_task=0, {len(_approved)} "
                    f"Skill() calls detected, LLM returned "
                    f"{attribution.overall_attribution.value}; "
                    f"coerced to failure_skill_used. "
                    f"{attribution.overall_rationale}"
                ),
            })

    logger.warning(
        "attribution verdict: trial=%s r_task=%d overall=%s "
        "knowledge_chars=%d",
        ctx.trial_id, ctx.r_task,
        attribution.overall_attribution.value,
        len(attribution.knowledge_to_extract),
    )

    result.attribution = attribution

    # Persist for post-hoc analysis.
    try:
        attr_path = ctx.trial_dir / "skillq_state" / "attribution_result.json"
        attr_path.parent.mkdir(parents=True, exist_ok=True)
        attr_path.write_text(
            json.dumps(
                attribution.model_dump(mode="json"), ensure_ascii=False
            )
            + "\n",
            encoding="utf-8",
        )
    except Exception:
        logger.exception(
            "Failed to persist attribution_result.json for trial %s",
            ctx.trial_id,
        )



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
    :func:`step_maintain_lib` (removes),
    :func:`step_incremental_edit` (replaces), and
    :func:`step_dispatch_evolve` (adds)) and writes a single
    end-of-trial snapshot.

    Pipeline invariant (2026-07-01): this step must run AFTER
    every lib-mutating step and BEFORE :func:`step_save_state`.
    Previously it ran at position 5, BEFORE
    :func:`step_dispatch_evolve` at position 7; L4 Create
    additions never reached ``emb_cache.json`` in the same
    trial (see [[emb-cache-ordering-bug]]).

    Best-effort: a cache-refresh failure logs and continues —
    the trial's lib / Q-table are unaffected. A redundant
    defensive ``save()`` is also issued at the very end of
    :func:`step_save_state` for the last-trial safety net.
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
        # "replace" carries only (skill_id, new_body). sync_lib_to_vector_table
        # wants (skill_id, old_body, new_body) — old_body is not
        # needed for the embed (only new is used), so pass an empty
        # string; it's unused inside the function.
        replaced = [
            (sid, "", body) for action, sid, body in changes
            if action == "replace" and body
        ]
        removed = [
            sid for action, sid, _ in changes
            if action == "remove"
        ]
        sync_lib_to_vector_table(
            added=added,
            replaced=replaced,
            removed=removed,
            vector_table=services.emb_cache,
            embedder=embedder,
        )
        services.emb_cache.save()
    except Exception:  # noqa: BLE001
        logger.exception("emb_cache refresh failed; continuing.")


# ---------------------------------------------------------------------------
# Step 6: incremental_edit (L4 — edit existing skill on FAILURE_SKILL_USED)
# ---------------------------------------------------------------------------
async def step_incremental_edit(ctx: "TrialContext", result: "StepResult") -> None:
    """L4 in-place edit when the failing trial's attribution
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
    logger.warning(
        "L3 incremental_edit: trial=%s diagnosis_chars=%d",
        ctx.trial_id, len(diagnosis),
    )
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

    # 2026-07-09: Q-value continuity on edit — a rewritten skill body
    # should not inherit the old Q-value wholesale (a bad skill with
    # Q=0.1 would stay stuck; a good skill with Q=0.8 would coast).
    # Decay toward the neutral prior (Q_init=0.5) proportional to
    # the edit distance: the more the body changed, the less history
    # is carried forward. Falls back to a moderate 0.5 decay when
    # embedding is unavailable.
    _old_q = services.mgr.q_for(new_skill.skill_id)
    if abs(_old_q - method.seed_initial_q) > 0.01:
        try:
            _emb = LiteLLMEmbedder(
                model=method.embedder_model,
                dim=int(getattr(method, "embedder_dim", 1536)),
            )
            _vecs = _emb([top.body[:2000], new_skill.body[:2000]])  # type: ignore[arg-type]
            _edit_dist = max(
                0.0,
                float(_cosine(_vecs[0].tolist(), _vecs[1].tolist())),
            )
        except Exception:
            _edit_dist = 0.5
        _new_q = _old_q * _edit_dist + method.seed_initial_q * (1.0 - _edit_dist)
        services.mgr.set_q(new_skill.skill_id, _new_q)
        logger.info(
            "L3 edit: skill=%s Q %.3f→%.3f (edit_dist=%.3f)",
            new_skill.skill_id, _old_q, _new_q, _edit_dist,
        )

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

    # 2026-07-01: funnel the edit through result.lib_changes so
    # step_refresh_emb_cache (which now runs LAST, after both L3
    # edit and L4 create) writes a single end-of-trial snapshot.
    # This fixes the emb_cache ordering bug: previously edits
    # re-embedded inline but L4 Create at pos 7 appended to
    # lib_changes AFTER the pos-5 emb_cache.save, so L4 additions
    # never reached disk in the same trial. Funnelling both
    # mutations through lib_changes means the SINGLE end-of-
    # pipeline refresh sees the full diff.
    #
    # Only push when the frontmatter description changed: a
    # no-op edit (editor returned a body identical to the top
    # skill's) doesn't need a re-embed.
    if _description_of(top.body) != _description_of(new_skill.body):
        result.lib_changes.append(
            ("replace", new_skill.skill_id, new_skill.body)
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

    # Fix 2 (2026-07-01, small10 gap 2): cross-check the "no skill used"
    # verdict against the container's PreToolUse calls_log. The LLM
    # occasionally misclassifies *_NO_SKILL_SEEN / *_SKILL_NOT_USED when
    # the agent actually called and used a skill present in the library.
    # calls_log is objective evidence — when the LLM and calls_log
    # disagree on "was a lib skill called+approved?" we trust calls_log
    # and skip L4 (no harvest, no buffer add).
    if attribution.overall_attribution in (
        Attribution.SUCCESS_NO_SKILL_SEEN,
        Attribution.FAILURE_SKILL_NOT_USED,
    ):
        _log_path = (
            ctx.trial_dir
            / "agent"
            / "sessions"
            / "_calls_log"
            / "skillq_skill_calls.jsonl"
        )
        _calls = _read_skill_calls_log(_log_path)
        if not _calls:
            _calls = _extract_skill_calls_from_session(ctx.trial_dir)
        _approved_lib_calls = [
            c for c in _calls
            if c.skill_id and not c.denied and c.skill_id in services.lib
        ]
        if _approved_lib_calls:
            logger.warning(
                "l4_dispatch_enum_override: trial=%s enum=%s but calls_log "
                "shows %d approved Skill() call(s) against lib skill(s) "
                "(first=%s) — verdict contradicted, skipping L4.",
                ctx.trial_id,
                attribution.overall_attribution.value,
                len(_approved_lib_calls),
                _approved_lib_calls[0].skill_id,
            )
            return

    knowledge = attribution.knowledge_to_extract.strip()
    gap_description = attribution.library_gap_skill_description.strip()
    triggered = False

    if not knowledge:
        if attribution.overall_attribution in (
            Attribution.SUCCESS_NO_SKILL_SEEN,
            Attribution.FAILURE_SKILL_NOT_USED,
        ):
            logger.warning(
                "l4_dispatch_skipped_empty_knowledge: trial=%s enum=%s "
                "(knowledge_to_extract empty); no seed for the buffer.",
                ctx.trial_id,
                attribution.overall_attribution.value,
            )
        return

    if knowledge:
        if (
            ctx.r_task
            and attribution.overall_attribution == Attribution.SUCCESS_NO_SKILL_SEEN
        ):
            logger.warning(
                "l4_dispatch_rule2_success: trial=%s knowledge_chars=%d",
                ctx.trial_id, len(knowledge),
            )
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
            logger.warning(
                "l4_dispatch_rule5_failure: trial=%s knowledge_chars=%d",
                ctx.trial_id, len(knowledge),
            )
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


def _write_extract_failure(
    trial_dir: Path,
    trial_id: str,
    mode: str,
    n_records: int,
    reason: str,
    task: str = "",
    knowledge: str = "",
) -> None:
    """Write an extract-failure record to the trial's audit log.

    Fix C (2026-07-01, small10 gap 4): previously extract_batch
    failures only appeared in the host logger — invisible in
    trial_dir. Now each failure appends a JSONL line to
    ``<trial_dir>/skillq_state/extract_failures.jsonl`` so the
    audit trail is self-contained per trial.
    """
    state_dir = trial_dir / "skillq_state"
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(state_dir / "extract_failures.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.time(),
                "trial_id": trial_id,
                "mode": mode,
                "n_records": n_records,
                "reason": reason,
                "task": task[:300],
                "knowledge": knowledge[:300],
            }) + "\n")
    except OSError:
        logger.warning(
            "Failed to write extract_failures.jsonl for trial %s",
            trial_id,
            exc_info=True,
        )


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
            _write_extract_failure(
                ctx.trial_dir, ctx.trial_id, mode,
                len(batch), "subprocess crashed",
                task=batch[0].get("task", "") if batch else "",
                knowledge=batch[0].get("knowledge", "") if batch else "",
            )
            continue
        if new_skill is None:
            logger.info(
                "extract_batch returned no skill (mode=%s, LLM skipped or "
                "output failed); batch of %d records discarded.",
                mode,
                len(batch),
            )
            _write_extract_failure(
                ctx.trial_dir, ctx.trial_id, mode,
                len(batch), "extract_batch returned None",
                task=batch[0].get("task", "") if batch else "",
                knowledge=batch[0].get("knowledge", "") if batch else "",
            )
            continue
        if new_skill.skill_id in services.lib:
            # -- name-collision resolution (Fix A, 2026-07-01) --
            # Instead of discarding the entire batch (previous behaviour),
            # version the skill name until we find a free slot.
            # Example: meeting-scheduler → meeting-scheduler__v2
            #
            # This preserves the new skill's body (distilled from fresh
            # trial experience) even when the LLM picks a name that
            # collides with a seed skill.
            new_id = f"{new_skill.skill_id}__v2"
            suffix = 2
            while new_id in services.lib:
                suffix += 1
                new_id = f"{new_skill.skill_id}__v{suffix}"
            logger.info(
                "extract_batch produced skill name %s (collision); renamed to %s.",
                new_skill.skill_id,
                new_id,
            )
            new_skill = replace(new_skill, skill_id=new_id)
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

    # 2026-07-01 defensive save: ensure emb_cache.json is written
    # even if step_refresh_emb_cache's save was skipped (e.g. empty
    # lib_changes or upstream cache layer swallowed an exception).
    # This is the last-trial safety net: small10 run #1 lost 8 L4
    # additions because the inline save fired before the L4 create
    # appended to lib_changes. With the reorder, that path is
    # closed; this is just belt-and-suspenders.
    try:
        services.emb_cache.save()
    except Exception:  # noqa: BLE001
        logger.exception(
            "defensive emb_cache.save() at end of step_save_state failed; "
            "the upstream step_refresh_emb_cache save (if any) is still on disk."
        )


# ---------------------------------------------------------------------------
# Pipeline — the order of execution at every on_trial_ended event
# ---------------------------------------------------------------------------
ON_TRIAL_ENDED_PIPELINE = (
    step_classify_failure,
    step_q_update,
    step_attribute,
    step_maintain_lib,
    step_incremental_edit,
    step_dispatch_evolve,
    step_refresh_emb_cache,
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