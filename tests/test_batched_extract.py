"""Tests for the batched auto-extract path.

These exercise the N-trial flush (N >= 2) which is the new design
migrated from SkillsVote's evolve_every_n_trials. Unlike the
test_bridge_extract.py suite (which uses ``extract_every_n_trials=1``
so the buffer flushes on the first qualifying trial), here we run
multiple trials and assert that:

  - The buffer accumulates records across trials
  - The extractor is called *exactly once* with N records aggregated
  - Force-flush on the final trial drains a partial buffer
  - With N > #trials, no flush happens (records stay buffered)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.method.attribution import Attribution, TrialAttribution  # noqa: E402
from skillq.method.library import LibManager  # noqa: E402
from skillq.method.state import QlibState  # noqa: E402
from skillq.method.types import Qlib, Skill  # noqa: E402
from skillq.skillq_runtime.config import MethodConfig  # noqa: E402


class _MockJob:
    """Mock Job that supports ``__len__`` (drives force-flush trigger)."""

    def __init__(self, n_trials: int) -> None:
        self.n_trials = n_trials
        self.on_ended: Any = None
        self.config = MagicMock()
        self.config.retry = MagicMock()
        self.config.retry.exclude_exceptions = None
        self.config.retry.include_exceptions = None

    def on_trial_ended(self, callback: Any) -> None:
        self.on_ended = callback

    def __len__(self) -> int:
        return self.n_trials


def _patch_litellm_backends(monkeypatch) -> None:
    from skillq.skillq_runtime import bridge as bridge_mod
    from skillq.method.attribution import StubAttributionBackend
    from skillq.method.retrieval import StubEmbedder

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
    monkeypatch.setattr(bridge_mod, "LiteLLMAttributionBackend", _StubAttributionShim)


def _patch_extractor_recording(monkeypatch) -> list[dict[str, Any]]:
    """Replace ``extract_batch`` with a recording stub. Returns a
    list that the stub appends to on each call (so tests can assert
    call count + kwargs).
    """
    from skillq.skillq_runtime import bridge as bridge_mod

    calls: list[dict[str, Any]] = []

    async def fake_extract_batch(self, **kwargs) -> Skill:
        calls.append(kwargs)
        return Skill(
            skill_id=f"batched-{len(calls)}",
            body="x" * 200,
        )

    monkeypatch.setattr(bridge_mod.SkillExtractor, "extract_batch", fake_extract_batch)
    return calls


def _fake_trial_result(reward: float, trial_uri: str) -> MagicMock:
    r = MagicMock()
    r.trial_uri = trial_uri
    r.trial_name = Path(trial_uri).name
    r.task_name = "sample-task"
    r.exception_info = None
    r.verifier_result = MagicMock()
    r.verifier_result.rewards = {"reward": reward}
    return r


def _fake_hook_event(trial_id: str, result: Any) -> MagicMock:
    event = MagicMock()
    event.event = "end"
    event.trial_id = trial_id
    event.task_name = "sample-task"
    event.result = result
    return event


def _seed_lib(method: MethodConfig) -> None:
    lib = Qlib(b_max=method.b_max)
    lib.add(Skill(skill_id="seed", body="seed body"))
    state = QlibState(method.resolved_state_path())
    state.save(
        lib,
        LibManager(b_max=method.b_max),
        lib_root=method.library_root,
        seed_initial_q=method.seed_initial_q,
    )


def _patch_attribution_no_skill_seen(monkeypatch) -> None:
    """Attribution that triggers the extract path on every trial."""
    from skillq.skillq_runtime import bridge as bridge_mod

    def returning(self, **kwargs):
        return TrialAttribution(
            overall_attribution=Attribution.SUCCESS_NO_SKILL_SEEN,
            overall_rationale="test",
            knowledge_to_extract="reusable knowledge",
        )

    monkeypatch.setattr(bridge_mod.AttributionAnalyzer, "analyze", returning)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_buffer_accumulates_until_threshold(tmp_path: Path, monkeypatch):
    """3 trials with N=4: 0 extract calls, 0 new skills added.

    The job is declared longer (n_trials=100) than the 3 trials we
    run, so the force-flush trigger is dormant and the buffer just
    accumulates.
    """
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_no_skill_seen(monkeypatch)
    calls = _patch_extractor_recording(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
                enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=4,       # > #trials
        new_skill_initial_q=0.0,
        q_alpha=0.0,    # freeze Q so the seed doesn't accumulate
    )
    _seed_lib(method)
    job = _MockJob(n_trials=100)        # long job → no force-flush
    from skillq.skillq_runtime import bridge as bridge_mod
    bridge_mod.attach_paper_registers(job, method)

    for i in range(3):
        result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / f"trial-{i}"))
        event = _fake_hook_event(f"trial-{i}", result=result)
        asyncio.run(job.on_ended(event))

    assert len(calls) == 0, f"expected 0 extract_batch calls, got {len(calls)}"
    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    assert "seed" in state["library"]["skills"]
    # No batched skills were added.
    batched = [k for k in state["library"]["skills"] if k.startswith("batched-")]
    assert batched == []


def test_threshold_hit_aggregates_n_records(tmp_path: Path, monkeypatch):
    """4 trials with N=4: 1 extract_batch call with 4 records, 1 new skill."""
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_no_skill_seen(monkeypatch)
    calls = _patch_extractor_recording(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
                enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=4,
        new_skill_initial_q=0.0,
        q_alpha=0.0,
    )
    _seed_lib(method)
    job = _MockJob(n_trials=4)
    from skillq.skillq_runtime import bridge as bridge_mod
    bridge_mod.attach_paper_registers(job, method)

    for i in range(4):
        result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / f"trial-{i}"))
        event = _fake_hook_event(f"trial-{i}", result=result)
        asyncio.run(job.on_ended(event))

    assert len(calls) == 1, f"expected 1 extract_batch call, got {len(calls)}"
    trials_arg = calls[0].get("trials", [])
    assert len(trials_arg) == 4, f"expected 4 aggregated records, got {len(trials_arg)}"
    # The 4 records have increasing trial names.
    names = [t["task"] for t in trials_arg]
    assert all(n == "sample-task" for n in names)
    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    assert "batched-1" in state["library"]["skills"]


def test_two_batches_in_eight_trials(tmp_path: Path, monkeypatch):
    """8 trials with N=4: 2 extract_batch calls, 2 new skills."""
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_no_skill_seen(monkeypatch)
    calls = _patch_extractor_recording(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=10,
                enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=4,
        new_skill_initial_q=0.0,
        q_alpha=0.0,
    )
    _seed_lib(method)
    job = _MockJob(n_trials=8)
    from skillq.skillq_runtime import bridge as bridge_mod
    bridge_mod.attach_paper_registers(job, method)

    for i in range(8):
        result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / f"trial-{i}"))
        event = _fake_hook_event(f"trial-{i}", result=result)
        asyncio.run(job.on_ended(event))

    assert len(calls) == 2, f"expected 2 extract_batch calls, got {len(calls)}"
    assert len(calls[0]["trials"]) == 4
    assert len(calls[1]["trials"]) == 4
    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    assert "batched-1" in state["library"]["skills"]
    assert "batched-2" in state["library"]["skills"]


def test_force_flush_on_last_trial_drains_partial(tmp_path: Path, monkeypatch):
    """3 trials with N=4: buffer has 3 records, force-flush on the
    last trial should drain it → 1 extract_batch call with 3 records.
    """
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_no_skill_seen(monkeypatch)
    calls = _patch_extractor_recording(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=10,
                enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=4,       # > #trials → no threshold hit
        new_skill_initial_q=0.0,
        q_alpha=0.0,
    )
    _seed_lib(method)
    # IMPORTANT: n_trials matches actual #trials so force-flush fires.
    job = _MockJob(n_trials=3)
    from skillq.skillq_runtime import bridge as bridge_mod
    bridge_mod.attach_paper_registers(job, method)

    for i in range(3):
        result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / f"trial-{i}"))
        event = _fake_hook_event(f"trial-{i}", result=result)
        asyncio.run(job.on_ended(event))

    assert len(calls) == 1, f"expected 1 force-flush call, got {len(calls)}"
    assert len(calls[0]["trials"]) == 3, "force-flush should drain all 3 buffered records"
    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    assert "batched-1" in state["library"]["skills"]


def test_no_force_flush_when_more_trials_remain(tmp_path: Path, monkeypatch):
    """3 actual trials but ``__len__(job)`` says 100: force-flush
    should NOT fire on the 3rd trial (we are not at the end).
    """
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_no_skill_seen(monkeypatch)
    calls = _patch_extractor_recording(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=10,
                enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=4,
        new_skill_initial_q=0.0,
        q_alpha=0.0,
    )
    _seed_lib(method)
    job = _MockJob(n_trials=100)   # long job; we only run 3 trials
    from skillq.skillq_runtime import bridge as bridge_mod
    bridge_mod.attach_paper_registers(job, method)

    for i in range(3):
        result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / f"trial-{i}"))
        event = _fake_hook_event(f"trial-{i}", result=result)
        asyncio.run(job.on_ended(event))

    assert len(calls) == 0, f"force-flush should NOT fire, got {len(calls)} calls"
    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    assert "batched-1" not in state["library"]["skills"]


def test_threshold_n_2_flushes_every_2_trials(tmp_path: Path, monkeypatch):
    """5 trials with N=2: 2 threshold flushes (trials 2 & 4) + 1 force-flush
    on trial 5 → 3 extract_batch calls total.
    """
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_no_skill_seen(monkeypatch)
    calls = _patch_extractor_recording(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=10,
                enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=2,
        new_skill_initial_q=0.0,
        q_alpha=0.0,
    )
    _seed_lib(method)
    job = _MockJob(n_trials=5)
    from skillq.skillq_runtime import bridge as bridge_mod
    bridge_mod.attach_paper_registers(job, method)

    for i in range(5):
        result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / f"trial-{i}"))
        event = _fake_hook_event(f"trial-{i}", result=result)
        asyncio.run(job.on_ended(event))

    assert len(calls) == 3, f"expected 3 extract_batch calls, got {len(calls)}"
    assert len(calls[0]["trials"]) == 2
    assert len(calls[1]["trials"]) == 2
    assert len(calls[2]["trials"]) == 1  # force-flush drains the remaining 1
