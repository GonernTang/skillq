"""Tests for the QlibState serialiser and the paper-mode bridge hook.

These tests do not require a real Harbor Job; the bridge is exercised
against a mock :class:`harbor.job.Job` whose ``on_trial_ended`` is a
spy that records the callback it received. We then invoke the callback
with a fake :class:`TrialHookEvent` to verify the four-layer method
runs end-to-end.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# Make the project importable when running ``pytest`` from the
# project root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from paper.method.library import LibManager  # noqa: E402
from paper.method.state import QlibState  # noqa: E402
from paper.method.types import Qlib, Skill  # noqa: E402
from paper.paper_mode.config import MethodConfig  # noqa: E402


# ---------------------------------------------------------------------------
# QlibState round-trip
# ---------------------------------------------------------------------------
def test_qlib_state_round_trip(tmp_path: Path):
    lib = Qlib(b_max=10)
    lib.add(Skill(skill_id="a", body="body a", n_retrievals=2, n_uses=1, n_success=1))
    lib.add(Skill(skill_id="b", body="body b", n_retrievals=0))
    mgr = LibManager(
        b_max=10, theta_admit=0.3, theta_evict=0.1, n_explore=5, n_stale=80
    )
    mgr.update_q(intent_hash=1, skill_id="a", delta=0.5)
    mgr.update_q(intent_hash=2, skill_id="b", delta=-0.2)
    mgr.mark_retrieved("a", current_step=7)
    state = QlibState(tmp_path / "method_state.json")
    state.step = 42
    state.save(lib, mgr, lib_root=tmp_path)

    # Reload into a fresh in-memory state.
    lib2 = Qlib()
    mgr2 = LibManager(
        b_max=10, theta_admit=0.3, theta_evict=0.1, n_explore=5, n_stale=80
    )
    state2 = QlibState(tmp_path / "method_state.json")
    assert state2.load_into(lib2, mgr2) is True
    assert state2.step == 42
    assert {s.skill_id for s in lib2.skills.values()} == {"a", "b"}
    assert lib2.b_max == 10
    assert mgr2.q_for(1, "a") == 0.5
    assert mgr2.q_for(2, "b") == -0.2
    assert mgr2.last_retrieval_step["a"] == 7


def test_qlib_state_handles_missing_file(tmp_path: Path):
    lib = Qlib(b_max=3)
    mgr = LibManager(
        b_max=3, theta_admit=0.3, theta_evict=0.1, n_explore=5, n_stale=80
    )
    state = QlibState(tmp_path / "missing.json")
    assert state.load_into(lib, mgr) is False
    # state stays at its default
    assert state.step == 0


# ---------------------------------------------------------------------------
# Bridge: hook registration + invocation (mock Job, no real Harbor run)
# ---------------------------------------------------------------------------
class _MockJob:
    """Minimal stand-in for ``harbor.job.Job``; records the registered hook."""

    def __init__(self) -> None:
        self.on_ended: Any = None
        self.config = MagicMock()
        # Default: no include/exclude list.
        self.config.retry = MagicMock()
        self.config.retry.exclude_exceptions = None
        self.config.retry.include_exceptions = None

    def on_trial_ended(self, callback: Any) -> None:
        # The bridge calls ``job.on_trial_ended(callback)`` (note: method,
        # not attribute). We mimic that.
        self.on_ended = callback

    def __len__(self) -> int:
        # The bridge uses ``len(job)`` to compute expected_terminal_trials
        # for the buffer force-flush on the last trial.
        return 1_000_000  # large sentinel so the force-flush never fires in tests


def test_attach_paper_registers_wires_on_trial_ended(tmp_path: Path, monkeypatch):
    """The bridge should register exactly one ``on_trial_ended`` callback."""
    # Patch the LiteLLM backends BEFORE calling attach_paper_registers.
    # ``attach_paper_registers`` instantiates both the embedder and the
    # verifier backend at hook-registration time, so the patches must
    # land in the bridge module's namespace first.
    _patch_litellm_backends(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        n_explore=2,
    )
    # Pre-seed the library with a single skill so the ranker has something
    # to retrieve.
    lib = Qlib(b_max=4)
    lib.add(Skill(skill_id="seed", body="seed body"))
    state = QlibState(method.resolved_state_path())
    state.save(lib, _fresh_manager(method), lib_root=method.library_root)

    job = _MockJob()
    from paper.paper_mode import bridge as bridge_mod
    bridge_mod.attach_paper_registers(job, method)
    assert job.on_ended is not None

    # Build a fake TrialHookEvent with a passing trial.
    fake_result = _build_fake_trial_result(reward=1.0, trial_uri=str(tmp_path / "trial-x"))
    event = _build_fake_hook_event(trial_id="trial-x", result=fake_result)

    # Run the hook to completion; the bridge must not raise.
    asyncio.run(job.on_ended(event))

    # State should have been written.
    state_path = method.resolved_state_path()
    assert state_path.exists()
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["step"] == 1
    # Library should still contain the seeded skill.
    assert "seed" in data["library"]["skills"]


def test_attach_paper_registers_skips_failed_trials(tmp_path: Path, monkeypatch):
    """Failed / retried trials must not be processed by the four-layer method."""
    _patch_litellm_backends(monkeypatch)

    method = MethodConfig(library_root=tmp_path / "lib", b_max=4, n_explore=2)
    state = QlibState(method.resolved_state_path())
    state.save(Qlib(b_max=4), _fresh_manager(method), lib_root=method.library_root)

    job = _MockJob()
    from paper.paper_mode import bridge as bridge_mod
    bridge_mod.attach_paper_registers(job, method)

    # Failed trial — exception_info is set.
    result = _build_fake_trial_result(reward=0.0, trial_uri=str(tmp_path / "t"))
    result.exception_info = MagicMock()
    result.exception_info.exception_type = "SomeError"
    event = _build_fake_hook_event(trial_id="t", result=result)
    asyncio.run(job.on_ended(event))

    # State.step must NOT have advanced.
    data = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    assert data["step"] == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _patch_litellm_backends(monkeypatch) -> None:
    """Replace LiteLLM embedder/verifier/attribution with stub shims
    that accept the ``model=`` kwarg the bridge passes.
    """
    from paper.paper_mode import bridge as bridge_mod
    from paper.method.attribution import StubAttributionBackend
    from paper.method.retrieval import StubEmbedder
    from paper.method.verifier import StubVerifierBackend

    class _StubVerifierShim(StubVerifierBackend):
        def __init__(self, *args, **kwargs) -> None:
            kwargs.pop("model", None)
            super().__init__(*args, **kwargs)

    class _StubEmbedderShim(StubEmbedder):
        def __init__(self, *args, **kwargs) -> None:
            kwargs.pop("model", None)
            kwargs.pop("dim", None)
            super().__init__()

    class _StubAttributionShim(StubAttributionBackend):
        def __init__(self, *args, **kwargs) -> None:
            kwargs.pop("model", None)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(bridge_mod, "LiteLLMEmbedder", _StubEmbedderShim)
    monkeypatch.setattr(bridge_mod, "LiteLLMVerifierBackend", _StubVerifierShim)
    monkeypatch.setattr(bridge_mod, "LiteLLMAttributionBackend", _StubAttributionShim)


def _fresh_manager(method: MethodConfig) -> LibManager:
    return LibManager(
        b_max=method.b_max,
        theta_admit=method.theta_admit,
        theta_evict=method.theta_evict,
        n_explore=method.n_explore,
        n_stale=method.n_stale,
    )


def _build_fake_trial_result(reward: float, trial_uri: str) -> MagicMock:
    result = MagicMock()
    result.trial_uri = trial_uri
    result.trial_name = Path(trial_uri).name
    result.task_name = "sample-task"
    result.exception_info = None
    result.verifier_result = MagicMock()
    result.verifier_result.rewards = {"reward": reward}
    return result


def _build_fake_hook_event(trial_id: str, result: Any) -> MagicMock:
    """Build a MagicMock that quacks like a ``TrialHookEvent``."""
    event = MagicMock()
    event.event = "end"
    event.trial_id = trial_id
    event.task_name = "sample-task"
    event.timestamp = datetime.now(timezone.utc)
    event.result = result
    return event
