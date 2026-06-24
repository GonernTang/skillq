"""Unit tests for the post-trial chown helper (2026-06-24, Bug #5 fix).

The chown helper exists to recover session jsonl files that are left
``root:root 0600`` on the host when an agent is OOM-killed mid-trial
(caffe-cifar-10, train-fasttext) and Harbor's
``prepare_logs_for_host()`` is skipped as a result. Without this fix,
Harbor's ``populate_context_post_run`` raises ``PermissionError`` and
the trajectory for that trial is never produced.

These tests pin the helper's contract:
  - Walks the trial_dir/agent/sessions/ tree recursively
  - Skips missing paths / non-dirs (no-op)
  - Swallows PermissionError / FileNotFoundError per entry
  - Never raises out of the helper (the Q-update caller wraps it in
    its own try/except as well)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.paper_mode.bridge import (  # noqa: E402
    _chown_agent_sessions_to_host_user,
)


def _make_session_tree(root: Path) -> Path:
    """Build a fake trial_dir/agent/sessions tree under root.

    Layout mimics what Harbor writes inside the container:
        <root>/agent/sessions/projects/-app/<uuid>.jsonl
        <root>/agent/sessions/<other>.jsonl
    """
    sessions = root / "agent" / "sessions"
    proj = sessions / "projects" / "-app"
    proj.mkdir(parents=True)
    (proj / "abc.jsonl").write_text('{"event":"session_start"}\n')
    (sessions / "other.jsonl").write_text('{"event":"x"}\n')
    return sessions


def test_chown_helper_noop_when_path_missing(tmp_path: Path):
    """Non-existent trial_dir → no os.chown calls."""
    nonexistent = tmp_path / "nope"
    with patch("skillq.paper_mode.bridge.os.chown") as mock_chown:
        _chown_agent_sessions_to_host_user(nonexistent)
        assert mock_chown.call_count == 0


def test_chown_helper_noop_when_agent_sessions_missing(tmp_path: Path):
    """trial_dir exists but no agent/sessions subdir → no chown calls."""
    trial_dir = tmp_path / "trial"
    trial_dir.mkdir()
    (trial_dir / "skillq_state").mkdir()
    with patch("skillq.paper_mode.bridge.os.chown") as mock_chown:
        _chown_agent_sessions_to_host_user(trial_dir)
        assert mock_chown.call_count == 0


def test_chown_helper_noop_when_trial_dir_none():
    """None trial_dir → silent no-op."""
    with patch("skillq.paper_mode.bridge.os.chown") as mock_chown:
        _chown_agent_sessions_to_host_user(None)
        _chown_agent_sessions_to_host_user("")
        assert mock_chown.call_count == 0


def test_chown_helper_walks_all_session_files(tmp_path: Path):
    """Helper chowns every file in agent/sessions/** recursively."""
    sessions = _make_session_tree(tmp_path)
    files = sorted(sessions.rglob("*"))
    n_files = len(files)
    assert n_files >= 3, f"expected ≥3 fake session files, got {files}"

    with patch("skillq.paper_mode.bridge.os.chown") as mock_chown:
        _chown_agent_sessions_to_host_user(tmp_path)
        assert mock_chown.call_count == n_files
        # All chowns should target os.getuid() / os.getgid()
        for call in mock_chown.call_args_list:
            args, _ = call
            assert args[1] == os.getuid()
            assert args[2] == os.getgid()


def test_chown_helper_swallows_permission_error(tmp_path: Path):
    """os.chown raises PermissionError → helper does not propagate."""
    _make_session_tree(tmp_path)
    with patch(
        "skillq.paper_mode.bridge.os.chown",
        side_effect=PermissionError("not root"),
    ) as mock_chown:
        # Must not raise
        _chown_agent_sessions_to_host_user(tmp_path)
        # It did try to chown every file (swallowed each one)
        assert mock_chown.call_count >= 3


def test_chown_helper_swallows_file_not_found(tmp_path: Path):
    """os.chown raises FileNotFoundError → helper does not propagate."""
    _make_session_tree(tmp_path)
    with patch(
        "skillq.paper_mode.bridge.os.chown",
        side_effect=FileNotFoundError("race: file disappeared"),
    ):
        # Must not raise
        _chown_agent_sessions_to_host_user(tmp_path)


def test_chown_helper_uses_follow_symlinks_false(tmp_path: Path):
    """follow_symlinks=False is passed (don't follow symlinks, avoid
    touching targets outside agent/sessions/)."""
    _make_session_tree(tmp_path)
    with patch("skillq.paper_mode.bridge.os.chown") as mock_chown:
        _chown_agent_sessions_to_host_user(tmp_path)
        for call in mock_chown.call_args_list:
            _, kwargs = call
            assert kwargs.get("follow_symlinks") is False, (
                f"follow_symlinks should be False, got {kwargs}"
            )


def test_chown_helper_accepts_string_path(tmp_path: Path):
    """Helper accepts a str path (not just Path)."""
    _make_session_tree(tmp_path)
    with patch("skillq.paper_mode.bridge.os.chown") as mock_chown:
        _chown_agent_sessions_to_host_user(str(tmp_path))
        assert mock_chown.call_count >= 3
