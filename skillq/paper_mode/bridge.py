"""Bridge between Harbor's trial-event stream and the four-layer method
(per-subtask hook refactor, 2026-06-11).

Two public functions:

- :func:`attach_paper_registers` — wires Harbor's per-trial lifecycle
  hooks for the paper method: ``on_trial_started`` (container
  wiring — see :mod:`paper.paper_mode.container_wiring`) and
  ``on_trial_ended`` (per-trial Q-update + library maintenance).
- :func:`run_paper_job` — high-level orchestrator that creates a Harbor
  :class:`Job`, starts the host-side embedding daemon, attaches both
  hooks, runs the job, and tears down the daemon in a try/finally.

**Simplified Q-update (2026-06-23)**:

- The Q-table is keyed by ``skill_id`` (single global value per
  skill). Eq. 4 reads it as ``mgr.q_table[skill_id]``; the Q-update
  writes to the same key.
- Skill calls are recovered from the container's PreToolUse hook
  log (``skillq_skill_calls.jsonl``), with a session-log fallback
  for agentic mode (no hook installed).
- The Q-update is now standard Eq.5 (task-only reward)::

      Q(skill) += alpha * (r_task - Q(skill))

  with ``r_task`` ∈ {0, 1} (binarized trial-level verifier reward).
  The pre-2026-06-23 path used an LLM judge to score each Skill()
  call as ``r_subtask`` ∈ {0, 1} and blended it with ``r_task``,
  but with pull-mode Top-K injection the agent typically calls
  exactly one skill per trial — so ``r_subtask`` collapsed to a
  binary that was almost always identical to ``r_task``, and the
  judge call was wasted compute.

**Container wiring lifecycle** (issue #2 fix):

- :func:`run_paper_job` calls :func:`start_container_wiring` BEFORE
  ``Job.create`` to spin up the FastAPI embed daemon.
- :func:`attach_paper_registers` registers an ``on_trial_started``
  hook that calls :func:`wire_one_trial` — re-dumps state, injects
  ``SKILLQ_*`` env vars, bind-mounts hook script + settings.json into
  the container.
- :func:`run_paper_job`'s try/finally calls
  :func:`stop_container_wiring` to stop the daemon cleanly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from harbor.job import Job
from harbor.models.trial.result import TrialResult
from harbor.trial.hooks import TrialHookEvent
from omegaconf import OmegaConf

from skillq.method.attribution import (
    Attribution,
    AttributionAnalyzer,
    LiteLLMAttributionBackend,
)
from skillq.method.editor_backend import LiteLLMEditBackend
from skillq.method.embedding_service import sync_embed
from skillq.method.extractor import SkillExtractor
from skillq.method.library import LibManager
from skillq.method.near_miss import NearMissRefiner
from skillq.method.retrieval import LiteLLMEmbedder
from skillq.method.skill_mirror import mirror_skill_to_host_dir
from skillq.method.state import QlibState
from skillq.method.vector_table import (
    _description_of,
    sync_lib_to_vector_table,
)
from skillq.method.types import Qlib, Skill
from skillq.method.vector_table import VectorTable
from skillq.paper_mode.config import MethodConfig
from skillq.paper_mode.container_wiring import (
    ContainerWiringHandle,
    start_container_wiring,
    stop_container_wiring,
    wire_one_trial,
)
from skillq.paper_mode.hook import _cosine  # per-pair cosine for Q-update weight

logger = logging.getLogger("paper.paper.bridge")


# ---------------------------------------------------------------------------
# Trial-level helpers
# ---------------------------------------------------------------------------
def _harbor_r_task(result: TrialResult) -> int:
    """Extract the binary trial reward from a Harbor TrialResult.

    Returns ``0`` if the result has no verifier reward (e.g. cancelled),
    ``1`` if the verifier passed, ``0`` if it failed. The value is
    rounded to ``int`` at the source — TB 2.0 tasks' ``tests/test.sh``
    already write ``0`` or ``1`` to ``/logs/verifier/reward.txt``, so
    we treat the harbor schema's ``float`` type as semantically binary.

    Callers should use the return value directly as a boolean
    (``if r_task:`` = success).
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


