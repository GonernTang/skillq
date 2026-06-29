"""Tests for the session-log fallback used by ``_q_update``.

When the PreToolUse hook is unavailable (agentic mode) or its log
was unreadable, the bridge scans the trial's Claude Code session
jsonl for ``Skill`` tool_use blocks to recover per-skill call info.

Covers:
- Empty / missing session directories.
- Empty jsonl.
- Malformed jsonl lines (skipped, not crashing).
- Mixed user / assistant / tool entries.
- Skill tool_use blocks in nested message content.
- Tool_use blocks for non-Skill tools are ignored.

End-to-end Q-update tests (with the session-log fallback wired in)
live in tests/test_q_update_task_only.py. The old SubTaskVerifier-stub
and Bug-8 parallel-wallclock tests were removed on 2026-06-23 when
the sub-task judge path was deleted.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.runtime import bridge as bridge_mod  # noqa: E402
from skillq.shared.calls_log import extract_skill_calls_from_session  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _write_session_jsonl(
    trial_dir: Path,
    *entries: dict[str, Any],
    session_name: str = "session-001.jsonl",
) -> Path:
    """Write a session jsonl under
    ``<trial_dir>/agent/sessions/projects/<proj>/<session_name>``.
    """
    proj_dir = trial_dir / "agent" / "sessions" / "projects" / "test-proj"
    proj_dir.mkdir(parents=True, exist_ok=True)
    p = proj_dir / session_name
    with p.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return p


def _skill_tool_use(skill_name: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "Skill",
                    "input": {"skill": skill_name},
                    "id": f"call_{skill_name}",
                }
            ],
        },
    }


def _text_msg(role: str, text: str) -> dict[str, Any]:
    return {"type": role, "message": {"role": role, "content": text}}


def _other_tool_use(tool_name: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": tool_name,
                    "input": {"cmd": "ls"},
                    "id": f"call_{tool_name}",
                }
            ],
        },
    }


# ---------------------------------------------------------------------------
# _extract_skill_calls_from_session — direct unit tests
# ---------------------------------------------------------------------------
def test_extract_returns_empty_when_session_dir_missing(tmp_path: Path):
    """No ``agent/sessions/projects`` dir → empty list, no exception."""
    assert extract_skill_calls_from_session(tmp_path) == []


def test_extract_returns_empty_when_no_jsonl_files(tmp_path: Path):
    """Dir exists but no jsonl files → empty list."""
    (tmp_path / "agent" / "sessions" / "projects" / "x").mkdir(parents=True)
    assert extract_skill_calls_from_session(tmp_path) == []


def test_extract_returns_empty_for_empty_jsonl(tmp_path: Path):
    p = _write_session_jsonl(tmp_path)
    assert p.stat().st_size == 0
    assert extract_skill_calls_from_session(tmp_path) == []


def test_extract_skips_malformed_jsonl_lines(tmp_path: Path):
    """Bad JSON lines are skipped, valid Skill entries still extracted."""
    proj_dir = tmp_path / "agent" / "sessions" / "projects" / "p"
    proj_dir.mkdir(parents=True)
    p = proj_dir / "s.jsonl"
    p.write_text(
        "{not valid json\n"
        + json.dumps(_skill_tool_use("fix-git-basics"))
        + "\n"
        + "still bad\n",
        encoding="utf-8",
    )
    out = extract_skill_calls_from_session(tmp_path)
    assert len(out) == 1
    assert out[0].skill_id == "fix-git-basics"


def test_extract_picks_skill_blocks_from_nested_content(tmp_path: Path):
    _write_session_jsonl(
        tmp_path,
        _text_msg("user", "fix my commit"),
        _other_tool_use("Bash"),
        _skill_tool_use("fix-git-basics"),
        _skill_tool_use("git-recover"),
        _text_msg("assistant", "I'll use the skill"),
        _other_tool_use("Edit"),
    )
    out = extract_skill_calls_from_session(tmp_path)
    assert [r.skill_id for r in out] == ["fix-git-basics", "git-recover"]


def test_extract_ignores_non_skill_tools(tmp_path: Path):
    """Bash, Edit, Read, etc. tool_use blocks are ignored."""
    _write_session_jsonl(
        tmp_path,
        _other_tool_use("Bash"),
        _other_tool_use("Edit"),
        _other_tool_use("Read"),
        _skill_tool_use("parse-cobol"),
    )
    out = extract_skill_calls_from_session(tmp_path)
    assert len(out) == 1
    assert out[0].skill_id == "parse-cobol"


def test_extract_skips_skill_blocks_with_empty_skill_name(tmp_path: Path):
    """A Skill tool_use block with input.skill == "" is ignored."""
    bad_block = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "Skill", "input": {"skill": ""}}
            ],
        },
    }
    _write_session_jsonl(
        tmp_path,
        bad_block,
        _skill_tool_use("fix-git-basics"),
    )
    out = extract_skill_calls_from_session(tmp_path)
    assert [r.skill_id for r in out] == ["fix-git-basics"]


def test_extract_uses_most_recent_jsonl(tmp_path: Path):
    """When multiple session jsonls exist, the most recent (by mtime)
    one is used. Use different content in two files to verify."""
    older = _write_session_jsonl(
        tmp_path, _skill_tool_use("from-older-session"),
        session_name="session-001.jsonl",
    )
    # Sleep to ensure a different mtime
    time.sleep(0.05)
    newer = _write_session_jsonl(
        tmp_path, _skill_tool_use("from-newer-session"),
        session_name="session-002.jsonl",
    )
    # Sanity: newer has a later mtime
    assert newer.stat().st_mtime > older.stat().st_mtime
    out = extract_skill_calls_from_session(tmp_path)
    assert [r.skill_id for r in out] == ["from-newer-session"]


def test_extract_returns_record_with_empty_metadata(tmp_path: Path):
    """Returned records have top_k=[], approved=True, ts=0.0,
    intent_text="" — the Q-update path doesn't need these."""
    _write_session_jsonl(tmp_path, _skill_tool_use("parse-cobol"))
    out = extract_skill_calls_from_session(tmp_path)
    assert len(out) == 1
    assert out[0].skill_id == "parse-cobol"
    assert out[0].requested == "parse-cobol"
    assert out[0].top_k == []
    assert out[0].approved is True
    assert out[0].ts == 0.0
    assert out[0].intent_text == ""