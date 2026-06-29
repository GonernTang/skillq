"""Tests for skillq.services.ranking_service — specifically the
``start_ranking_service_background`` ready-wait fix added
2026-06-26.

The race window: ``start_ranking_service_background`` spawns a
daemon thread running uvicorn, then returns immediately. uvicorn
takes ~50-150ms to actually bind to the port, so any hook call
fired in that window hits ECONNREFUSED, the embedding service
returns ``None``, and the hook silently degrades the entire L1
layer (``sim=null`` for every skill → all Skill calls denied by
the Hard Gate).

The fix polls ``GET /healthz`` on loopback after spawning the
thread, returning only after the server answers 200 or a 5-second
timeout elapses.
"""
from __future__ import annotations

import socket
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from skillq.services.ranking_service import (  # noqa: E402
    start_ranking_service_background,
    stop_ranking_service,
)


# When the second daemon in test_ready_wait_logs_warning_on_timeout
# fails to bind, uvicorn calls ``sys.exit(1)`` from inside the
# daemon thread. pytest 8+ escalates any uncaught thread exception
# to a test failure — even if the test's own assertions passed.
# We expect this, so silence the warning.
pytestmark = pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnhandledThreadExceptionWarning"
)


def _free_port() -> int:
    """Ask the kernel for an unused TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_ready_wait_returns_after_server_binds():
    """Happy path: start returns, then /healthz on loopback answers 200.

    Without the fix, there is a measurable window after the function
    returns where the port is still unbound. With the fix, the
    function does not return until /healthz responds 200, so by
    the time callers receive the handle the server is guaranteed
    ready to serve real requests.
    """
    port = _free_port()
    h = start_ranking_service_background(
        port=port, host="127.0.0.1", ready_timeout_sec=5.0,
    )
    try:
        # If ready-wait worked, the server MUST be reachable now.
        # We measure the request time; it should be a few ms at most
        # because the function already waited for /healthz to succeed.
        import requests
        t0 = time.monotonic()
        r = requests.get(f"http://127.0.0.1:{port}/healthz", timeout=2.0)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
        assert elapsed_ms < 100, (
            f"ready-wait didn't actually wait: /healthz round-trip "
            f"took {elapsed_ms}ms after start returned"
        )
    finally:
        stop_ranking_service(h)


def test_ready_wait_logs_warning_on_timeout():
    """If the server can't bind (e.g., port already in use), the
    function logs a warning and still returns the handle so the
    trial can proceed with a degraded (Q+UCB-only) hook.

    We force a bind failure by asking for a privileged port (1-1023)
    that the unprivileged test user can't bind to. This is more
    reliable than the "two daemons on the same port" approach:
    the first daemon's /healthz would happily answer the second
    daemon's poll loop (they share the loopback interface), masking
    the bind failure.
    """
    import os
    if os.geteuid() == 0:
        pytest.skip(
            "running as root — privileged ports bind successfully, "
            "can't simulate bind failure"
        )

    with patch(
        # Step 3 (2026-06-26) of the refactor moved the FastAPI
        # daemon into ``skillq.services.ranking_service``. The
        # warning is emitted from there, not from the legacy
        # ``embedding_service`` shim (which now only re-exports
        # the new module's names).
        "skillq.services.ranking_service.logger"
    ) as mock_logger:
        # Port 80 is privileged on Linux; unprivileged bind fails
        # with EACCES, uvicorn calls sys.exit(1) in the thread,
        # the poll loop never sees /healthz return 200, and the
        # ready_timeout_sec elapses.
        second = start_ranking_service_background(
            port=80,
            host="127.0.0.1",
            ready_timeout_sec=0.3,
        )
        try:
            # Handle returned (no exception from start_ranking_service_background).
            assert second is not None
            all_calls = (
                mock_logger.info.call_args_list
                + mock_logger.warning.call_args_list
            )
            assert any(
                "NOT ready" in str(call) for call in all_calls
            ), (
                "expected a 'NOT ready' warning when ready_timeout_sec "
                f"elapses; got calls: {[str(c) for c in all_calls]}"
            )
        finally:
            stop_ranking_service(second)


def test_handle_dict_has_required_keys():
    """Sanity check: the returned handle has the keys
    stop_ranking_service needs.
    """
    port = _free_port()
    h = start_ranking_service_background(
        port=port, host="127.0.0.1", ready_timeout_sec=5.0,
    )
    try:
        assert set(h.keys()) >= {"thread", "server", "port", "stop_event"}
        assert h["port"] == port
        assert h["thread"].is_alive()
    finally:
        stop_ranking_service(h)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
