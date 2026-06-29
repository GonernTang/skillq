"""Runtime context + accumulator types — Step 4 (2026-06-26) refactor.

This module defines the **three datatypes** the new closure-free
``runtime/bridge.py`` and ``runtime/steps.py`` pipeline operates on:

- :class:`MethodServices` — long-lived service handles (lib, mgr,
  emb_cache, state, method, attribution_analyzer, refiner, extractor,
  extract_buffer, expected_terminal_trials). One instance per job;
  constructed once in :func:`skillq.runtime.bridge.attach_registers`
  and shared across every trial.

- :class:`TrialContext` — per-trial **immutable** snapshot. Built
  from a Harbor ``TrialHookEvent`` + the services bag. Frozen
  dataclass so step functions can't accidentally mutate trial-level
  state — only :class:`StepResult` is mutable.

- :class:`StepResult` — per-trial **mutable** accumulator. Each
  step writes a small piece of state (Q-update entries, attribution
  verdict, edit proposal, dispatch decision, lib changes). The next
  trial re-initialises a fresh :class:`StepResult` (this is the
  fix for the latent ``lib_changes_this_trial`` non-reset bug in
  the legacy ``bridge.py`` closure).

The split mirrors the SkillsVote harbor-as-kernel pattern: Harbor
hands the kernel a :class:`TrialHookEvent`; the kernel builds the
context, runs the pipeline, writes the per-trial artifact, and
returns. Step functions are **pure** with respect to ``ctx`` — they
read from it, they don't mutate it. Mutations go through
``services`` (long-lived handles) or ``result`` (per-trial
accumulator). This is what "closure-free" means in practice.

Why a separate ``context.py``:

- ``bridge.py`` should orchestrate, not type-define. Putting these
  dataclasses here means ``steps.py`` and ``bridge.py`` import a
  tiny module rather than each defining its own copy.
- Tests can build a :class:`TrialContext` directly and call any
  single :func:`step_xxx` without spinning up a Harbor Job.
- Step 5's new ``runtime/hook.py`` reads :class:`MethodServices`
  to inject env vars — same types, no glue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from skillq.layers.l3_attribution.analyzer import TrialAttribution
from skillq.layers.l4_evolve.extract_buffer import ExtractBuffer
from skillq.shared.classify_trial_failure import TrialFailureClass
from skillq.shared.embeddings import VectorTable
from skillq.shared.library import LibManager
from skillq.shared.types import Qlib

if TYPE_CHECKING:
    from skillq.config import MethodConfig
    from skillq.layers.l3_attribution.analyzer import AttributionAnalyzer
    from skillq.layers.l3_attribution.edit import EditRefiner
    from skillq.layers.l4_evolve.create import SkillExtractor
    from skillq.shared.library import QlibState


@dataclass
class TrialContext:
    """Per-trial **mostly-immutable** snapshot.

    Built once at the top of :func:`skillq.runtime.bridge.on_trial_ended`
    from a Harbor ``TrialHookEvent`` + the job-level
    :class:`MethodServices`. Step functions read from this and don't
    mutate the *identification* fields (``trial_id`` / ``trial_dir`` /
    ``intent_text`` / ``r_task`` / ``services``) — those are stable for
    the whole trial. The ``failure`` field is the one exception: it's
    populated by :func:`runtime.steps.step_classify_failure` at the
    head of the pipeline and read by downstream steps to decide whether
    to skip the trial. We keep it mutable so step 1 can set it
    in-place without building a new ``TrialContext`` (which would
    force every step to take a separate ``failure`` parameter).

    Attributes
    ----------
    trial_id
        ``event.trial_id``. Used for log lines + per-trial artifact
        filenames.
    trial_dir
        Host-side directory containing this trial's artifacts
        (resolved from ``event.result.trial_uri``). Most steps
        read subpaths like ``trial_dir / "agent" / "sessions"
        / "skillq_skill_calls.jsonl"`` and ``trial_dir /
        "skillq_state"``.
    intent_text
        Best-effort human-readable description of what the agent
        was supposed to do. Used by the attribution analyzer
        (``task=intent_text``) and the L4 extract buffer
        (``task=intent_text``). Falls back to ``trial_dir.name``
        when ``event.task_name`` is empty.
    r_task
        Binarised trial-level reward from the verifier
        (``0`` = failed, ``1`` = passed, ``0`` = no reward /
        cancelled). Computed by the legacy ``_harbor_r_task``
        helper — same semantics.
    failure
        Trial-failure classification (see
        :class:`skillq.shared.classify_trial_failure.TrialFailureClass`).
        Set by :func:`runtime.steps.step_classify_failure` at the
        head of the pipeline; downstream steps read it to decide
        whether to skip the trial. ``None`` until step 1 runs.
    services
        Long-lived job-level handle bag. See :class:`MethodServices`.
    event
        The Harbor :class:`TrialHookEvent` (typed ``Any`` to avoid
        pulling in the heavy harbor.models import for type
        checkers). Step 1 reads ``event.result.exception_info`` to
        drive :func:`classify_trial_failure`. The classifier was
        originally event-driven; the new pipeline passes the event
        via this field rather than re-deriving exception_info from
        the already-baked ``r_task``. This was a Step 1 fix
        (2026-06-27, Step 7 of the 4-layer refactor) — without it
        :func:`step_classify_failure` would always short-circuit
        to ``SKIP_ALL`` because ``event=None`` failed
        ``event.result is None``.
        Stable for the whole trial; we never reassign it; we only
        mutate its ``lib`` / ``mgr`` / ``emb_cache`` / ``state``
        fields (which are mutable dataclasses).
    """

    trial_id: str
    trial_dir: Path
    intent_text: str
    r_task: int
    failure: TrialFailureClass | None = None
    services: "MethodServices" = None  # type: ignore[assignment]
    event: Any = None  # Harbor TrialHookEvent; see field docstring above


@dataclass
class MethodServices:
    """Long-lived job-level service handles.

    One instance per job. Constructed by
    :func:`skillq.runtime.bridge.attach_registers` and shared
    across every trial's :class:`TrialContext`. Mutable by
    design — the in-memory lib / Q-table / emb_cache grow and
    shrink as trials run.

    Why this dataclass exists separately from :class:`TrialContext`:

    - It can be built **once** at job start (the legacy closure
      built it inside ``attach_paper_registers`` too, but the
      closure made it impossible to inspect from outside).
    - Step 5's :mod:`runtime.hook` reads it to seed ``app.state``
      in the ranking service daemon.
    - Tests can construct one with a tiny seed lib and pass it
      to a pipeline run — no need to spin up Harbor.

    Attributes
    ----------
    lib
        :class:`Qlib` — the live in-memory skill library. Mutated
        by ``step_maintain_lib`` (Q-driven eviction) and
        ``step_dispatch_evolve`` (Rule 2 + Rule 5 add).
    mgr
        :class:`LibManager` — Q-table + UCB bookkeeping. Mutated
        by ``step_q_update`` (``mgr.update_q``) and
        ``step_maintain_lib`` (``mgr.maintain``).
    emb_cache
        :class:`VectorTable` — per-skill description embeddings.
        Mutated by ``step_refresh_emb_cache`` (after lib changes).
    state
        :class:`QlibState` — ``method_state.json`` writer. Step
        ``step_save_state`` calls ``state.save(...)`` at the end of
        every trial to atomically persist the post-edit lib + Q-table.
    method
        :class:`MethodConfig` — the parsed method YAML / CLI
        arguments. Pure read-only after construction.
    attribution_analyzer
        :class:`AttributionAnalyzer` — L3 verdict engine. Always
        called in :func:`step_attribute` (the L3 edit gate reads
        the verdict even when L4 is disabled).
    refiner
        :class:`EditRefiner` — L3 in-place edit. Called by
        ``step_incremental_edit`` when the verdict is
        ``FAILURE_SKILL_USED``.
    extractor
        :class:`SkillExtractor` or ``None`` — L4 batched
        ``claude --print`` subprocess. ``None`` when the user
        sets ``method.enable_auto_extract=False``.
    extract_buffer
        :class:`ExtractBuffer` — Rule 2 + Rule 5 record queue.
        :meth:`ExtractBuffer.add` in
        :func:`step_dispatch_evolve`, :meth:`ExtractBuffer.flush`
        in the same step when the threshold is hit.
    expected_terminal_trials
        ``len(job)`` at job-create time. Used by
        ``step_dispatch_evolve`` to force-flush the buffer on the
        very last trial so a near-full buffer doesn't get
        discarded at job end.
    """

    lib: Qlib
    mgr: LibManager
    emb_cache: VectorTable
    state: "QlibState"
    method: "MethodConfig"
    attribution_analyzer: "AttributionAnalyzer"
    refiner: "EditRefiner"
    extractor: "SkillExtractor | None"
    extract_buffer: ExtractBuffer
    expected_terminal_trials: int


@dataclass
class StepResult:
    """Per-trial **mutable** accumulator.

    Re-initialised at the top of every :func:`on_trial_ended` call
    so each trial sees a clean accumulator. This is the fix for
    the legacy ``lib_changes_this_trial`` non-reset bug (it lived
    on the closure and was reset by ``nonlocal``; under the new
    pipeline we get the same behaviour for free because the
    dataclass is re-constructed).

    Attributes
    ----------
    q_updates
        Per-skill Q-update entries from :func:`step_q_update`.
        Each entry is a dict ``{trial, skill, calls, r_task,
        q_old, q_delta, q_new, cosine_sim}``. Written to
        ``<trial_dir>/skillq_state/q_updates.jsonl`` inside
        :func:`step_q_update` itself (for durability); this
        attribute is kept for tests + future traces.
    attribution
        :class:`TrialAttribution` verdict from
        :func:`step_attribute`. Cached here so
        :func:`step_incremental_edit` can read it without
        re-running the analyzer (saves a duplicate LLM call).
        ``None`` until ``step_attribute`` runs.
    lib_changes
        ``(action, skill_id, body)`` triples accumulated during
        the trial. ``action`` is one of ``"add"`` (from
        :func:`step_dispatch_evolve` after a batched extract)
        or ``"remove"`` (from :func:`step_maintain_lib` when
        ``mgr.maintain`` evicts a low-Q skill). Consumed by
        :func:`step_refresh_emb_cache` to update the embedding
        cache without re-embedding unchanged skills.
    edited_skill_id
        ``skill_id`` of the skill replaced by
        :func:`step_incremental_edit`. ``None`` if no edit
        fired. Used by ``step_save_state`` log lines.
    dispatched_mode
        ``"success"`` / ``"failure"`` / ``None`` — the most
        recent mode added to the extract buffer this trial.
        Useful for tracing; not consumed by downstream steps.
    """

    q_updates: list[dict[str, Any]] = field(default_factory=list)
    attribution: TrialAttribution | None = None
    lib_changes: list[tuple[str, str, str]] = field(default_factory=list)
    edited_skill_id: str | None = None
    dispatched_mode: str | None = None


__all__ = [
    "MethodServices",
    "TrialContext",
    "StepResult",
]