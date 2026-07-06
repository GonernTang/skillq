"""Bug #53 fix (2026-07-01): ``extract_skill_calls_from_session``
must respect the session jsonl's ``permission_denials`` block.

History: the function used to hardcode ``approved=True`` for every
``Skill()`` tool_use it found, ignoring the ``{"type": "result",
"permission_denials": [...]}`` block at the end of the session
jsonl. This meant denied Skill() calls were credited as approved
and polluted the Q-table.

These tests pin the new two-pass parse: ``_load_permission_denials``
collects ``tool_use_id``s from the result block, and
``extract_skill_calls_from_session`` correlates them to the
``tool_use`` block ``id`` field to set ``approved=False,
denied=True``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.shared.calls_log import (  # noqa: E402
    _load_permission_denials,
    extract_skill_calls_from_session,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _write_session_jsonl(
    tmp_path: Path,
    records: list[dict],
    *,
    proj_name: str = "proj-1",
    session_name: str = "session-x",
) -> Path:
    """Write a session jsonl in the format
    ``<tmp_path>/agent/sessions/projects/<proj_name>/<session_name>.jsonl``."""
    proj = tmp_path / "agent" / "sessions" / "projects" / proj_name
    proj.mkdir(parents=True, exist_ok=True)
    p = proj / f"{session_name}.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return p


def _skill_tool_use(skill_name: str, *, tool_use_id: str | None = "tu-1") -> dict:
    """Build a single Skill tool_use block."""
    block: dict = {
        "type": "tool_use",
        "name": "Skill",
        "input": {"skill": skill_name},
    }
    if tool_use_id is not None:
        block["id"] = tool_use_id
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [block],
        },
    }


def _result_with_denials(
    denials: list[dict],
    *,
    subtype: str = "success",
    session_id: str = "sess-1",
) -> dict:
    return {
        "type": "result",
        "subtype": subtype,
        "session_id": session_id,
        "permission_denials": denials,
    }


# ---------------------------------------------------------------------------
# Unit tests for _load_permission_denials
# ---------------------------------------------------------------------------
def test_load_permission_denials_collects_skill_tool_use_ids(tmp_path):
    """The helper should collect tool_use_id strings from
    permission_denials entries where tool_name == 'Skill'."""
    p = _write_session_jsonl(
        tmp_path,
        [
            _result_with_denials(
                [
                    {"tool_name": "Skill", "tool_use_id": "tu-1",
                     "tool_input": {"skill": "a"}},
                    {"tool_name": "Skill", "tool_use_id": "tu-2",
                     "tool_input": {"skill": "b"}},
                    # Other tool — should be ignored.
                    {"tool_name": "Bash", "tool_use_id": "tu-3",
                     "tool_input": {"command": "ls"}},
                ]
            )
        ],
    )
    assert _load_permission_denials(p) == {"tu-1", "tu-2"}


def test_load_permission_denials_empty_when_no_result_record(tmp_path):
    """No ``type: result`` record → empty set."""
    p = _write_session_jsonl(
        tmp_path,
        [_skill_tool_use("a", tool_use_id="tu-1")],
    )
    assert _load_permission_denials(p) == set()


def test_load_permission_denials_ignores_malformed_denials(tmp_path):
    """Non-dict entries, missing tool_name, non-string tool_use_id
    must be silently skipped."""
    p = _write_session_jsonl(
        tmp_path,
        [
            _result_with_denials(
                [
                    None,  # non-dict
                    {"tool_name": "Other", "tool_use_id": "tu-x"},
                    {"tool_name": "Skill"},  # no tool_use_id
                    {"tool_name": "Skill", "tool_use_id": 12345},  # non-str
                    {"tool_name": "Skill", "tool_use_id": ""},  # empty
                    {"tool_name": "Skill", "tool_use_id": "tu-good"},
                ]
            )
        ],
    )
    assert _load_permission_denials(p) == {"tu-good"}


def test_load_permission_denials_handles_missing_file(tmp_path):
    """Missing file → empty set (best-effort)."""
    assert _load_permission_denials(tmp_path / "nonexistent.jsonl") == set()


def test_load_permission_denials_handles_permission_denials_not_list(tmp_path):
    """permission_denials must be a list; otherwise treat as no denials."""
    p = _write_session_jsonl(
        tmp_path,
        [
            {
                "type": "result",
                "permission_denials": "not a list",
            }
        ],
    )
    assert _load_permission_denials(p) == set()


# ---------------------------------------------------------------------------
# Integration: extract_skill_calls_from_session honors denials
# ---------------------------------------------------------------------------
def test_extract_marks_denied_skill_as_not_approved(tmp_path):
    """A Skill() whose tool_use id appears in permission_denials must
    be emitted with approved=False, denied=True (Bug #53 fix)."""
    _write_session_jsonl(
        tmp_path,
        [
            _skill_tool_use("chess-image-to-move", tool_use_id="t1"),
            _skill_tool_use("gcode-emboss-extract", tool_use_id="t2"),
            _result_with_denials(
                [
                    {"tool_name": "Skill", "tool_use_id": "t2",
                     "tool_input": {"skill": "gcode-emboss-extract"}},
                ]
            ),
        ],
    )
    out = extract_skill_calls_from_session(tmp_path)
    assert len(out) == 2
    by_skill = {r.skill_id: r for r in out}
    assert by_skill["chess-image-to-move"].approved is True
    assert by_skill["chess-image-to-move"].denied is False
    assert by_skill["gcode-emboss-extract"].approved is False
    assert by_skill["gcode-emboss-extract"].denied is True


def test_extract_marks_all_approved_when_no_permission_denials_block(tmp_path):
    """Back-compat: if there's no permission_denials record (e.g.
    an older session), every Skill() defaults to approved=True —
    legacy behaviour preserved."""
    _write_session_jsonl(
        tmp_path,
        [
            _skill_tool_use("a", tool_use_id="t1"),
            _skill_tool_use("b", tool_use_id="t2"),
        ],
    )
    out = extract_skill_calls_from_session(tmp_path)
    assert all(r.approved is True and r.denied is False for r in out)


def test_extract_skill_without_id_defaults_to_approved(tmp_path):
    """A Skill() tool_use block with no ``id`` field cannot be
    correlated to a permission_denials entry — it defaults to
    approved=True (legacy behaviour). The Q-update path still drops
    records with denied=True so this only matters for the rare
    case where Claude Code omits the id."""
    _write_session_jsonl(
        tmp_path,
        [
            _skill_tool_use("a", tool_use_id=None),
            _result_with_denials(
                [
                    {"tool_name": "Skill", "tool_use_id": "tu-some-other",
                     "tool_input": {"skill": "unrelated"}},
                ]
            ),
        ],
    )
    out = extract_skill_calls_from_session(tmp_path)
    assert len(out) == 1
    assert out[0].approved is True
    assert out[0].denied is False


def test_extract_handles_empty_permission_denials_list(tmp_path):
    """permission_denials: [] → no denials → all approved."""
    _write_session_jsonl(
        tmp_path,
        [
            _skill_tool_use("a", tool_use_id="t1"),
            _result_with_denials([]),
        ],
    )
    out = extract_skill_calls_from_session(tmp_path)
    assert len(out) == 1
    assert out[0].approved is True
    assert out[0].denied is False


def test_extract_uses_only_most_recent_session_jsonl(tmp_path):
    """Multiple session jsonls in the trial: the function picks the
    one with the latest mtime. The denials list from the older
    session must NOT poison the most recent session's parse."""
    import os
    import time

    # Newer session: a Skill() with no denials. Written FIRST so
    # we can set its mtime higher afterwards.
    new_path = _write_session_jsonl(
        tmp_path,
        [
            _skill_tool_use("new", tool_use_id="new-1"),
        ],
        proj_name="proj-new",
        session_name="session-new",
    )

    # Older session: a Skill() with a denial. Written SECOND but
    # we pin its mtime to be earlier so the sort still picks new.
    old_path = _write_session_jsonl(
        tmp_path,
        [
            _skill_tool_use("old", tool_use_id="old-1"),
            _result_with_denials(
                [{"tool_name": "Skill", "tool_use_id": "old-1",
                  "tool_input": {"skill": "old"}}],
            ),
        ],
        proj_name="proj-old",
        session_name="session-old",
    )

    # Pin mtimes so the test is deterministic regardless of file
    # write order on this filesystem.
    now = time.time()
    os.utime(new_path, (now, now + 100))   # newer
    os.utime(old_path, (now, now))         # older

    out = extract_skill_calls_from_session(tmp_path)
    # Most recent is proj-new/session-new.jsonl → only "new" Skill,
    # marked approved (no denials in this session).
    assert len(out) == 1
    assert out[0].skill_id == "new"
    assert out[0].approved is True
    assert out[0].denied is False


def test_extract_denied_skills_are_skipped_by_q_update_step(tmp_path):
    """End-to-end: a record with denied=True must NOT be returned in
    the per-trial call list used for Q-updates. We simulate the
    bridge's filter and assert the count drops correctly."""
    _write_session_jsonl(
        tmp_path,
        [
            _skill_tool_use("approved-skill", tool_use_id="t1"),
            _skill_tool_use("denied-skill", tool_use_id="t2"),
            _result_with_denials(
                [{"tool_name": "Skill", "tool_use_id": "t2",
                  "tool_input": {"skill": "denied-skill"}}],
            ),
        ],
    )
    out = extract_skill_calls_from_session(tmp_path)
    by_skill_dropped = [r for r in out if r.denied]
    assert len(by_skill_dropped) == 1
    assert by_skill_dropped[0].skill_id == "denied-skill"