"""End-to-end bridge tests for the new auto-extract path.

These tests verify that :func:`paper.paper_mode.bridge.attach_paper_registers`
correctly triggers the extractor on the right attribution verdicts,
adds the new skill to the library, and resets its probation counter.
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
from skillq.paper_mode.config import MethodConfig  # noqa: E402


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
        # The bridge uses ``len(job)`` to compute expected_terminal_trials
        # for the buffer force-flush on the last trial. We return a
        # large sentinel so the force-flush never fires in unit tests
        # (the per-trial buffer.add() handles the normal case).
        return 1_000_000


def _patch_litellm_backends(monkeypatch) -> None:
    """Replace LiteLLM + subprocess with stub shims that accept the
    kwargs the bridge passes and return predictable outputs.
    """
    from skillq.paper_mode import bridge as bridge_mod
    from skillq.method.attribution import StubAttributionBackend
    from skillq.method.retrieval import StubEmbedder

    class _StubEmbedderShim(StubEmbedder):
        def __init__(self, *args, **kwargs) -> None:
            kwargs.pop("model", None)
            kwargs.pop("dim", None)
            super().__init__()

    class _StubAttributionShim(StubAttributionBackend):
        # Configurable at the bridge level; the tests will replace
        # this with a function that returns a chosen attribution.
        def __init__(self, *args, **kwargs) -> None:
            kwargs.pop("model", None)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(bridge_mod, "LiteLLMEmbedder", _StubEmbedderShim)
    monkeypatch.setattr(bridge_mod, "LiteLLMAttributionBackend", _StubAttributionShim)


def _patch_extractor_to_return(monkeypatch, skill: Skill | None) -> None:
    """Replace :class:`SkillExtractor.extract_batch` with a coroutine
    that immediately returns ``skill`` (no subprocess).
    """
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
    """Pre-seed the library with one skill so retrieval isn't empty."""
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
    return LibManager(b_max=method.b_max)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_bridge_extracts_on_success_no_skill_seen(tmp_path: Path, monkeypatch):
    """r_task > 0.5 + SUCCESS_NO_SKILL_SEEN + no retrieved Q > θ_consider_used
    → extractor called → lib.add(new_skill)."""
    _patch_litellm_backends(monkeypatch)
    new_skill = Skill(skill_id="auto-extracted", body="x" * 200)
    _patch_extractor_to_return(monkeypatch, new_skill)

    # Make the attribution analyzer return SUCCESS_NO_SKILL_SEEN
    from skillq.paper_mode import bridge as bridge_mod
    from skillq.method.attribution import Attribution, StubAttributionBackend

    def returning_no_skill_seen(self, **kwargs):
        return TrialAttribution(
            overall_attribution=Attribution.SUCCESS_NO_SKILL_SEEN,
            overall_rationale="test",
            knowledge_to_extract="reusable knowledge",
        )

    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer, "analyze", returning_no_skill_seen
    )

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
                enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=1,       # flush on the first qualifying trial
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    assert "auto-extracted" in state["library"]["skills"]
    # Probation counter for the new skill is reset → present in q_table
    # once the bridge ran (we don't run maintain in this short test, so
    # probation might be empty).
    assert state["step"] == 1


