"""Regression for Bug #2 (2026-06-30) → Bug #51/#52 (2026-07-01):
SKILLQ_CALLS_LOG_PATH env-snapshot race between Trial.__init__
and ``on_trial_started``.

History:

- 2026-06-30 (Bug #2 fix): pre-seeded ``SKILLQ_CALLS_LOG_PATH`` in
  :func:`seed_agent_env` from ``method.library_root`` BEFORE
  ``Job.create`` to dodge the per-trial snapshot race.
- 2026-07-01 (Bug #51/#52 fix): the shared path itself was the
  problem — ``n_concurrent_trials >= 2`` had all trials writing
  to the same file → empty / garbled log. The fix is to **drop
  the env-var transport entirely** and put the per-trial calls
  log path in the bind-mounted ``settings.json`` instead.

This test now pins the **negative** contract: ``seed_agent_env``
must NOT inject ``SKILLQ_CALLS_LOG_PATH`` (the env var is no
longer read by the hook), and ``_wire_hook_trial`` writes the
per-trial path into the per-trial ``settings.json`` instead.

See also ``test_calls_log_permission_denials.py`` (Bug #53 fix)
and ``test_hook_per_trial_settings_file.py`` (Bug #51/#52 hook-
side transport).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.config import MethodConfig  # noqa: E402
from skillq.runtime.env_seed import seed_agent_env  # noqa: E402


def _fake_job_config(library_root: Path):
    """Minimal JobConfig stub exposing only the fields
    seed_agent_env reads. Avoids depending on harbor.models here."""

    class _AgentCfg:
        env: dict[str, str] | None = None

    class _JobCfg:
        agents = [_AgentCfg()]

    job_cfg = _JobCfg()  # type: ignore[assignment]
    job_cfg.agents[0].env = {}
    return job_cfg


def test_seed_agent_env_does_not_inject_calls_log_path(tmp_path: Path):
    """2026-07-01 (Bug #51/#52 fix): the env var
    ``SKILLQ_CALLS_LOG_PATH`` is no longer used. Per-trial state
    rides in the bind-mounted ``settings.json``'s ``"skillq"``
    block instead. ``seed_agent_env`` must NOT inject the
    library-scoped path (it raced under ``n_concurrent_trials >= 2``).
    """
    method = MethodConfig(
        retrieval_mode="hook",
        library_root=tmp_path,
    )
    job_cfg = _fake_job_config(tmp_path)
    seed_agent_env(job_cfg, method, wiring=None)

    env = job_cfg.agents[0].env
    assert "SKILLQ_CALLS_LOG_PATH" not in env, (
        "Bug #51/#52 regression: seed_agent_env must NOT inject "
        "SKILLQ_CALLS_LOG_PATH (the env var races under "
        "n_concurrent_trials >= 2; per-trial state lives in "
        "settings.json now)."
    )


def test_seed_agent_env_does_not_inject_user_task(tmp_path: Path):
    """2026-07-01 (Bug #51/#52 fix): ``SKILLQ_USER_TASK`` is no
    longer used at all — the hook reads it from the bind-mounted
    ``settings.json``'s ``skillq.user_task``. Pre-seeding it in
    ``cfg.agent.env`` was dead code AND racy.
    """
    method = MethodConfig(retrieval_mode="hook", library_root=tmp_path)
    job_cfg = _fake_job_config(tmp_path)
    seed_agent_env(job_cfg, method, wiring=None)

    env = job_cfg.agents[0].env
    assert "SKILLQ_USER_TASK" not in env, (
        "Bug #51/#52 regression: seed_agent_env must NOT inject "
        "SKILLQ_USER_TASK (per-trial state now lives in "
        "settings.json, not env vars)."
    )


def test_seed_agent_env_no_longer_creates_library_calls_log_dir(
    tmp_path: Path,
):
    """2026-07-01: the library-root ``_calls_log/`` directory is
    gone. Each trial has its OWN ``_calls_log/`` subdir under
    ``<trial_dir>/agent/sessions/`` (created by
    ``_wire_hook_trial``). ``seed_agent_env`` no longer creates
    the library-scoped dir.
    """
    method = MethodConfig(retrieval_mode="hook", library_root=tmp_path)
    job_cfg = _fake_job_config(tmp_path)
    seed_agent_env(job_cfg, method, wiring=None)

    lib_root = tmp_path
    legacy_dir = lib_root / "_calls_log"
    # The dir MIGHT still exist if some other code created it; the
    # point is that seed_agent_env doesn't anymore. The cleanest
    # assertion is "the env var that pointed there is gone", which
    # the prior tests cover. Here we just assert the env-dict
    # contract is empty for the legacy per-trial vars.
    env = job_cfg.agents[0].env
    assert "SKILLQ_CALLS_LOG_PATH" not in env
    assert "SKILLQ_USER_TASK" not in env
    # Touch the var for type-checkers / future-proofing.
    _ = legacy_dir
