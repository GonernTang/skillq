"""Fix A+ + Issue 65: container wiring loads instruction.md + isolates env.

Two related bugs covered here:

1. **Fix A+**: ``cfg.agent.env["SKILLQ_USER_TASK"]`` used to be the
   task slug only (e.g. ``"chess-best-move"``, ~15 chars). For L1
   sim this is a very thin query. The wiring now reads
   ``<input_root>/<benchmark>/<task>/instruction.md`` and uses its
   full text (200-2700 chars) as the SKILLQ_USER_TASK value.

2. **Issue 65**: harbor's ``JobConfig.agents[0]`` is a shared
   reference across all trials in a job. Mutating ``cfg.agent.env``
   in trial N would leak into trial N+1 (residual pollution). The
   wiring now shallow-copies the env dict per trial.

These tests run the wiring against a synthetic ``TrialHookEvent``
with a fake cfg and assert on the resulting env state. No real
container is launched.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.config import MethodConfig  # noqa: E402


def _make_method(input_root: Path, library_root: Path) -> MethodConfig:
    return MethodConfig(
        library_root=library_root,
        benchmark_input_path=input_root,
        # Force hook mode so the wiring takes the _wire_hook_trial
        # branch (the agentic branch needs services.mgr + lib skills
        # which we don't set up in this test).
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
    """Fake harbor JobConfig. ``agent.env`` is the dict we mutate."""
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

    # Minimal services object — lib size drives retrieval_mode.
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


# ---------------------------------------------------------------------------
# Fix A+: SKILLQ_USER_TASK loads instruction.md
# ---------------------------------------------------------------------------
def test_user_task_loads_instruction_md_from_terminal_bench(tmp_path):
    """When terminal-bench/<task>/instruction.md exists, the env
    var carries the full body (truncated to 2000 chars), not the slug.
    """
    inp = tmp_path / "input"
    _seed_instruction(
        inp, "terminal-bench", "chess-best-move",
        "The file chess_board.png has an image of a chess board. "
        "It is currently white to move. Write the best move for white "
        "to play to /app/move.txt in the form [src][dst].",
    )
    method = _make_method(inp, tmp_path / "lib")
    handle, cw = _build_handle(method, tmp_path)
    cfg = _make_cfg()

    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name="chess-best-move", cfg=cfg,
                          trial_dir=tmp_path / "trial-x"),
    )
    intent = cfg.agent.env["SKILLQ_USER_TASK"]
    assert "chess_board.png" in intent
    assert "best move" in intent
    # The slug alone would be 15 chars; loaded body is much longer.
    assert len(intent) > 50


def test_user_task_falls_back_to_slug_when_instruction_md_missing(tmp_path):
    """If instruction.md is absent in every benchmark subdir, fall
    back to the task name slug (preserves legacy behavior).
    """
    inp = tmp_path / "input"
    # No instruction.md seeded anywhere
    method = _make_method(inp, tmp_path / "lib")
    handle, cw = _build_handle(method, tmp_path)
    cfg = _make_cfg()

    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name="chess-best-move", cfg=cfg,
                          trial_dir=tmp_path / "trial-x"),
    )
    assert cfg.agent.env["SKILLQ_USER_TASK"] == "chess-best-move"


def test_user_task_truncates_oversized_instruction_to_2000_chars(tmp_path):
    """Hard cap at 2000 chars: prevents pathological payloads from
    blowing the embedder input window.
    """
    inp = tmp_path / "input"
    _seed_instruction(inp, "terminal-bench", "build-cython-ext", "x" * 5000)
    method = _make_method(inp, tmp_path / "lib")
    handle, cw = _build_handle(method, tmp_path)
    cfg = _make_cfg()

    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name="build-cython-ext", cfg=cfg,
                          trial_dir=tmp_path / "trial-x"),
    )
    assert len(cfg.agent.env["SKILLQ_USER_TASK"]) == 2000


def test_user_task_searches_multiple_benchmark_subdirs(tmp_path):
    """The loader tries terminal-bench / swebenchpro / tb-pro /
    swebench in order. instruction.md under swebenchpro must be
    picked up just as well as terminal-bench.
    """
    inp = tmp_path / "input"
    _seed_instruction(
        inp, "swebenchpro", "django__django-12345",
        "Fix the migration rollback crash when dropping a foreign key.",
    )
    method = _make_method(inp, tmp_path / "lib")
    handle, cw = _build_handle(method, tmp_path)
    cfg = _make_cfg()

    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name="django__django-12345", cfg=cfg,
                          trial_dir=tmp_path / "trial-x"),
    )
    assert "migration rollback crash" in cfg.agent.env["SKILLQ_USER_TASK"]


def test_user_task_uses_trial_dir_name_when_task_name_missing(tmp_path):
    """event.task_name is None → use trial_dir.name as the task
    identifier. Falls back to slug if instruction.md missing.
    """
    inp = tmp_path / "input"
    method = _make_method(inp, tmp_path / "lib")
    handle, cw = _build_handle(method, tmp_path)
    # trial_dir is resolved from cfg.trials_dir/cfg.trial_name in the
    # wiring, not from event.trial_dir, so set cfg.trial_name here.
    cfg = _make_cfg(trial_name="extract-elf-trial")

    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name=None, cfg=cfg, trial_dir=tmp_path),
    )
    assert cfg.agent.env["SKILLQ_USER_TASK"] == "extract-elf-trial"


# ---------------------------------------------------------------------------
# Issue 65: cfg.agent.env is shallow-copied per trial (no cross-trial leak)
# ---------------------------------------------------------------------------
def test_agent_env_is_shallow_copied_per_trial(tmp_path):
    """Issue 65 regression pin: harbor shares ``cfg.agent`` across
    trials. Trial N's mutation must NOT leak into trial N+1. We
    simulate this by passing the same cfg object to two wiring
    calls and asserting the second call's mutations don't appear
    in any "shadow" record we kept of the first.
    """
    inp = tmp_path / "input"
    _seed_instruction(inp, "terminal-bench", "chess-best-move",
                      "chess board instruction body")
    _seed_instruction(inp, "terminal-bench", "extract-elf",
                      "extract elf instruction body")
    method = _make_method(inp, tmp_path / "lib")
    handle, cw = _build_handle(method, tmp_path)

    # Real harbor pattern: same cfg object across trials.
    cfg = _make_cfg()

    # Trial 1: chess-best-move
    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name="chess-best-move", cfg=cfg,
                          trial_dir=tmp_path / "trial-chess"),
    )
    trial1_env = dict(cfg.agent.env)  # snapshot what the container saw
    assert "chess board" in trial1_env["SKILLQ_USER_TASK"]

    # Trial 2: extract-elf (same cfg object — the bug condition)
    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name="extract-elf", cfg=cfg,
                          trial_dir=tmp_path / "trial-extract"),
    )
    trial2_env = dict(cfg.agent.env)
    assert "extract elf" in trial2_env["SKILLQ_USER_TASK"]
    # Critical: trial 2's intent must NOT contain trial 1's chess body.
    assert "chess board" not in trial2_env["SKILLQ_USER_TASK"]
    # And trial 1's snapshot should NOT have been mutated by trial 2.
    assert "extract elf" not in trial1_env["SKILLQ_USER_TASK"]


def test_wiring_replaces_env_dict_reference(tmp_path):
    """Issue 65 invariant: after wiring, ``cfg.agent.env`` is a
    *different* dict object from what was passed in. This is the
    mechanism that prevents cross-trial leak — if the wiring only
    mutates the shared dict, harbor's next trial sees the same
    object and inherits our mutations.
    """
    method = _make_method(tmp_path / "input", tmp_path / "lib")
    handle, cw = _build_handle(method, tmp_path)
    original_env = {"EXISTING_KEY": "preset"}
    cfg = _make_cfg(env=original_env)
    original_id = id(cfg.agent.env)

    cw.wire_one_trial(
        handle=handle,
        event=_make_event(task_name="chess-best-move", cfg=cfg,
                          trial_dir=tmp_path / "trial-x"),
    )

    assert id(cfg.agent.env) != original_id
    # Pre-existing keys must still be present (shallow copy preserves them).
    assert cfg.agent.env["EXISTING_KEY"] == "preset"