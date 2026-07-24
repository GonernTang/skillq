"""Regression tests for fail-closed L3 attribution and L4 editing."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from skillq.layers.l3_attribution.models import (
    AnalysisStatus,
    Attribution,
    DiagnosisStatus,
    SkillUsageAssessment,
    SkillUsageStatus,
    TrialAttribution,
)
from skillq.layers.l4_evolve.edit import EditRefiner, validate_edited_skill
from skillq.runtime import steps as steps_mod
from skillq.shared.types import Skill

from tests.test_ablation_switches import MockMethod, _build_ctx


def _call(skill_id: str) -> MagicMock:
    return MagicMock(
        skill_id=skill_id,
        requested=skill_id,
        approved=True,
        denied=False,
        intent_text="test-intent",
    )


def _attribution(
    *,
    diagnosis_status: DiagnosisStatus = DiagnosisStatus.ACTIONABLE,
    candidate: str | None = "skill-a",
    usage_status: SkillUsageStatus = SkillUsageStatus.FOLLOWED,
    causal: bool = True,
    confidence: float = 0.95,
    analysis_status: AnalysisStatus = AnalysisStatus.VALID,
) -> TrialAttribution:
    return TrialAttribution(
        overall_attribution=Attribution.FAILURE_SKILL_USED,
        overall_rationale="structured test attribution",
        analysis_status=analysis_status,
        diagnosis_status=diagnosis_status,
        diagnosis_confidence=confidence,
        failure_mechanism="The skill omits a required verification step.",
        proposed_skill_change="Add the verification step after writing output.",
        edit_candidate_skill_id=candidate,
        skill_usage_assessments=(
            [
                SkillUsageAssessment(
                    skill_id=candidate,
                    status=usage_status,
                    evidence=["the session followed the relevant instruction"],
                    causal_to_failure=causal,
                    confidence=confidence,
                )
            ]
            if candidate
            else []
        ),
    )


def test_attribution_backend_exception_is_fail_closed(tmp_path: Path, monkeypatch):
    """An attribution outage must not be converted into edit/create evidence."""
    ctx, result = _build_ctx(
        tmp_path,
        method=MockMethod(enable_auto_extract=True),
        r_task=0,
        lib_skills=["skill-a"],
    )
    monkeypatch.setattr(
        steps_mod, "_read_skill_calls_log", lambda *_a, **_k: [_call("skill-a")]
    )
    ctx.services.attribution_analyzer.analyze.side_effect = RuntimeError("offline")

    asyncio.run(steps_mod.step_attribute(ctx, result))
    assert result.attribution is not None
    assert result.attribution.analysis_status == AnalysisStatus.INVALID

    asyncio.run(steps_mod.step_incremental_edit(ctx, result))
    asyncio.run(steps_mod.step_dispatch_evolve(ctx, result))
    ctx.services.refiner.propose_edit.assert_not_called()
    ctx.services.extract_buffer.add.assert_not_called()


@pytest.mark.parametrize(
    "status",
    [
        DiagnosisStatus.UNCERTAIN,
        DiagnosisStatus.VERIFIER_MISMATCH,
        DiagnosisStatus.ENVIRONMENT,
        DiagnosisStatus.INSUFFICIENT_EVIDENCE,
    ],
)
def test_non_actionable_diagnosis_never_edits(
    tmp_path: Path, monkeypatch, status: DiagnosisStatus
):
    monkeypatch.setattr(
        steps_mod, "_read_skill_calls_log", lambda *_a, **_k: [_call("skill-a")]
    )
    ctx, result = _build_ctx(
        tmp_path,
        r_task=0,
        lib_skills=["skill-a"],
        attribution=_attribution(diagnosis_status=status),
    )

    asyncio.run(steps_mod.step_incremental_edit(ctx, result))
    ctx.services.refiner.propose_edit.assert_not_called()
    ctx.services.lib.replace.assert_not_called()


def test_called_but_ignored_neither_edits_nor_creates(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        steps_mod, "_read_skill_calls_log", lambda *_a, **_k: [_call("skill-a")]
    )
    attribution = _attribution(
        diagnosis_status=DiagnosisStatus.AGENT_NONCOMPLIANCE,
        usage_status=SkillUsageStatus.IGNORED,
        causal=False,
    )
    ctx, result = _build_ctx(
        tmp_path,
        method=MockMethod(enable_auto_extract=True),
        r_task=0,
        lib_skills=["skill-a"],
        attribution=attribution,
    )

    asyncio.run(steps_mod.step_incremental_edit(ctx, result))
    asyncio.run(steps_mod.step_dispatch_evolve(ctx, result))
    ctx.services.refiner.propose_edit.assert_not_called()
    ctx.services.extract_buffer.add.assert_not_called()


def test_inconsistent_actionable_ignored_assessment_still_does_not_edit(
    tmp_path: Path, monkeypatch
):
    """The runtime gate must defend against an internally inconsistent model response."""
    monkeypatch.setattr(
        steps_mod, "_read_skill_calls_log", lambda *_a, **_k: [_call("skill-a")]
    )
    attribution = _attribution(
        diagnosis_status=DiagnosisStatus.ACTIONABLE,
        usage_status=SkillUsageStatus.IGNORED,
        causal=True,
    )
    ctx, result = _build_ctx(
        tmp_path,
        r_task=0,
        lib_skills=["skill-a"],
        attribution=attribution,
    )

    asyncio.run(steps_mod.step_incremental_edit(ctx, result))
    ctx.services.refiner.propose_edit.assert_not_called()


def test_multiple_called_skills_edits_only_causal_candidate(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        steps_mod,
        "_read_skill_calls_log",
        lambda *_a, **_k: [_call("skill-a"), _call("skill-b")],
    )
    ctx, result = _build_ctx(
        tmp_path,
        r_task=0,
        lib_skills=["skill-a", "skill-b"],
        attribution=_attribution(candidate="skill-b"),
    )
    ctx.services.refiner.propose_edit.side_effect = lambda **kw: kw["skill"]

    asyncio.run(steps_mod.step_incremental_edit(ctx, result))
    ctx.services.refiner.propose_edit.assert_called_once()
    assert (
        ctx.services.refiner.propose_edit.call_args.kwargs["skill"].skill_id
        == "skill-b"
    )


def test_actionable_without_candidate_does_not_edit(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        steps_mod, "_read_skill_calls_log", lambda *_a, **_k: [_call("skill-a")]
    )
    ctx, result = _build_ctx(
        tmp_path,
        r_task=0,
        lib_skills=["skill-a"],
        attribution=_attribution(candidate=None),
    )

    asyncio.run(steps_mod.step_incremental_edit(ctx, result))
    ctx.services.refiner.propose_edit.assert_not_called()


def test_actionable_below_confidence_threshold_does_not_edit(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        steps_mod, "_read_skill_calls_log", lambda *_a, **_k: [_call("skill-a")]
    )
    ctx, result = _build_ctx(
        tmp_path,
        r_task=0,
        lib_skills=["skill-a"],
        attribution=_attribution(confidence=0.79),
    )

    asyncio.run(steps_mod.step_incremental_edit(ctx, result))
    ctx.services.refiner.propose_edit.assert_not_called()


def test_mirror_failure_keeps_in_memory_skill_unchanged(
    tmp_path: Path, monkeypatch
):
    """A disk mirror failure must reject the candidate before lib.replace."""
    monkeypatch.setattr(
        steps_mod, "_read_skill_calls_log", lambda *_a, **_k: [_call("skill-a")]
    )
    monkeypatch.setattr(
        steps_mod, "mirror_skill_to_host_dir", lambda *_a, **_k: False
    )
    ctx, result = _build_ctx(
        tmp_path,
        method=MockMethod(seed_skills_dir=tmp_path / "mounted-skills"),
        r_task=0,
        lib_skills=["skill-a"],
        attribution=_attribution(),
    )
    old = ctx.services.lib.skills["skill-a"]
    ctx.services.refiner.propose_edit.return_value = Skill(
        skill_id="skill-a",
        body="edited-body",
    )

    asyncio.run(steps_mod.step_incremental_edit(ctx, result))

    ctx.services.refiner.propose_edit.assert_called_once()
    ctx.services.lib.replace.assert_not_called()
    assert ctx.services.lib.skills["skill-a"] is old
    assert result.edited_skill_id is None


BASE_BODY = """---
name: alpha
description: A deterministic alpha workflow.
---
# Alpha

