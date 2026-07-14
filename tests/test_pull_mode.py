"""Tests for pull-mode (L1 retrieval via /rank) — Step 7 (2026-06-27).

Originally this file covered:
  - hook.py UserPromptSubmit dispatch (local embed + score)
  - _seed_lib_files helper
  - main() event dispatch

After Step 5 (2026-06-26), the container-side hook no longer does
local embedding/scoring — it POSTs to the host's /rank daemon
(see runtime/hook.py:_call_rank). The legacy local-embed tests
were dropped here because they test functionality that no longer
exists. New tests covering the /rank-based hook live in
``test_hook_force_use_text.py`` (text format) and the integration
tests under ``test_ranking_service.py`` (server side).

What remains here:

  1. MethodConfig defaults: b_max, hook_pull_top_k, retrieval_mode
  2. resolve_retrieval_mode: 'pull' → 'hook' (same wiring)
  3. hook_settings_json: SessionStart (pull-mode) registration
  4. _format_pull_context: pure text formatting (Step 5 contract)
  5. score_skills: Eq.4 + Hard Gate (now lives in
     layers.l1_retrieval.scoring; this is the unit-level test
     pinned to the layer's contract)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.runtime.agent import hook_settings_json  # noqa: E402
from skillq.runtime.container_wiring import resolve_retrieval_mode  # noqa: E402
from skillq.config import MethodConfig  # noqa: E402
from skillq.runtime.hook import (  # noqa: E402
    _format_pull_context,
    _make_session_start_context,
)
from skillq.layers.l1_retrieval.scoring import score_skills as _score_skills


# ---------------------------------------------------------------------------
# Config: b_max default + hook_pull_top_k + retrieval_mode='pull' accepted
# ---------------------------------------------------------------------------
def test_b_max_default_is_1000():
    """On 2026-06-23 default raised from 50 to 1000 after TB2 full run
    hit 100/100 and started evicting on every auto_extract insert."""
    assert MethodConfig().b_max == 1000


def test_hook_pull_top_k_default_is_3():
    """Sanity: pull-mode K defaults to 3 (matches hook_top_k default)."""
    assert MethodConfig().hook_pull_top_k == 3


def test_retrieval_mode_pull_is_accepted():
    """'pull' is a new accepted value; field is unconstrained str so
    no validator change needed."""
    m = MethodConfig(retrieval_mode="pull")
    assert m.retrieval_mode == "pull"


def test_retrieval_mode_pull_resolves_to_hook():
    """'pull' wires the same as 'hook' (PreToolUse path); the
    SessionStart entry is added by container_wiring based on
    method.retrieval_mode == 'pull'."""
    m = MethodConfig(retrieval_mode="pull")
    assert resolve_retrieval_mode(m, n_lib_skills=50) == "hook"
    assert resolve_retrieval_mode(m, n_lib_skills=2) == "hook"


# ---------------------------------------------------------------------------
# hook_settings_json: SessionStart registration
# ---------------------------------------------------------------------------
def test_hook_settings_json_default_has_no_session_start():
    """Backward-compat: default settings.json registers only PreToolUse."""
    s = hook_settings_json(hook_container_path="/x.py")
    assert "PreToolUse" in s["hooks"]
    assert "UserPromptSubmit" not in s["hooks"]


def test_hook_settings_json_pull_mode_registers_user_prompt_submit():
    """When ``include_pull=True``, a UserPromptSubmit hook is added so
    Claude Code fires our pull-mode /rank call on the user's prompt."""
    s = hook_settings_json(
        hook_container_path="/x.py",
        include_pull=True,
    )
    ups_hooks = s["hooks"].get("UserPromptSubmit", [])
    commands = [
        cmd
        for entry in ups_hooks
        for h in entry.get("hooks", [])
        for cmd in [h.get("command")]
        if cmd == "python3 /x.py"
    ]
    assert commands, (
        "include_pull=True must register a UserPromptSubmit hook"
    )


def test_hook_settings_json_command_path_uses_provided_path():
    """The hook command echoes the path we passed."""
    s = hook_settings_json(hook_container_path="/custom/path.py")
    ups = s["hooks"]["PreToolUse"]
    assert ups[0]["hooks"][0]["command"] == "python3 /custom/path.py"
    assert ups[0]["hooks"][0]["type"] == "command"


# ---------------------------------------------------------------------------
# _make_session_start_context: pure formatting
# ---------------------------------------------------------------------------
def test_make_session_start_context_wraps_text_in_envelope():
    """The additionalContext envelope wraps the text under
    hookSpecificOutput.additionalContext with a UserPromptSubmit marker."""
    ctx = _make_session_start_context("hello world")
    assert ctx["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert ctx["hookSpecificOutput"]["additionalContext"] == "hello world"


# ---------------------------------------------------------------------------
# _format_pull_context: pure text formatting
# ---------------------------------------------------------------------------
def test_format_pull_context_includes_all_top_k_skills():
    """Every dict entry becomes a numbered list item."""
    top_k = [
        {"skill_id": "a", "score": 0.42, "description": "alpha"},
        {"skill_id": "b", "score": -0.13, "description": "beta"},
    ]
    text = _format_pull_context(top_k)
    assert "a" in text
    assert "b" in text
    assert "0.420" in text
    # Both descriptions appear.
    assert "alpha" in text
    assert "beta" in text


def test_format_pull_context_truncates_long_descriptions():
    """Avoid blowing context budget on huge descriptions."""
    long_desc = "x" * 500
    text = _format_pull_context([
        {"skill_id": "a", "score": 0.1, "description": long_desc},
    ])
    # Truncated to 200 chars in the new hook (Step 5).
    assert long_desc[:200] in text
    assert long_desc[201:] not in text


# ---------------------------------------------------------------------------
# Reuse check — score_skills is the same function the PreToolUse branch uses
# ---------------------------------------------------------------------------
def test_score_skills_reused_unchanged():
    """The hook's PreToolUse branch reuses score_skills verbatim. Quick
    smoke that it still produces sorted top-k output."""
    skills = [
        {"skill_id": "a", "n_retrievals": 0},
        {"skill_id": "b", "n_retrievals": 5},
    ]
    q_table = {"a": 0.9, "b": 0.1}
    emb_cache = {"a": [1.0, 0.0], "b": [0.0, 1.0]}
    # Subtask aligns with a.
    top = _score_skills(
        subtask_emb=[0.99, 0.01],
        skills=skills,
        q_table=q_table,
        emb_cache=emb_cache,
        lambda_=0.5,
        c_ucb=0.0,
        top_k=2,
    )
    assert [sid for sid, _ in top] == ["a", "b"]
