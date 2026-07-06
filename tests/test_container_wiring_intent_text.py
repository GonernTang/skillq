"""Fix A+ + Issue 65 + Bug #51/#52: container wiring loads instruction.md + isolates env.

Three related contracts covered here:

1. **Fix A+**: the per-trial user_task used to be the task slug only
   (e.g. ``"chess-best-move"``, ~15 chars). For L1 sim this is a
   very thin query. The wiring now reads
   ``<input_root>/<benchmark>/<task>/instruction.md`` and uses its
   full text (200-2700 chars) as the per-trial ``user_task``.

2. **Issue 65**: harbor's ``JobConfig.agents[0]`` is a shared
   reference across all trials in a job. The wiring shallow-copies
   ``cfg.agent.env`` per trial so mutation in trial N does not leak
   into trial N+1.

3. **Bug #51/#52 (2026-07-01)**: per-trial ``user_task`` and
   ``calls_log_path`` are now transported via the bind-mounted
   per-trial ``<trial_dir>/skillq_state/settings.json`` (the
   ``"skillq"`` block), NOT via ``cfg.agent.env`` (env-var
   mutation here raced against Harbor's per-trial snapshot under
   ``n_concurrent_trials >= 2``).

These tests run the wiring against a synthetic ``TrialHookEvent``
with a fake cfg and assert on the resulting settings.json file
contents. No real container is launched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.config import MethodConfig  # noqa: E402


def _make_method(input_root: Path, library_root: Path) -> MethodConfig:
    return MethodConfig(
        library_root=library_root,
        benchmark_input_path=input_root,
        retrieval_mode="hook",
    )


def _make_event(*, task_name: str, cfg, trial_dir: Path,
                trial_id: str | None = None):
    """Fake harbor TrialHookEvent (only the fields wiring uses)."""
    return SimpleNamespace(
        task_name=task_name,
        config=cfg,
        trial_dir=trial_dir,
        trial_id=trial_id or trial_dir.name,
    )


def _make_cfg(env: dict | None = None, trials_dir: Path | None = None,
              trial_name: str = "trial-x"):
    """Fake harbor JobConfig. ``agent.env`` is the dict we mutate.

    Note: ``_resolve_trial_dir(event)`` derives the trial_dir from
    ``cfg.trials_dir / cfg.trial_name``. Tests that want the
    settings.json to land at a specific path MUST set
    ``trials_dir`` to the parent and ``trial_name`` to the
    desired basename.
    """
    cfg = SimpleNamespace()
    cfg.agent = SimpleNamespace(env=env if env is not None else {})
    cfg.environment = SimpleNamespace(mounts_json=None)
    cfg.trials_dir = str(trials_dir or Path("/tmp"))
    cfg.trial_name = trial_name
    return cfg


def _build_handle(method, tmp_path: Path):
    """Build a minimal ContainerWiringHandle. We patch the
    pieces of handle.services the wiring reads (lib size) and
    the ranker port the pull-mode branch uses.
    """
    from skillq.runtime import container_wiring as cw
    from skillq.shared.types import Qlib

    services = SimpleNamespace(lib=Qlib())
    handle = SimpleNamespace(
        method=method,
        services=services,
        ranking={"port": 8765},
    )
    return handle, cw


def _seed_instruction(parent: Path, benchmark_subdir: str, task_name: str, body: str) -> None:
    """Write a synthetic instruction.md under the expected layout."""
    p = parent / benchmark_subdir / task_name / "instruction.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _read_settings_json(trial_dir: Path) -> dict:
    """Read the per-trial settings.json the wiring wrote."""
    p = trial_dir / "skillq_state" / "settings.json"
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Bug #51/#52 (2026-07-01): settings.json carries per-trial user_task
# ---------------------------------------------------------------------------
def test_user_task_loads_instruction_md_into_settings_json(tmp_path):
    """When terminal-bench/<task>/instruction.md exists, the
    settings.json's skillq.user_task field carries the full body
    (truncated to 2000 chars), not the slug."""
    inp = tmp_path / "input"
    _seed_instruction(
        inp, "terminal-bench", "chess-best-move",
        "The file chess_board.png has an image of a chess board. "
        "It is currently white to move. Write the best move for white "
        "to play to /app/move.txt in the form [src][dst].",
    )
    method = _make_method(inp, tmp_path / "lib")
    handle, cw = _build_handle(method, tmp_path)
    cfg = _make_cfg(trials_dir=tmp_path)

    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name="chess-best-move", cfg=cfg,
                          trial_dir=tmp_path / "trial-x"),
    )
    settings = _read_settings_json(tmp_path / "trial-x")
    intent = settings["skillq"]["user_task"]
    assert "chess_board.png" in intent
    assert "best move" in intent
    assert len(intent) > 50


def test_user_task_falls_back_to_slug_in_settings_json(tmp_path):
    """If instruction.md is absent in every benchmark subdir, fall
    back to the task name slug (preserves legacy behavior)."""
    inp = tmp_path / "input"
    method = _make_method(inp, tmp_path / "lib")
    handle, cw = _build_handle(method, tmp_path)
    cfg = _make_cfg(trials_dir=tmp_path)

    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name="chess-best-move", cfg=cfg,
                          trial_dir=tmp_path / "trial-x"),
    )
    settings = _read_settings_json(tmp_path / "trial-x")
    assert settings["skillq"]["user_task"] == "chess-best-move"


def test_user_task_truncates_oversized_instruction_in_settings_json(tmp_path):
    """Hard cap at 2000 chars: prevents pathological payloads from
    blowing the embedder input window."""
    inp = tmp_path / "input"
    _seed_instruction(inp, "terminal-bench", "build-cython-ext", "x" * 5000)
    method = _make_method(inp, tmp_path / "lib")
    handle, cw = _build_handle(method, tmp_path)
    cfg = _make_cfg(trials_dir=tmp_path)

    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name="build-cython-ext", cfg=cfg,
                          trial_dir=tmp_path / "trial-x"),
    )
    settings = _read_settings_json(tmp_path / "trial-x")
    assert len(settings["skillq"]["user_task"]) == 2000


def test_user_task_searches_multiple_benchmark_subdirs(tmp_path):
    """The loader tries terminal-bench / swebenchpro / tb-pro /
    swebench in order. instruction.md under swebenchpro must be
    picked up just as well as terminal-bench."""
    inp = tmp_path / "input"
    _seed_instruction(
        inp, "swebenchpro", "django__django-12345",
        "Fix the migration rollback crash when dropping a foreign key.",
    )
    method = _make_method(inp, tmp_path / "lib")
    handle, cw = _build_handle(method, tmp_path)
    cfg = _make_cfg(trials_dir=tmp_path)

    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name="django__django-12345", cfg=cfg,
                          trial_dir=tmp_path / "trial-x"),
    )
    settings = _read_settings_json(tmp_path / "trial-x")
    assert "migration rollback crash" in settings["skillq"]["user_task"]


def test_user_task_uses_trial_dir_name_when_task_name_missing(tmp_path):
    """event.task_name is None → use trial_dir.name as the task
    identifier. Falls back to slug if instruction.md missing."""
    inp = tmp_path / "input"
    method = _make_method(inp, tmp_path / "lib")
    handle, cw = _build_handle(method, tmp_path)
    cfg = _make_cfg(trials_dir=tmp_path, trial_name="extract-elf-trial")

    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name=None, cfg=cfg, trial_dir=tmp_path),
    )
    settings = _read_settings_json(tmp_path / "extract-elf-trial")
    assert settings["skillq"]["user_task"] == "extract-elf-trial"


# ---------------------------------------------------------------------------
# Bug #51/#52: per-trial cross-trial isolation (settings.json is per-trial)
# ---------------------------------------------------------------------------
def test_settings_json_is_per_trial_isolated(tmp_path):
    """Bug #51/#52 fix regression: with the same cfg object wired
    twice, each trial writes its OWN settings.json (not a shared
    one). Trial 2's settings.json must NOT see trial 1's user_task.
    """
    inp = tmp_path / "input"
    _seed_instruction(inp, "terminal-bench", "chess-best-move",
                      "chess board instruction body")
    _seed_instruction(inp, "terminal-bench", "extract-elf",
                      "extract elf instruction body")
    method = _make_method(inp, tmp_path / "lib")
    handle, cw = _build_handle(method, tmp_path)

    cfg = _make_cfg(trials_dir=tmp_path)

    # Trial 1: chess-best-move (cfg.trial_name must match the
    # trial_dir basename so _resolve_trial_dir lands at the expected
    # path — this is the harbor pattern.)
    cfg.trial_name = "trial-chess"
    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name="chess-best-move", cfg=cfg,
                          trial_dir=tmp_path / "trial-chess"),
    )
    cfg.trial_name = "trial-extract"  # harbor updates trial_name per-trial
    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name="extract-elf", cfg=cfg,
                          trial_dir=tmp_path / "trial-extract"),
    )
    chess_settings = _read_settings_json(tmp_path / "trial-chess")
    extract_settings = _read_settings_json(tmp_path / "trial-extract")
    assert "chess board" in chess_settings["skillq"]["user_task"]
    assert "extract elf" in extract_settings["skillq"]["user_task"]
    # Critical: trial 2's settings.json must NOT contain trial 1's chess body.
    assert "chess board" not in extract_settings["skillq"]["user_task"]
    # And trial 1's settings.json must NOT be polluted by trial 2 either.
    assert "extract elf" not in chess_settings["skillq"]["user_task"]


# ---------------------------------------------------------------------------
# Bug #51/#52: env var must NOT be set by wiring
# ---------------------------------------------------------------------------
def test_wiring_does_not_mutate_skillq_user_task_env_var(tmp_path):
    """Bug #51/#52 regression: ``_wire_hook_trial`` must NOT set
    ``cfg.agent.env["SKILLQ_USER_TASK"]``. That env var raced
    against Harbor's per-trial snapshot under
    ``n_concurrent_trials >= 2``. The value now lives in
    settings.json's ``skillq.user_task`` field."""
    inp = tmp_path / "input"
    _seed_instruction(inp, "terminal-bench", "chess-best-move",
                      "chess board instruction body")
    method = _make_method(inp, tmp_path / "lib")
    handle, cw = _build_handle(method, tmp_path)
    cfg = _make_cfg(trials_dir=tmp_path, env={"SOME_OTHER_KEY": "untouched"})

    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name="chess-best-move", cfg=cfg,
                          trial_dir=tmp_path / "trial-x"),
    )

    assert "SKILLQ_USER_TASK" not in cfg.agent.env, (
        "Bug #51 regression: wiring must NOT set SKILLQ_USER_TASK "
        "(env-var mutation raced under n_concurrent_trials >= 2)"
    )
    assert cfg.agent.env["SOME_OTHER_KEY"] == "untouched"


