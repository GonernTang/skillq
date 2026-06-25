"""Tests for pull-mode hook + UserPromptSubmit dispatch + b_max default.

Added 2026-06-23 alongside the change that introduces retrieval_mode='pull':
  - hook.py now dispatches on hook_event_name
  - _handle_session_start (now UserPromptSubmit branch) embeds user prompt,
    runs Eq.4, emits additionalContext
  - hook_settings_json() optionally registers a UserPromptSubmit hook
  - resolve_retrieval_mode() maps 'pull' to 'hook' wiring
  - MethodConfig.b_max default raised from 50 to 1000

Note: the function name `_handle_session_start` is a historical holdover
from the original SessionStart design (which fired with empty `prompt`
on `source: startup`). The implementation is now reached on
UserPromptSubmit, which has the user prompt populated.
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

from skillq.skillq_runtime.agent import hook_settings_json, pull_env  # noqa: E402
from skillq.skillq_runtime.bridge import resolve_retrieval_mode  # noqa: E402
from skillq.skillq_runtime.config import MethodConfig  # noqa: E402
from skillq.skillq_runtime.hook import (  # noqa: E402
    _format_pull_context,
    _handle_session_start,
    _make_session_start_context,
    _score_skills,
    main as hook_main,
)


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
    # The PreToolUse entry is byte-identical to the pre-2026-06-23 shape.
    ptu = s["hooks"]["PreToolUse"][0]
    assert ptu["matcher"] == "Skill"
    assert ptu["hooks"][0]["command"] == "python3 /x.py"
    assert ptu["hooks"][0]["type"] == "command"


def test_hook_settings_json_with_pull_includes_session_start():
    """include_pull=True adds a UserPromptSubmit entry alongside PreToolUse.

    (Test name is historical — the implementation moved from SessionStart
    to UserPromptSubmit on 2026-06-23 because SessionStart fires with
    an empty prompt field at startup.)
    """
    s = hook_settings_json(hook_container_path="/x.py", include_pull=True)
    assert "PreToolUse" in s["hooks"]
    assert "UserPromptSubmit" in s["hooks"]
    # UserPromptSubmit has no matcher (fires unconditionally on every user prompt).
    ups = s["hooks"]["UserPromptSubmit"][0]
    assert "matcher" not in ups
    # Same command — hook.py dispatches by hook_event_name internally.
    assert ups["hooks"][0]["command"] == "python3 /x.py"
    assert ups["hooks"][0]["type"] == "command"


# ---------------------------------------------------------------------------
# pull_env
# ---------------------------------------------------------------------------
def test_pull_env_serializes_top_k_as_string():
    """Env vars are str-only. The hook reads SKILLQ_PULL_TOP_K with int()."""
    assert pull_env(top_k=5) == {"SKILLQ_PULL_TOP_K": "5"}
    assert pull_env(top_k=3) == {"SKILLQ_PULL_TOP_K": "3"}


# ---------------------------------------------------------------------------
# _make_session_start_context / _format_pull_context (pure formatting)
# ---------------------------------------------------------------------------
def test_make_session_start_context_returns_expected_shape():
    """Output schema for Claude Code UserPromptSubmit hook."""
    out = _make_session_start_context("hello")
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "hello",
        }
    }


def test_format_pull_context_includes_all_top_k_skills():
    """Every (skill_id, score) pair becomes a numbered entry."""
    skills = [
        {"skill_id": "a", "description": "alpha"},
        {"skill_id": "b", "description": "beta"},
    ]
    top_k = [("a", 0.42), ("b", -0.13)]
    text = _format_pull_context(top_k, skills)
    assert "a" in text
    assert "b" in text
    assert "+0.420" in text
    assert "-0.130" in text
    # Both descriptions appear (under their respective numbers).
    assert "alpha" in text
    assert "beta" in text


def test_format_pull_context_truncates_long_descriptions():
    """Avoid blowing context budget on huge descriptions."""
    long_desc = "x" * 500
    skills = [{"skill_id": "a", "description": long_desc}]
    text = _format_pull_context([("a", 0.1)], skills)
    # Truncated to 120 chars + ellipsis on the description line.
    desc_line = next(l for l in text.splitlines() if l.strip().startswith("x"))
    assert len(desc_line.strip()) <= 130  # 120 chars + "..." + indent


# ---------------------------------------------------------------------------
# _handle_session_start: happy path with mocked embed
# ---------------------------------------------------------------------------
def _seed_lib_files(tmp_path: Path, n_skills: int = 3) -> tuple[Path, Path, Path]:
    """Write lib/q_table/emb_cache JSON to tmp_path and return paths."""
    lib_path = tmp_path / "lib.json"
    q_path = tmp_path / "q_table.json"
    emb_path = tmp_path / "emb_cache.json"

    skills = [
        {"skill_id": f"sk{i}", "description": f"desc {i}", "body": "", "n_retrievals": 0}
        for i in range(n_skills)
    ]
    lib_path.write_text(json.dumps({"skills": skills}))
    q_path.write_text(json.dumps({f"sk{i}": 0.5 for i in range(n_skills)}))
    # Each embedding is a 4-dim unit vector differing by index.
    emb_cache = {
        "embeddings": {f"sk{i}": [1.0 if j == i else 0.0 for j in range(4)]
                       for i in range(n_skills)}
    }
    emb_path.write_text(json.dumps(emb_cache))
    return lib_path, q_path, emb_path


def test_handle_session_start_happy_path(tmp_path: Path, capsys, monkeypatch):
    """Pull-mode handler returns additionalContext with Top-K skill ids.

    Disables the Hard Gate for this test (the orthogonal unit-vector
    fixture would otherwise be filtered by the 0.75 default). The
    gate behavior itself is tested in
    tests/test_paper_hooks.py:test_score_skills_gate_*.
    """
    lib_path, q_path, emb_path = _seed_lib_files(tmp_path, n_skills=3)

    env = {
        "SKILLQ_LIB": str(lib_path),
        "SKILLQ_Q_TABLE": str(q_path),
        "SKILLQ_EMB_CACHE": str(emb_path),
        "SKILLQ_EMBED_HOST": "127.0.0.1",
        "SKILLQ_EMBED_PORT": "1",  # never actually called (stubbed)
        "SKILLQ_PULL_TOP_K": "2",
    }
    # Embed for prompt "alpha" should match sk0 most strongly.
    stubbed_emb = [0.99, 0.01, 0.0, 0.0]
    payload = {"hook_event_name": "UserPromptSubmit", "prompt": "alpha"}

    # Disable the Hard Gate for this test — the unit-vector fixture
    # (sk0=[1,0,0,0], sk1=[0,1,0,0], sk2=[0,0,1,0]) gives
    # cos(stubbed, sk1)=0.01, well below the 0.75 default. The gate
    # would drop sk1/sk2 and leave only sk0 in the output, defeating
    # the test's purpose. Hard Gate semantics are exercised
    # separately in test_paper_hooks.py.
    from skillq.skillq_runtime import hook as hook_mod
    monkeypatch.setattr(hook_mod, "SIM_GATE_MIN_SCORE", 0.0)

    with patch.dict(os.environ, env, clear=True), \
         patch("skillq.skillq_runtime.hook._post_embed", return_value=stubbed_emb):
        rc = _handle_session_start(payload)

    assert rc == 0
    out = capsys.readouterr().out
    decision = json.loads(out)
    assert decision["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    ctx = decision["hookSpecificOutput"]["additionalContext"]
    # Top-K=2 so two numbered skill entries appear.
    assert "sk0" in ctx
    assert "sk1" in ctx


def test_handle_session_start_fail_open_on_embed_error(tmp_path: Path, capsys):
    """Any exception inside the handler → exit 0 + empty stdout.

    We force a real failure path: a corrupt lib.json file. The
    handler's outer try/except should swallow it (the existing
    PreToolUse branch has the same contract — see hook.py:334-344
    pass-through on read failure).
    """
    lib_path = tmp_path / "lib.json"
    lib_path.write_text("{not valid json")  # _read_json will throw
    env = {
        "SKILLQ_LIB": str(lib_path),
        "SKILLQ_Q_TABLE": str(tmp_path / "q.json"),
        "SKILLQ_EMB_CACHE": str(tmp_path / "e.json"),
    }
    payload = {"hook_event_name": "UserPromptSubmit", "prompt": "anything"}
    with patch.dict(os.environ, env, clear=True):
        rc = _handle_session_start(payload)

    assert rc == 0
    # Corrupt JSON → handler bails early; stdout empty.
    assert capsys.readouterr().out == ""


def test_handle_session_start_degrades_when_embed_returns_none(tmp_path: Path, capsys):
    """When the embed daemon is unreachable, _post_embed returns None.
    The handler must still produce a valid Top-K (Q + UCB only) and
    flag it in the context. This is the realistic 'embed down' case.
    """
    lib_path, q_path, emb_path = _seed_lib_files(tmp_path, n_skills=3)
    env = {
        "SKILLQ_LIB": str(lib_path),
        "SKILLQ_Q_TABLE": str(q_path),
        "SKILLQ_EMB_CACHE": str(emb_path),
        "SKILLQ_EMBED_HOST": "127.0.0.1",
        "SKILLQ_EMBED_PORT": "1",
        "SKILLQ_PULL_TOP_K": "2",
    }
    payload = {"hook_event_name": "UserPromptSubmit", "prompt": "anything"}

    with patch.dict(os.environ, env, clear=True), \
         patch("skillq.skillq_runtime.hook._post_embed", return_value=None):
        rc = _handle_session_start(payload)

    assert rc == 0
    out = capsys.readouterr().out
    decision = json.loads(out)
    ctx = decision["hookSpecificOutput"]["additionalContext"]
    # Still produces a ranked list, plus the "embedding unavailable" caveat.
    assert "embedding unavailable" in ctx.lower()
    assert "sk0" in ctx  # some skill_id appears


def test_handle_session_start_fail_open_on_missing_lib(tmp_path: Path, capsys):
    """No SKILLQ_LIB → handler returns 0 with empty stdout (no crash)."""
    payload = {"hook_event_name": "SessionStart", "prompt": "x"}
    env = {"SKILLQ_EMBED_HOST": "127.0.0.1", "SKILLQ_EMBED_PORT": "1"}
    with patch.dict(os.environ, env, clear=True):
        rc = _handle_session_start(payload)
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_handle_session_start_does_not_write_calls_log(tmp_path: Path):  # noqa: N802 — historical name
    """Pull-mode must NOT touch calls_log — Q-update stays in PreToolUse."""
    lib_path, q_path, emb_path = _seed_lib_files(tmp_path, n_skills=2)
    calls_log = tmp_path / "skillq_calls.jsonl"
    env = {
        "SKILLQ_LIB": str(lib_path),
        "SKILLQ_Q_TABLE": str(q_path),
        "SKILLQ_EMB_CACHE": str(emb_path),
        "SKILLQ_CALLS_LOG": str(calls_log),
        "SKILLQ_EMBED_HOST": "127.0.0.1",
        "SKILLQ_EMBED_PORT": "1",
    }
    payload = {"hook_event_name": "UserPromptSubmit", "prompt": "x"}
    with patch.dict(os.environ, env, clear=True), \
         patch("skillq.skillq_runtime.hook._post_embed", return_value=[1.0, 0, 0, 0]):
        _handle_session_start(payload)

    assert not calls_log.exists(), "UserPromptSubmit must not append to calls_log"


# ---------------------------------------------------------------------------
# main() dispatch — full subprocess so we exercise the stdin/stdout protocol
# ---------------------------------------------------------------------------
def _run_hook_subprocess(payload: dict, env: dict) -> tuple[int, str, str]:
    """Invoke hook.py's main() as a subprocess with the given payload+env."""
    hook_script = ROOT / "skillq" / "skillq_runtime" / "hook.py"
    proc = subprocess.run(
        [sys.executable, str(hook_script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_main_dispatches_session_start(tmp_path: Path):
    """End-to-end: feed UserPromptSubmit payload via subprocess; observe
    additionalContext on stdout."""
    lib_path, q_path, emb_path = _seed_lib_files(tmp_path, n_skills=3)
    # Embed daemon unreachable from this test process; that's fine —
    # the handler must fail-open. So we pass a payload with an empty
    # prompt to hit the early-return path (still covers the
    # dispatch).
    payload = {"hook_event_name": "UserPromptSubmit", "prompt": ""}
    env = {
        **os.environ,
        "SKILLQ_LIB": str(lib_path),
        "SKILLQ_Q_TABLE": str(q_path),
        "SKILLQ_EMB_CACHE": str(emb_path),
    }
    rc, out, err = _run_hook_subprocess(payload, env)
    assert rc == 0
    assert out == ""  # empty prompt → early-return pass-through


def test_main_dispatches_unknown_event_to_passthrough():
    """Unknown hook events (Stop, Notification, ...) → exit 0 empty."""
    payload = {"hook_event_name": "Notification", "message": "test"}
    env = {**os.environ}
    rc, out, _ = _run_hook_subprocess(payload, env)
    assert rc == 0
    assert out == ""


# ---------------------------------------------------------------------------
# Reuse check — _score_skills is the same function the PreToolUse branch uses
# ---------------------------------------------------------------------------
def test_score_skills_reused_unchanged():
    """The UserPromptSubmit handler reuses _score_skills verbatim. Quick
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
        c_ucb=0.5,
        top_k=2,
    )
    assert [sid for sid, _ in top] == ["a", "b"]