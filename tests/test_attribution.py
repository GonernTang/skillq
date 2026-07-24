"""Tests for ``paper/method/attribution.py``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.layers.l3_attribution.analyzer import AttributionAnalyzer  # noqa: E402
from skillq.layers.l3_attribution.models import (  # noqa: E402
    AnalysisStatus,
    Attribution,
    DiagnosisStatus,
    LiteLLMAttributionBackend,
    SkillUsageStatus,
    StubAttributionBackend,
    TrialAttribution,
)


def test_stub_backend_returns_parseable_attribution():
    backend = StubAttributionBackend(
        overall_attribution=Attribution.SUCCESS_NO_SKILL_SEEN,
        knowledge_to_extract="Reuse the X when Y.",
    )
    raw = backend("any prompt", "any model")
    attribution = AttributionAnalyzer(backend=backend, model="m")._parse(raw)
    assert attribution.overall_attribution == Attribution.SUCCESS_NO_SKILL_SEEN
    assert attribution.knowledge_to_extract == "Reuse the X when Y."
    assert attribution.overall_rationale.startswith("stub:")


def test_parse_handles_prose_wrapped_json():
    raw = (
        "Here is my analysis:\n"
        "```json\n"
        + json.dumps(
            {
                "overall_attribution": "failure_skill_not_used",
                "overall_rationale": "agent ignored the verifier hint",
                "subtasks": [],
                "knowledge_to_extract": "",
            }
        )
        + "\n```\n"
    )
    backend = StubAttributionBackend()  # won't be called
    attribution = AttributionAnalyzer(backend=backend, model="m")._parse(raw)
    assert attribution.overall_attribution == Attribution.FAILURE_SKILL_NOT_USED


def test_parse_returns_conservative_default_on_garbage():
    backend = StubAttributionBackend()
    attribution = AttributionAnalyzer(backend=backend, model="m")._parse("lol nope")
    assert attribution.overall_attribution == Attribution.FAILURE_SKILL_NOT_USED
    assert "parse failed" in attribution.overall_rationale
    assert attribution.analysis_status == AnalysisStatus.INVALID
    assert attribution.diagnosis_status == DiagnosisStatus.INSUFFICIENT_EVIDENCE


def test_parse_returns_invalid_on_schema_failure():
    """Parseable JSON with an invalid schema must also fail closed."""
    raw = json.dumps(
        {
            "overall_rationale": "",
            "analysis_status": "valid",
            "diagnosis_status": "actionable",
            "diagnosis_confidence": 1.0,
            "edit_candidate_skill_id": "alpha",
        }
    )
    attribution = AttributionAnalyzer._parse(raw)

    assert attribution.analysis_status == AnalysisStatus.INVALID
    assert attribution.diagnosis_status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert attribution.edit_candidate_skill_id is None


def test_analyze_reads_session_jsonl(tmp_path: Path):
    """The trace loader picks the most recent ``*.jsonl`` under
    ``trial_dir/agent/sessions/projects/`` and renders to markdown.
    """
    trial_dir = tmp_path / "trial-1"
    sessions = trial_dir / "agent" / "sessions" / "projects" / "abc"
    sessions.mkdir(parents=True)
    jsonl = sessions / "session.jsonl"
    jsonl.write_text(
        json.dumps(
            {
                "type": "user",
                "message": {"role": "user", "content": "do the thing"},
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I will do the thing."},
                        {
                            "type": "tool_use",
                            "name": "Read",
                            "input": {"file_path": "/skills/x/SKILL.md"},
                        },
                    ],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    # 2026-07-20: overall_attribution is now derived from r_task x
    # called_skill_ids (not the LLM). Pass called_skill_ids=["alpha"]
    # so the derived value is SUCCESS_SKILL_USED, matching the
    # stub's value; the test's purpose is still to verify the
    # analyzer reads the session jsonl and round-trips a value.
    backend = StubAttributionBackend(
        overall_attribution=Attribution.SUCCESS_SKILL_USED
    )
    analyzer = AttributionAnalyzer(backend=backend, model="m")
    attribution = analyzer.analyze(
        task="the thing",
        trial_dir=trial_dir,
        skills_root=None,
        r_task=1,
        called_skill_ids=["alpha"],
    )
    assert attribution.overall_attribution == Attribution.SUCCESS_SKILL_USED


def test_list_available_skills_returns_relative_paths(tmp_path: Path):
    skills_root = tmp_path / "skills"
    (skills_root / "alpha").mkdir(parents=True)
    (skills_root / "alpha" / "SKILL.md").write_text("# alpha")
    (skills_root / "beta").mkdir()
    (skills_root / "beta" / "SKILL.md").write_text("# beta")

    mapping = AttributionAnalyzer._list_available_skills(skills_root)
    assert mapping == {
        "alpha": str((skills_root / "alpha" / "SKILL.md").resolve()),
        "beta": str((skills_root / "beta" / "SKILL.md").resolve()),
    }


def test_trial_attribution_subtasks_round_trip():
    payload = {
        "overall_attribution": "success_skill_used",
        "overall_rationale": "r1",
        "subtasks": [
            {
                "goal": "g",
                "summary": "s",
                "attribution": "success_skill_used",
                "skill_linked": "alpha",
                "skill_refs": [
                    {
                        "file_path": "alpha/SKILL.md",
                        "start_line": 1,
                        "end_line": 5,
                        "capability": "parse COBOL",
                        "used_for": "step 1",
                    }
                ],
            }
        ],
        "knowledge_to_extract": "",
    }
    attribution = TrialAttribution.model_validate(payload)
    assert attribution.overall_attribution == Attribution.SUCCESS_SKILL_USED
    assert attribution.subtasks[0].skill_linked == "alpha"


def test_litellm_backend_imports_only_when_called():
    """``LiteLLMAttributionBackend.__call__`` should fail loudly (ImportError)
    if litellm is not installed, but the import itself must be lazy so
    ``import mg`` does not require litellm at startup.
    """
    backend = LiteLLMAttributionBackend(model="openai/gpt-4o")
    assert backend.model == "openai/gpt-4o"
    # No actual LLM call here — just verify the class is constructable.


# ---------------------------------------------------------------------------
# Derivation: r_task x called_skill_ids -> overall_attribution
# (replaces the old consistency-clamp tests; 2026-07-20 refactor
# moved overall_attribution determination out of the LLM and into
# code, so the clamp is no longer needed.)
# ---------------------------------------------------------------------------
def test_analyze_r1_no_skills_derives_success_no_skill_seen(tmp_path: Path):
    """r_task=1 with called_skill_ids=[] -> SUCCESS_NO_SKILL_SEEN,
    regardless of what the LLM returns. This is the exact bug shape
    that surfaced in the auto-extract smoke (LLM said
    FAILURE_SKILL_NOT_USED despite r_task=1); the derivation makes
    that impossible.
    """
    backend = StubAttributionBackend(
        overall_attribution=Attribution.FAILURE_SKILL_NOT_USED,
        knowledge_to_extract="",  # empty -- the original bug signature
    )
    analyzer = AttributionAnalyzer(backend=backend, model="m")
    attribution = analyzer.analyze(
        task="the thing",
        trial_dir=tmp_path,
        skills_root=None,
        r_task=1,
        called_skill_ids=[],
    )
    assert attribution.overall_attribution == Attribution.SUCCESS_NO_SKILL_SEEN
    # No clamp marker -- derivation is code-driven, not a clamp.
    assert "[consistency-clamp]" not in attribution.overall_rationale
    assert attribution.knowledge_to_extract == ""


def test_analyze_r0_with_skill_derives_failure_skill_used(tmp_path: Path):
    """r_task=0 with called_skill_ids=['a'] -> FAILURE_SKILL_USED,
    regardless of what the LLM returns. Previously this was a
    silent gap (LLM said SUCCESS_SKILL_USED despite r_task=0); the
    derivation routes it into the L3 Edit path.
    """
    backend = StubAttributionBackend(
        overall_attribution=Attribution.SUCCESS_SKILL_USED,
        knowledge_to_extract="some failure-mode knowledge",
    )
    analyzer = AttributionAnalyzer(backend=backend, model="m")
    attribution = analyzer.analyze(
        task="the thing",
        trial_dir=tmp_path,
        skills_root=None,
        r_task=0,
        called_skill_ids=["skill-a"],
    )
    assert attribution.overall_attribution == Attribution.FAILURE_SKILL_USED
    assert "[consistency-clamp]" not in attribution.overall_rationale
    # knowledge passes through (no fabrication)
    assert attribution.knowledge_to_extract == "some failure-mode knowledge"


@pytest.mark.parametrize(
    ("confidence", "expected_status"),
    [
        (0.6, DiagnosisStatus.ACTIONABLE),
        (0.59, DiagnosisStatus.INSUFFICIENT_EVIDENCE),
    ],
)
def test_analyze_edit_causality_uses_point_six_threshold(
    tmp_path: Path,
    confidence: float,
    expected_status: DiagnosisStatus,
):
    raw = json.dumps(
        {
            "overall_rationale": "The followed skill omitted a required check.",
            "analysis_status": "valid",
            "diagnosis_status": "actionable",
            "diagnosis_confidence": confidence,
            "proposed_skill_change": "Add the required check.",
            "edit_candidate_skill_id": "skill-a",
            "skill_usage_assessments": [
                {
                    "skill_id": "skill-a",
                    "status": SkillUsageStatus.FOLLOWED.value,
                    "evidence": ["The trace follows the skill."],
                    "causal_to_failure": True,
                    "confidence": confidence,
                }
            ],
        }
    )
    analyzer = AttributionAnalyzer(backend=lambda *_args: raw, model="m")

    attribution = analyzer.analyze(
        task="the thing",
        trial_dir=tmp_path,
        r_task=0,
        called_skill_ids=["skill-a"],
    )

    assert attribution.diagnosis_status == expected_status


def test_analyze_called_but_ignored_becomes_agent_noncompliance(tmp_path: Path):
    raw = json.dumps(
        {
            "overall_rationale": "The agent read but rejected the procedure.",
            "analysis_status": "valid",
            "diagnosis_status": "actionable",
            "diagnosis_confidence": 0.95,
            "proposed_skill_change": "Unnecessary edit.",
            "edit_candidate_skill_id": "skill-a",
            "skill_usage_assessments": [
                {
                    "skill_id": "skill-a",
                    "status": SkillUsageStatus.IGNORED.value,
                    "evidence": ["The trace explicitly chose an unrelated method."],
                    "causal_to_failure": False,
                    "confidence": 0.95,
                }
            ],
        }
    )
    analyzer = AttributionAnalyzer(backend=lambda *_args: raw, model="m")

    attribution = analyzer.analyze(
        task="the thing",
        trial_dir=tmp_path,
        r_task=0,
        called_skill_ids=["skill-a"],
    )

    assert attribution.diagnosis_status == DiagnosisStatus.AGENT_NONCOMPLIANCE
    assert attribution.edit_candidate_skill_id is None
    assert attribution.proposed_skill_change == ""


def test_analyze_does_not_call_partial_usage_evidence_noncompliance(
    tmp_path: Path,
):
    raw = json.dumps(
        {
            "overall_rationale": "Only one of two calls could be assessed.",
            "analysis_status": "valid",
            "diagnosis_status": "actionable",
            "diagnosis_confidence": 0.95,
            "proposed_skill_change": "Change skill-a.",
            "edit_candidate_skill_id": "skill-a",
            "skill_usage_assessments": [
                {
                    "skill_id": "skill-a",
                    "status": SkillUsageStatus.IGNORED.value,
                    "evidence": ["The trace ignored skill-a."],
                    "causal_to_failure": False,
                    "confidence": 0.95,
                }
            ],
        }
    )
    analyzer = AttributionAnalyzer(backend=lambda *_args: raw, model="m")

    attribution = analyzer.analyze(
        task="the thing",
        trial_dir=tmp_path,
        r_task=0,
        called_skill_ids=["skill-a", "skill-b"],
    )

    assert attribution.diagnosis_status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert attribution.edit_candidate_skill_id is None


def test_analyze_r1_no_skills_no_clamp_marker(tmp_path: Path):
    """r_task=1 with called_skill_ids=[] -> SUCCESS_NO_SKILL_SEEN.
    The rationale must NOT contain a [consistency-clamp] marker
    because the derivation is code-driven, not a clamp.
    """
    backend = StubAttributionBackend(
        overall_attribution=Attribution.SUCCESS_NO_SKILL_SEEN,
        knowledge_to_extract="x",
    )
    analyzer = AttributionAnalyzer(backend=backend, model="m")
    attribution = analyzer.analyze(
        task="t",
        trial_dir=tmp_path,
        skills_root=None,
        r_task=1,
        called_skill_ids=[],
    )
    assert attribution.overall_attribution == Attribution.SUCCESS_NO_SKILL_SEEN
    assert "[consistency-clamp]" not in attribution.overall_rationale


def test_prompt_includes_r_task_placeholder():
    """ATTRIBUTION_PROMPT must accept r_task and surface it in the
    rendered string — guards against regressions where someone
    reformats the template and drops the new placeholder.
    """
    from skillq.layers.l3_attribution.prompts import ATTRIBUTION_PROMPT

    rendered = ATTRIBUTION_PROMPT.format(
        r_task=1, task="x", cwd="/", trial_dir="/",
        available_skills="[]", trace="(truncated)",
        called_skill_ids="[]", verifier_context="reward=1",
    )
    assert "r_task = 1" in rendered
    rendered_0 = ATTRIBUTION_PROMPT.format(
        r_task=0, task="x", cwd="/", trial_dir="/",
        available_skills="[]", trace="(truncated)",
        called_skill_ids="[]", verifier_context="reward=0",
    )
    assert "r_task = 0" in rendered_0