def resolve_retrieval_mode(method: "MethodConfig", n_lib_skills: int) -> str:
    """Resolve the effective retrieval mode for an ``on_trial_started``
    call.

    The config field ``retrieval_mode`` is one of:

    - ``"agentic"`` — Method A. Returned verbatim.
    - ``"hook"``    — Method B (PreToolUse only). Returned verbatim.
    - ``"pull"``    — Method B + SessionStart inject (2026-06-23).
      Returned as ``"hook"`` since the wiring is identical except
      for the extra ``hooks.SessionStart`` entry that
      ``container_wiring._settings_json_path`` adds when
      ``method.retrieval_mode == "pull"``.
    - ``"auto"``    — picks ``"agentic"`` if the current lib has
      fewer than ``method.library_size_threshold`` skills, else
      ``"hook"``. Decided at the start of each trial (per design
      choice 2026-06-14).
    """
    mode = method.retrieval_mode
    if mode == "auto":
        return "agentic" if n_lib_skills < method.library_size_threshold else "hook"
    if mode == "pull":
        return "hook"
    return mode


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
    """Buffer of (task, knowledge, mode) records awaiting a batched-extract flush.

    ``mode`` is one of:

    - ``"success"`` — the knowledge came from a successful trajectory
      (Rule 2: unused + success → new skill). Uses
      :data:`paper.method.prompts.BATCHED_EXTRACT_SKILL_PROMPT`.
    - ``"failure"`` — the knowledge came from a failure attribution
      (Rule 5: unused + failure → new skill). Uses
      :data:`paper.method.prompts.BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT`.

    Records with different modes are flushed into separate batches
    so each ``claude --print`` invocation gets the right prompt.
    """

    n_trials_threshold: int
    pending: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        *,
        task: str,
        knowledge: str,
        mode: str = "success",
    ) -> bool:
        """Add a record. Returns ``True`` when the buffer has hit its
        threshold (caller should then call :meth:`flush`).
        """
        if not knowledge.strip():
            return False
        self.pending.append({"task": task, "knowledge": knowledge, "mode": mode})
        return len(self.pending) >= self.n_trials_threshold

    def flush(self) -> list[tuple[str, list[dict[str, Any]]]]:
        """Drain everything, grouped by mode."""
        if not self.pending:
            return []
        return self._drain_by_mode()

    def _drain_by_mode(self) -> list[tuple[str, list[dict[str, Any]]]]:
        out: list[tuple[str, list[dict[str, Any]]]] = []
        for mode in ("success", "failure"):
            batch = [r for r in self.pending if r.get("mode", "success") == mode]
            if batch:
                # Strip the internal "mode" key from the records that go
                # to the extractor (it doesn't read it).
                out.append(
                    (mode, [{k: v for k, v in r.items() if k != "mode"} for r in batch])
                )
        self.pending = []
        return out

    def __len__(self) -> int:
        return len(self.pending)

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
    Each record represents one Skill() call the agent made; the
    Q-update path groups by ``skill_id`` and counts calls per skill
    to drive ``n_retrievals`` and the Eq.5 update.
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


