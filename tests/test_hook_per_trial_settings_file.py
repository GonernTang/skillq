"""Bug #51/#52 fix (2026-07-01): hook reads per-trial state from
``/logs/agent/sessions/settings.json``'s ``"skillq"`` block.

The hook used to read ``SKILLQ_USER_TASK`` / ``SKILLQ_CALLS_LOG_PATH``
from env vars. Those env vars raced against Harbor's per-trial
``agent._extra_env`` snapshot under ``n_concurrent_trials >= 2``.
The fix moves per-trial state into the bind-mounted
``/logs/agent/sessions/settings.json``'s ``"skillq"`` block, which
the hook reads lazily (with module-level cache) on every request.

These tests build a fake settings.json file at the expected
container path, point the hook's ``_SETTINGS_PATH`` at it, reset
its cache, and exercise the readers end-to-end.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Settings-file reader: must read the per-trial ``"skillq"`` block.
# ---------------------------------------------------------------------------
def _write_settings_file(
    container_root: Path,
    *,
    user_task: str = "",
    calls_log_path: str = "",
) -> Path:
    """Write a fake ``/logs/agent/sessions/settings.json`` the hook
    will read."""
    p = container_root / "logs" / "agent" / "sessions" / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Skill",
                            "hooks": [
                                {"type": "command", "command": "python3 /x.py"}
                            ],
                        }
                    ]
                },
                "skillq": {
                    "user_task": user_task,
                    "calls_log_path": calls_log_path,
                },
            }
        ),
        encoding="utf-8",
    )
    return p


@pytest.fixture
def hook_with_settings(tmp_path):
    """Import skillq.runtime.hook with ``_SETTINGS_PATH`` pointed at
    a tmp_path-based settings.json. Returns the module with its
    cache + module-level ``CALLS_LOG_PATH`` reset (other tests
    like ``test_hook_calls_log_l1_sim.py`` mutate these globals).

    Yields the (hook_mod, container_root) tuple so each test can
    populate / overwrite the settings file before exercising the
    readers.
    """
    container_root = tmp_path / "container"
    container_root.mkdir(parents=True, exist_ok=True)
    fake_settings = (
        container_root / "logs" / "agent" / "sessions" / "settings.json"
    )
    fake_settings.parent.mkdir(parents=True, exist_ok=True)

    import skillq.runtime.hook as hook_mod

    # Snapshot module globals so we can restore them at teardown.
    saved_settings_path = hook_mod._SETTINGS_PATH
    saved_cache = hook_mod._SETTINGS_CACHE
    saved_calls_log_path = hook_mod.CALLS_LOG_PATH

    # Reset cache + repoint the path BEFORE the test writes the file.
    hook_mod._SETTINGS_PATH = str(fake_settings)
    hook_mod._SETTINGS_CACHE = None
    hook_mod.CALLS_LOG_PATH = ""  # neutralize cross-test pollution

    yield hook_mod, container_root

    # Restore defaults so other tests aren't affected.
    hook_mod._SETTINGS_PATH = saved_settings_path
    hook_mod._SETTINGS_CACHE = saved_cache
    hook_mod.CALLS_LOG_PATH = saved_calls_log_path


def test_user_task_reads_from_settings_json(tmp_path, hook_with_settings):
    """_user_task() must return the ``skillq.user_task`` field from
    the bind-mounted settings.json, NOT the env var."""
    hook_mod, container_root = hook_with_settings
    _write_settings_file(
        container_root,
        user_task="Solve chess best move",
        calls_log_path="/logs/agent/sessions/_calls_log/abc.jsonl",
    )
    hook_mod._SETTINGS_CACHE = None  # reset cache after file write

    # Env var is empty (the new code doesn't read it) — the file
    # value must still win.
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("SKILLQ_USER_TASK", "")
        assert hook_mod._user_task() == "Solve chess best move"


def test_calls_log_path_reads_from_settings_json(tmp_path, hook_with_settings):
    """_calls_log_path() must return the ``skillq.calls_log_path``
    field from the bind-mounted settings.json, NOT the env var."""
    hook_mod, container_root = hook_with_settings
    _write_settings_file(
        container_root,
        user_task="",
        calls_log_path="/logs/agent/sessions/_calls_log/abc.jsonl",
    )
    hook_mod._SETTINGS_CACHE = None

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("SKILLQ_CALLS_LOG_PATH", "")
        assert hook_mod._calls_log_path() == "/logs/agent/sessions/_calls_log/abc.jsonl"


def test_settings_file_missing_returns_empty_strings(tmp_path, hook_with_settings):
    """If the settings.json is missing (or unreadable), the readers
    return empty strings — the hook falls back to env vars /
    transcript tail."""
    hook_mod, _container_root = hook_with_settings
    # Don't write settings.json at all.
    hook_mod._SETTINGS_CACHE = None
    assert hook_mod._user_task() == ""
    assert hook_mod._calls_log_path() == ""


def test_settings_cache_returns_same_dict_across_calls(tmp_path, hook_with_settings):
    """Module-level cache: the second call to _load_skillq_settings
    must return the same dict object (no disk re-read)."""
    hook_mod, container_root = hook_with_settings
    _write_settings_file(container_root, user_task="task A")
    hook_mod._SETTINGS_CACHE = None

    a = hook_mod._load_skillq_settings()
    b = hook_mod._load_skillq_settings()
    assert a is b, "settings cache should be hit on second call"


def test_user_task_wins_over_env_var_when_settings_present(tmp_path, hook_with_settings):
    """When the settings file has a non-empty user_task, it must
    take precedence over any SKILLQ_USER_TASK env var (the env var
    is legacy fallback only)."""
    hook_mod, container_root = hook_with_settings
    _write_settings_file(container_root, user_task="from settings file")
    hook_mod._SETTINGS_CACHE = None

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("SKILLQ_USER_TASK", "from env var")
        assert hook_mod._user_task() == "from settings file"


def test_calls_log_path_falls_back_to_module_global_when_settings_empty(tmp_path, hook_with_settings):
    """Back-compat: if the settings file has an empty
    calls_log_path, the module-level ``CALLS_LOG_PATH`` (set at
    import time from ``SKILLQ_CALLS_LOG_PATH`` env var) is used.
    This preserves legacy hooks that still rely on the env var.
    """
    hook_mod, container_root = hook_with_settings
    _write_settings_file(container_root, calls_log_path="")
    hook_mod._SETTINGS_CACHE = None

    # Simulate an env-var-set module global (legacy import-time read).
    hook_mod.CALLS_LOG_PATH = "/tmp/legacy.jsonl"
    try:
        assert hook_mod._calls_log_path() == "/tmp/legacy.jsonl"
    finally:
        hook_mod.CALLS_LOG_PATH = ""


def test_settings_file_malformed_json_returns_empty_dict(tmp_path, hook_with_settings):
    """A malformed settings.json must not crash the hook — the
    readers return empty strings (which the hook treats as
    "no per-trial state available")."""
    hook_mod, container_root = hook_with_settings
    fake_settings_path = (
        container_root / "logs" / "agent" / "sessions" / "settings.json"
    )
    fake_settings_path.write_text("not valid json {", encoding="utf-8")
    hook_mod._SETTINGS_CACHE = None

    assert hook_mod._user_task() == ""
    assert hook_mod._calls_log_path() == ""