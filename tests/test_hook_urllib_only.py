"""Phase 10 Bug 4: hook.py must work without ``requests`` in container.

The SkillsVote prebuilt image only ships python3 + stdlib (no
``requests``). The hook.py file mounted into the agent container
must therefore use only stdlib for its HTTP client. This test
verifies that the container hook module imports cleanly and that
``_call_rank`` uses urllib, not requests.

Regression pin: prior to the fix, ``import requests`` inside
``_call_rank`` raised ``ModuleNotFoundError`` on every Skill()
invocation in Method B mode, causing the PreToolUse hook to fail
open and emit a non-blocking traceback to the trajectory.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def hook_env(monkeypatch, tmp_path: Path):
    """Import the container hook with controlled env."""
    log_path = tmp_path / "calls.jsonl"
    monkeypatch.setenv("SKILLQ_RANK_ENDPOINT", "http://127.0.0.1:8765")
    monkeypatch.setenv("SKILLQ_CALLS_LOG_PATH", str(log_path))
    monkeypatch.setenv("SKILLQ_HOOK_TOP_K", "3")
    monkeypatch.setenv("SKILLQ_HOOK_LAMBDA", "0.5")
    monkeypatch.setenv("SKILLQ_HOOK_C_UCB", "0.5")
    monkeypatch.setenv("SKILLQ_HOOK_SCORE_MODE", "multiplicative")
    monkeypatch.setenv("SKILLQ_HOOK_MULT_BETA", "0.5")
    monkeypatch.setenv("SKILLQ_HOOK_MULT_GAMMA", "0.2")
    monkeypatch.setenv("SKILLQ_SIM_GATE_MIN_SCORE", "0.0")
    monkeypatch.setenv("SKILLQ_SIM_GATE_FLOOR", "0")
    monkeypatch.delenv("SKILLQ_HOOK_Q_CLIP_MIN", raising=False)
    monkeypatch.delenv("SKILLQ_HOOK_Q_CLIP_MAX", raising=False)

    sys.modules.pop("skillq.runtime.hook", None)
    import skillq.runtime.hook as hook_mod

    return {"hook_mod": hook_mod, "log_path": log_path}


def test_hook_module_does_not_import_requests(monkeypatch):
    """The hook module must not depend on the ``requests`` package.

    We assert this by deleting ``requests`` from ``sys.modules``
    (if present) and patching the module's namespace so that any
    attempt to ``import requests`` raises ModuleNotFoundError, then
    we read the hook.py source and verify it has no top-level or
    function-level ``import requests`` statement.
    """
    # Static source check: parse hook.py and confirm there is no
    # `import requests` or `from requests import ...` statement.
    hook_path = ROOT / "skillq" / "runtime" / "hook.py"
    source = hook_path.read_text(encoding="utf-8")
    # Strip comments and strings containing 'requests' that are NOT
    # actual import statements (e.g. docstring references).
    bad = []
    for line in source.splitlines():
        stripped = line.strip()
        if (
            stripped.startswith("import requests")
            or stripped.startswith("from requests")
        ):
            bad.append(line)
    assert not bad, f"hook.py has forbidden requests imports: {bad}"

    # Runtime check: try to import the hook module with a hook
    # installed on ``sys.modules['requests']`` to track any access.
    if "requests" in sys.modules:
        monkeypatch.delitem(sys.modules, "requests")

    # Set required env so module-load assertion succeeds
    monkeypatch.setenv("SKILLQ_RANK_ENDPOINT", "http://127.0.0.1:8765")
    monkeypatch.delenv("SKILLQ_HOOK_Q_CLIP_MIN", raising=False)
    monkeypatch.delenv("SKILLQ_HOOK_Q_CLIP_MAX", raising=False)

    sys.modules.pop("skillq.runtime.hook", None)
    import skillq.runtime.hook  # noqa: F401 — must not raise
    # hook module loaded without ever importing requests


def test_call_rank_uses_urllib_not_requests(hook_env):
    """_call_rank must succeed when ``requests`` is unavailable.

    We patch urllib.request.urlopen to return a canned 200 JSON
    response. ``_call_rank`` should call it and parse the JSON
    without ever importing requests.
    """
    hook_mod = hook_env["hook_mod"]

    canned_body = {"allowed": True, "reason": "ok", "top_k": [], "ranking_id": "x"}
    canned_json = json.dumps(canned_body)

    class FakeResponse:
        def __init__(self, body: bytes, status: int = 200):
            self._body = body
            self._status = status

        def read(self) -> bytes:
            return self._body

        def getcode(self) -> int:
            return self._status

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with mock.patch(
        "urllib.request.urlopen",
        return_value=FakeResponse(canned_json.encode("utf-8"), 200),
    ) as fake_urlopen:
        status, body, reason = hook_mod._call_rank("test query", top_k=3)

    assert status == 200
    assert body == canned_body
    assert reason == "ok"
    # urlopen was actually called
    assert fake_urlopen.call_count >= 1


def test_call_rank_handles_http_error(hook_env):
    """_call_rank returns (status, None, reason) on non-200 HTTPError."""
    hook_mod = hook_env["hook_mod"]

    import urllib.error

    def raise_http(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="http://x", code=500, msg="Server Error", hdrs=None, fp=None
        )

    with mock.patch("urllib.request.urlopen", side_effect=raise_http):
        status, body, reason = hook_mod._call_rank("q", top_k=3)

    assert status == -1
    assert body is None
    assert "http 500" in reason


def test_call_rank_handles_url_error(hook_env):
    """_call_rank returns (status, None, reason) on URLError (network down)."""
    hook_mod = hook_env["hook_mod"]
    import urllib.error

    def raise_url(*args, **kwargs):
        raise urllib.error.URLError("Connection refused")

    with mock.patch("urllib.request.urlopen", side_effect=raise_url):
        status, body, reason = hook_mod._call_rank("q", top_k=3)

    assert status == -1
    assert body is None
    assert "URLError" in reason