def _extract_skill_calls_from_session(trial_dir: Path) -> list[_SubTaskCallRecord]:
    """Fallback per-skill signal source for agentic mode (no PreToolUse
    hook installed).

    Scans the trial's Claude Code session log under
    ``<trial_dir>/agent/sessions/projects/*/*.jsonl`` for ``tool_use``
    blocks whose ``name`` is ``Skill``, and returns one
    :class:`_SubTaskCallRecord` per invocation. Fields that the session
    log does not provide (``top_k``, ``ts``, ``intent_text``) are
    filled with empty defaults — the Q-update path only needs
    ``skill_id``.

    Always enabled (not gated on retrieval_mode): even in hook mode
    this serves as a safety net if the host-side ``skillq_skill_calls.jsonl``
    mount was read-only and the hook failed to write.

    Best-effort — silently returns ``[]`` on any structural failure
    (missing dir, missing files, malformed JSON lines).
    """
    sessions_root = trial_dir / "agent" / "sessions" / "projects"
    if not sessions_root.exists():
        return []
    # Use the most recent session jsonl (latest mtime).
    try:
        jsonls = sorted(
            (p for p in sessions_root.glob("*/*.jsonl")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return []
    if not jsonls:
        return []
    out: list[_SubTaskCallRecord] = []
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
                # Claude Code session entries look like:
                #   {"type": "assistant", "message": {"content":
                #       [{"type": "tool_use", "name": "Skill",
                #         "input": {"skill": "..."}}]}}
                msg = rec.get("message", {})
                if not isinstance(msg, dict):
                    continue
                content = msg.get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    if block.get("name") != "Skill":
                        continue
                    inp = block.get("input", {}) or {}
                    skill_name = str(inp.get("skill", "")).strip()
                    if not skill_name:
                        continue
                    out.append(
                        _SubTaskCallRecord(
                            skill_id=skill_name,
                            requested=skill_name,
                            top_k=[],          # not available from session log
                            approved=True,     # if it's in the log, the agent called it
                            ts=0.0,            # not available
                            intent_text="",    # not available
                        )
                    )
    except OSError:
        return out
    return out


# ---------------------------------------------------------------------------
# Public: hook registration
# ---------------------------------------------------------------------------
def attach_paper_registers(
    job: Job,
    method: MethodConfig,
    wiring: ContainerWiringHandle | None = None,
) -> None:
    """Wire the PreToolUse hook and the per-trial Q-update.

    Registers two Harbor lifecycle hooks on the job:

    - ``on_trial_started`` (only if ``wiring`` is provided) — calls
      :func:`wire_one_trial` to dump fresh state to the trial
      directory, inject the ``SKILLQ_*`` env vars into the agent
      config, and bind-mount the hook script + ``settings.json``
      into the container.
    - ``on_trial_ended`` — reads the PreToolUse hook log (or the
      session-log fallback), applies the task-only Eq.5 Q-update
      ``Q(skill) += alpha * (r_task - Q(skill))`` per unique skill
      called in the trial, and maintains the lib.

    Both callbacks swallow exceptions (the bridge's safety net so a
    bug in the method never aborts the trial).

    ``wiring=None`` is the legacy / unit-test mode: the PreToolUse
    hook is not registered, so on_trial_started is skipped. The
    end-of-trial Q-update still runs via the session-log fallback
    (recovering Skill calls from the agent's Claude Code jsonl).
    """
    lib = Qlib(b_max=method.b_max)
    mgr = LibManager(
        b_max=method.b_max,
        q_clip_floor=method.q_clip_floor,
        q_clip_ceiling=method.q_clip_ceiling,
    )
    # State + emb_cache load
    state = QlibState(method.resolved_state_path())
    state.load_into(lib, mgr, lib_root=method.library_root)
    # Plan D: if the in-memory library is still empty (no prior
    # method_state.json, or one with empty library.skills), seed it
    # from the on-disk seed library. This is the auto-load path so
    # users don't have to hand-write method_state.json. No-op when
    # ``method.seed_skills_dir`` is unset, when the dir doesn't
    # exist, or when ``lib.skills`` already has entries.
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
    emb_cache = VectorTable(method.resolved_state_path().parent / "emb_cache.json")
    emb_cache.load()

    # Plan D (cont.): pre-compute emb_cache for the seeded skills.
    # The hook ranks Skill() calls by cosine(subtask_emb, skill_emb)
    # + Q + UCB (Eq. 4). With an empty emb_cache, every skill's
    # cosine is 0 → all scores tie → top-3 is just file-system order,
    # not semantic match. So the first time the seed library is
    # loaded (here), we embed every seeded skill's description and
    # write the result to emb_cache.json. Subsequent trials just
    # load the existing cache; only add/remove/replace events
    # (handled by the per-trial ``_refresh_emb_cache`` path below)
    # touch it.
    #
    # No-op when (a) the cache already has every skill in lib
    # (subsequent trials — incremental path covers delta) or (b)
    # the host embed service is unavailable (the hook then falls
    # back to Q+UCB-only ranking, which still works; the cosine
    # term is what gets dropped). Errors are logged and swallowed
    # — the trial must still run even if pre-compute fails.
    if lib.skills and len(emb_cache) < len(lib.skills):
        try:
            missing = [
                sid for sid in lib.skills
                if sid not in emb_cache
            ]
            if missing:
                embedder = LiteLLMEmbedder(
                    model=method.embedder_model,
                    dim=int(getattr(method, "embedder_dim", 1536)),
                )
                added = [
                    (sid, lib.skills[sid].body) for sid in missing
                ]
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
    # Failure-mode extractor (Rule 5). Built lazily from the same
    # SkillExtractor template; only differs in prompt_mode.
    def _extractor_for_mode(mode: str) -> SkillExtractor:
        assert extractor is not None
        return SkillExtractor(
            claude_cli=extractor.claude_cli,
            model=extractor.model,
            timeout_sec=extractor.timeout_sec,
            name_min_words=extractor.name_min_words,
            name_max_words=extractor.name_max_words,
            body_min_tokens=extractor.body_min_tokens,
            body_max_tokens=extractor.body_max_tokens,
            prompt_mode=mode,
        )
    extract_buffer = _ExtractBuffer(n_trials_threshold=method.extract_every_n_trials)

    # Track which lib mutates fired this on_ended call (so we can
    # batch emb_cache refresh at the end).
    lib_changes_this_trial: list[tuple[str, str, str]] = []  # (action, sid, body)

    expected_terminal_trials = len(job)

    async def _flush_buffer() -> None:
        """Drain the extract buffer, processing each (mode, batch) group
        with the right extractor. Records that share a mode are batched
        into one ``claude --print`` call; different modes spawn separate
        subprocesses.
        """
        groups = extract_buffer.flush()
        for mode, batch in groups:
            if not batch:
                continue
            try:
                mode_extractor = _extractor_for_mode(mode)
                new_skill = await mode_extractor.extract_batch(
                    trials=batch,
                    available_skill_names=[s.skill_id for s in lib.skills.values()],
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
            if new_skill.skill_id in lib:
                logger.warning(
                    "extract_batch produced skill %s which is already in lib; "
                    "skipping lib.add.",
                    new_skill.skill_id,
                )
                continue
            new_skill.admission_exempt = True
            lib.add(new_skill)
            # Mirror the new skill to the host skill dir so it is
            # visible to subsequent trials' containers via the
            # existing bind-mount at /skills. Best-effort: a write
            # failure does not abort the trial (the function catches
            # OSError internally and returns False).
            mirror_skill_to_host_dir(new_skill, method.seed_skills_dir)
            # Seed Q on the new skill (global, no per-intent).
            mgr.set_q(new_skill.skill_id, method.new_skill_initial_q)
            # Schedule emb_cache refresh for the new skill.
            lib_changes_this_trial.append(("add", new_skill.skill_id, new_skill.body))
            logger.info(
                "Batched extract (mode=%s) created skill %s (Q_init=%.2f) from %d trials",
                mode,
                new_skill.skill_id,
                method.new_skill_initial_q,
                len(batch),
            )

    # ------------------------------------------------------------------
    # Per-trial sub-steps, factored out of on_ended for readability.
    # Each one takes everything it needs as parameters; nothing relies
    # on a closure over attach_paper_registers. The Q-table and lib
    # are passed in (and mutated in place).
    # ------------------------------------------------------------------
    def _q_update(
        *,
        trial_id: str,
        trial_dir: Path,
        r_task: int,
    ) -> list[dict[str, Any]]:
        """Apply the task-only Q-update (Eq.5) for one trial.

        For every skill the agent called this trial (counted from the
        PreToolUse hook log, with a session-log fallback for agentic
        mode), apply::

            Q(skill) += alpha * (r_task - Q(skill))

        ``r_task`` is shared by every skill called in the trial
        (already binarised to {0, 1} by ``_harbor_r_task``).

        Per-skill counters updated as a side-effect:

        - ``n_retrievals += n_calls`` — feeds the next trial's UCB
          exploration bonus (see :mod:`paper_mode.hook`). Counts
          every approved call so skills that get called a lot see
          their exploration bonus decay.
        - ``n_uses += 1`` — "did the agent use this skill at all in
          the trial" counter (one per trial regardless of call count).
        - ``n_success += 1 if r_task`` — task-success counter per
          skill (gated on the trial-level reward only).

        Skills evicted between call-time and end-of-trial are skipped
        (we don't Q-update a skill that no longer exists).

        Returns the per-skill Q-update entries so the caller can
        persist them (currently used only for the trace file; the
        Q-table itself is updated in place via ``mgr.update_q``).
        """
        # The hook writes its per-call log to
        # ``/logs/agent/sessions/skillq_skill_calls.jsonl`` inside
        # the container, which is inside Harbor's auto-injected
        # ``agent_dir`` bind mount (``trial_dir/agent`` →
        # ``/logs/agent``, see
        # ``harbor/trial/trial.py::_agent_env_mounts``). That mount
        # is read-write, so the hook appends freely and the file
        # is visible on the host at
        # ``<trial_dir>/agent/sessions/skillq_skill_calls.jsonl``
        # by the time we get here. This replaces the old approach
        # of writing into a SkillQ-staged
        # ``<trial_dir>/skillq_state/calls_log.jsonl`` via a custom
        # ``read_only=False`` bind mount, which violated Harbor's
        # ``ServiceVolumeConfig.read_only: Literal[True]`` TypedDict
        # and broke ``--resume`` (Bug 2).
        calls_log = _read_skill_calls_log(
            trial_dir / "agent" / "sessions" / "skillq_skill_calls.jsonl"
        )
        if not calls_log:
            # Fallback: the PreToolUse hook may not have fired (agentic
            # mode) or its log was unreadable. Extract the per-skill
            # call list from the agent's Claude Code session jsonl.
            calls_log = _extract_skill_calls_from_session(trial_dir)
        by_skill: dict[str, list[_SubTaskCallRecord]] = defaultdict(list)
        for c in calls_log:
            if not c.skill_id:
                continue
            by_skill[c.skill_id].append(c)

        if not by_skill:
            return []

        # 2026-06-24 (Fix 3): Cosine-weighted Q-update. Compute phi(q)
        # ONCE per trial by re-embedding the first call's intent_text
        # (or trial_id as fallback). Each per-skill delta is then
        # scaled by max(cos(phi(q), phi(s)), 0). Skills orthogonal to
        # the trial's intent get delta=0 — Q is not polluted by
        # failures on wrongly-recommended skills.
        phi_q: list[float] | None = None
        if method.q_update_cosine_weight:
            intent_text = ""
            if calls_log:
                intent_text = (calls_log[0].intent_text or "").strip()
            if not intent_text:
                # Fallback: trial_id typically encodes the task_name.
                intent_text = trial_id
            try:
                phi_q = sync_embed(
                    text=intent_text,
                    host="127.0.0.1",
                    port=method.hook_embedding_service_port,
                )
                logger.info(
                    "phi(q) embedded: text_len=%d emb_dim=%d",
                    len(intent_text),
                    len(phi_q),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "phi(q) embed failed; cosine weight disabled for "
                    "trial %s: %s",
                    trial_id,
                    exc,
                )
                phi_q = None

        out: list[dict[str, Any]] = []
        for skill_id, calls in by_skill.items():
            if skill_id not in lib:
                # Skill was in the agent's view at call time but has
                # since been evicted. Skip — we don't Q-update a
                # skill that no longer exists.
                continue
            n_calls = len(calls)
            # Standard Q-learning (Eq.5, binary reward):
            # target = r_task
            # delta  = alpha * (target - Q(skill))
            q_old = mgr.q_for(skill_id)
            target = r_task
            delta = method.q_alpha * (target - q_old)

            # 2026-06-24 (Fix 3): cosine-weighted Q-update.
            # Multiply delta by max(cos(phi(q), phi(s)), 0).
            # Skills orthogonal to the trial get delta=0; their Q is
            # preserved at q_old (no pollution from the failure).
            cosine_sim: float | None = None
            if phi_q is not None:
                phi_s = emb_cache.get(skill_id)
                if phi_s is None:
                    # No embedding for this skill — skip update.
                    # Prevents polluting Q on skills never seen by
                    # the embedder (e.g. brand-new auto-extracted
                    # skills with a description that wasn't yet
                    # embedded for cosine search).
                    logger.debug(
                        "Q-update skipped: no embedding for skill=%s",
                        skill_id,
                    )
                    continue
                # VectorTable returns np.ndarray; coerce to list for _cosine.
                phi_s_list = (
                    phi_s.tolist() if hasattr(phi_s, "tolist") else list(phi_s)
                )
                sim = _cosine(phi_q, phi_s_list)
                sim_clamped = max(sim, 0.0)
                cosine_sim = sim_clamped
                delta = delta * sim_clamped
                if sim_clamped == 0.0:
                    logger.debug(
                        "Q-update zeroed: sim=%.3f skill=%s",
                        sim,
                        skill_id,
                    )

            if delta != 0.0:
                mgr.update_q(skill_id, delta)
            skill_obj = lib.get(skill_id)
            if skill_obj is not None:
                skill_obj.n_retrievals += n_calls
                skill_obj.n_uses += 1
                if r_task:
                    skill_obj.n_success += 1
            out.append(
                {
                    "trial": trial_id,
                    "skill": skill_id,
                    "calls": n_calls,
                    "r_task": r_task,
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
                int(r_task),
                f"{cosine_sim:.3f}" if cosine_sim is not None else "n/a",
                q_old,
                q_old + delta,
            )
        # Per-trial trace: write the Q-update entries to a
        # trial-local file so the trail survives even if the
        # later ``state.save()`` in ``on_ended`` fails. The file
        # is small (one JSONL line per (skill, trial)) and lives
        # next to the other trial state dumps in
        # ``<trial_dir>/skillq_state/``.
        if out:
            try:
                q_path = trial_dir / "skillq_state" / "q_updates.jsonl"
                q_path.parent.mkdir(parents=True, exist_ok=True)
                with open(q_path, "w", encoding="utf-8") as f:
                    for entry in out:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:  # noqa: BLE001
                # Best-effort: never let the trace writer abort Q-update.
                logger.exception("failed to write q_updates.jsonl for %s", trial_id)
        return out

    async def _attribution_and_extract_dispatch(
        *,
        intent_text: str,
        trial_dir: Path,
        event: TrialHookEvent,
        r_task: int,
    ) -> None:
        """Run the attribution step and feed (task, knowledge) into
        the extract buffer.

        Two paper rules trigger a new-skill creation here:

        - **Rule 2** (success path): r_task == 1 AND
          attribution ∈ {SUCCESS_NO_SKILL_SEEN,
          SUCCESS_VIEWED_SKILL_BUT_NOT_USED} AND
          ``knowledge_to_extract`` is non-empty. The knowledge is a
          reusable procedure; we add to the buffer with
          ``mode="success"`` so the right prompt is used.
        - **Rule 5** (failure path): r_task == 0 AND
          attribution ∈ {FAIL_AGENT_ISSUE, FAIL_SKILL_ISSUE} AND
          ``knowledge_to_extract`` is non-empty. The knowledge is a
          failure attribution; we add to the buffer with
          ``mode="failure"`` so the guard-rail prompt is used.

        Note: a previous version of this gate checked "no existing
        skill has high Q" before allowing extraction. That gate is
        intentionally removed — a successful novel-task trajectory
        should always be allowed to evolve into a new skill regardless
        of how good the existing lib looks. Lib growth is bounded
        independently by the Q-driven ``b_max`` cap in
        ``LibManager.maintain``.
        """
        if extractor is None:
            return
        attribution = attribution_analyzer.analyze(
            task=intent_text,
            trial_dir=trial_dir,
            skills_root=_find_skills_dir(event),
            r_task=r_task,
        )
        knowledge = attribution.knowledge_to_extract.strip()
        triggered = False
        if knowledge:
            if r_task and attribution.overall_attribution in (
                Attribution.SUCCESS_VIEWED_SKILL_BUT_NOT_USED,
                Attribution.SUCCESS_NO_SKILL_SEEN,
            ):
                # Rule 2: success trajectory with no relevant skill
                # in lib → new skill from the success trajectory.
                buffer_full = extract_buffer.add(
                    task=intent_text, knowledge=knowledge, mode="success"
                )
                if buffer_full:
                    await _flush_buffer()
                triggered = True
            elif not r_task and attribution.overall_attribution in (
                Attribution.FAIL_AGENT_ISSUE,
                Attribution.FAIL_SKILL_ISSUE,
            ):
                # Rule 5: failure attributed to agent or to an
                # unused skill → new skill (guard-rail) from the
                # failure attribution. Note: FAIL_ENV_ISSUE is
                # excluded because the failure was external, not a
                # missing-skill problem.
                buffer_full = extract_buffer.add(
                    task=intent_text, knowledge=knowledge, mode="failure"
                )
                if buffer_full:
                    await _flush_buffer()
                triggered = True
        if not triggered:
            return
        # Final-trial force flush so a buffer that's almost full
        # doesn't get discarded at the end of the run.
        if extract_buffer and (state.step + 1) >= expected_terminal_trials:
            await _flush_buffer()

    def _maintain_lib() -> list[tuple[str, str, str]]:
        """Run the Q-driven admission/eviction pass and record the
        (action, skill_id, body) diff the emb_cache refresh will need.
        """
        changes: list[tuple[str, str, str]] = list(lib_changes_this_trial)
        skills_before = set(lib.skills.keys())
        mgr.maintain(lib, current_step=state.step + 1)
        skills_after = set(lib.skills.keys())
        for sid in skills_before - skills_after:
            changes.append(("remove", sid, ""))
            if sid in mgr.q_table:
                del mgr.q_table[sid]
        return changes

    def _refresh_emb_cache(changes: list[tuple[str, str, str]]) -> None:
        """Apply a batched emb_cache update from the lib changes."""
        if not changes:
            return
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
                vector_table=emb_cache,
                embedder=embedder,
            )
            emb_cache.save()
        except Exception:  # noqa: BLE001
            logger.exception("emb_cache refresh failed; continuing.")

    def _incremental_edit_on_failure(
        *,
        r_task: int,
        intent_text: str,
        trial_dir: Path,
        trial_id: str,
    ) -> None:
        """Layer 4 (Sec. 3.4 incremental editing): if the trial failed
        (r_task == 0), ask the editor backend to propose a minimal
        edit on the highest-Q skill and re-embed the description if
        it changed.

        The previous near-miss gate (``Q >= theta_near_miss``) was
        removed 2026-06-22; see the comment in the function body.
        """
        if not r_task or not lib.skills:
            return
        top = max(
            lib.skills.values(),
            key=lambda s: mgr.q_for(s.skill_id),
            default=None,
        )
        if top is None:
            return
        # 2026-06-22: previously gated by
        # ``refiner.is_near_miss(r_task, current_q, method.theta_near_miss)``.
        # That gate was structurally unreachable (low-Q failed-trial
        # scenarios drifted below ``theta_near_miss=0.5``), so every
        # failed trial was silently skipped. Removed: any failed trial
        # with a non-empty lib now invokes the editor LLM.
        # 2026-06-23: with the sub-task judge path removed, this gate's
        # only blocker (the unreachable blend) is gone.
        new_skill = refiner.propose_edit(
            skill=top,
            task=intent_text,
            failure_trace=str(trial_dir),
        )
        if new_skill is top:
            return
        lib.replace(new_skill)
        # Re-embed the description only if the frontmatter changed.
        if _description_of(top.body) != _description_of(new_skill.body):
            try:
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
                logger.exception("emb_cache refresh after incremental edit failed; continuing.")
        logger.info(
            "Incremental edit on failure: skill %s, trial %s",
            new_skill.skill_id,
            trial_id,
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

            # 1. Per-trial Q-update (task-only, Eq.5). Synchronous:
            # no LLM call, just a per-skill dict update.
            _q_update(
                trial_id=event.trial_id,
                trial_dir=trial_dir,
                r_task=r_task,
            )

            # 2. Attribution + auto-extract dispatch.
            await _attribution_and_extract_dispatch(
                intent_text=intent_text,
                trial_dir=trial_dir,
                event=event,
                r_task=r_task,
            )

            # 3. Library maintenance (admission/eviction).
            changes = _maintain_lib()

            # 4. Refresh emb_cache from the lib changes.
            _refresh_emb_cache(changes)

            # 5. Persist state.
            state.step += 1
            state.save(
                lib,
                mgr,
                lib_root=method.library_root,
                seed_initial_q=method.seed_initial_q,
            )

            # 5b. Bug 3: re-dump q_table.json to the per-trial staging
            # dir so users inspecting the trial artifacts see the
            # post-trial Q-values (matching method_state.json), not
            # the trial-START snapshot written by
            # ``container_wiring._write_state_files``. Mirrors the
            # format of that function exactly. Defensive mkdir
            # + try/except: never let a method-bug-side I/O error
            # abort the trial.
            trial_q_path = trial_dir / "skillq_state" / "q_table.json"
            try:
                trial_q_path.parent.mkdir(parents=True, exist_ok=True)
                trial_q_path.write_text(
                    json.dumps(dict(mgr.q_table), ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            except Exception:
                logger.exception(
                    "Bug 3 mirror: failed to re-dump per-trial q_table.json "
                    "for trial %s",
                    event.trial_id,
                )

            # 6. Incremental edit on failure (Sec. 3.4 / Layer 4).
            _incremental_edit_on_failure(
                r_task=r_task,
                intent_text=intent_text,
                trial_dir=trial_dir,
                trial_id=event.trial_id,
            )
        except Exception as exc:
            # Never let a method bug abort the trial. But do write a
            # per-trial record so users can diagnose what broke —
            # ``trial.log`` does not always capture the bridge's
            # stderr (different streams depending on the launcher),
            # so the previous bare ``logger.exception`` was
            # effectively silent. Writing to
            # ``<trial_dir>/skillq_state/method_errors.jsonl`` lands
            # the failure in the trial's host-side artifacts dir,
            # which is always preserved.
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
                # Last-resort: never let the diagnostic writer itself
                # raise. If we can't write the error file the
                # ``logger.exception`` line above is the only signal.
                pass

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
