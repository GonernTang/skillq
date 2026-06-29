"""Read the last few assistant messages from a trial's session jsonl.

Step 1 of the 2026-06-26 refactor extracted
``_read_session_assistant_tail`` from :mod:`skillq.runtime.bridge`
into :mod:`skillq.shared.session_tail` so the bridge can be reduced
to a thin pipeline of step functions. The function is used by the
L3 EditRefiner path (2026-06-26, L3-H3) to give the editor LLM
context about what the agent was doing just before it failed.

Public name: :func:`read_session_assistant_tail`. Legacy private
alias ``_read_session_assistant_tail`` is kept for backward
compatibility until Step 6.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("skillq.shared.session_tail")


def read_session_assistant_tail(
    trial_dir: Path,
    k: int = 3,
    per_message_chars: int = 2000,
) -> str:
    """Return the last ``k`` assistant messages from the most recent
    session jsonl under ``<trial_dir>/agent/sessions/projects/*/*.jsonl``.

    Returns ``""`` on any structural failure (missing dir, missing
    files, malformed lines). Never raises. Mirrors the glob +
    mtime-sort pattern of :func:`extract_skill_calls_from_session`
    (same per-second mtime precision so a subagent and main agent
    jsonl created in the same second resolve in deterministic
    order). If the jsonl schema changes, update all three readers
    (:func:`extract_skill_calls_from_session`,
    :meth:`AttributionAnalyzer._load_session_trace`, this).
    """
    sessions_root = trial_dir / "agent" / "sessions" / "projects"
    if not sessions_root.exists():
        return ""
    try:
        jsonls = sorted(
            sessions_root.glob("*/*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return ""
    if not jsonls:
        return ""
    blocks: list[str] = []
    try:
        with jsonls[0].open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict) or rec.get("type") != "assistant":
                    continue
                content = (rec.get("message") or {}).get("content", "")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            content = block.get("text", "")
                            break
                    else:
                        continue
                if isinstance(content, str) and content.strip():
                    blocks.append(content.strip()[:per_message_chars])
    except OSError:
        pass
    return "\n\n".join(blocks[-k:])


_read_session_assistant_tail = read_session_assistant_tail


__all__ = ["read_session_assistant_tail"]