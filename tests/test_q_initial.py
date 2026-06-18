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

from skillq.method.library import LibManager  # noqa: E402
from skillq.method.state import QlibState  # noqa: E402
from skillq.method.types import Qlib, Skill  # noqa: E402
from skillq.paper_mode.config import MethodConfig  # noqa: E402


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
    from skillq.paper_mode import bridge as bridge_mod
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


def _patch_extractor_to_return(monkeypatch, skill: Skill | None) -> None:
    from skillq.paper_mode import bridge as bridge_mod

    async def fake_extract_batch(self, **kwargs) -> Skill | None:
        return skill

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
    state.save(
        lib,
        _fresh_mgr(method),
        lib_root=method.library_root,
        seed_initial_q=method.seed_initial_q,
    )


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
    mgr.set_q(new_skill.skill_id, new_skill_initial_q). Default 0.5.
    """
    _patch_litellm_backends(monkeypatch)
    new_skill = Skill(skill_id="auto-extracted", body="x" * 200)
    _patch_extractor_to_return(monkeypatch, new_skill)

    from skillq.paper_mode import bridge as bridge_mod
    from skillq.method.attribution import Attribution, TrialAttribution

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
        seed_initial_q=0.0,             # seed skill Q=0 so auto-extract fires
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    # Q-table is stored as [skill_id, q] pairs (global-Q refactor)
    auto_rows = [row for row in state["q_table"] if row[0] == "auto-extracted"]
    assert auto_rows, "auto-extracted skill should have a Q-table entry"
    for row in auto_rows:
        assert abs(row[1] - 0.5) < 1e-9, f"expected Q=0.5, got {row[1]}"


def test_extract_uses_configured_initial_q(tmp_path: Path, monkeypatch):
    """new_skill_initial_q=0.3 (not the default 0.5) is honoured."""
    _patch_litellm_backends(monkeypatch)
    new_skill = Skill(skill_id="auto", body="x" * 200)
    _patch_extractor_to_return(monkeypatch, new_skill)

    from skillq.paper_mode import bridge as bridge_mod
    from skillq.method.attribution import Attribution, TrialAttribution

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
        seed_initial_q=0.0,             # seed skill Q=0 so auto-extract fires
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)
    result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    auto_qs = [row[1] for row in state["q_table"] if row[0] == "auto"]
    assert auto_qs, "expected an auto-extracted Q entry"
    for q in auto_qs:
        assert abs(q - 0.3) < 1e-9


def test_seed_skill_load_into_gets_q_initial(tmp_path: Path):
    """When QlibState.load_into runs and a seed skill has no
    Q-table entry, it gets a synthetic skill_id → 0.5 entry.
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
        assert mgr2.q_for(sid) == 0.5


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
    assert mgr2.q_for("seed") == 0.0


def test_resume_does_not_overwrite_existing_q(tmp_path: Path):
    """If a skill already has a skill_id → q entry in the saved
    state, load_into must NOT overwrite it (resume is idempotent).
    """
    lib = Qlib(b_max=10)
    lib.add(Skill(skill_id="seed", body="x"))
    mgr = LibManager(
        b_max=10, theta_admit=0.3, theta_evict=0.1, n_explore=5, n_stale=80
    )
    # Pre-populate with a custom Q
    mgr.update_q("seed", 0.7)
    state = QlibState(tmp_path / "method_state.json")
    state.save(lib, mgr, lib_root=tmp_path, seed_initial_q=0.5)

    lib2 = Qlib()
    mgr2 = LibManager(
        b_max=10, theta_admit=0.3, theta_evict=0.1, n_explore=5, n_stale=80
    )
    state2 = QlibState(tmp_path / "method_state.json")
    state2.load_into(lib2, mgr2, lib_root=tmp_path)
    assert mgr2.q_for("seed") == 0.7  # not 0.5


def test_method_config_default_for_new_skill_initial_q():
    """The default new_skill_initial_q is 0.5."""
    cfg = MethodConfig()
    assert cfg.new_skill_initial_q == 0.5