1. Read the input.
2. Normalize it.
3. Write the result.
4. Verify the result.
"""


class _BodyBackend:
    def __init__(self, body: str) -> None:
        self.body = body

    def __call__(self, prompt: str, model: str) -> str:
        return self.body


@pytest.mark.parametrize(
    "proposal",
    [
        "# Alpha\n\nNo frontmatter.",
        "---\nname: beta\ndescription: renamed\n---\n# Alpha\n",
        "---\nname: alpha\ndescription: ''\n---\n# Alpha\n",
        "```markdown\n" + BASE_BODY + "\n```",
        "---\nname: alpha\ndescription: Tiny\n---\n# A\n",
    ],
    ids=[
        "malformed-frontmatter",
        "renamed-skill",
        "empty-description",
        "code-fence",
        "destructive-rewrite",
    ],
)
def test_edit_refiner_rejects_invalid_or_destructive_output(proposal: str):
    old = Skill(skill_id="alpha", body=BASE_BODY)
    refiner = EditRefiner(backend=_BodyBackend(proposal), model="stub")

    assert validate_edited_skill(old, proposal) is None
    assert refiner.propose_edit(old, task="t") is old


def test_edit_refiner_accepts_valid_minimal_edit():
    proposal = BASE_BODY.replace(
        "4. Verify the result.",
        "4. Verify the result.\n5. Record the verification outcome.",
    )
    old = Skill(skill_id="alpha", body=BASE_BODY)
    refiner = EditRefiner(backend=_BodyBackend(proposal), model="stub")

    normalized = validate_edited_skill(old, proposal)
    assert normalized is not None
    edited = refiner.propose_edit(old, task="t")
    assert edited is not old
    assert edited.skill_id == old.skill_id
    assert "Record the verification outcome" in edited.body


def test_edit_validation_preserves_existing_frontmatter_alias():
    """Some imported skills intentionally use a folder id that differs from name."""
    old_body = BASE_BODY.replace("name: alpha", "name: upstream-alpha")
    proposal = old_body.replace(
        "4. Verify the result.",
        "4. Verify the result.\n5. Record the verification outcome.",
    )
    old = Skill(skill_id="folder-alpha", body=old_body)

    assert validate_edited_skill(old, proposal) is not None
    assert (
        validate_edited_skill(
            old, proposal.replace("name: upstream-alpha", "name: renamed")
        )
        is None
    )
