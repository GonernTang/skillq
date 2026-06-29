"""Tests for the L1 force-use hook text — Step 7 (2026-06-27) update.

Originally these tests pinned the 2026-06-26 L1 force-use text change:
the deny-reason text now ends with MUST-call language instead of the
previous advisory "Re-call Skill with one of these, or skip if none
fit." When ``top_k`` is empty (no relevant skills), the hook tells the
agent to solve directly — MUST-call would be a lie if there is
nothing relevant to call.

The Step 5 (2026-06-26) rewrite of ``runtime/hook.py`` shrunk the
hook from ~800 lines (stdlib Eq.4 implementation) to ~150 lines
(``/rank`` HTTP client). The text format changed during that rewrite:
top-k candidates are now formatted as a list (one per line with the
``(score=...)`` tag) and the empty-state messages use a fresh
wording. The tests below were rewritten to match the new format
while still pinning the contract:

- Non-empty top_k → MUST-call language must appear
- Empty top_k → MUST-call language must NOT appear (telling the
  agent to MUST-call something nonexistent is a lie)
- Old advisory "or skip if none fit" text is gone

The hook itself remains fail-open at the protocol level (the agent
can technically ignore the deny), but the text sharpens the
contract.
"""
from __future__ import annotations


def test_format_top_k_non_empty_uses_must():
    """When top_k has candidates, the header line invokes MUST-call."""
    from skillq.runtime import hook

    text = hook._format_top_k([
        {"skill_id": "foo", "score": 0.85, "description": "f desc"},
        {"skill_id": "bar", "score": 0.72, "description": "b desc"},
    ])
    # New Step-5 format header line.
    assert "MUST call Skill()" in text


def test_format_top_k_non_empty_lists_candidates():
    """When top_k has candidates, both skill names appear in the text."""
    from skillq.runtime import hook

    text = hook._format_top_k([
        {"skill_id": "foo", "score": 0.85, "description": "f desc"},
        {"skill_id": "bar", "score": 0.72, "description": "b desc"},
    ])
    assert "foo" in text
    assert "bar" in text
    # New Step-5 format: each entry on its own line with score tag.
    assert "score=" in text


def test_format_top_k_empty_does_not_use_must():
    """When top_k is empty, MUST-call language must NOT appear
    (telling the agent to MUST-call something nonexistent is a lie)."""
    from skillq.runtime import hook

    text = hook._format_top_k([])
    assert "MUST" not in text
    # Empty-path message guides the agent to skip Skill().
    assert "Skill" in text
    assert "Continue without" in text


def test_format_pull_context_non_empty_includes_must_or_invokable():
    """Pull-mode non-empty top_k mentions the Skill tool as invokable."""
    from skillq.runtime import hook

    text = hook._format_pull_context([
        {"skill_id": "foo", "score": 0.85, "description": "some desc"},
    ])
    assert "Skill" in text
    # Step 5 explicitly tells the agent HOW to call Skill() in pull mode.
    assert 'Skill(skill=' in text


def test_format_pull_context_non_empty_lists_candidates():
    """Pull-mode non-empty lists the skill_id."""
    from skillq.runtime import hook

    text = hook._format_pull_context([
        {"skill_id": "foo", "score": 0.85, "description": "a useful procedure"},
    ])
    assert "foo" in text
    assert "a useful procedure" in text


def test_format_pull_context_empty_keeps_no_skills_message():
    """Pull-mode empty top_k keeps the "No skills" message and no MUST."""
    from skillq.runtime import hook

    text = hook._format_pull_context([])
    assert "No skills" in text
    assert "MUST" not in text


def test_no_advisory_skip_text_anywhere():
    """The old "or skip if none fit" advisory text is gone everywhere."""
    from skillq.runtime import hook

    non_empty = hook._format_top_k([
        {"skill_id": "foo", "score": 0.5, "description": "f"},
    ])
    assert "or skip if none fit" not in non_empty
    pull = hook._format_pull_context([
        {"skill_id": "foo", "score": 0.5, "description": "d"},
    ])
    # Pull-mode never had the "or skip" text; just make sure no
    # permissive "may skip" wording leaked in.
    assert "may skip" not in pull.lower()