def test_bridge_redumps_q_table_to_staging_on_ended(tmp_path: Path, monkeypatch):
    """Bug 3 fix: after on_ended, trial_dir/skillq_state/q_table.json
    must reflect the post-trial Q-table, not the trial-START snapshot
    written by ``container_wiring._write_state_files``.

    Setup:
        - Trial staging has an "old" q_table.json (the trial-START
          snapshot, all 0.5 for known skills).
        - on_ended triggers auto-extract → ``mgr.set_q(new_skill,
          0.42)`` mutates the in-memory Q-table.

    Assertion:
        - The post-trial staging file shows the new skill at 0.42.
        - The pre-existing seed skill remains at 0.0 (un-mutated).
    """
    _patch_litellm_backends(monkeypatch)
    new_skill = Skill(skill_id="auto-fix-cwe", body="x" * 200)
    _patch_extractor_to_return(monkeypatch, new_skill)

    from skillq.paper_mode import bridge as bridge_mod
    from skillq.method.attribution import Attribution, TrialAttribution

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
        extract_every_n_trials=1,
        seed_initial_q=0.0,             # seed skill Q=0 so auto-extract fires
        new_skill_initial_q=0.42,       # distinctive value to grep for
    )
    _seed_lib(method)

    # Mimic trial-START: container_wiring._write_state_files writes
    # the per-trial staging q_table.json from mgr.q_table BEFORE
    # on_ended runs. We reproduce the same format here.
    trial_dir = tmp_path / "trial-bug3"
    trial_dir.mkdir()
    staging = trial_dir / "skillq_state"
    staging.mkdir(parents=True, exist_ok=True)
    # Load the just-saved state to read mgr.q_table at trial-START.
    lib_start = Qlib()
    mgr_start = _fresh_mgr(method)
    state_start = QlibState(method.resolved_state_path())
    state_start.load_into(lib_start, mgr_start, lib_root=method.library_root)
    staging_q_path = staging / "q_table.json"
    staging_q_path.write_text(
        json.dumps(dict(mgr_start.q_table), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    pre_onshot_snapshot = json.loads(staging_q_path.read_text(encoding="utf-8"))
    # Sanity: trial-START snapshot does NOT yet contain the new skill
    # (it does not exist until auto-extract fires inside on_ended).
    assert "auto-fix-cwe" not in pre_onshot_snapshot

    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)
    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-bug3", result=result)
    asyncio.run(job.on_ended(event))

    # Post-trial: staging q_table.json must be re-dumped with the
    # post-trial Q-table (Bug 3 fix).
    post_snapshot = json.loads(staging_q_path.read_text(encoding="utf-8"))
    # The new skill must now appear with its initial Q.
    assert "auto-fix-cwe" in post_snapshot
    assert abs(post_snapshot["auto-fix-cwe"] - 0.42) < 1e-9


# ---------------------------------------------------------------------------
# Bug 5 — Q-value clip (q_clip_floor / q_clip_ceiling on LibManager)
# ---------------------------------------------------------------------------
def test_q_clip_default_no_clip():
    """Default q_clip_floor=None, q_clip_ceiling=None: update_q
    and set_q accept any value. Existing behaviour preserved.
    """
    mgr = LibManager(
        b_max=10, theta_admit=0.25, theta_evict=0.15,
        n_explore=8, n_stale=80,
    )
    mgr.update_q("a", -10.0)   # big negative delta
    assert mgr.q_for("a") == -10.0  # not clipped
    mgr.set_q("b", 2.0)         # value > 1
    assert mgr.q_for("b") == 2.0   # not clipped


def test_q_clip_floor_zero_forbids_negative():
    """q_clip_floor=0.0: Q never goes below 0 via update_q OR set_q.
    """
    mgr = LibManager(
        b_max=10, theta_admit=0.25, theta_evict=0.15,
        n_explore=8, n_stale=80,
        q_clip_floor=0.0,
    )
    mgr.update_q("a", -10.0)
    assert mgr.q_for("a") == 0.0  # clipped to floor
    mgr.set_q("b", -0.5)
    assert mgr.q_for("b") == 0.0  # clipped to floor


def test_q_clip_ceiling_one_forbids_above_one():
    """q_clip_ceiling=1.0: Q never goes above 1 via update_q OR set_q.
    """
    mgr = LibManager(
        b_max=10, theta_admit=0.25, theta_evict=0.15,
        n_explore=8, n_stale=80,
        q_clip_ceiling=1.0,
    )
    mgr.set_q("a", 2.0)
    assert mgr.q_for("a") == 1.0  # clipped to ceiling
    mgr.update_q("b", 100.0)  # huge positive delta
    assert mgr.q_for("b") == 1.0


def test_q_clip_both_bounds():
    """q_clip_floor=-0.5, q_clip_ceiling=0.5: Q stays in [-0.5, 0.5].
    """
    mgr = LibManager(
        b_max=10, theta_admit=0.25, theta_evict=0.15,
        n_explore=8, n_stale=80,
        q_clip_floor=-0.5, q_clip_ceiling=0.5,
    )
    mgr.update_q("a", 100.0)
    assert mgr.q_for("a") == 0.5
    mgr.update_q("a", -100.0)
    assert mgr.q_for("a") == -0.5


def test_method_config_q_clip_default_none():
    """MethodConfig.q_clip_floor / q_clip_ceiling default to None.
    """
    cfg = MethodConfig()
    assert cfg.q_clip_floor is None
    assert cfg.q_clip_ceiling is None


def test_method_config_q_clip_floor_zero_roundtrip():
    """q_clip_floor=0.0 round-trips through pydantic validation.
    """
    cfg = MethodConfig(q_clip_floor=0.0)
    assert cfg.q_clip_floor == 0.0
    # And wires into LibManager via the bridge plumbing (the
    # bridge's LibManager(...) call passes it through).
    mgr = LibManager(
        b_max=10, theta_admit=0.25, theta_evict=0.15,
        n_explore=8, n_stale=80,
        q_clip_floor=cfg.q_clip_floor,
    )
    mgr.update_q("a", -1.0)
    assert mgr.q_for("a") == 0.0
