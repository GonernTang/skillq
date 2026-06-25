"""Unit tests for ``_classify_trial_failure`` in ``skillq.skillq_runtime.bridge``.

The classifier decides which ``on_ended`` paths run after a Harbor
trial. The classification is the foundation of the 2026-06-25 fix
that lets auto_extract fire on ``NonZeroAgentExitCodeError`` /
``AgentTimeoutError`` when a usable trajectory is on disk.

14 scenarios are pinned here. Each constructs a fake
``TrialHookEvent``-shaped MagicMock, runs the classifier, and
asserts the returned ``TrialFailureClass`` enum value.

Trajectory presence is controlled by writing or omitting
``<trial_dir>/agent/trajectory.json`` with a list containing one
``{"type": "assistant", ...}`` entry. The classifier is
intentionally tolerant of malformed trajectory files — it returns
False on any I/O / JSON / shape error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.skillq_runtime.bridge import (  # noqa: E402
    TrialFailureClass,
    _classify_trial_failure,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _write_usable_trajectory(trial_dir: Path) -> None:
    """Write a 1-entry trajectory.json (assistant message)."""
    traj_dir = trial_dir / "agent"
    traj_dir.mkdir(parents=True, exist_ok=True)
    traj = traj_dir / "trajectory.json"
    traj.write_text(
        json.dumps(
            [{"type": "assistant", "message": {"content": "ok"}}]
        ),
        encoding="utf-8",
    )


def _make_event(
    trial_uri: str | None,
    exception_type: str | None,
    exception_message: str = "",
    retry_excludes: list[str] | None = None,
    retry_includes: list[str] | None = None,
    max_retries: int = 0,
) -> MagicMock:
    """Build a MagicMock TrialHookEvent with the given exception
    shape. Pass ``trial_uri=None`` to simulate ``event.result is None``.
    """
    event = MagicMock()
    event.trial_id = "trial-x"
    event.task_name = "sample-task"

    if trial_uri is None:
        event.result = None
        return event

    result = MagicMock()
    result.trial_uri = trial_uri
    if exception_type is None:
        result.exception_info = None
    else:
        exc_info = MagicMock()
        exc_info.exception_type = exception_type
        exc_info.exception_message = exception_message
        result.exception_info = exc_info
    event.result = result

    # retry config on the job. Use SimpleNamespace (not MagicMock)
    # because MagicMock's `is not None` is always True and its
    # `__contains__` is always False, which would silently corrupt
    # retry-classification. ``max_retries=0`` is the default
    # (no retries — the user runs with this in production).
    event.config = SimpleNamespace(
        retry=SimpleNamespace(
            max_retries=max_retries,
            exclude_exceptions=retry_excludes,
            include_exceptions=retry_includes,
        )
    )
    return event


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
class TestClassifyTrialFailure:
    """The 14-scenario contract pinned in
    ~/.claude/plans/bug-3-per-trial-q-table-json-hashed-quilt.md
    (2026-06-25 revision).
    """

    def test_1_no_exception_runs_normal(self, tmp_path: Path):
        trial_dir = tmp_path / "t1"
        event = _make_event(
            trial_uri=str(trial_dir),
            exception_type=None,
        )
        assert _classify_trial_failure(
            event, event.config.retry, trial_dir
        ) is TrialFailureClass.RUN_NORMAL

    def test_2_nonzero_agent_exit_with_trajectory_runs_task_failure(
        self, tmp_path: Path
    ):
        trial_dir = tmp_path / "t2"
        _write_usable_trajectory(trial_dir)
        event = _make_event(
            trial_uri=str(trial_dir),
            exception_type="NonZeroAgentExitCodeError",
            exception_message="Command failed (exit 1): claude",
        )
        assert _classify_trial_failure(
            event, event.config.retry, trial_dir
        ) is TrialFailureClass.RUN_TASK_FAILURE

    def test_3_oom_kill_with_trajectory_skips_all(
        self, tmp_path: Path
    ):
        """OOM is ALWAYS infra failure per user direction (2026-06-25),
        even if a partial trajectory was written."""
        trial_dir = tmp_path / "t3"
        _write_usable_trajectory(trial_dir)
        event = _make_event(
            trial_uri=str(trial_dir),
            exception_type="NonZeroAgentExitCodeError",
            exception_message="Command failed (exit 137): killed",
        )
        assert _classify_trial_failure(
            event, event.config.retry, trial_dir
        ) is TrialFailureClass.SKIP_ALL

    def test_4_oom_kill_without_trajectory_skips_all(
        self, tmp_path: Path
    ):
        trial_dir = tmp_path / "t4"
        # no trajectory.json
        event = _make_event(
            trial_uri=str(trial_dir),
            exception_type="NonZeroAgentExitCodeError",
            exception_message="Command failed (exit 137): killed",
        )
        assert _classify_trial_failure(
            event, event.config.retry, trial_dir
        ) is TrialFailureClass.SKIP_ALL

    def test_5_agent_timeout_with_trajectory_runs_task_failure(
        self, tmp_path: Path
    ):
        """Per user direction, AgentTimeoutError is task failure
        (the agent got stuck, ran to the wall, full trajectory)."""
        trial_dir = tmp_path / "t5"
        _write_usable_trajectory(trial_dir)
        event = _make_event(
            trial_uri=str(trial_dir),
            exception_type="AgentTimeoutError",
            exception_message="agent.run timeout",
        )
        assert _classify_trial_failure(
            event, event.config.retry, trial_dir
        ) is TrialFailureClass.RUN_TASK_FAILURE

    def test_6_agent_timeout_without_trajectory_skips_all(
        self, tmp_path: Path
    ):
        trial_dir = tmp_path / "t6"
        event = _make_event(
            trial_uri=str(trial_dir),
            exception_type="AgentTimeoutError",
            exception_message="agent.run timeout",
        )
        assert _classify_trial_failure(
            event, event.config.retry, trial_dir
        ) is TrialFailureClass.SKIP_ALL

    def test_7_verifier_timeout_excluded_from_retry_runs_task_failure(
        self, tmp_path: Path
    ):
        """VerifierTimeoutError is in the user's
        ``retry.exclude_exceptions`` list. With max_retries=0 the
        list is inert at runtime, but the classifier still applies
        it: an excluded exception is treated as a durable task
        failure (the user said "this is the final answer, learn
        from it")."""
        trial_dir = tmp_path / "t7"
        _write_usable_trajectory(trial_dir)
        event = _make_event(
            trial_uri=str(trial_dir),
            exception_type="VerifierTimeoutError",
            exception_message="verifier timeout",
            retry_excludes=["VerifierTimeoutError"],
        )
        assert _classify_trial_failure(
            event, event.config.retry, trial_dir
        ) is TrialFailureClass.RUN_TASK_FAILURE

    def test_8_nonzero_agent_exit_no_trajectory_skips_all(
        self, tmp_path: Path
    ):
        """No trajectory → can't extract anything → SKIP_ALL."""
        trial_dir = tmp_path / "t8"
        event = _make_event(
            trial_uri=str(trial_dir),
            exception_type="NonZeroAgentExitCodeError",
            exception_message="Command failed (exit 1): claude",
        )
        assert _classify_trial_failure(
            event, event.config.retry, trial_dir
        ) is TrialFailureClass.SKIP_ALL

    def test_9_environment_start_timeout_skips_all(
        self, tmp_path: Path
    ):
        trial_dir = tmp_path / "t9"
        event = _make_event(
            trial_uri=str(trial_dir),
            exception_type="EnvironmentStartTimeoutError",
            exception_message="env start timeout",
        )
        assert _classify_trial_failure(
            event, event.config.retry, trial_dir
        ) is TrialFailureClass.SKIP_ALL

    def test_10_healthcheck_error_skips_all(
        self, tmp_path: Path
    ):
        trial_dir = tmp_path / "t10"
        event = _make_event(
            trial_uri=str(trial_dir),
            exception_type="HealthcheckError",
            exception_message="env healthcheck failed",
        )
        assert _classify_trial_failure(
            event, event.config.retry, trial_dir
        ) is TrialFailureClass.SKIP_ALL

    def test_11_runtime_error_install_failed_skips_all(
        self, tmp_path: Path
    ):
        """`RuntimeError("Agent install failed: …")` is infra."""
        trial_dir = tmp_path / "t11"
        event = _make_event(
            trial_uri=str(trial_dir),
            exception_type="RuntimeError",
            exception_message="Agent install failed: …",
        )
        assert _classify_trial_failure(
            event, event.config.retry, trial_dir
        ) is TrialFailureClass.SKIP_ALL

    def test_12_top_level_asyncio_timeout_skips_all(
        self, tmp_path: Path
    ):
        """`asyncio.TimeoutError` escaping the per-step wrapper
        (trial.py:1009) is caught at the top level and treated as
        infra."""
        trial_dir = tmp_path / "t12"
        event = _make_event(
            trial_uri=str(trial_dir),
            exception_type="asyncio.TimeoutError",
            exception_message="top-level",
        )
        assert _classify_trial_failure(
            event, event.config.retry, trial_dir
        ) is TrialFailureClass.SKIP_ALL

    def test_13_retryable_skips_all(self, tmp_path: Path):
        """If the user has configured ``max_retries > 0`` AND
        ``include_exceptions`` to include this exception, the trial
        is retryable → SKIP_ALL."""
        trial_dir = tmp_path / "t13"
        _write_usable_trajectory(trial_dir)
        event = _make_event(
            trial_uri=str(trial_dir),
            exception_type="NonZeroAgentExitCodeError",
            exception_message="Command failed (exit 1): claude",
            retry_includes=["NonZeroAgentExitCodeError"],
            max_retries=2,
        )
        assert _classify_trial_failure(
            event, event.config.retry, trial_dir
        ) is TrialFailureClass.SKIP_ALL

    def test_14_no_result_skips_all(self, tmp_path: Path):
        trial_dir = tmp_path / "t14"  # never used; result is None
        event = _make_event(
            trial_uri=None,
            exception_type=None,
        )
        assert _classify_trial_failure(
            event, event.config.retry, trial_dir
        ) is TrialFailureClass.SKIP_ALL


# ---------------------------------------------------------------------------
# Trajectory-shape edge cases
# ---------------------------------------------------------------------------
class TestUsableTrajectoryHeuristic:
    """``_has_usable_trajectory`` gates the
    RUN_TASK_FAILURE promotion. These cases pin the heuristic so
    future refactors don't silently broaden/narrow it."""

    def test_missing_traj_dir_returns_false(self, tmp_path: Path):
        from skillq.skillq_runtime.bridge import _has_usable_trajectory
        assert _has_usable_trajectory(tmp_path / "nope") is False

    def test_empty_traj_dir_returns_false(self, tmp_path: Path):
        from skillq.skillq_runtime.bridge import _has_usable_trajectory
        # directory exists, file does not
        (tmp_path / "agent").mkdir()
        assert _has_usable_trajectory(tmp_path) is False

    def test_truncated_json_returns_false(self, tmp_path: Path):
        from skillq.skillq_runtime.bridge import _has_usable_trajectory
        traj = tmp_path / "agent" / "trajectory.json"
        traj.parent.mkdir(parents=True, exist_ok=True)
        traj.write_text('[{"type": "assistant", "mess', encoding="utf-8")
        assert _has_usable_trajectory(tmp_path) is False

    def test_non_list_json_returns_false(self, tmp_path: Path):
        from skillq.skillq_runtime.bridge import _has_usable_trajectory
        traj = tmp_path / "agent" / "trajectory.json"
        traj.parent.mkdir(parents=True, exist_ok=True)
        traj.write_text('{"type": "assistant"}', encoding="utf-8")
        assert _has_usable_trajectory(tmp_path) is False

    def test_list_with_no_assistant_returns_false(self, tmp_path: Path):
        from skillq.skillq_runtime.bridge import _has_usable_trajectory
        traj = tmp_path / "agent" / "trajectory.json"
        traj.parent.mkdir(parents=True, exist_ok=True)
        traj.write_text(
            json.dumps([{"type": "user"}, {"type": "system"}]),
            encoding="utf-8",
        )
        assert _has_usable_trajectory(tmp_path) is False

    def test_list_with_assistant_returns_true(self, tmp_path: Path):
        from skillq.skillq_runtime.bridge import _has_usable_trajectory
        traj = tmp_path / "agent" / "trajectory.json"
        traj.parent.mkdir(parents=True, exist_ok=True)
        traj.write_text(
            json.dumps(
                [{"type": "user"}, {"type": "assistant", "message": {}}]
            ),
            encoding="utf-8",
        )
        assert _has_usable_trajectory(tmp_path) is True


# ---------------------------------------------------------------------------
# OOM detection
# ---------------------------------------------------------------------------
class TestOomKillDetection:
    """Pin the ``_is_oom_kill`` substring heuristic so it doesn't
    drift."""

    def test_nonzero_137_is_oom(self):
        from skillq.skillq_runtime.bridge import _is_oom_kill
        exc = MagicMock()
        exc.exception_type = "NonZeroAgentExitCodeError"
        exc.exception_message = (
            "Command failed (exit 137): killed by kernel OOM"
        )
        assert _is_oom_kill(exc) is True

    def test_nonzero_1_is_not_oom(self):
        from skillq.skillq_runtime.bridge import _is_oom_kill
        exc = MagicMock()
        exc.exception_type = "NonZeroAgentExitCodeError"
        exc.exception_message = "Command failed (exit 1): claude"
        assert _is_oom_kill(exc) is False

    def test_other_exception_with_137_in_msg_is_not_oom(self):
        """The OOM classifier requires NonZeroAgentExitCodeError +
        exit 137 together. A random exception that happens to
        mention "137" should NOT trigger OOM classification."""
        from skillq.skillq_runtime.bridge import _is_oom_kill
        exc = MagicMock()
        exc.exception_type = "RuntimeError"
        exc.exception_message = "something with exit 137 mentioned"
        assert _is_oom_kill(exc) is False

    def test_none_info_is_not_oom(self):
        from skillq.skillq_runtime.bridge import _is_oom_kill
        assert _is_oom_kill(None) is False
