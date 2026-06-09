"""Tests for new-skill Q=0.5 initialisation.

Covers three paths:
  1. Fresh-extract path (bridge.py writes Q=0.5 on lib.add).
  2. Seed-skill path (QlibState.load_into writes Q=0.5 for any
     skill that has no Q-table entry).
  3. Configurable value (MethodConfig.new_skill_initial_q).
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

from paper.method.library import LibManager  # noqa: E402
from paper.method.state import QlibState  # noqa: E402
from paper.method.types import Qlib, Skill  # noqa: E402
from paper.paper_mode.config import MethodConfig  # noqa: E402


# ---------------------------------------------------------------------------
# Test fixtures (mirrors tests/test_bridge_extract.py)
# ---------------------------------------------------------------------------
class _MockJob:
    def __init__(self) -> None:
        self.on_ended: Any = None
        self.config = MagicMock()
        self.config.retry = MagicMock()
        self.config.retry.exclude_exceptions = None
        self.config.retry.include_exceptions = None

    def on_trial_ended(self, callback: Any) -> None:
        self.on_ended = callback

    def __len__(self) -> int:
        # The bridge uses ``len(job)`` for the buffer force-flush
        # trigger; a large sentinel keeps it dormant in unit tests.
        return 1_000_000


def _patch_litellm_backends(monkeypatch) -> None:
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


def _patch_extractor_to_return(monkeypatch, skill: Skill | None) -> None:
    from paper.paper_mode import bridge as bridge_mod

    async def fake_extract(self, **kwargs) -> Skill | None:
        return skill

    async def fake_extract_batch(self, **kwargs) -> Skill | None:
        return skill

    monkeypatch.setattr(bridge_mod.SkillExtractor, "extract", fake_extract)
    monkeypatch.setattr(bridge_mod.SkillExtractor, "extract_batch", fake_extract_batch)


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
    state.save(lib, _fresh_mgr(method), lib_root=method.library_root)


def _fresh_mgr(method: MethodConfig) -> LibManager:
    return LibManager(
        b_max=method.b_max,
        theta_admit=method.theta_admit,
        theta_evict=method.theta_evict,
        n_explore=method.n_explore,
        n_stale=method.n_stale,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_extract_writes_q_initial_to_q_table(tmp_path: Path, monkeypatch):
    """After lib.add(new_skill), the bridge writes
    mgr.update_q(intent_hash, new_skill.skill_id, new_skill_initial_q).
    Default value 0.5.
    """
    _patch_litellm_backends(monkeypatch)
    new_skill = Skill(skill_id="auto-extracted", body="x" * 200)
    _patch_extractor_to_return(monkeypatch, new_skill)

    from paper.paper_mode import bridge as bridge_mod
    from paper.method.attribution import Attribution, TrialAttribution

    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.SUCCESS_NO_SKILL_SEEN,
            overall_rationale="test",
            knowledge_to_extract="reusable knowledge",
        ),
    )

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        n_explore=2,
        enable_auto_extract=True,
        extract_every_n_trials=1,       # flush on the first qualifying trial
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    # Q-table is stored as [intent, skill_id, q] triples
    auto_rows = [row for row in state["q_table"] if row[1] == "auto-extracted"]
    assert auto_rows, "auto-extracted skill should have a Q-table entry"
    # The intent_hash recorded is the trial's task_name hash; we
    # just check the Q value is 0.5, not 0.
    for row in auto_rows:
        assert abs(row[2] - 0.5) < 1e-9, f"expected Q=0.5, got {row[2]}"


def test_extract_uses_configured_initial_q(tmp_path: Path, monkeypatch):
    """new_skill_initial_q=0.3 (not the default 0.5) is honoured."""
    _patch_litellm_backends(monkeypatch)
    new_skill = Skill(skill_id="auto", body="x" * 200)
    _patch_extractor_to_return(monkeypatch, new_skill)

    from paper.paper_mode import bridge as bridge_mod
    from paper.method.attribution import Attribution, TrialAttribution

    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.SUCCESS_NO_SKILL_SEEN,
            overall_rationale="test",
            knowledge_to_extract="x",
        ),
    )

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        n_explore=2,
        enable_auto_extract=True,
        extract_every_n_trials=1,       # flush on the first qualifying trial
        new_skill_initial_q=0.3,
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)
    result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    auto_qs = [row[2] for row in state["q_table"] if row[1] == "auto"]
    assert auto_qs, "expected an auto-extracted Q entry"
    for q in auto_qs:
        assert abs(q - 0.3) < 1e-9


def test_seed_skill_load_into_gets_q_initial(tmp_path: Path):
    """When QlibState.load_into runs and a seed skill has no
    Q-table entry, it gets a synthetic (0, skill_id) → 0.5 entry.
    """
    lib = Qlib(b_max=10)
    lib.add(Skill(skill_id="seed-skill-A", body="body A"))
    lib.add(Skill(skill_id="seed-skill-B", body="body B"))
    mgr = LibManager(
        b_max=10, theta_admit=0.3, theta_evict=0.1, n_explore=5, n_stale=80
    )
    state = QlibState(tmp_path / "method_state.json")
    state.save(lib, mgr, lib_root=tmp_path, seed_initial_q=0.5)

    # Now load fresh and confirm seed skills have Q=0.5
    lib2 = Qlib()
    mgr2 = LibManager(
        b_max=10, theta_admit=0.3, theta_evict=0.1, n_explore=5, n_stale=80
    )
    state2 = QlibState(tmp_path / "method_state.json")
    state2.load_into(lib2, mgr2, lib_root=tmp_path)
    for sid in ("seed-skill-A", "seed-skill-B"):
        assert mgr2.q_for(0, sid) == 0.5
        assert mgr2.q_for(42, sid) == 0.0  # other intents are 0


def test_seed_initial_q_0_disables_seeding(tmp_path: Path):
    """If seed_initial_q=0, no synthetic entries are written."""
    lib = Qlib(b_max=10)
    lib.add(Skill(skill_id="seed", body="x"))
    mgr = LibManager(
        b_max=10, theta_admit=0.3, theta_evict=0.1, n_explore=5, n_stale=80
    )
    state = QlibState(tmp_path / "method_state.json")
    state.save(lib, mgr, lib_root=tmp_path, seed_initial_q=0.0)

    lib2 = Qlib()
    mgr2 = LibManager(
        b_max=10, theta_admit=0.3, theta_evict=0.1, n_explore=5, n_stale=80
    )
    state2 = QlibState(tmp_path / "method_state.json")
    state2.load_into(lib2, mgr2, lib_root=tmp_path)
    assert mgr2.q_for(0, "seed") == 0.0


def test_resume_does_not_overwrite_existing_q(tmp_path: Path):
    """If a skill already has a (0, skill_id) Q entry in the saved
    state, load_into must NOT overwrite it (resume is idempotent).
    """
    lib = Qlib(b_max=10)
    lib.add(Skill(skill_id="seed", body="x"))
    mgr = LibManager(
        b_max=10, theta_admit=0.3, theta_evict=0.1, n_explore=5, n_stale=80
    )
    # Pre-populate with a custom Q
    mgr.update_q(0, "seed", 0.7)
    state = QlibState(tmp_path / "method_state.json")
    state.save(lib, mgr, lib_root=tmp_path, seed_initial_q=0.5)

    lib2 = Qlib()
    mgr2 = LibManager(
        b_max=10, theta_admit=0.3, theta_evict=0.1, n_explore=5, n_stale=80
    )
    state2 = QlibState(tmp_path / "method_state.json")
    state2.load_into(lib2, mgr2, lib_root=tmp_path)
    assert mgr2.q_for(0, "seed") == 0.7  # not 0.5


def test_method_config_default_for_new_skill_initial_q():
    """The default new_skill_initial_q is 0.5."""
    cfg = MethodConfig()
    assert cfg.new_skill_initial_q == 0.5
