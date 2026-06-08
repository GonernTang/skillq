"""Tests for ``mg/method/attribution.py``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mg.method.attribution import (  # noqa: E402
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
        task="the thing", trial_dir=trial_dir, skills_root=None
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
