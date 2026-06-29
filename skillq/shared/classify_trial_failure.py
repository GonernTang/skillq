"""Per-trial failure classifier (Sec. 3 of the paper, runtime).

Step 1 of the 2026-06-26 refactor extracted
:func:`_classify_trial_failure` and its helpers from
:mod:`skillq.runtime.bridge` into
:mod:`skillq.shared.classify_trial_failure` so the bridge can be
reduced to a thin pipeline of step functions.

Public names: :class:`TrialFailureClass`, :func:`classify_trial_failure`,
:func:`is_oom_kill`, :func:`has_usable_trajectory`. Legacy ``_``-prefixed
aliases are kept for backward compatibility until Step 6.
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("skillq.shared.classify_trial_failure")


class TrialFailureClass(str, Enum):
    """Per-trial classifier outcome.

    - ``RUN_NORMAL``       — no exception_info, or the user has
      explicitly excluded this exception from retries. Full path.
    - ``RUN_TASK_FAILURE`` — task-side exception (agent ran but
      ``claude --print`` exited non-zero; or agent hit per-task
      ``AgentTimeoutError``; or verifier errored) AND a usable
      trajectory exists on disk. We treat the agent's failure
      reflection as worth extracting from.
    - ``SKIP_ALL``         — everything else. Do nothing. (Per
      2026-06-25 user decision, infra failures and OOM kills both
      fold into this single outcome; no Q-update, no library
      maintenance, no state.save.)
    """

    RUN_NORMAL = "run_normal"
    RUN_TASK_FAILURE = "run_task_failure"
    SKIP_ALL = "skip_all"


# Exception types that ALWAYS land in SKIP_ALL — no useful trajectory
# can be expected, so even Q-update has nothing to learn from.
# ``NonZeroAgentExitCodeError`` is NOT in this set: when its message
# does NOT contain "exit 137" (OOM) AND a trajectory exists, it
# promotes to RUN_TASK_FAILURE. See :func:`is_oom_kill` below.
_INFRA_EXCEPTIONS: frozenset[str] = frozenset({
    "EnvironmentStartTimeoutError",
    "HealthcheckError",
    "AgentSetupTimeoutError",
    "asyncio.TimeoutError",     # top-level — escapes unconverted (trial.py:1009)
    "asyncio.CancelledError",
    "RuntimeError",              # "Agent install failed: …" + step setup non-zero
    "ValueError",
    "FileNotFoundError",
})


def is_oom_kill(exception_info: Any) -> bool:
    """True iff exception is ``NonZeroAgentExitCodeError`` AND message
    contains ``"exit 137"`` (kernel OOM-kill signal).

    Per 2026-06-25 user direction, OOM is ALWAYS infra failure even
    if a partial trajectory was written. The user wants the OOM
    signal preserved, not papered over with a partial-extract.
    """
    if exception_info is None:
        return False
    if getattr(exception_info, "exception_type", None) != "NonZeroAgentExitCodeError":
        return False
    msg = getattr(exception_info, "exception_message", "") or ""
    return "exit 137" in msg


_is_oom_kill = is_oom_kill


def has_usable_trajectory(trial_dir: Path) -> bool:
    """True iff ``<trial_dir>/agent/trajectory.json`` exists, parses,
    and contains ≥ 1 ``type == "assistant"`` entry.

    Used by the classifier to gate RUN_TASK_FAILURE promotion. A
    truncated JSON file (last line mid-object) will fail
    ``json.loads`` and return False — that case falls through to
    SKIP_ALL, which is the safer default. (A finer-grained truncation
    detector that would partial-extract a single-line tail is left as
    a TODO; see plan Gap B.)
    """
    if not trial_dir:
        return False
    traj = Path(trial_dir) / "agent" / "trajectory.json"
    if not traj.is_file():
        return False
    try:
        text = traj.read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, list):
        return False
    return any(
        isinstance(e, dict) and e.get("type") == "assistant"
        for e in data
    )


_has_usable_trajectory = has_usable_trajectory


def classify_trial_failure(
    event: Any,
    retry_config: Any,
    trial_dir: Path,
) -> TrialFailureClass:
    """Decide which ``on_ended`` paths run for a given trial.

    Order matters: the OOM check runs before the
    ``_INFRA_EXCEPTIONS`` membership test because
    ``NonZeroAgentExitCodeError`` is in neither set and we need to
    short-circuit on "exit 137" first.

    The retryable check below is *not* delegated to a private helper
    because that earlier helper ignored ``max_retries`` and returned
    True for the common default configuration of
    ``include_exceptions=None, exclude_exceptions=None``, which would
    silently classify every failed trial as SKIP_ALL. The user
    explicitly runs with ``max_retries: 0`` and wants the paper
    method to *learn* from a failed agent run; we re-implement the
    retry semantics here with the correct default.
    """
    if event.result is None:
        return TrialFailureClass.SKIP_ALL

    exc = event.result.exception_info

    # 1. No exception → normal path.
    if exc is None:
        return TrialFailureClass.RUN_NORMAL

    # 2. Retryable. The user is responsible for setting
    #    ``max_retries`` AND the include/exclude lists; the
    #    default ``max_retries=0`` makes the trial non-retryable
    #    even with no include/exclude filters.
    max_retries = getattr(retry_config, "max_retries", 0) or 0
    if max_retries > 0:
        exc_type = exc.exception_type
        exclude = getattr(retry_config, "exclude_exceptions", None)
        include = getattr(retry_config, "include_exceptions", None)
        if exclude is not None and exc_type in exclude:
            pass  # explicitly excluded → treat as durable failure
        elif include is not None and exc_type not in include:
            pass  # not in the include-list → treat as durable failure
        else:
            # Retryable: Harbor will re-run. Do nothing this trial.
            return TrialFailureClass.SKIP_ALL

    # 3. OOM: always infra failure.
    if is_oom_kill(exc):
        return TrialFailureClass.SKIP_ALL

    # 4. Other infra exceptions.
    if exc.exception_type in _INFRA_EXCEPTIONS:
        return TrialFailureClass.SKIP_ALL

    # 5. Task-side failures (NonZeroAgentExitCodeError no-OOM,
    #    AgentTimeoutError, VerifierTimeoutError, RewardFile*,
    #    VerifierOutputParseError, etc.). Trajectory decides.
    if has_usable_trajectory(trial_dir):
        return TrialFailureClass.RUN_TASK_FAILURE
    return TrialFailureClass.SKIP_ALL


_classify_trial_failure = classify_trial_failure


__all__ = [
    "TrialFailureClass",
    "classify_trial_failure",
    "is_oom_kill",
    "has_usable_trajectory",
]