def test_wiring_does_not_mutate_skillq_calls_log_path_env_var(tmp_path):
    """Bug #51/#52 regression: ``_wire_hook_trial`` must NOT set
    ``cfg.agent.env["SKILLQ_CALLS_LOG_PATH"]``. The per-trial path
    lives in settings.json's ``skillq.calls_log_path`` field."""
    inp = tmp_path / "input"
    method = _make_method(inp, tmp_path / "lib")
    handle, cw = _build_handle(method, tmp_path)
    cfg = _make_cfg(trials_dir=tmp_path, env={})

    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name="chess-best-move", cfg=cfg,
                          trial_dir=tmp_path / "trial-x"),
    )

    assert "SKILLQ_CALLS_LOG_PATH" not in cfg.agent.env, (
        "Bug #52 regression: wiring must NOT set SKILLQ_CALLS_LOG_PATH "
        "(shared env var raced under n_concurrent_trials >= 2)"
    )


# ---------------------------------------------------------------------------
# Bug #51/#52: settings.json has both skillq fields populated
# ---------------------------------------------------------------------------
def test_settings_json_calls_log_path_is_per_trial(tmp_path):
    """The settings.json's ``skillq.calls_log_path`` must be unique
    per trial (the per-trial file the hook writes)."""
    inp = tmp_path / "input"
    method = _make_method(inp, tmp_path / "lib")
    handle, cw = _build_handle(method, tmp_path)
    cfg = _make_cfg(trials_dir=tmp_path, trial_name="trial-foo")

    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name="chess-best-move", cfg=cfg,
                          trial_dir=tmp_path / "trial-foo"),
    )

    settings = _read_settings_json(tmp_path / "trial-foo")
    clp = settings["skillq"]["calls_log_path"]
    assert clp, "calls_log_path must be populated"
    assert "trial-foo" in clp, (
        f"calls_log_path should include trial_name, got {clp}"
    )
    assert clp.endswith(".jsonl")