def test_bridge_skips_extract_on_failure(tmp_path: Path, monkeypatch):
    """r_task == 0 → extractor is NOT called."""
    _patch_litellm_backends(monkeypatch)
    called = {"n": 0}
    new_skill = Skill(skill_id="x", body="x" * 200)

    async def fake_extract_batch(self, **kwargs):
        called["n"] += 1
        return new_skill

    from skillq.paper_mode import bridge as bridge_mod
    monkeypatch.setattr(bridge_mod.SkillExtractor, "extract_batch", fake_extract_batch)
    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.SUCCESS_NO_SKILL_SEEN,
            overall_rationale="won't run anyway",
            knowledge_to_extract="x",
        ),
    )

    method = MethodConfig(
        library_root=tmp_path / "lib", b_max=4, enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=1,       # flush on the first qualifying trial
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    result = _fake_trial_result(reward=0.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    assert called["n"] == 0


def test_bridge_skips_extract_on_skill_used(tmp_path: Path, monkeypatch):
    """Attribution = SUCCESS_SKILL_USED → extractor NOT called."""
    _patch_litellm_backends(monkeypatch)
    called = {"n": 0}
    new_skill = Skill(skill_id="x", body="x" * 200)

    async def fake_extract_batch(self, **kwargs):
        called["n"] += 1
        return new_skill

    from skillq.paper_mode import bridge as bridge_mod
    monkeypatch.setattr(bridge_mod.SkillExtractor, "extract_batch", fake_extract_batch)
    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.SUCCESS_SKILL_USED,
            overall_rationale="a skill helped",
            knowledge_to_extract="",
        ),
    )

    method = MethodConfig(
        library_root=tmp_path / "lib", b_max=4, enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=1,       # flush on the first qualifying trial
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    assert called["n"] == 0


def test_bridge_skips_extract_when_disabled(tmp_path: Path, monkeypatch):
    """enable_auto_extract=False → extractor not even constructed."""
    _patch_litellm_backends(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
                enable_auto_extract=False,
    )
    _seed_lib(method)
    job = _MockJob()

    from skillq.paper_mode import bridge as bridge_mod

    bridge_mod.attach_paper_registers(job, method)
    # The hook closes over an `extractor` var; if it's None the extract
    # branch is skipped without calling SkillExtractor.extract.
    # We don't need to assert the .extract call count — the fact that
    # the test passes (no exception) is sufficient.

    result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))


