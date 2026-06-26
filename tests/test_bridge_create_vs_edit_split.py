"""Tests for the 2026-06-26 L3/L4 create-vs-edit split.

After this change the bridge routes trials based on attribution
enum:

  - r_task=1 + SUCCESS_NO_SKILL_SEEN     → Create (mode="success")
  - r_task=0 + FAILURE_SKILL_NOT_USED    → Create (mode="failure")
  - r_task=0 + FAILURE_SKILL_USED        → Edit (no Create)
  - r_task=1 + SUCCESS_SKILL_USED        → nothing
  - r_task=0 + FAIL_ENV_ISSUE            → nothing

The Q-update formula is unchanged (always runs); only the create
path and the edit path are gated on the enum.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
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
    def __init__(self) -> None:
        self.on_ended: Any = None
        self.config = SimpleNamespace(
            retry=SimpleNamespace(
                max_retries=0,
                exclude_exceptions=None,
                include_exceptions=None,
            )
        )

    def on_trial_ended(self, callback: Any) -> None:
        self.on_ended = callback

    def __len__(self) -> int:
        return 1_000_000


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
    # 2026-06-25+ : semantic dedup calls sync_embed at the bridge
    # boundary. Without a daemon reachable from the test env, that
    # call hangs for ~30s. Stub it to None so dedup falls open and
    # the test runs in <1s.
    monkeypatch.setattr(bridge_mod, "sync_embed", lambda **kwargs: None)


def _patch_attribution_to(monkeypatch, attribution: Attribution,
                          knowledge: str = "reusable knowledge"):
    """Force AttributionAnalyzer.analyze to return a fixed verdict."""
    from skillq.skillq_runtime import bridge as bridge_mod

    def returning(self, **kwargs):
        return TrialAttribution(
            overall_attribution=attribution,
            overall_rationale="test",
            knowledge_to_extract=knowledge,
        )

    monkeypatch.setattr(bridge_mod.AttributionAnalyzer, "analyze", returning)


def _patch_paths(monkeypatch) -> tuple[dict, dict]:
    """Patch SkillExtractor.extract_batch + EditRefiner.propose_edit to
    record calls. Returns (extract_calls, edit_calls) mutable dicts.

    Note: the bridge passes ``mode`` via the *prompt_mode* on the
    SkillExtractor instance (not as a kwarg to extract_batch). The
    extractor instance is created by ``_extractor_for_mode(mode)``
    inside ``_flush_buffer``; we therefore capture the mode by
    inspecting ``self.prompt_mode`` on the call.
    """
    from skillq.skillq_runtime import bridge as bridge_mod

    extract_calls: dict = {"n": 0, "modes": []}
    edit_calls: dict = {"n": 0, "skill_ids": []}

    async def fake_extract_batch(self, **kwargs):
        extract_calls["n"] += 1
        extract_calls["modes"].append(getattr(self, "prompt_mode", None))
        return Skill(skill_id="auto-extracted", body="x" * 200)

    def fake_propose_edit(self, skill, task, failure_trace):
        edit_calls["n"] += 1
        edit_calls["skill_ids"].append(skill.skill_id)
        return skill  # no-op edit

    monkeypatch.setattr(bridge_mod.SkillExtractor, "extract_batch", fake_extract_batch)
    monkeypatch.setattr(bridge_mod.EditRefiner, "propose_edit", fake_propose_edit)
    return extract_calls, edit_calls


def _seed_lib(method: MethodConfig) -> None:
    lib = Qlib(b_max=method.b_max)
    lib.add(Skill(skill_id="seed", body="# Seed\n\ndescription: pre-existing skill.\n"))
    state = QlibState(method.resolved_state_path())
    state.save(
        lib,
        LibManager(b_max=method.b_max),
        lib_root=method.library_root,
        seed_initial_q=method.seed_initial_q,
    )


def _run_trial(tmp_path: Path, method: MethodConfig, r_task: int) -> None:
    from skillq.skillq_runtime import bridge as bridge_mod

    trial_dir = tmp_path / "trial-x"
    trial_dir.mkdir()
    result = MagicMock()
    result.trial_uri = str(trial_dir)
    result.trial_name = "trial-x"
    result.task_name = "sample-task"
    result.exception_info = None
    result.verifier_result = MagicMock()
    result.verifier_result.rewards = {"reward": float(r_task)}

    event = MagicMock()
    event.event = "end"
    event.trial_id = "trial-x"
    event.task_name = "sample-task"
    event.result = result

    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)
    # Verify the bridge actually loaded the seeded lib (the edit
    # gate short-circuits on empty lib). If this fails, the seed
    # helper is broken — not the test.
    assert method.resolved_state_path().exists(), (
        f"state file not written at {method.resolved_state_path()}"
    )
    state_data = json.loads(
        method.resolved_state_path().read_text(encoding="utf-8")
    )
    seeded = state_data["library"]["skills"]
    assert len(seeded) >= 1, (
        f"seed helper produced empty lib: {seeded}"
    )
    asyncio.run(job.on_ended(event))


def _build_method(tmp_path: Path) -> MethodConfig:
    return MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=1,
    )


# ---------------------------------------------------------------------------
# Create path
# ---------------------------------------------------------------------------
def test_create_path_success_no_skill_seen(tmp_path, monkeypatch):
    """r_task=1 + SUCCESS_NO_SKILL_SEEN → extract fires, edit does not."""
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(monkeypatch, Attribution.SUCCESS_NO_SKILL_SEEN)
    extract_calls, edit_calls = _patch_paths(monkeypatch)

    method = _build_method(tmp_path)
    _seed_lib(method)
    _run_trial(tmp_path, method, r_task=1)

    assert extract_calls["n"] == 1
    assert extract_calls["modes"] == ["success"]
    assert edit_calls["n"] == 0


def test_create_path_failure_skill_not_used(tmp_path, monkeypatch):
    """r_task=0 + FAILURE_SKILL_NOT_USED → extract fires, edit does not."""
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(monkeypatch, Attribution.FAILURE_SKILL_NOT_USED)
    extract_calls, edit_calls = _patch_paths(monkeypatch)

    method = _build_method(tmp_path)
    _seed_lib(method)
    _run_trial(tmp_path, method, r_task=0)

    assert extract_calls["n"] == 1
    assert extract_calls["modes"] == ["failure"]
    assert edit_calls["n"] == 0


# ---------------------------------------------------------------------------
# Edit path
# ---------------------------------------------------------------------------
def test_edit_path_failure_skill_used(tmp_path, monkeypatch):
    """r_task=0 + FAILURE_SKILL_USED → extract does NOT fire, edit DOES.

    The new contract: a failed trial attributed to "the skill was
    used and the trial still failed" is the L3 Edit path. Create is
    intentionally skipped — adding a new skill would be redundant
    with editing the failing one.
    """
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(monkeypatch, Attribution.FAILURE_SKILL_USED)
    extract_calls, edit_calls = _patch_paths(monkeypatch)

    method = _build_method(tmp_path)
    _seed_lib(method)
    _run_trial(tmp_path, method, r_task=0)

    assert extract_calls["n"] == 0, (
        "FAILURE_SKILL_USED should NOT trigger create — the bridge "
        "should route to edit instead"
    )
    assert edit_calls["n"] >= 1, (
        "FAILURE_SKILL_USED should trigger edit on top-Q skill"
    )
    # The edit target is the highest-Q skill (only "seed" exists).
    assert "seed" in edit_calls["skill_ids"]


def test_edit_path_edits_top_q_skill(tmp_path, monkeypatch):
    """Edit path targets the highest-Q skill in the library."""
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(monkeypatch, Attribution.FAILURE_SKILL_USED)
    _, edit_calls = _patch_paths(monkeypatch)

    method = _build_method(tmp_path)
    # Seed with two skills; the bridge should pick the higher-Q one.
    lib = Qlib(b_max=method.b_max)
    lib.add(Skill(skill_id="alpha", body="# Alpha\n\ndescription: first.\n"))
    lib.add(Skill(skill_id="beta", body="# Beta\n\ndescription: second.\n"))
    mgr = LibManager(b_max=method.b_max)
    state = QlibState(method.resolved_state_path())
    state.save(lib, mgr, lib_root=method.library_root,
               seed_initial_q=method.seed_initial_q)
    # Manually push beta's Q higher than alpha's via set_q.
    mgr.set_q("alpha", 0.2)
    mgr.set_q("beta", 0.9)
    state.save(lib, mgr, lib_root=method.library_root,
               seed_initial_q=method.seed_initial_q)

    _run_trial(tmp_path, method, r_task=0)

    assert edit_calls["n"] >= 1
    assert edit_calls["skill_ids"][0] == "beta", (
        "edit should target the highest-Q skill (beta at 0.9, "
        "alpha at 0.2)"
    )


# ---------------------------------------------------------------------------
# No-op paths
# ---------------------------------------------------------------------------
def test_no_action_on_success_skill_used(tmp_path, monkeypatch):
    """r_task=1 + SUCCESS_SKILL_USED → neither path fires."""
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(monkeypatch, Attribution.SUCCESS_SKILL_USED)
    extract_calls, edit_calls = _patch_paths(monkeypatch)

    method = _build_method(tmp_path)
    _seed_lib(method)
    _run_trial(tmp_path, method, r_task=1)

    assert extract_calls["n"] == 0
    assert edit_calls["n"] == 0


def test_no_action_on_fail_env_issue(tmp_path, monkeypatch):
    """r_task=0 + FAIL_ENV_ISSUE → neither path fires."""
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(monkeypatch, Attribution.FAIL_ENV_ISSUE)
    extract_calls, edit_calls = _patch_paths(monkeypatch)

    method = _build_method(tmp_path)
    _seed_lib(method)
    _run_trial(tmp_path, method, r_task=0)

    assert extract_calls["n"] == 0
    assert edit_calls["n"] == 0


# ---------------------------------------------------------------------------
# Knowledge empty guard
# ---------------------------------------------------------------------------
def test_no_create_when_knowledge_empty(tmp_path, monkeypatch):
    """Even with SUCCESS_NO_SKILL_SEEN, empty knowledge skips Create."""
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(
        monkeypatch, Attribution.SUCCESS_NO_SKILL_SEEN, knowledge=""
    )
    extract_calls, _ = _patch_paths(monkeypatch)

    method = _build_method(tmp_path)
    _seed_lib(method)
    _run_trial(tmp_path, method, r_task=1)

    assert extract_calls["n"] == 0


def test_no_create_when_extractor_disabled(tmp_path, monkeypatch):
    """enable_auto_extract=False → Create path is dead, no extract calls."""
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(monkeypatch, Attribution.SUCCESS_NO_SKILL_SEEN)
    extract_calls, _ = _patch_paths(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=False,  # extractor not built at all
        seed_initial_q=0.0,
    )
    _seed_lib(method)
    _run_trial(tmp_path, method, r_task=1)

    assert extract_calls["n"] == 0


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------
def test_create_persists_new_skill_to_state(tmp_path, monkeypatch):
    """End-to-end: SUCCESS_NO_SKILL_SEEN + knowledge → state has new skill."""
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(monkeypatch, Attribution.SUCCESS_NO_SKILL_SEEN)
    _patch_paths(monkeypatch)

    method = _build_method(tmp_path)
    _seed_lib(method)
    _run_trial(tmp_path, method, r_task=1)

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    assert "auto-extracted" in state["library"]["skills"]
    assert "seed" in state["library"]["skills"]


# ---------------------------------------------------------------------------
# L3-H1: edited body must persist to method_state.json
# ---------------------------------------------------------------------------
def test_edit_path_persists_edited_body_to_method_state(tmp_path, monkeypatch):
    """H1: state.save must run AFTER the L3 edit so the post-edit
    body lands on disk. The seed skill's body on disk should
    contain the marker after on_ended completes.
    """
    from skillq.skillq_runtime import bridge as bridge_mod

    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(monkeypatch, Attribution.FAILURE_SKILL_USED)
    _patch_paths(monkeypatch)

    # Override the default no-op propose_edit with one that returns
    # a Skill whose body has a recognizable marker.
    marker = "-- EDITED BODY MARKER --"
    def marker_edit(self, skill, task, failure_trace):
        from skillq.method.types import Skill as _Skill
        return _Skill(
            skill_id=skill.skill_id,
            body=f"# Edited\n\ndescription: edited by L3.\n\n{marker}",
            n_retrievals=skill.n_retrievals,
            n_uses=skill.n_uses,
            n_success=skill.n_success,
            metadata=skill.metadata,
        )
    monkeypatch.setattr(bridge_mod.EditRefiner, "propose_edit", marker_edit)

    method = _build_method(tmp_path)
    _seed_lib(method)
    _run_trial(tmp_path, method, r_task=0)

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    assert marker in state["library"]["skills"]["seed"]["body"], (
        "method_state.json should contain the edited body — H1 fix "
        "re-orders step 5 (state.save) to run AFTER step 6 (L3 edit)"
    )


# ---------------------------------------------------------------------------
# L3-M3: propose_edit exception must not abort the trial
# ---------------------------------------------------------------------------
def test_l3_propose_edit_exception_does_not_abort_trial(tmp_path, monkeypatch):
    """M3: a transient LLM error in propose_edit must be caught
    by an inner try/except. state.save must still run, and
    method_errors.jsonl must NOT exist (inner catch, not outer).
    """
    from skillq.skillq_runtime import bridge as bridge_mod

    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(monkeypatch, Attribution.FAILURE_SKILL_USED)
    _patch_paths(monkeypatch)

    def boom(self, skill, task, failure_trace):
        raise RuntimeError("simulated transient LLM error")

    monkeypatch.setattr(bridge_mod.EditRefiner, "propose_edit", boom)

    method = _build_method(tmp_path)
    _seed_lib(method)
    _run_trial(tmp_path, method, r_task=0)

    # state.save ran: q_table.json mirror exists at the trial staging dir.
    q_path = tmp_path / "trial-x" / "skillq_state" / "q_table.json"
    assert q_path.exists(), (
        "q_table.json should exist — state.save ran after the L3 "
        "exception was caught by the inner try/except"
    )

    # Inner catch swallowed the error — the outer on_ended except did
    # NOT fire, so method_errors.jsonl should not exist.
    err_path = tmp_path / "trial-x" / "skillq_state" / "method_errors.jsonl"
    assert not err_path.exists(), (
        "method_errors.jsonl should NOT exist — the inner try/except "
        "caught the exception, not the outer on_ended handler"
    )