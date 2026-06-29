"""L1 transcript-query builder — assembles the text the hook embeds.

Step 2 of the 2026-06-26 refactor extracted ``_build_subtask_text`` and
``_read_recent_assistant_messages`` from
:mod:`skillq.runtime.hook`. The container-side hook
(``runtime/hook.py``, Step 5) and the host-side ``ranking_service``
both use these to assemble the query string the embedder sees.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Hard cap on the assembled query text — matches the PreToolUse
# hook's ``[:4000]`` tail-clip in the legacy implementation.
QUERY_MAX_CHARS = 4000


def read_recent_assistant_messages(
    transcript_path: str | None,
    k: int = 3,
) -> list[str]:
    """Read the last ``k`` assistant messages from the Claude Code session
    transcript (JSONL on disk).

    Returns ``[]`` on any structural failure (missing file, malformed
    JSON lines, wrong schema). Never raises. Stops reading once the
    file is exhausted; an entry whose ``content`` is not a plain
    string (e.g., it's a list of tool_use blocks) is silently skipped.
    """
    if not transcript_path:
        return []
    p = Path(transcript_path)
    if not p.is_file():
        return []
    out: list[str] = []
    try:
        with p.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict) or rec.get("type") != "assistant":
                    continue
                content = (rec.get("message") or {}).get("content", "")
                if isinstance(content, list):
                    # Pull out the text block, skip tool_use blocks.
                    text_block: str | None = None
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_block = block.get("text", "")
                            break
                    if text_block is None:
                        continue
                    content = text_block
                if isinstance(content, str) and content.strip():
                    out.append(content.strip())
    except OSError:
        return out
    return out[-k:]


_read_recent_assistant_messages = read_recent_assistant_messages


def build_query_text(
    *,
    tool_input: dict[str, Any],
    recent_assistant: list[str],
    user_task_hint: str | None = None,
) -> str:
    """Concatenate the user-task hint + recent assistant messages +
    the requested skill name into a single query string for the embedder.

    Hard-cap at :data:`QUERY_MAX_CHARS` chars so a malicious /
    pathological payload can't blow the embedder's input window. The
    legacy implementation uses the same ``" || "`` separator and the
    same ``[:4000]`` tail-clip; parity test pins this contract.
    """
    parts: list[str] = []
    if user_task_hint:
        parts.append(user_task_hint)
    parts.extend(recent_assistant)
    parts.append(f"Trying skill: {tool_input.get('skill', '?')}")
    return " || ".join(parts)[:QUERY_MAX_CHARS]


_build_subtask_text = build_query_text  # legacy private alias


__all__ = [
    "read_recent_assistant_messages",
    "build_query_text",
    "QUERY_MAX_CHARS",
]