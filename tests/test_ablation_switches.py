"""Tests for the 7 ablation switches added to ``MethodConfig`` and the
pipeline steps in ``skillq.runtime.steps`` / ``skillq.runtime.env_seed``.

The switches (all default ``True``):

- ``enable_retrieval`` — gates Layer 1 retrieval env seeding
  (``seed_agent_env``). When False, the agent container gets no
  retrieval tunables (the hook falls back to inert defaults).
- ``enable_q_retrieval`` — gates the Q-influence on retrieval scoring.
  When False, ``SKILLQ_HOOK_MULT_BETA`` / ``SKILLQ_HOOK_MULT_GAMMA`` /
  ``SKILLQ_HOOK_C_UCB`` are zeroed so Q / UCB cannot promote skills.
- ``enable_q_learning`` — gates the Eq.5 Q-update step
  (:func:`step_q_update`). When False, no Q-values change.
- ``enable_attribution`` — gates the L3 attribution LLM call
  (:func:`step_attribute`). When False, the step returns without
  calling the analyzer.
- ``enable_skill_edit`` — gates the L3 in-place edit
  (:func:`step_incremental_edit`). When False, no skill body is
  rewritten.
- ``enable_success_skill_create`` — gates the L4 Rule 2 (success path)
  skill creation in :func:`step_dispatch_evolve`.
- ``enable_failure_skill_create`` — gates the L4 Rule 5 (failure path)
  skill creation in :func:`step_dispatch_evolve`.

These tests are written ahead of the implementation (TDD): they pin
the contract the code agent must satisfy. Tests that touch a
``MethodConfig`` field not yet declared will fail at collection /
runtime until the field lands; each such test is marked with a
``pytest.skip`` guard that detects the missing attribute and notes
which tests can't run yet.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.config import MethodConfig  # noqa: E402
from skillq.layers.l3_attribution.models import (  # noqa: E402
    Attribution,
    DiagnosisStatus,
    SkillUsageAssessment,
    SkillUsageStatus,
    TrialAttribution,
)
from skillq.runtime import steps as steps_mod  # noqa: E402
from skillq.runtime.context import StepResult, TrialContext  # noqa: E402
from skillq.runtime.env_seed import seed_agent_env  # noqa: E402
from skillq.shared.types import Skill  # noqa: E402

SWITCH_NAMES = (
    "enable_retrieval",
    "enable_q_retrieval",
    "enable_q_learning",
    "enable_attribution",
    "enable_skill_edit",
    "enable_success_skill_create",
    "enable_failure_skill_create",
)


def _switches_present() -> bool:
    """True iff all 7 ablation switches are declared on MethodConfig.

    Used to skip tests that require the fields to exist; the code
    agent implementing the switches will make this return True.
    """
    return all(hasattr(MethodConfig(), name) for name in SWITCH_NAMES)


def _set_switch(method: MethodConfig, name: str, value: bool) -> None:
    """Set an ablation switch on a MethodConfig, working whether or
    not the field is formally declared yet (bypasses pydantic
    validation via object.__setattr__).
    """
    object.__setattr__(method, name, value)


# ---------------------------------------------------------------------------
# Minimal JobConfig stub for seed_agent_env (mirrors test_env_seed_calls_log_path)
# ---------------------------------------------------------------------------
class _AgentCfg:
    def __init__(self) -> None:
        self.env: dict[str, str] | None = None


class _JobCfg:
    def __init__(self) -> None:
        self.agents = [_AgentCfg()]


# ---------------------------------------------------------------------------
# Mock MethodConfig for step tests — carries every attribute the step
# functions read, plus the 7 ablation switches.
# ---------------------------------------------------------------------------
class MockMethod:
    """Minimal stand-in for MethodConfig used by the step tests.

    Only the attributes the steps actually touch are populated; the
    7 ablation switches default to True and can be overridden via
    kwargs.
    """

    def __init__(self, **kwargs: Any) -> None:
        # Defaults that the steps read.
        self.hook_top_k = 3
        self.hook_lambda = 0.5
        self.hook_c_ucb = 0.0
        self.hook_score_mode = "multiplicative"
        self.hook_multiplicative_beta = 0.5
        self.hook_multiplicative_gamma = 0.2
        self.hook_pull_top_k = 3
        self.hook_embedding_service_port = 8765
        self.sim_gate_min_score = 0.7
        self.sim_gate_floor = 0
        self.hook_rank_timeout_sec = 5.0
        self.retrieval_mode = "pull"
        self.q_alpha = 0.3
        self.q_update_cosine_weight = False
        self.b_max = 8
        self.seed_initial_q = 0.5
        self.new_skill_initial_q = 0.5
        self.embedder_model = "openai/text-embedding-3-small"
        self.embedder_dim = 1536
        self.seed_skills_dir = None
        self.library_root = Path("./.skillq_library")
        self.enable_auto_extract = False
        self.extract_every_n_trials = 4
        self.enforce_failure_skill_structure = True
        # 7 ablation switches — default True.
        self.enable_retrieval = True
        self.enable_q_retrieval = True
        self.enable_q_learning = True
        self.enable_attribution = True
        self.enable_skill_edit = True
        self.enable_success_skill_create = True
        self.enable_failure_skill_create = True
        for k, v in kwargs.items():
            setattr(self, k, v)


def _build_ctx(
    tmp_path: Path,
    method: Any | None = None,
    *,
    r_task: int = 0,
    intent_text: str = "test-intent",
    trial_id: str = "trial-1",
    lib_skills: list[str] | None = None,
    attribution: TrialAttribution | None = None,
) -> tuple[TrialContext, StepResult]:
    """Build a TrialContext + StepResult wired with MagicMock services.

    Returns ``(ctx, result)``. The services bag is a MagicMock with the
    concrete ``method`` (MockMethod) attached so step functions can read
    real switch values while everything else stays a mock.
    """
    if method is None:
        method = MockMethod()

    services = MagicMock()
    services.method = method
    services.expected_terminal_trials = 10

    # lib: a MagicMock supporting ``in`` / ``.get`` / ``.skills`` / ``.replace`` / ``.add``.
    lib = MagicMock()
    lib.skills = {}
    if lib_skills:
        for sid in lib_skills:
            sk = MagicMock()
            sk.skill_id = sid
            sk.body = f"body-{sid}"
            sk.n_retrievals = 0
            sk.n_uses = 0
            sk.n_success = 0
            lib.skills[sid] = sk
            lib.__contains__ = lambda self, s, _skills=lib.skills: s in _skills
    lib.__contains__ = lambda self, s, _skills=lib.skills: s in _skills
    services.lib = lib

    # mgr: MagicMock Q-table manager.
    mgr = MagicMock()
    mgr.q_table = {}
    mgr.q_for = MagicMock(return_value=0.5)
    mgr.update_q = MagicMock()
    mgr.set_q = MagicMock()
    services.mgr = mgr

    # emb_cache
    emb_cache = MagicMock()
    emb_cache.get = MagicMock(return_value=None)
    services.emb_cache = emb_cache

    # state
    state = MagicMock()
    state.step = 0
    services.state = state

    # attribution_analyzer
    services.attribution_analyzer = MagicMock()

    # refiner
    services.refiner = MagicMock()

    # extractor
    services.extractor = MagicMock()
    services.extract_buffer = MagicMock()

    ctx = TrialContext(
        trial_id=trial_id,
        trial_dir=tmp_path,
        intent_text=intent_text,
        r_task=r_task,
        services=services,
        event=MagicMock(),
    )
    result = StepResult()
    if attribution is not None:
        result.attribution = attribution
    return ctx, result


# ===========================================================================
# Test 1: all switches default to True
# ===========================================================================
def test_all_switches_default_true():
    """All 7 ablation switches default to True on MethodConfig."""
    if not _switches_present():
        pytest.skip(
            "Ablation switches not yet declared on MethodConfig; "
            "test_all_switches_default_true cannot run until the code "
            "agent adds the 7 fields."
        )
    m = MethodConfig()
    for name in SWITCH_NAMES:
        assert getattr(m, name) is True, f"{name} should default to True"


# ===========================================================================
# Test 2: enable_retrieval=False → seed_agent_env sets only
# SKILLQ_PULL_TOP_K="0" and no other SKILLQ_* vars
# ===========================================================================
def test_enable_retrieval_skips_env_seed(tmp_path: Path):
    """When ``enable_retrieval=False``, ``seed_agent_env`` must seed
    only ``SKILLQ_PULL_TOP_K="0"`` (disabling pull injection) and no
    other ``SKILLQ_*`` tunables — the agent container runs without the
    retrieval hook's scoring params.
    """
    if not _switches_present():
        pytest.skip(
            "enable_retrieval not yet declared on MethodConfig; "
            "test_enable_retrieval_skips_env_seed cannot run until "
            "the code agent adds the field + the early-return in "
            "seed_agent_env."
        )
    method = MethodConfig(library_root=tmp_path)
    _set_switch(method, "enable_retrieval", False)
    job_cfg = _JobCfg()
    seed_agent_env(job_cfg, method, wiring=None)

    env = job_cfg.agents[0].env
    skillq_vars = {k: v for k, v in env.items() if k.startswith("SKILLQ_")}
    assert skillq_vars == {"SKILLQ_PULL_TOP_K": "0"}, (
        f"enable_retrieval=False should seed only SKILLQ_PULL_TOP_K='0'; "
        f"got {skillq_vars}"
    )


# ===========================================================================
# Test 3: enable_q_retrieval=False → beta/gamma/c_ucb zeroed
# ===========================================================================
def test_enable_q_retrieval_zeroes_params(tmp_path: Path):
    """When ``enable_q_retrieval=False``, the Q/UCB influence on
    retrieval scoring is neutralised: ``SKILLQ_HOOK_MULT_BETA``,
    ``SKILLQ_HOOK_MULT_GAMMA``, and ``SKILLQ_HOOK_C_UCB`` are all
    seeded as ``"0.000000"``.
    """
    if not _switches_present():
        pytest.skip(
            "enable_q_retrieval not yet declared on MethodConfig; "
            "test_enable_q_retrieval_zeroes_params cannot run until "
            "the code agent adds the field + the zeroing in "
            "seed_agent_env."
        )
    method = MethodConfig(
        library_root=tmp_path,
        hook_multiplicative_beta=0.5,
        hook_multiplicative_gamma=0.2,
        hook_c_ucb=0.3,
    )
    _set_switch(method, "enable_q_retrieval", False)
    job_cfg = _JobCfg()
    seed_agent_env(job_cfg, method, wiring=None)

    env = job_cfg.agents[0].env
    assert env["SKILLQ_HOOK_MULT_BETA"] == "0.000000", env
    assert env["SKILLQ_HOOK_MULT_GAMMA"] == "0.000000", env
    assert env["SKILLQ_HOOK_C_UCB"] == "0.000000", env


# ===========================================================================
# Test 4: enable_q_learning=False → step_q_update skips
# ===========================================================================
def test_enable_q_learning_false_skips_update(tmp_path: Path, monkeypatch):
    """When ``enable_q_learning=False``, :func:`step_q_update` must
    perform no Q-updates even when the calls log records approved
    Skill() calls.
    """
    # Patch the calls-log reader to return one approved call so the
    # step would normally fire an update.
    fake_call = MagicMock()
    fake_call.skill_id = "skill-a"
    fake_call.denied = False
    fake_call.intent_text = "do-thing"
    monkeypatch.setattr(
        steps_mod, "_read_skill_calls_log", lambda *_a, **_k: [fake_call]
    )
    # lib contains the called skill so the by_skill loop would proceed.
    method = MockMethod(enable_q_learning=False)
    ctx, result = _build_ctx(tmp_path, method=method, r_task=1, lib_skills=["skill-a"])

    asyncio.run(steps_mod.step_q_update(ctx, result))

    assert result.q_updates == [], (
        "enable_q_learning=False must produce no Q-update entries"
    )
    ctx.services.mgr.update_q.assert_not_called()


# ===========================================================================
# Test 5: enable_attribution=False → step_attribute skips the LLM call
# ===========================================================================
def test_enable_attribution_false_skips_llm(tmp_path: Path, monkeypatch):
    """When ``enable_attribution=False``, :func:`step_attribute` must
    return without invoking the attribution analyzer (no LLM call).
    """
    monkeypatch.setattr(steps_mod, "_read_skill_calls_log", lambda *_a, **_k: [])
    method = MockMethod(enable_attribution=False)
    ctx, result = _build_ctx(tmp_path, method=method, r_task=0)

    asyncio.run(steps_mod.step_attribute(ctx, result))

    ctx.services.attribution_analyzer.analyze.assert_not_called()


# ===========================================================================
# Test 6: enable_skill_edit=False → step_incremental_edit returns early
# ===========================================================================
def test_enable_skill_edit_false_skips_edit(tmp_path: Path, monkeypatch):
    """When ``enable_skill_edit=False``, :func:`step_incremental_edit`
    must return early — the refiner is never invoked and no skill body
    is replaced.
    """
    monkeypatch.setattr(steps_mod, "_read_skill_calls_log", lambda *_a, **_k: [])
    method = MockMethod(enable_skill_edit=False)
    attribution = TrialAttribution(
        overall_attribution=Attribution.FAILURE_SKILL_USED,
        overall_rationale="test",
        knowledge_to_extract="some knowledge",
    )
    ctx, result = _build_ctx(
        tmp_path,
        method=method,
        r_task=0,
        lib_skills=["skill-a"],
        attribution=attribution,
    )

    asyncio.run(steps_mod.step_incremental_edit(ctx, result))

    ctx.services.refiner.propose_edit.assert_not_called()
    assert result.edited_skill_id is None


# ===========================================================================
# Test 7: enable_success_skill_create=False → Rule 2 skipped
# ===========================================================================
def test_enable_success_skill_create_false(tmp_path: Path, monkeypatch):
    """When ``enable_success_skill_create=False`` and the attribution
    is ``SUCCESS_NO_SKILL_SEEN``, :func:`step_dispatch_evolve` must
    NOT add to the extract buffer (Rule 2 disabled).
    """
    monkeypatch.setattr(steps_mod, "_read_skill_calls_log", lambda *_a, **_k: [])
    method = MockMethod(enable_success_skill_create=False)
    attribution = TrialAttribution(
        overall_attribution=Attribution.SUCCESS_NO_SKILL_SEEN,
        overall_rationale="test",
        knowledge_to_extract="harvestable knowledge",
        diagnosis_status=DiagnosisStatus.ACTIONABLE,
        diagnosis_confidence=0.95,
    )
    ctx, result = _build_ctx(
        tmp_path, method=method, r_task=1, attribution=attribution
    )

    asyncio.run(steps_mod.step_dispatch_evolve(ctx, result))

    ctx.services.extract_buffer.add.assert_not_called()
    assert result.dispatched_mode is None


# ===========================================================================
# Test 8: enable_failure_skill_create=False → Rule 5 skipped
# ===========================================================================
def test_enable_failure_skill_create_false(tmp_path: Path, monkeypatch):
    """When ``enable_failure_skill_create=False`` and the attribution
    is ``FAILURE_SKILL_NOT_USED``, :func:`step_dispatch_evolve` must
    NOT add to the extract buffer (Rule 5 disabled).
    """
    monkeypatch.setattr(steps_mod, "_read_skill_calls_log", lambda *_a, **_k: [])
    method = MockMethod(enable_failure_skill_create=False)
    attribution = TrialAttribution(
        overall_attribution=Attribution.FAILURE_SKILL_NOT_USED,
        overall_rationale="test",
        knowledge_to_extract="harvestable knowledge",
        diagnosis_status=DiagnosisStatus.ACTIONABLE,
        diagnosis_confidence=0.95,
    )
    ctx, result = _build_ctx(
        tmp_path, method=method, r_task=0, attribution=attribution
    )

    asyncio.run(steps_mod.step_dispatch_evolve(ctx, result))

    ctx.services.extract_buffer.add.assert_not_called()
    assert result.dispatched_mode is None


# ===========================================================================
# Test 9: all switches True → steps run normally (smoke test)
# ===========================================================================
def test_all_enabled_runs_normally(tmp_path: Path, monkeypatch):
    """With all 7 switches True, the gated steps execute their normal
    path without short-circuiting on the ablation guard. Smoke test:
    each step completes without raising.
    """
    fake_call = MagicMock()
    fake_call.skill_id = "skill-a"
    fake_call.denied = False
    fake_call.intent_text = "do-thing"
    monkeypatch.setattr(
        steps_mod, "_read_skill_calls_log", lambda *_a, **_k: [fake_call]
    )
    method = MockMethod()  # all switches True
    attribution = TrialAttribution(
        overall_attribution=Attribution.SUCCESS_NO_SKILL_SEEN,
        overall_rationale="test",
        knowledge_to_extract="harvestable knowledge",
        diagnosis_status=DiagnosisStatus.ACTIONABLE,
        diagnosis_confidence=0.95,
    )
    ctx, result = _build_ctx(
        tmp_path,
        method=method,
        r_task=1,
        lib_skills=["skill-a"],
        attribution=attribution,
    )

    # step_q_update should produce an update entry (switch on).
    asyncio.run(steps_mod.step_q_update(ctx, result))
    assert result.q_updates != [], (
        "With enable_q_learning=True, step_q_update should record updates"
    )

    # step_dispatch_evolve should buffer a success record (switch on).
    # Re-patch the calls log to empty so the enum_override guard
    # (which skips L4 when calls_log contradicts SUCCESS_NO_SKILL_SEEN)
    # does not fire — we want the normal Rule 2 buffering path.
    monkeypatch.setattr(steps_mod, "_read_skill_calls_log", lambda *_a, **_k: [])
    ctx.services.extract_buffer.add = MagicMock(return_value=False)
    asyncio.run(steps_mod.step_dispatch_evolve(ctx, result))
    ctx.services.extract_buffer.add.assert_called_once()
    assert result.dispatched_mode == "success"


# ===========================================================================
# Test 10: enable_retrieval=False → no AssertionError from the
# SKILLQ_RANK_ENDPOINT post-condition assert
# ===========================================================================
def test_enable_retrieval_false_env_seed_assert_safe(tmp_path: Path):
    """When ``enable_retrieval=False``, :func:`seed_agent_env` must
    return BEFORE the ``SKILLQ_RANK_ENDPOINT`` post-condition assert
    fires — so no ``AssertionError`` is raised even though the rank
    endpoint was never seeded.
    """
    if not _switches_present():
        pytest.skip(
            "enable_retrieval not yet declared on MethodConfig; "
            "test_enable_retrieval_false_env_seed_assert_safe cannot "
            "run until the code agent adds the field + the early-return "
            "in seed_agent_env."
        )
    method = MethodConfig(library_root=tmp_path)
    _set_switch(method, "enable_retrieval", False)
    job_cfg = _JobCfg()

    # Must not raise.
    seed_agent_env(job_cfg, method, wiring=None)

    env = job_cfg.agents[0].env
    # The rank endpoint assert was skipped, so it is absent.
    assert "SKILLQ_RANK_ENDPOINT" not in env, (
        "enable_retrieval=False should return before the RANK_ENDPOINT "
        "assert; the var should not be seeded."
    )


@pytest.mark.parametrize(
    ("r_task", "attribution_enum", "mode"),
    [
        (1, Attribution.SUCCESS_NO_SKILL_SEEN, "success"),
        (0, Attribution.FAILURE_SKILL_NOT_USED, "failure"),
    ],
)
def test_create_paths_ignore_diagnosis_confidence(
    tmp_path: Path,
    monkeypatch,
    r_task: int,
    attribution_enum: Attribution,
    mode: str,
):
    """No-skill create rules dispatch despite a low-confidence diagnosis."""
    monkeypatch.setattr(steps_mod, "_read_skill_calls_log", lambda *_a, **_k: [])
    attribution = TrialAttribution(
        overall_attribution=attribution_enum,
        overall_rationale="trace has reusable knowledge",
        knowledge_to_extract="harvestable workflow",
        diagnosis_status=DiagnosisStatus.INSUFFICIENT_EVIDENCE,
        diagnosis_confidence=0.0,
    )
    ctx, result = _build_ctx(
        tmp_path, method=MockMethod(), r_task=r_task, attribution=attribution
    )
    ctx.services.extract_buffer.add = MagicMock(return_value=False)

    asyncio.run(steps_mod.step_dispatch_evolve(ctx, result))

    ctx.services.extract_buffer.add.assert_called_once()
    assert result.dispatched_mode == mode


@pytest.mark.parametrize(
    ("confidence", "should_edit"),
    [(0.6, True), (0.59, False)],
)
def test_failure_skill_edit_uses_point_six_confidence_threshold(
    tmp_path: Path,
    monkeypatch,
    confidence: float,
    should_edit: bool,
):
    """Confidence gates only existing-skill edits, at the 0.6 boundary."""
    call = MagicMock(skill_id="skill-a", denied=False)
    monkeypatch.setattr(steps_mod, "_read_skill_calls_log", lambda *_a, **_k: [call])
    attribution = TrialAttribution(
        overall_attribution=Attribution.FAILURE_SKILL_USED,
        overall_rationale="the followed skill omitted a required check",
        diagnosis_status=DiagnosisStatus.ACTIONABLE,
        diagnosis_confidence=confidence,
        proposed_skill_change="Add the required check.",
        edit_candidate_skill_id="skill-a",
        skill_usage_assessments=[
            SkillUsageAssessment(
                skill_id="skill-a",
                status=SkillUsageStatus.FOLLOWED,
                evidence=["trace followed the skill"],
                causal_to_failure=True,
                confidence=confidence,
            )
        ],
    )
    ctx, result = _build_ctx(
        tmp_path,
        method=MockMethod(),
        r_task=0,
        lib_skills=["skill-a"],
        attribution=attribution,
    )
    skill = Skill(skill_id="skill-a", body="existing skill body")
    ctx.services.lib.skills["skill-a"] = skill
    ctx.services.refiner.propose_edit.side_effect = lambda **kwargs: kwargs["skill"]

    asyncio.run(steps_mod.step_incremental_edit(ctx, result))

    assert ctx.services.refiner.propose_edit.called is should_edit
