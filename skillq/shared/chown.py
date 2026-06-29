"""Best-effort chown of the agent's session tree back to the host user.

Step 1 of the 2026-06-26 refactor extracted this helper from
:mod:`skillq.runtime.bridge` into
:mod:`skillq.shared.chown` so the bridge can be reduced to a
thin pipeline of step functions.

Workaround for the 2026-06-24 OOM-kill bug on caffe-cifar-10 /
train-fasttext: when the agent is OOM-killed (exit 137) Harbor's
``Trial._maybe_download_logs`` chown path is skipped (it lives inside
an ``if step_result.exception_info is None:`` guard at
``harbor/trial/trial.py:649-655``). The session jsonl at
``<trial_dir>/agent/sessions/projects/-app/<uuid>.jsonl`` stays
owned by ``root:root 0600`` and a later
``populate_context_post_run`` (which runs as the host user) raises
``PermissionError`` and produces no trajectory.

SkillQ runs as the host user (no container involved here), so this
helper can do the chown directly. We walk the tree, swallow
``PermissionError`` / ``FileNotFoundError`` per entry (the agent may
have left a half-flushed file mid-OOM), and log a summary.

This is intentionally a no-op when:

- ``trial_dir`` is None or empty (we don't know where to chown).
- ``<trial_dir>/agent/sessions`` does not exist (no agent output was
  produced, e.g. early-setup failure).

Failures are logged at WARNING/DEBUG level and never raise — the
Q-update path (which calls this) must not be aborted by a secondary
filesystem fixup.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("skillq.shared.chown")


def chown_agent_sessions_to_host_user(trial_dir: Path | str | None) -> None:
    """Recursively chown ``<trial_dir>/agent/sessions/**`` to the host user.

    Public name (no leading underscore): the helper is now in
    :mod:`skillq.shared` and may be imported by anything in the
    runtime stack. The legacy private alias
    ``_chown_agent_sessions_to_host_user`` is kept as a shim for
    existing call sites until Step 6.
    """
    if not trial_dir:
        return
    try:
        agent_sessions = Path(trial_dir) / "agent" / "sessions"
    except (TypeError, ValueError):
        return
    if not agent_sessions.exists():
        return
    host_uid = os.getuid()
    host_gid = os.getgid()
    n_ok, n_skip = 0, 0
    for p in agent_sessions.rglob("*"):
        try:
            os.chown(p, host_uid, host_gid, follow_symlinks=False)
            n_ok += 1
        except (PermissionError, FileNotFoundError):
            n_skip += 1
        except OSError as exc:
            logger.debug("chown skipped for %s: %s", p, exc)
            n_skip += 1
    logger.info(
        "post-trial chown: %s ok=%d skip=%d",
        agent_sessions, n_ok, n_skip,
    )


# Back-compat alias for call sites that still reference the private
# name. Removed in Step 6 when the old alias under skillq.runtime was deleted.
_chown_agent_sessions_to_host_user = chown_agent_sessions_to_host_user


__all__ = ["chown_agent_sessions_to_host_user"]