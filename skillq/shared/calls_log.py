"""Parse the container-side Skill() call log.

Step 1 of the 2026-06-26 refactor extracted the JSONL reader
(``_read_skill_calls_log``) and the session-log fallback
(``_extract_skill_calls_from_session``) from
:mod:`skillq.runtime.bridge` into
:mod:`skillq.shared.calls_log` so the bridge can be reduced to a
thin pipeline of step functions.

Public names: :class:`SubTaskCallRecord` (was ``_SubTaskCallRecord``)
plus :func:`read_skill_calls_log` and :func:`extract_skill_calls_from_session`.
The legacy ``_``-prefixed names are kept as aliases for existing call
sites until Step 6.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("skillq.shared.calls_log")


@dataclass
class SubTaskCallRecord:
    """One Skill() invocation recovered from the container hook JSONL.

    Fields:

    - ``skill_id`` / ``requested`` — the agent's requested skill name.
      Same value for both fields; the ``requested`` alias is preserved
      for log readability.
    - ``top_k`` — the ranked Top-K the hook returned to the agent.
      Empty when the record was reconstructed from the session log
      fallback (the session log does not carry Top-K metadata).
    - ``approved`` — True iff the hook issued
      ``permissionDecision: "allow"``.
    - ``denied`` — True iff the hook issued ``permissionDecision: "deny"``.
      The Q-update path skips denied records to honour the strict-gate
      invariant: irrelevant skills must not pollute Q-table evolution.
    - ``ts`` — unix timestamp when the hook fired.
    - ``intent_text`` — the user prompt / agent task string that the
      hook embedded for retrieval. Empty when reconstructed from
      session log fallback.
    - ``l1_sims`` — post-gate cosine sims keyed by ``skill_id``,
      in the order the hook received them from ``/rank``. Empty
      when the Hard Gate dropped everything (strict mode) or when
      the hook version did not yet write the field (Phase 10 Bug 2
      and later).
    - ``l1_sims_top5_pre_gate`` — top-5 pre-gate raw sims the host's
      ``/rank`` returned in ``debug.pre_gate_top5`` (each entry is
      ``{"skill_id": str, "sim": float}``). Survives Hard Gate
      drops, so an audit can distinguish "L1 saw 0.05 sims (off-topic
      query)" from "L1 saw 0.65 sims (gate too strict)". Empty when
      the hook version did not yet write the field (Phase 10
      Debug-Log and later).
    """

    skill_id: str
    requested: str
    top_k: list[dict[str, Any]]
    approved: bool
    ts: float
    intent_text: str
    # 2026-06-25: explicit `denied` flag from the hook. Derive from
    # `approved` for backward-compat with hook versions that did not
    # write it.
    denied: bool = False
    # 2026-06-29 (Phase 10 Bug 2): post-gate L1 sims in top-k order.
    l1_sims: dict[str, float] = field(default_factory=dict)
    # 2026-06-29 (Phase 10 Debug-Log): pre-gate top-5 sim snapshot.
    l1_sims_top5_pre_gate: list[dict[str, Any]] = field(
        default_factory=list
    )


# Back-compat alias used inside skillq.runtime.bridge until Step 6.
_SubTaskCallRecord = SubTaskCallRecord


def read_skill_calls_log(log_path: Path) -> list[SubTaskCallRecord]:
    """Parse the JSONL the hook wrote during a trial.

    Returns [] on any structural failure (missing file, bad JSON).
    Each record represents one Skill() call the agent made; the
    Q-update path groups by ``skill_id`` and counts calls per skill
    to drive ``n_retrievals`` and the Eq.5 update.
    """
    if not log_path.exists():
        return []
    out: list[SubTaskCallRecord] = []
    try:
        f = open(log_path, "r", encoding="utf-8")
    except OSError:
        return []
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            approved = bool(rec.get("approved", False))
            denied = bool(rec.get("denied", not approved))
            # 2026-06-29 (Phase 10 Bug 2 + Debug-Log): forward the
            # L1 sim fields written by the hook. Both are best-effort:
            # an older hook that didn't write them yields empty
            # defaults (the field is marked default_factory on the
            # dataclass).
            raw_l1 = rec.get("l1_sims")
            l1_sims: dict[str, float] = (
                {str(k): float(v) for k, v in raw_l1.items()}
                if isinstance(raw_l1, dict)
                else {}
            )
            raw_pre = rec.get("l1_sims_top5_pre_gate")
            l1_sims_top5_pre_gate: list[dict[str, Any]] = (
                list(raw_pre) if isinstance(raw_pre, list) else []
            )
            out.append(
                SubTaskCallRecord(
                    skill_id=str(rec.get("requested", "")),
                    requested=str(rec.get("requested", "")),
                    top_k=list(rec.get("top_k", [])),
                    approved=approved,
                    denied=denied,
                    ts=float(rec.get("ts", 0.0)),
                    intent_text=str(rec.get("intent_text", "")),
                    l1_sims=l1_sims,
                    l1_sims_top5_pre_gate=l1_sims_top5_pre_gate,
                )
            )
    return out


_read_skill_calls_log = read_skill_calls_log


def _load_permission_denials(jsonl_path: Path) -> set[str]:
    """Return the set of ``tool_use_id`` strings whose ``Skill()`` calls
    were denied by the host's PreToolUse hook, as recorded in the
    end-of-session ``{"type": "result", "permission_denials": [...]}``
    block of the Claude Code session jsonl.

    2026-07-01 (Bug #53 fix): previously the session-fallback
    extractor (used when the hook log is empty) hardcoded
    ``approved=True`` for every Skill() it found, which credited
    denied calls as approved and polluted the Q-table. Now we
    parse ``permission_denials`` and join against the
    ``tool_use`` block's ``id`` field to set ``denied=True``
    correctly.

    Best-effort — returns ``set()`` on any read failure or schema
    mismatch. A missing ``permission_denials`` block (older
    sessions) yields the empty set, which preserves the legacy
    "all approved" behaviour for those sessions.
    """
    denied: set[str] = set()
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") != "result":
                    continue
                denials = rec.get("permission_denials", [])
                if not isinstance(denials, list):
                    continue
                for d in denials:
                    if not isinstance(d, dict):
                        continue
                    if d.get("tool_name") != "Skill":
                        continue
                    tid = d.get("tool_use_id")
                    if isinstance(tid, str) and tid:
                        denied.add(tid)
    except OSError:
        pass
    return denied


def extract_skill_calls_from_session(
    trial_dir: Path,
) -> list[SubTaskCallRecord]:
    """Fallback per-skill signal source for agentic mode (no PreToolUse
    hook installed).

    Scans the trial's Claude Code session log under
    ``<trial_dir>/agent/sessions/projects/*/*.jsonl`` for ``tool_use``
    blocks whose ``name`` is ``Skill``, and returns one
    :class:`SubTaskCallRecord` per invocation. Fields that the session
    log does not provide (``top_k``, ``ts``, ``intent_text``) are
    filled with empty defaults — the Q-update path only needs
    ``skill_id``.

    Always enabled (not gated on retrieval_mode): even in hook mode
    this serves as a safety net if the host-side
    ``skillq_skill_calls.jsonl`` mount was read-only and the hook
    failed to write.

    2026-07-01 (Bug #53 fix): a Skill() call is now marked
    ``approved=False, denied=True`` iff its ``tool_use`` block's
    ``id`` appears in the end-of-session ``permission_denials``
    list. Calls without an ``id``, or sessions without a
    ``permission_denials`` block, default to ``approved=True``
    (legacy behaviour). The Q-update path
    (:func:`skillq.runtime.steps.step_q_update`) drops records
    where ``denied=True``, so denied calls no longer pollute the
    Q-table.

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
    # 2026-07-01 (Bug #53 fix): load the denied tool_use_ids once
    # so we can correlate each tool_use block by its ``id``.
    denied_ids = _load_permission_denials(jsonls[0])
    out: list[SubTaskCallRecord] = []
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
                #         "input": {"skill": "..."}, "id": "..."}]}}
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
                    tool_use_id = block.get("id") or ""
                    is_denied = (
                        isinstance(tool_use_id, str)
                        and bool(tool_use_id)
                        and tool_use_id in denied_ids
                    )
                    out.append(
                        SubTaskCallRecord(
                            skill_id=skill_name,
                            requested=skill_name,
                            top_k=[],
                            approved=not is_denied,
                            denied=is_denied,
                            ts=0.0,
                            intent_text="",
                        )
                    )
    except OSError:
        pass
    return out


_extract_skill_calls_from_session = extract_skill_calls_from_session


__all__ = [
    "SubTaskCallRecord",
    "read_skill_calls_log",
    "extract_skill_calls_from_session",
    "_load_permission_denials",
]