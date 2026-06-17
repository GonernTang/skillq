"""Tests for ``paper/method/attribution.py``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.method.attribution import (  # noqa: E402
    Attribution,
    AttributionAnalyzer,
    LiteLLMAttributionBackend,
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
                "overall_attribution": "fail_agent_issue",
                "overall_rationale": "agent ignored the verifier hint",
                "subtasks": [],
                "knowledge_to_extract": "",
            }
        )
        + "\n```\n"
    )
    backend = StubAttributionBackend()  # won't be called
    attribution = AttributionAnalyzer(backend=backend, model="m")._parse(raw)
    assert attribution.overall_attribution == Attribution.FAIL_AGENT_ISSUE


def test_parse_returns_conservative_default_on_garbage():
    backend = StubAttributionBackend()
    attribution = AttributionAnalyzer(backend=backend, model="m")._parse("lol nope")
    assert attribution.overall_attribution == Attribution.FAIL_AGENT_ISSUE
    assert "parse failed" in attribution.overall_rationale


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
    backend = StubAttributionBackend(
        overall_attribution=Attribution.SUCCESS_VIEWED_SKILL_BUT_NOT_USED
    )
    analyzer = AttributionAnalyzer(backend=backend, model="m")
    attribution = analyzer.analyze(
        task="the thing", trial_dir=trial_dir, skills_root=None, r_task=1
    )
    assert attribution.overall_attribution == Attribution.SUCCESS_VIEWED_SKILL_BUT_NOT_USED


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
# Consistency clamp: r_task ↔ overall_attribution invariant
# ---------------------------------------------------------------------------
def test_consistency_clamp_r_task_1_with_fail_enum(tmp_path: Path):
    """r_task=1 with a fail_* enum from the LLM should be clamped to
    SUCCESS_NO_SKILL_SEEN (most conservative success enum). This is
    the exact bug shape that surfaced in the auto-extract smoke.
    """
    backend = StubAttributionBackend(
        overall_attribution=Attribution.FAIL_AGENT_ISSUE,
        knowledge_to_extract="",  # empty — the original bug signature
    )
    analyzer = AttributionAnalyzer(backend=backend, model="m")
    attribution = analyzer.analyze(
        task="the thing", trial_dir=tmp_path, skills_root=None, r_task=1
    )
    assert attribution.overall_attribution == Attribution.SUCCESS_NO_SKILL_SEEN
    assert "[consistency-clamp]" in attribution.overall_rationale
    # NB: knowledge is still empty here — the clamp only fixes the
    # enum. The prompt's hard constraint is what populates
    # knowledge_to_extract in production.
    assert attribution.knowledge_to_extract == ""


def test_consistency_clamp_r_task_0_with_success_enum(tmp_path: Path):
    """r_task=0 with a success_* enum from the LLM should be clamped
    to FAIL_SKILL_ISSUE (most conservative fail enum). Previously
    silently ignored; now routes into Rule 5.
    """
    backend = StubAttributionBackend(
        overall_attribution=Attribution.SUCCESS_SKILL_USED,
        knowledge_to_extract="some failure-mode knowledge",
    )
    analyzer = AttributionAnalyzer(backend=backend, model="m")
    attribution = analyzer.analyze(
        task="the thing", trial_dir=tmp_path, skills_root=None, r_task=0
    )
    assert attribution.overall_attribution == Attribution.FAIL_SKILL_ISSUE
    assert "[consistency-clamp]" in attribution.overall_rationale
    # knowledge passes through (no fabrication)
    assert attribution.knowledge_to_extract == "some failure-mode knowledge"


def test_consistency_clamp_no_op_when_consistent(tmp_path: Path):
    """When the LLM and r_task agree, the clamp is a no-op and the
    rationale is *not* prefixed with the marker.
    """
    backend = StubAttributionBackend(
        overall_attribution=Attribution.SUCCESS_NO_SKILL_SEEN,
        knowledge_to_extract="x",
    )
    analyzer = AttributionAnalyzer(backend=backend, model="m")
    attribution = analyzer.analyze(
        task="t", trial_dir=tmp_path, skills_root=None, r_task=1
    )
    assert attribution.overall_attribution == Attribution.SUCCESS_NO_SKILL_SEEN
    assert "[consistency-clamp]" not in attribution.overall_rationale


def test_prompt_includes_r_task_placeholder():
    """ATTRIBUTION_PROMPT must accept r_task and surface it in the
    rendered string — guards against regressions where someone
    reformats the template and drops the new placeholder.
    """
    from skillq.method.prompts import ATTRIBUTION_PROMPT

    rendered = ATTRIBUTION_PROMPT.format(
        r_task=1, task="x", cwd="/", trial_dir="/",
        available_skills="[]", trace="(truncated)",
    )
    assert "r_task = 1" in rendered
    rendered_0 = ATTRIBUTION_PROMPT.format(
        r_task=0, task="x", cwd="/", trial_dir="/",
        available_skills="[]", trace="(truncated)",
    )
    assert "r_task = 0" in rendered_0
