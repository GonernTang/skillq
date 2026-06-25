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
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

# Make the project importable when running ``pytest`` from the
# project root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.method.library import LibManager  # noqa: E402
from skillq.method.state import QlibState  # noqa: E402
from skillq.method.types import Qlib, Skill  # noqa: E402
from skillq.skillq_runtime.config import MethodConfig  # noqa: E402


# ---------------------------------------------------------------------------
# QlibState round-trip
# ---------------------------------------------------------------------------
def test_qlib_state_round_trip(tmp_path: Path):
    lib = Qlib(b_max=10)
    lib.add(Skill(skill_id="a", body="body a", n_retrievals=2, n_uses=1, n_success=1))
    lib.add(Skill(skill_id="b", body="body b", n_retrievals=0))
    mgr = LibManager(
        b_max=10
    )
    mgr.update_q(skill_id="a", delta=0.5)
    mgr.update_q(skill_id="b", delta=-0.2)
    state = QlibState(tmp_path / "method_state.json")
    state.step = 42
    state.save(lib, mgr, lib_root=tmp_path)

    # Reload into a fresh in-memory state.
    lib2 = Qlib()
    mgr2 = LibManager(
        b_max=10
    )
    state2 = QlibState(tmp_path / "method_state.json")
    assert state2.load_into(lib2, mgr2) is True
    assert state2.step == 42
    assert {s.skill_id for s in lib2.skills.values()} == {"a", "b"}
    assert lib2.b_max == 10
    assert mgr2.q_for("a") == 0.5
    assert mgr2.q_for("b") == -0.2


def test_qlib_state_handles_missing_file(tmp_path: Path):
    lib = Qlib(b_max=3)
    mgr = LibManager(
        b_max=3
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
        # 2026-06-25: switched from MagicMock to SimpleNamespace —
        # MagicMock's __contains__ and `is not None` semantics silently
        # corrupt the retry-classification inside the bridge. Pinning
        # max_retries=0 matches the production YAML.
        self.config = SimpleNamespace(
            retry=SimpleNamespace(
                max_retries=0,
                exclude_exceptions=None,
                include_exceptions=None,
            )
        )

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
    )
    # Pre-seed the library with a single skill so the ranker has something
    # to retrieve.
    lib = Qlib(b_max=4)
    lib.add(Skill(skill_id="seed", body="seed body"))
    state = QlibState(method.resolved_state_path())
    state.save(lib, _fresh_manager(method), lib_root=method.library_root)

    job = _MockJob()
    from skillq.skillq_runtime import bridge as bridge_mod
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

    method = MethodConfig(library_root=tmp_path / "lib", b_max=4)
    state = QlibState(method.resolved_state_path())
    state.save(Qlib(b_max=4), _fresh_manager(method), lib_root=method.library_root)

    job = _MockJob()
    from skillq.skillq_runtime import bridge as bridge_mod
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


def _fresh_manager(method: MethodConfig) -> LibManager:
    return LibManager(b_max=method.b_max)


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


# ---------------------------------------------------------------------------
# _score_skills — Fix 1 (Hard Gate) + Fix 2 (multiplicative scoring)
# (2026-06-24)
# ---------------------------------------------------------------------------
from skillq.skillq_runtime.hook import _score_skills as _score_skills_hook  # noqa: E402


def _build_score_input():
    """Build a 3-skill fixture for _score_skills tests.

    Skills: A (sim=1.0, Q=0.9), B (sim=0.5, Q=0.5), C (sim=0.0, Q=0.1).
    Embeddings: orthogonal unit vectors; query is along A.
    """
    skills = [
        {"skill_id": "A", "n_retrievals": 0},
        {"skill_id": "B", "n_retrievals": 0},
        {"skill_id": "C", "n_retrievals": 0},
    ]
    q_table = {"A": 0.9, "B": 0.5, "C": 0.1}
    emb_cache = {
        "A": [1.0, 0.0, 0.0],
        "B": [0.0, 1.0, 0.0],
        "C": [0.0, 0.0, 1.0],
    }
    subtask_emb = [1.0, 0.0, 0.0]
    return subtask_emb, skills, q_table, emb_cache


def test_score_skills_additive_unchanged_regression():
    """Additive mode (legacy Eq.4): z-scored sim + z-scored Q + UCB."""
    subtask_emb, skills, q_table, emb_cache = _build_score_input()
    result = _score_skills_hook(
        subtask_emb=subtask_emb,
        skills=skills,
        q_table=q_table,
        emb_cache=emb_cache,
        lambda_=0.5,
        c_ucb=0.5,
        top_k=3,
        score_mode="additive",
    )
    # A (highest sim, highest Q) → highest score
    assert result[0][0] == "A"
    # All three skills appear
    assert {sid for sid, _ in result} == {"A", "B", "C"}


