"""Tests for the 2026-06-26 L1 force-use hook text change.

The hook deny-reason text now ends with MUST-call language instead
of the previous advisory "Re-call Skill with one of these, or skip
if none fit." When ``top_k`` is empty (no relevant skills), the
hook still tells the agent to solve directly — MUST-call would be
a lie if there is nothing relevant to call.

The hook itself remains fail-open at the protocol level (the agent
can technically ignore the deny), but the text sharpens the
contract.
"""
from __future__ import annotations


def test_format_top_k_non_empty_ends_with_must():
    """When top_k has candidates, the closing line requires MUST-call."""
    from skillq.skillq_runtime import hook

    text = hook._format_top_k([("foo", 0.85), ("bar", 0.72)])
    assert text.endswith(
        "You MUST call Skill() with one of these — re-issue the "
        "Skill() call before continuing."
    )


def test_format_top_k_non_empty_lists_candidates():
    """When top_k has candidates, both skill names appear in the text."""
    from skillq.skillq_runtime import hook

    text = hook._format_top_k([("foo", 0.85), ("bar", 0.72)])
    assert "foo" in text
    assert "bar" in text


def test_format_top_k_empty_does_not_use_must():
    """When top_k is empty, MUST-call language must NOT appear
    (telling the agent to MUST-call something nonexistent is a lie)."""
    from skillq.skillq_runtime import hook

    text = hook._format_top_k([])
    assert "MUST" not in text
    # Empty-path message is "No skills in the library are relevant..."
    # followed by "solve this directly" guidance.
    assert "No skills" in text
    assert "relevant" in text.lower()
    assert "solve this directly" in text.lower()


def test_format_pull_context_non_empty_ends_with_must():
    """Pull-mode non-empty top_k also closes with MUST-call."""
    from skillq.skillq_runtime import hook

    text = hook._format_pull_context(
        [("foo", 0.85)],
        [{"skill_id": "foo", "description": "some desc"}],
    )
    assert text.endswith(
        "You MUST call Skill() with one of these before using other tools."
    )


def test_format_pull_context_non_empty_lists_candidates():
    """Pull-mode non-empty lists the skill_id and description."""
    from skillq.skillq_runtime import hook

    text = hook._format_pull_context(
        [("foo", 0.85)],
        [{"skill_id": "foo", "description": "a useful procedure"}],
    )
    assert "foo" in text
    assert "a useful procedure" in text


def test_format_pull_context_empty_keeps_dont_invoke():
    """Pull-mode empty top_k keeps the "Don't invoke" message."""
    from skillq.skillq_runtime import hook

    text = hook._format_pull_context([], [])
    assert "Don't invoke the Skill tool" in text
    assert "MUST" not in text


def test_no_advisory_skip_text_anywhere():
    """The old "or skip if none fit" advisory text is gone everywhere."""
    from skillq.skillq_runtime import hook

    non_empty = hook._format_top_k([("foo", 0.5)])
    assert "or skip if none fit" not in non_empty
    pull = hook._format_pull_context(
        [("foo", 0.5)],
        [{"skill_id": "foo", "description": "d"}],
    )
    # Pull-mode never had the "or skip" text; just make sure no
    # permissive "may skip" wording leaked in.
    assert "may skip" not in pull.lower()