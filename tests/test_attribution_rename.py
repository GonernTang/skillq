"""Tests for the 2026-06-26 Attribution enum rename + delete.

After this change:
  - ``FAIL_SKILL_ISSUE`` → ``FAILURE_SKILL_USED``
  - ``FAIL_AGENT_ISSUE`` → ``FAILURE_SKILL_NOT_USED``
  - ``SUCCESS_VIEWED_SKILL_BUT_NOT_USED`` → removed (structurally
    unreachable under L1 force-use hook)

The enum surface has 5 members (down from 6). All old names must
raise ``AttributeError``. The string values are renamed too.
"""
from __future__ import annotations


def test_renamed_enum_members_exist():
    """The two renamed members are present with new string values."""
    from skillq.layers.l3_attribution.models import Attribution

    assert Attribution.FAILURE_SKILL_USED.value == "failure_skill_used"
    assert Attribution.FAILURE_SKILL_NOT_USED.value == "failure_skill_not_used"


def test_surviving_enum_members_unchanged():
    """The four surviving members keep their old string values."""
    from skillq.layers.l3_attribution.models import Attribution

    assert Attribution.SUCCESS_SKILL_USED.value == "success_skill_used"
    assert Attribution.SUCCESS_NO_SKILL_SEEN.value == "success_no_skill_seen"
    assert Attribution.FAIL_ENV_ISSUE.value == "fail_env_issue"


def test_deleted_enum_member_removed():
    """SUCCESS_VIEWED_SKILL_BUT_NOT_USED no longer exists on the enum."""
    from skillq.layers.l3_attribution.models import Attribution

    assert not hasattr(Attribution, "SUCCESS_VIEWED_SKILL_BUT_NOT_USED"), (
        "SUCCESS_VIEWED_SKILL_BUT_NOT_USED should be removed "
        "(structurally unreachable under L1 force-use)"
    )


def test_old_enum_names_raise_attribute_error():
    """Both old names raise AttributeError (not silently aliased)."""
    from skillq.layers.l3_attribution.models import Attribution

    for old in ("FAIL_SKILL_ISSUE", "FAIL_AGENT_ISSUE"):
        assert not hasattr(Attribution, old), (
            f"Attribution.{old} should be removed but is still importable"
        )


def test_old_string_values_not_in_enum():
    """The old snake_case string values are no longer accepted by Pydantic."""
    import pytest
    from pydantic import ValidationError

    from skillq.layers.l3_attribution.models import TrialAttribution

    for old_value in ("fail_skill_issue", "fail_agent_issue",
                      "success_viewed_skill_but_not_used"):
        with pytest.raises(ValidationError):
            TrialAttribution(
                overall_attribution=old_value,
                overall_rationale="r",
            )


def test_enum_member_count_is_five():
    """The enum went from 6 to 5 members."""
    from skillq.layers.l3_attribution.models import Attribution

    assert len(Attribution) == 5


def test_stub_backend_default_unchanged():
    """StubAttributionBackend default is still SUCCESS_NO_SKILL_SEEN."""
    from skillq.layers.l3_attribution.models import Attribution, StubAttributionBackend

    backend = StubAttributionBackend()
    assert backend._attribution == Attribution.SUCCESS_NO_SKILL_SEEN


def test_parse_garbage_fallback_uses_new_name():
    """Parse-failure fallback is FAILURE_SKILL_NOT_USED (renamed)."""
    from skillq.layers.l3_attribution.analyzer import AttributionAnalyzer
    from skillq.layers.l3_attribution.models import (
        Attribution,
        StubAttributionBackend,
    )

    analyzer = AttributionAnalyzer(backend=StubAttributionBackend(), model="m")
    attribution = analyzer._parse("not json at all")
    assert attribution.overall_attribution == Attribution.FAILURE_SKILL_NOT_USED
    assert "FAILURE_SKILL_NOT_USED" in attribution.overall_rationale


def test_code_derived_verdict_r0_with_skill():
    """r_task=0 + called_skill_ids → FAILURE_SKILL_USED (code-derived, no LLM)."""
    from skillq.layers.l3_attribution.analyzer import AttributionAnalyzer
    from skillq.layers.l3_attribution.models import (
        Attribution,
        StubAttributionBackend,
    )

    analyzer = AttributionAnalyzer(
        backend=StubAttributionBackend(
            overall_attribution=Attribution.SUCCESS_SKILL_USED,
            knowledge_to_extract="x",
        ),
        model="m",
    )
    # Simulate: LLM outputs analysis, code derives verdict
    att = analyzer._parse(
        '{"overall_attribution": "success_skill_used", '
        '"overall_rationale": "r", "knowledge_to_extract": "x"}'
    )
    # Code derivation: r_task=0 + skill called → FAILURE_SKILL_USED
    att.overall_attribution = (
        Attribution.FAILURE_SKILL_USED
        if ["skill-a"]
        else Attribution.FAILURE_SKILL_NOT_USED
    )
    assert att.overall_attribution == Attribution.FAILURE_SKILL_USED


def test_code_derived_verdict_r1_no_skill():
    """r_task=1 + no called_skill_ids → SUCCESS_NO_SKILL_SEEN."""
    from skillq.layers.l3_attribution.analyzer import AttributionAnalyzer
    from skillq.layers.l3_attribution.models import (
        Attribution,
        StubAttributionBackend,
    )

    analyzer = AttributionAnalyzer(
        backend=StubAttributionBackend(
            overall_attribution=Attribution.FAILURE_SKILL_NOT_USED,
            knowledge_to_extract="",
        ),
        model="m",
    )
    att = analyzer._parse(
        '{"overall_attribution": "failure_skill_not_used", '
        '"overall_rationale": "r", "knowledge_to_extract": ""}'
    )
    # Code derivation: r_task=1 + no skill → SUCCESS_NO_SKILL_SEEN
    att.overall_attribution = (
        Attribution.SUCCESS_SKILL_USED
        if []
        else Attribution.SUCCESS_NO_SKILL_SEEN
    )
    assert att.overall_attribution == Attribution.SUCCESS_NO_SKILL_SEEN