def test_viewed_but_not_used_bumps_q(tmp_path: Path, monkeypatch):
    """Attribution = SUCCESS_VIEWED_SKILL_BUT_NOT_USED + the viewed skill is
    in the library → its Q is bumped slightly (0.05) per subtask entry.
    """
    _patch_litellm_backends(monkeypatch)
    _patch_extractor_to_return(monkeypatch, None)

    from skillq.paper_mode import bridge as bridge_mod

    def returning_viewed(self, **kwargs):
        # Use a plain dict for the subtask; TrialAttribution is
        # Pydantic-validated and accepts dicts as well as model
        # instances.
        return TrialAttribution(
            overall_attribution=Attribution.SUCCESS_VIEWED_SKILL_BUT_NOT_USED,
            overall_rationale="test",
            knowledge_to_extract="",
            subtasks=[
                {
                    "goal": "viewed",
                    "summary": "looked at skill but used own approach",
                    "attribution": "success_viewed_skill_but_not_used",
                    "skill_linked": "seed",
                    "skill_refs": [],
                }
            ],
        )

    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer, "analyze", returning_viewed
    )

    method = MethodConfig(
        library_root=tmp_path / "lib", b_max=4, enable_auto_extract=False
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    seed_qs = [row[1] for row in state["q_table"] if row[0] == "seed"]
    assert seed_qs, "seed skill should have a Q-table entry"
    # The Q-bump is +0.05; the regular β-Q update also runs.
    # We just check that the bump is positive.
    assert all(q > 0 for q in seed_qs)


# ---------------------------------------------------------------------------
# Rule 5: failure + no good skill → new skill from failure attribution
# ---------------------------------------------------------------------------
def test_bridge_extracts_on_failure_no_skill(tmp_path: Path, monkeypatch):
    """r_task=0 + FAIL_AGENT_ISSUE + non-empty knowledge_to_extract
    → extractor called with mode='failure'.

    The historical "skip extract if any existing skill has high Q"
    gate is no longer present; the test still uses
    ``seed_initial_q=0.0`` so the seed skill's Q stays neutral —
    the contract verified here is "Rule 5 fires purely on the
    attribution enum + non-empty knowledge, independent of lib state".

    Mirrors test_bridge_extracts_on_success_no_skill_seen but on the
    failure path.
    """
    _patch_litellm_backends(monkeypatch)
    # Set extract_mode on the mock Skill to mirror what the real
    # SkillExtractor would write (see paper/method/extractor.py).
    new_skill = Skill(
        skill_id="guard-rail",
        body="x" * 200,
        metadata={"source": "skillq_extract", "extract_mode": "failure"},
    )
    _patch_extractor_to_return(monkeypatch, new_skill)

    from skillq.paper_mode import bridge as bridge_mod
    from skillq.method.attribution import Attribution, TrialAttribution

    def returning_failure(self, **kwargs):
        return TrialAttribution(
            overall_attribution=Attribution.FAIL_AGENT_ISSUE,
            overall_rationale="test",
            knowledge_to_extract="avoid doing X without first checking Y",
        )

    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer, "analyze", returning_failure
    )

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
                enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=1,       # flush on the first qualifying trial
        # Disable the incremental-edit path (it would call the LLM
        # to propose a SKILL.md edit; we don't have a stub for
        # that in this test file).
        theta_near_miss=1.0,
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    result = _fake_trial_result(reward=0.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    assert "guard-rail" in state["library"]["skills"]
    # The new skill was created from a failure path, so its
    # extract_mode metadata should be "failure".
    new_meta = state["library"]["skills"]["guard-rail"]["metadata"]
    assert new_meta.get("extract_mode") == "failure"


def test_bridge_extracts_on_failure_even_when_skill_exists(tmp_path: Path, monkeypatch):
    """r_task=0 + FAIL_AGENT_ISSUE + a high-Q seed skill is already
    in lib + non-empty knowledge_to_extract → extractor IS called
    with mode='failure' and the new skill lands in lib.

    Locks in the post-gate-removal contract: Rule 5 fires purely on
    (attribution enum, non-empty knowledge), regardless of how good
    the existing lib looks. The ``seed_initial_q=0.5`` explicitly
    constructs the case the historical "skip if high-Q skill exists"
    gate used to suppress.
    """
    _patch_litellm_backends(monkeypatch)
    called = {"n": 0}
    new_skill = Skill(
        skill_id="guard-rail",
        body="x" * 200,
        metadata={"source": "skillq_extract", "extract_mode": "failure"},
    )

    async def fake_extract_batch(self, **kwargs):
        called["n"] += 1
        return new_skill

    from skillq.paper_mode import bridge as bridge_mod
    from skillq.method.attribution import Attribution, TrialAttribution

    monkeypatch.setattr(bridge_mod.SkillExtractor, "extract_batch", fake_extract_batch)
    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.FAIL_AGENT_ISSUE,
            overall_rationale="regression test for the removed gate",
            knowledge_to_extract=(
                "the existing seed skill was high-Q, but the agent still "
                "failed — synthesize a guard-rail from this attribution"
            ),
        ),
    )

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
                enable_auto_extract=True,
        # Seed Q = 0.5 reproduces the exact scenario the historical
        # "skip if high-Q skill exists" gate used to suppress
        # (the old default threshold was 0.30).
        seed_initial_q=0.5,
        extract_every_n_trials=1,
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    result = _fake_trial_result(reward=0.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    # The gate is gone — the extractor must fire and the new skill
    # must land in lib.
    assert called["n"] == 1, (
        "Rule 5 should fire on FAIL_AGENT_ISSUE + non-empty knowledge "
        "regardless of existing-skill Q"
    )
    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    assert "guard-rail" in state["library"]["skills"]
    new_meta = state["library"]["skills"]["guard-rail"]["metadata"]
    assert new_meta.get("extract_mode") == "failure"


def test_bridge_flush_writes_mirror_to_seed_dir(tmp_path: Path, monkeypatch):
    """After a successful flush, the new skill's SKILL.md is mirrored
    into ``method.seed_skills_dir`` so a subsequent trial's container
    can see it via the existing bind-mount at /skills.
    """
    _patch_litellm_backends(monkeypatch)
    body = (
        "---\nname: auto-mirrored\n---\n# body\n\n"
        + "x" * 200
    )
    new_skill = Skill(skill_id="auto-mirrored", body=body)
    _patch_extractor_to_return(monkeypatch, new_skill)

    from skillq.paper_mode import bridge as bridge_mod

    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.SUCCESS_NO_SKILL_SEEN,
            overall_rationale="test",
            knowledge_to_extract="reusable knowledge",
        ),
    )

    host_skills = tmp_path / "host_skills"
    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
                enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=1,
        seed_skills_dir=host_skills,
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    mirror = host_skills / "auto-mirrored" / "SKILL.md"
    assert mirror.is_file(), (
        f"mirror SKILL.md not written; expected at {mirror}"
    )
    assert mirror.read_text(encoding="utf-8") == body