def test_score_skills_multiplicative_basic():
    """Multiplicative: sim·(1 + β·Q_norm) + γ·UCB. Key property: when
    sim=0, score = γ·UCB only — Q cannot promote the irrelevant skill.
    """
    subtask_emb, skills, q_table, emb_cache = _build_score_input()
    result = _score_skills_hook(
        subtask_emb=subtask_emb,
        skills=skills,
        q_table=q_table,
        emb_cache=emb_cache,
        lambda_=0.5,                # ignored in multiplicative mode
        c_ucb=0.5,
        top_k=3,
        score_mode="multiplicative",
        mult_beta=0.5,
        mult_gamma=0.2,
        q_clip_min=0.0,
        q_clip_max=1.0,
    )
    # A is highest (sim=1.0 × (1 + 0.5 × 0.9) + γ·UCB ≈ 1.45 + small)
    assert result[0][0] == "A"
    # C's score should be ONLY γ·UCB (no sim term, no Q amplification)
    c_score = next(s for sid, s in result if sid == "C")
    # UCB term: c_ucb * sqrt(log(n_total) / n); n_total=1+1=2, n=0+1=1
    # = 0.5 * sqrt(log(2)/1) ≈ 0.5 * 0.833 = 0.417
    import math
    expected_c = 0.2 * 0.5 * math.sqrt(math.log(2) / 1)
    assert abs(c_score - expected_c) < 1e-6, f"C score {c_score} != {expected_c}"


def test_score_skills_gate_filters():
    """Hard Gate: candidates with sim < threshold dropped before scoring."""
    subtask_emb, skills, q_table, emb_cache = _build_score_input()
    # sims: A=1.0, B=0.0, C=0.0. Gate at 0.3 → only A survives.
    result = _score_skills_hook(
        subtask_emb=subtask_emb,
        skills=skills,
        q_table=q_table,
        emb_cache=emb_cache,
        lambda_=0.5,
        c_ucb=0.5,
        top_k=3,
        score_mode="multiplicative",
        mult_beta=0.5,
        mult_gamma=0.2,
        sim_gate_threshold=0.3,
        sim_gate_min_score=0.3,
        sim_gate_floor=1,
    )
    # Only A should remain (B and C had sim=0.0 < 0.3)
    assert {sid for sid, _ in result} == {"A"}


def test_score_skills_gate_floor_fallback():
    """Hard Gate floor: if all skills would be gated out, keep the
    top-N by descending sim anyway.
    """
    subtask_emb, skills, q_table, emb_cache = _build_score_input()
    # Threshold higher than any sim → all would be gated → floor=1 keeps A
    result = _score_skills_hook(
        subtask_emb=subtask_emb,
        skills=skills,
        q_table=q_table,
        emb_cache=emb_cache,
        lambda_=0.5,
        c_ucb=0.5,
        top_k=3,
        score_mode="multiplicative",
        sim_gate_threshold=0.99,
        sim_gate_min_score=0.99,
        sim_gate_floor=1,
    )
    # floor=1 → at least A (highest sim) retained
    assert {sid for sid, _ in result} == {"A"}


def test_score_skills_gate_aggressive_default():
    """sim_gate_threshold=0.75 → aggressive gate: only the highest-sim
    candidates pass through. In our 3-skill fixture where only A has
    sim=1.0 and B/C have sim=0.0, only A survives (floor=1 retains it).
    """
    subtask_emb, skills, q_table, emb_cache = _build_score_input()
    result = _score_skills_hook(
        subtask_emb=subtask_emb,
        skills=skills,
        q_table=q_table,
        emb_cache=emb_cache,
        lambda_=0.5,
        c_ucb=0.5,
        top_k=3,
        score_mode="multiplicative",
        # explicit threshold — the production YAML opts in at 0.75
        sim_gate_threshold=0.75,
        sim_gate_min_score=0.75,
        sim_gate_floor=1,
    )
    # sims: A=1.0, B=0.0, C=0.0. Gate at 0.75 → only A survives.
    # floor=1 means at least 1 candidate retained (A).
    assert {sid for sid, _ in result} == {"A"}


def test_score_skills_zero_sim_only_ucb():
    """Critical property: skill with sim=0 and high Q cannot reach top."""
    skills = [
        {"skill_id": "relevant", "n_retrievals": 0},  # sim=1.0
        {"skill_id": "irrelevant_high_q", "n_retrievals": 0},  # sim=0, Q=0.99
    ]
    q_table = {"relevant": 0.5, "irrelevant_high_q": 0.99}
    emb_cache = {
        "relevant": [1.0, 0.0],
        "irrelevant_high_q": [0.0, 1.0],  # orthogonal
    }
    subtask_emb = [1.0, 0.0]
    result = _score_skills_hook(
        subtask_emb=subtask_emb,
        skills=skills,
        q_table=q_table,
        emb_cache=emb_cache,
        lambda_=0.5,
        c_ucb=0.5,
        top_k=2,
        score_mode="multiplicative",
        mult_beta=0.5,
        mult_gamma=0.2,
    )
    # Even though irrelevant_high_q has Q=0.99, its score is purely
    # γ·UCB — must rank below "relevant" (sim=1.0, Q=0.5)
    assert result[0][0] == "relevant"
    # The Q=0.99 did NOT allow irrelevant_high_q to overtake relevant
    irrelevant_score = next(s for sid, s in result if sid == "irrelevant_high_q")
    assert irrelevant_score < 1.0  # purely γ·UCB, well below 1.0+
