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
            out.append(
                SubTaskCallRecord(
                    skill_id=str(rec.get("requested", "")),
                    requested=str(rec.get("requested", "")),
                    top_k=list(rec.get("top_k", [])),
                    approved=approved,
                    denied=denied,
                    ts=float(rec.get("ts", 0.0)),
                    intent_text=str(rec.get("intent_text", "")),
                )
            )
    return out


_read_skill_calls_log = read_skill_calls_log


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
                        SubTaskCallRecord(
                            skill_id=skill_name,
                            requested=skill_name,
                            top_k=[],
                            approved=True,
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
]