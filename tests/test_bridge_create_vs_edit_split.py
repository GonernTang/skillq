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

from skillq.layers.l3_attribution.models import Attribution, TrialAttribution  # noqa: E402
from skillq.shared.q_table import LibManager  # noqa: E402
from skillq.shared.library import QlibState  # noqa: E402
from skillq.shared.types import Qlib, Skill  # noqa: E402
from skillq.config import MethodConfig  # noqa: E402


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

    def on_trial_started(self, callback: Any) -> None:
        self.on_started = callback  # Step 7: new pipeline needs both

    def __len__(self) -> int:
        return 1_000_000


def _patch_litellm_backends(monkeypatch) -> None:
    from skillq.runtime import bridge as bridge_mod
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
    # 2026-06-29 (Step 6 migration): sync_embed lives in
    # skillq.services.ranking_service and is imported by
    # skillq.runtime.steps. Patch the steps import path; the daemon
    # is unreachable from this test env so the call would hang.
    # (2026-06-30: the bridge_mod patch is no longer needed —
    # bridge.py doesn't import sync_embed.)
    try:
        from skillq.runtime import steps as steps_mod
        monkeypatch.setattr(steps_mod, "sync_embed", lambda **kwargs: None)
    except ImportError:
        pass


def _patch_attribution_to(monkeypatch, attribution: Attribution,
                          knowledge: str = "reusable knowledge"):
    """Force AttributionAnalyzer.analyze to return a fixed verdict."""
    from skillq.runtime import bridge as bridge_mod

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

    2026-06-26 (L3-H3): propose_edit signature changed from
    (self, skill, task, failure_trace) to
    (self, skill, task, failure_diagnosis="", session_tail="").
    The default mock returns ``skill`` (no-op edit) and captures
    the new kwargs in ``edit_calls["diagnoses"]`` and
    ``edit_calls["tails"]`` for tests that want to inspect them.
    """
    from skillq.runtime import bridge as bridge_mod

    extract_calls: dict = {"n": 0, "modes": []}
    edit_calls: dict = {
        "n": 0,
        "skill_ids": [],
        "diagnoses": [],
        "tails": [],
    }

    async def fake_extract_batch(self, **kwargs):
        extract_calls["n"] += 1
        extract_calls["modes"].append(getattr(self, "prompt_mode", None))
        return Skill(skill_id="auto-extracted", body="x" * 200), None

    def fake_propose_edit(
        self, skill, task, failure_diagnosis="", session_tail="",
    ):
        edit_calls["n"] += 1
        edit_calls["skill_ids"].append(skill.skill_id)
        edit_calls["diagnoses"].append(failure_diagnosis)
        edit_calls["tails"].append(session_tail)
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
    from skillq.runtime import bridge as bridge_mod

    trial_dir = tmp_path / "trial-x"
    # exist_ok=True so H3 tests that pre-create trial_dir to seed
    # session jsonls don't get FileExistsError.
    trial_dir.mkdir(exist_ok=True)
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
    bridge_mod.attach_layered_registers(job, method)
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
    from skillq.runtime import bridge as bridge_mod

    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(monkeypatch, Attribution.FAILURE_SKILL_USED)
    _patch_paths(monkeypatch)

    # Override the default no-op propose_edit with one that returns
    # a Skill whose body has a recognizable marker.
    marker = "-- EDITED BODY MARKER --"
    def marker_edit(self, skill, task, failure_diagnosis="", session_tail=""):
        from skillq.shared.types import Skill as _Skill
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


def test_edit_path_mirrors_edited_body_to_seed_skills_dir(
    tmp_path, monkeypatch,
):
    """Phase 10 Bug 3 regression pin: L3 EditRefiner must mirror the
    edited body to ``seed_skills_dir`` so the next trial's container
    (which reads bind-mounted ``/skills``) sees the new body, not
    the seed body or L3's prior write. Without this mirror, the
    in-memory lib is correct but the bind-mount view is stale and
    every subsequent L3 edit silently never lands on disk.
    """
    from skillq.runtime import bridge as bridge_mod

    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(monkeypatch, Attribution.FAILURE_SKILL_USED)
    _patch_paths(monkeypatch)

    marker = "-- L3 MIRROR MARKER --"
    def marker_edit(self, skill, task, failure_diagnosis="", session_tail=""):
        from skillq.shared.types import Skill as _Skill
        return _Skill(
            skill_id=skill.skill_id,
            body=f"# L3-mirrored body\n\n{marker}",
            n_retrievals=skill.n_retrievals,
            n_uses=skill.n_uses,
            n_success=skill.n_success,
            metadata=skill.metadata,
        )
    monkeypatch.setattr(bridge_mod.EditRefiner, "propose_edit", marker_edit)

    # Build a method with an explicit seed_skills_dir and pre-create
    # the seed SKILL.md so the mirror's force=True path is exercised
    # (the file already exists from the seed scan).
    seed_dir = tmp_path / "seed_skills"
    seed_dir.mkdir()
    (seed_dir / "seed").mkdir()
    seed_md = seed_dir / "seed" / "SKILL.md"
    seed_md.write_text("# ORIGINAL seed body\n", encoding="utf-8")

    method = MethodConfig(
        library_root=tmp_path / "lib",
        seed_skills_dir=seed_dir,
        b_max=4,
        enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=1,
    )
    _seed_lib(method)
    _run_trial(tmp_path, method, r_task=0)

    # After on_ended, the seed_skills_dir SKILL.md must contain the
    # *edited* body, not the original seed body. This proves the
    # mirror call (with force=True) actually ran and overwrote the
    # pre-existing file.
    on_disk = seed_md.read_text(encoding="utf-8")
    assert marker in on_disk, (
        f"L3 mirror failed: seed_skills_dir SKILL.md still shows the "
        f"original seed body, not the L3 edit. Got:\n{on_disk[:200]}"
    )
    assert "# ORIGINAL seed body" not in on_disk, (
        "L3 mirror fell through to the idempotent-skip path; the file "
        "was NOT overwritten despite force=True. Bug 3 is not fixed."
    )


# ---------------------------------------------------------------------------
# L3-M3: propose_edit exception must not abort the trial
# ---------------------------------------------------------------------------
def test_l3_propose_edit_exception_does_not_abort_trial(tmp_path, monkeypatch):
    """M3: a transient LLM error in propose_edit must be caught
    by an inner try/except. state.save must still run, and
    method_errors.jsonl must NOT exist (inner catch, not outer).
    """
    from skillq.runtime import bridge as bridge_mod

    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(monkeypatch, Attribution.FAILURE_SKILL_USED)
    _patch_paths(monkeypatch)

    def boom(self, skill, task, failure_diagnosis="", session_tail=""):
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


# ---------------------------------------------------------------------------
# L3-H2: L3 fires even when L4 (auto_extract) is disabled
# ---------------------------------------------------------------------------
def test_l3_fires_when_extractor_disabled(tmp_path, monkeypatch):
    """H2: enable_auto_extract=False must NOT disable L3. The
    attribution analyzer must still run (for step 5★ to gate on
    FAILURE_SKILL_USED), only the L4 buffer.add is gated on
    extractor. With FAILURE_SKILL_USED + extractor disabled, edit
    fires, no extract.
    """
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(monkeypatch, Attribution.FAILURE_SKILL_USED)
    extract_calls, edit_calls = _patch_paths(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=False,  # L4 disabled
        seed_initial_q=0.0,
        extract_every_n_trials=1,
    )
    _seed_lib(method)
    _run_trial(tmp_path, method, r_task=0)

    # L3 must fire (FAILURE_SKILL_USED + lib non-empty).
    assert edit_calls["n"] >= 1, (
        "L3 edit should fire even when enable_auto_extract=False — "
        "H2 fix decoupled attribution analyzer from L4 extractor"
    )
    # L4 must NOT fire (extractor is None).
    assert extract_calls["n"] == 0


def test_no_l3_when_attribution_not_skill_used_with_extractor_disabled(
    tmp_path, monkeypatch,
):
    """H2 negative: with enable_auto_extract=False AND
    attribution == FAILURE_SKILL_NOT_USED (a gap signal, not a
    skill-at-fault signal), neither path should fire.
    """
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(monkeypatch, Attribution.FAILURE_SKILL_NOT_USED)
    extract_calls, edit_calls = _patch_paths(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=False,
        seed_initial_q=0.0,
        extract_every_n_trials=1,
    )
    _seed_lib(method)
    _run_trial(tmp_path, method, r_task=0)

    assert edit_calls["n"] == 0, (
        "L3 must not fire for FAILURE_SKILL_NOT_USED — the gate is "
        "FAILURE_SKILL_USED only"
    )
    assert extract_calls["n"] == 0, (
        "L4 must not fire when extractor is None"
    )


# ---------------------------------------------------------------------------
# L3-H3: failure trace threading (diagnosis + session_tail)
# ---------------------------------------------------------------------------
def test_edit_path_threads_diagnosis_to_propose_edit(tmp_path, monkeypatch):
    """H3 (1/5): the diagnosis kwarg passed to propose_edit must
    contain the analyzer's knowledge_to_extract and the
    library_gap_skill_description. It must NOT contain
    overall_attribution (a known constant at this point) or
    overall_rationale (noise / irrelevant for the edit prompt).
    """
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(
        monkeypatch,
        Attribution.FAILURE_SKILL_USED,
        knowledge="skill forgot chmod +x the binary",
    )
    _, edit_calls = _patch_paths(monkeypatch)

    method = _build_method(tmp_path)
    _seed_lib(method)
    _run_trial(tmp_path, method, r_task=0)

    diag = edit_calls["diagnoses"][-1]
    assert "knowledge_to_extract" in diag
    assert "skill forgot chmod +x the binary" in diag
    # Field-pruning: overall_attribution and overall_rationale must
    # NOT be in the diagnosis (they're noise at this point).
    assert "overall_attribution" not in diag
    assert "overall_rationale" not in diag


def test_edit_path_threads_session_tail_to_propose_edit(tmp_path, monkeypatch):
    """H3 (2/5): k=3 boundary. Write 8 assistant messages in the
    session log; assert propose_edit receives only the LAST 3
    (MSG-3 through MSG-8, NOT MSG-1/MSG-2).
    """
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(monkeypatch, Attribution.FAILURE_SKILL_USED)
    _, edit_calls = _patch_paths(monkeypatch)

    method = _build_method(tmp_path)
    _seed_lib(method)
    # Pre-create the trial dir so we can write the session jsonl
    # before _run_trial fires on_ended.
    trial_dir = tmp_path / "trial-x"
    trial_dir.mkdir()
    session_dir = (
        trial_dir / "agent" / "sessions" / "projects" / "fake-proj"
    )
    session_dir.mkdir(parents=True)
    jsonl_path = session_dir / "fake-session.jsonl"
    lines = []
    for i in range(1, 9):  # 8 messages: MSG-1 .. MSG-8
        lines.append(json.dumps({
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": f"MSG-{i} content"}],
            },
        }))
    jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    _run_trial(tmp_path, method, r_task=0)

    tail = edit_calls["tails"][-1]
    # Last 3 included (MSG-6, MSG-7, MSG-8).
    for i in (6, 7, 8):
        assert f"MSG-{i} content" in tail, (
            f"MSG-{i} should be in the k=3 tail"
        )
    # First 5 NOT included.
    for i in (1, 2, 3, 4, 5):
        assert f"MSG-{i} content" not in tail, (
            f"MSG-{i} should be outside the k=3 tail"
        )


def test_edit_path_no_session_log_still_fires(tmp_path, monkeypatch):
    """H3 (3/5): graceful degradation. No agent/sessions/ dir →
    session_tail="" but diagnosis still populated; edit fires.
    """
    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(
        monkeypatch,
        Attribution.FAILURE_SKILL_USED,
        knowledge="some diagnosis",
    )
    _, edit_calls = _patch_paths(monkeypatch)

    method = _build_method(tmp_path)
    _seed_lib(method)
    _run_trial(tmp_path, method, r_task=0)

    assert edit_calls["n"] >= 1
    assert edit_calls["tails"][-1] == "", (
        "missing sessions dir should yield empty tail, not crash"
    )
    assert edit_calls["diagnoses"][-1] != "", (
        "diagnosis must still be populated even when session log is missing"
    )


def test_edit_prompt_contains_diagnosis_label(tmp_path, monkeypatch):
    """H3 (4/5): EDIT_PROMPT rewrite actually uses the new
    placeholders. The formatted prompt sent to the backend must
    contain "FAILURE DIAGNOSIS" and "knowledge_to_extract".
    """
    from skillq.runtime import bridge as bridge_mod

    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(
        monkeypatch,
        Attribution.FAILURE_SKILL_USED,
        knowledge="skill forgot chmod +x",
    )
    _, _ = _patch_paths(monkeypatch)

    captured: dict = {"prompt": None}

    def capture_edit(self, skill, task, failure_diagnosis="", session_tail=""):
        from skillq.layers.l3_attribution.prompts import EDIT_PROMPT
        prompt = EDIT_PROMPT.format(
            task=task,
            diagnosis=failure_diagnosis[: 6000 // 2],
            tail=session_tail[: 6000 // 2],
            tail_k=3,
            old_skill=skill.body,
        )
        captured["prompt"] = prompt
        # Return a body that differs from original (passes no-op check).
        return Skill(
            skill_id=skill.skill_id,
            body=skill.body + "\n<!-- edited -->\n",
            n_retrievals=skill.n_retrievals,
            n_uses=skill.n_uses,
            n_success=skill.n_success,
            metadata=skill.metadata,
        )

    monkeypatch.setattr(bridge_mod.EditRefiner, "propose_edit", capture_edit)

    method = _build_method(tmp_path)
    _seed_lib(method)
    _run_trial(tmp_path, method, r_task=0)

    assert captured["prompt"] is not None
    assert "FAILURE DIAGNOSIS" in captured["prompt"]
    assert "knowledge_to_extract" in captured["prompt"]


def test_edit_prompt_drops_20pct_token_cap(tmp_path, monkeypatch):
    """H3 (5/5): the stale 20% token cap (already removed from
    edit.py:73-77 since 2026-06-25) must also be gone from
    EDIT_PROMPT — they're now consistent.
    """
    from skillq.runtime import bridge as bridge_mod

    _patch_litellm_backends(monkeypatch)
    _patch_attribution_to(monkeypatch, Attribution.FAILURE_SKILL_USED)
    _, _ = _patch_paths(monkeypatch)

    captured: dict = {"prompt": None}

    def capture_edit(self, skill, task, failure_diagnosis="", session_tail=""):
        from skillq.layers.l3_attribution.prompts import EDIT_PROMPT
        prompt = EDIT_PROMPT.format(
            task=task,
            diagnosis=failure_diagnosis[: 6000 // 2],
            tail=session_tail[: 6000 // 2],
            tail_k=3,
            old_skill=skill.body,
        )
        captured["prompt"] = prompt
        return Skill(
            skill_id=skill.skill_id,
            body=skill.body + "\n<!-- edited -->\n",
            n_retrievals=skill.n_retrievals,
            n_uses=skill.n_uses,
            n_success=skill.n_success,
            metadata=skill.metadata,
        )

    monkeypatch.setattr(bridge_mod.EditRefiner, "propose_edit", capture_edit)

    method = _build_method(tmp_path)
    _seed_lib(method)
    _run_trial(tmp_path, method, r_task=0)

    assert captured["prompt"] is not None
    assert "20% of the original token count" not in captured["prompt"]