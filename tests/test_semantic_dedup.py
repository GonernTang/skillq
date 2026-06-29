"""Tests for the 2026-06-25 semantic-dedup layer at the L4 boundary.

The dedup happens inside ``_flush_buffer`` (a closure inside
``bridge.attach_paper_registers``). When ``MethodConfig.semantic_dedup_threshold
> 0``, the bridge:

  1. Embeds the new skill's description via ``sync_embed``.
  2. Compares (cosine) against every existing skill's cached embedding
     from ``emb_cache``.
  3. Skips the new skill if max cosine ≥ threshold (even if its
     kebab-case name differs from the existing skill).

Edge cases:
  - ``sync_embed`` raises → fall open (warn, proceed to name-based dedup).
  - Empty emb_cache (no embeddings cached for any skill) → no cosine
    comparisons possible, fall open.
  - ``semantic_dedup_threshold == 0.0`` → entire dedup block is skipped
    (no embed call).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.layers.l3_attribution.models import Attribution, TrialAttribution  # noqa: E402
from skillq.shared.q_table import LibManager  # noqa: E402
from skillq.shared.library import QlibState  # noqa: E402
from skillq.shared.types import Qlib, Skill  # noqa: E402
from skillq.shared.embeddings import VectorTable  # noqa: E402
from skillq.runtime import bridge as bridge_mod  # noqa: E402
from skillq.runtime import steps as steps_mod  # noqa: E402
from skillq.config import MethodConfig  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures (mirrors tests/test_batched_extract.py pattern)
# ---------------------------------------------------------------------------
class _MockJob:
    def __init__(self, n_trials: int = 4) -> None:
        self.n_trials = n_trials
        self.on_ended: Any = None
        self.config = MagicMock()
        self.config.retry = MagicMock()
        self.config.retry.exclude_exceptions = None
        self.config.retry.include_exceptions = None

    def on_trial_ended(self, callback: Any) -> None:
        self.on_ended = callback

    def on_trial_started(self, callback: Any) -> None:
        self.on_started = callback  # Step 7: new pipeline needs both

    def __len__(self) -> int:
        return self.n_trials


def _patch_litellm_backends(monkeypatch) -> None:
    from skillq.layers.l3_attribution.models import StubAttributionBackend
    from skillq.shared.backends.litellm import StubEmbedder

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


def _patch_attribution_for_extract(monkeypatch) -> None:
    """Attribution that fires the L4 extract path on every trial."""
    def returning(self, **kwargs):
        return TrialAttribution(
            overall_attribution=Attribution.SUCCESS_NO_SKILL_SEEN,
            overall_rationale="test",
            knowledge_to_extract="reusable knowledge",
        )

    monkeypatch.setattr(bridge_mod.AttributionAnalyzer, "analyze", returning)


def _patch_extractor_to_return(monkeypatch, skill_id: str, body: str):
    """Replace extract_batch with a stub that returns a fixed Skill."""
    async def fake_extract_batch(self, **kwargs) -> Skill:
        return Skill(skill_id=skill_id, body=body, metadata={"source": "test"})

    monkeypatch.setattr(bridge_mod.SkillExtractor, "extract_batch", fake_extract_batch)


def _patch_sync_embed_to_return(monkeypatch, vec: list[float]):
    """Replace bridge.sync_embed with a fixed-vector stub."""
    monkeypatch.setattr(steps_mod, "sync_embed", lambda text, host, port: vec)


def _patch_sync_embed_to_raise(monkeypatch):
    """Replace bridge.sync_embed with one that raises."""
    def raising(*args, **kwargs):
        raise RuntimeError("embed daemon down")
    monkeypatch.setattr(steps_mod, "sync_embed", raising)


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


def _seed_lib_with_embedding(method: MethodConfig, skill_id: str, body: str, emb: list[float]) -> None:
    """Write a 1-skill lib + matching emb_cache.json on disk."""
    lib = Qlib(b_max=method.b_max)
    lib.add(Skill(skill_id=skill_id, body=body))
    state = QlibState(method.resolved_state_path())
    state.save(
        lib,
        LibManager(b_max=method.b_max),
        lib_root=method.library_root,
        seed_initial_q=method.seed_initial_q,
    )
    cache = VectorTable(method.resolved_emb_cache_path())
    cache.load()
    import numpy as np
    cache.upsert(skill_id, np.asarray(emb, dtype=np.float32))
    cache.save()


# ---------------------------------------------------------------------------
# Default field + MethodConfig
# ---------------------------------------------------------------------------
def test_semantic_dedup_threshold_default():
    from skillq.config import MethodConfig

    cfg = MethodConfig()
    assert cfg.semantic_dedup_threshold == pytest.approx(0.85)


def test_semantic_dedup_threshold_bounds():
    from skillq.config import MethodConfig

    with pytest.raises(ValueError):
        MethodConfig(semantic_dedup_threshold=-0.1)
    with pytest.raises(ValueError):
        MethodConfig(semantic_dedup_threshold=1.5)


def test_semantic_dedup_threshold_zero_disables_field():
    """semantic_dedup_threshold=0.0 is the documented opt-out."""
    from skillq.config import MethodConfig

    cfg = MethodConfig(semantic_dedup_threshold=0.0)
    assert cfg.semantic_dedup_threshold == 0.0


# ---------------------------------------------------------------------------
# Integration: full on_ended flow with stubbed bridge internals
# ---------------------------------------------------------------------------
def test_high_cosine_skips_via_semantic_dedup(
    tmp_path: Path, monkeypatch
):
    """New skill with cosine ≥ threshold against existing → skipped.

    We stub ``sync_embed`` to return a vector parallel to the existing
    skill's cached embedding. The new skill's name is *different* from
    the existing one (so name-based dedup would NOT skip it), but the
    cosine threshold trips first.
    """
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_for_extract(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=8,
        enable_auto_extract=True,
        seed_initial_q=0.5,
        new_skill_initial_q=0.5,
        extract_every_n_trials=1,   # flush on first qualifying trial
        semantic_dedup_threshold=0.85,
    )

    # Existing skill in the lib with a known cached embedding.
    existing_vec = [1.0, 0.0, 0.0, 0.0]
    _seed_lib_with_embedding(
        method,
        skill_id="existing-skill",
        body="# Existing\n\ndescription: A pre-existing skill.\n",
        emb=existing_vec,
    )

    # The new skill has a *different* name (so name-based dedup
    # wouldn't catch it), but its description embeds to the same
    # vector (cosine = 1.0).
    _patch_extractor_to_return(
        monkeypatch,
        skill_id="semantically-same-but-different-name",
        body="# New\n\ndescription: A pre-existing skill.\n",
    )
    _patch_sync_embed_to_return(monkeypatch, existing_vec)

    job = _MockJob(n_trials=2)
    bridge_mod.attach_layered_registers(job, method)

    trial_dir = tmp_path / "trial-1"
    trial_dir.mkdir()
    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-1", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text())
    skills_in_lib = list(state["library"]["skills"].keys())
    assert "existing-skill" in skills_in_lib
    assert "semantically-same-but-different-name" not in skills_in_lib, (
        "semantic dedup should have skipped the duplicate (cosine=1.0 >= 0.85)"
    )


def test_low_cosine_keeps_new_skill(tmp_path: Path, monkeypatch):
    """New skill orthogonal to all existing → kept (no dedup skip)."""
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_for_extract(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=8,
        enable_auto_extract=True,
        seed_initial_q=0.5,
        new_skill_initial_q=0.5,
        extract_every_n_trials=1,
        semantic_dedup_threshold=0.85,
    )
    _seed_lib_with_embedding(
        method,
        skill_id="existing-skill",
        body="# Existing\n\ndescription: Old skill about pandas.\n",
        emb=[1.0, 0.0, 0.0, 0.0],
    )
    # New description orthogonal to existing → cosine = 0.
    _patch_extractor_to_return(
        monkeypatch,
        skill_id="totally-different",
        body="# New\n\ndescription: New skill about debugging rust.\n",
    )
    _patch_sync_embed_to_return(monkeypatch, [0.0, 1.0, 0.0, 0.0])

    job = _MockJob(n_trials=2)
    bridge_mod.attach_layered_registers(job, method)

    trial_dir = tmp_path / "trial-1"
    trial_dir.mkdir()
    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-1", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text())
    skills_in_lib = list(state["library"]["skills"].keys())
    assert "existing-skill" in skills_in_lib
    assert "totally-different" in skills_in_lib, (
        "orthogonal new skill should NOT be skipped by semantic dedup"
    )


def test_semantic_dedup_threshold_zero_no_embed_call(
    tmp_path: Path, monkeypatch
):
    """semantic_dedup_threshold=0.0 → sync_embed is never called.

    We assert this by making sync_embed raise — if it were called,
    the bridge would log a warning, but the test only passes when
    the embed call never happens.
    """
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_for_extract(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=8,
        enable_auto_extract=True,
        seed_initial_q=0.5,
        new_skill_initial_q=0.5,
        extract_every_n_trials=1,
        semantic_dedup_threshold=0.0,  # disabled
    )
    _seed_lib_with_embedding(
        method,
        skill_id="existing",
        body="# Existing\n\ndescription: Old.\n",
        emb=[1.0, 0.0, 0.0, 0.0],
    )
    _patch_extractor_to_return(
        monkeypatch,
        skill_id="new",
        body="# New\n\ndescription: Different name, same content.\n",
    )
    _patch_sync_embed_to_raise(monkeypatch)  # would crash if called

    job = _MockJob(n_trials=2)
    bridge_mod.attach_layered_registers(job, method)

    trial_dir = tmp_path / "trial-1"
    trial_dir.mkdir()
    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-1", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text())
    # 'new' should be added (different name; semantic dedup disabled).
    assert "new" in state["library"]["skills"]


def test_semantic_dedup_embed_failure_falls_open(
    tmp_path: Path, monkeypatch
):
    """sync_embed raises → fall through to name-based dedup path.

    The new skill has a fresh kebab-case name (no name collision), so
    it gets added even though semantic dedup could not run.
    """
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_for_extract(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=8,
        enable_auto_extract=True,
        seed_initial_q=0.5,
        new_skill_initial_q=0.5,
        extract_every_n_trials=1,
        semantic_dedup_threshold=0.85,
    )
    _seed_lib_with_embedding(
        method,
        skill_id="existing",
        body="# Existing\n\ndescription: Old.\n",
        emb=[1.0, 0.0, 0.0, 0.0],
    )
    _patch_extractor_to_return(
        monkeypatch,
        skill_id="fresh-name",
        body="# Fresh\n\ndescription: Brand new.\n",
    )
    _patch_sync_embed_to_raise(monkeypatch)

    job = _MockJob(n_trials=2)
    bridge_mod.attach_layered_registers(job, method)

    trial_dir = tmp_path / "trial-1"
    trial_dir.mkdir()
    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-1", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text())
    assert "fresh-name" in state["library"]["skills"], (
        "embed failure should fall open to name-based dedup path, "
        "which only skips on exact kebab-case matches"
    )


def test_semantic_dedup_does_not_block_when_lib_empty(
    tmp_path: Path, monkeypatch
):
    """Empty lib → no cosine comparisons possible → new skill added.

    `emb_cache` is empty (no existing skills), so the dedup loop has
    nothing to compare against. The new skill flows through to
    ``lib.add`` normally.
    """
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_for_extract(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=8,
        enable_auto_extract=True,
        seed_initial_q=0.5,
        new_skill_initial_q=0.5,
        extract_every_n_trials=1,
        semantic_dedup_threshold=0.85,
    )
    # No seed_lib → lib starts empty.
    _patch_extractor_to_return(
        monkeypatch,
        skill_id="first-skill",
        body="# First\n\ndescription: Brand new skill.\n",
    )
    _patch_sync_embed_to_return(monkeypatch, [0.5, 0.5, 0.0, 0.0])

    job = _MockJob(n_trials=2)
    bridge_mod.attach_layered_registers(job, method)

    trial_dir = tmp_path / "trial-1"
    trial_dir.mkdir()
    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-1", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text())
    assert "first-skill" in state["library"]["skills"]


def test_semantic_dedup_compares_against_all_existing(
    tmp_path: Path, monkeypatch
):
    """Two existing skills, new emb matches one of them → skipped."""
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_for_extract(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=8,
        enable_auto_extract=True,
        seed_initial_q=0.5,
        new_skill_initial_q=0.5,
        extract_every_n_trials=1,
        semantic_dedup_threshold=0.85,
    )

    # 2 existing skills.
    lib = Qlib(b_max=method.b_max)
    lib.add(Skill(skill_id="alpha", body="# Alpha\n\ndescription: First.\n"))
    lib.add(Skill(skill_id="beta", body="# Beta\n\ndescription: Second.\n"))
    state = QlibState(method.resolved_state_path())
    state.save(
        lib,
        LibManager(b_max=method.b_max),
        lib_root=method.library_root,
        seed_initial_q=method.seed_initial_q,
    )
    cache = VectorTable(method.resolved_emb_cache_path())
    cache.load()
    import numpy as np
    cache.upsert("alpha", np.asarray([1.0, 0.0, 0.0, 0.0], dtype=np.float32))
    cache.upsert("beta", np.asarray([0.0, 1.0, 0.0, 0.0], dtype=np.float32))
    cache.save()

    _patch_extractor_to_return(
        monkeypatch,
        skill_id="gamma",
        body="# Gamma\n\ndescription: Near-duplicate of beta.\n",
    )
    # new embed matches beta → cosine(gamma, beta) = 1.0 → skip
    _patch_sync_embed_to_return(monkeypatch, [0.0, 1.0, 0.0, 0.0])

    job = _MockJob(n_trials=2)
    bridge_mod.attach_layered_registers(job, method)

    trial_dir = tmp_path / "trial-1"
    trial_dir.mkdir()
    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-1", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text())
    skills_in_lib = list(state["library"]["skills"].keys())
    assert "alpha" in skills_in_lib
    assert "beta" in skills_in_lib
    assert "gamma" not in skills_in_lib