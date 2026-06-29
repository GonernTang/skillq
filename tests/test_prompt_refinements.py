"""Snapshot tests for the 2026-06-25 prompt refinements.

These tests pin the text of three prompts that drive the
auto_extract pipeline:

- :data:`HOOK_INSTRUCTIONS_SNIPPET` (agent-facing, Method B) —
  tells the agent when to call Skill() vs refuse with a
  LIBRARY_GAP note.
- :data:`ATTRIBUTION_PROMPT` (feedback analyzer) — adds the
  ``library_gap_skill_description`` field so the attribution
  step records what skill the library SHOULD have contained.
- :data:`BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT` (claude
  --print synthesis) — requires a Diagnostic checklist + Stop
  signal in the synthesized SKILL.md and prefers the gap
  description as the seed.

The circuit-fibsqrt case study (2026-06-24 full run) revealed
that all three prompts were too permissive and produced
"compliance-theater" skills; these tests pin the fixes so
future edits don't silently regress.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.layers.l3_attribution.models import TrialAttribution  # noqa: E402
from skillq.layers.l3_attribution.prompts import (  # noqa: E402
    ATTRIBUTION_PROMPT,
)
from skillq.layers.l4_evolve.prompts import (  # noqa: E402
    BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT,
    BATCHED_EXTRACT_SKILL_PROMPT,
)
from skillq.runtime.agentic_search import HOOK_INSTRUCTIONS_SNIPPET  # noqa: E402


# ---------------------------------------------------------------------------
# Edit 1 — HOOK_INSTRUCTIONS_SNIPPET
# ---------------------------------------------------------------------------
def test_hook_instructions_drops_compliance_theater():
    """The agent must NOT see 'Calling the wrong skill is fine' —
    that line caused the 2026-06-24 circuit-fibsqrt agent to call
    ruvnet-git-workflow as a tick-the-box gesture."""
    assert "Calling the wrong skill is fine" not in HOOK_INSTRUCTIONS_SNIPPET, (
        "Hook prompt still permits compliance-theater Skill() calls"
    )


def test_hook_instructions_mentions_library_gap():
    """The new LIBRARY_GAP instruction must be present so the
    agent has a way to refuse with a useful signal."""
    assert "LIBRARY_GAP" in HOOK_INSTRUCTIONS_SNIPPET


def test_hook_instructions_emphasises_specificity():
    """The new prompt must demand specificity ('names the
    technology, file format, or procedure') over keyword match."""
    assert "names the" in HOOK_INSTRUCTIONS_SNIPPET
    assert "specificity" in HOOK_INSTRUCTIONS_SNIPPET.lower()


# ---------------------------------------------------------------------------
# Edit 2 — ATTRIBUTION_PROMPT
# ---------------------------------------------------------------------------
def test_attribution_prompt_has_gap_field():
    """The new library_gap_skill_description field must appear
    in the output schema."""
    assert "library_gap_skill_description" in ATTRIBUTION_PROMPT


def test_attribution_prompt_lists_gap_enums():
    """The two gap-signaling enums must be named alongside the
    new field — otherwise the LLM has no signal when to populate
    it. 2026-06-26: SUCCESS_VIEWED_SKILL_BUT_NOT_USED removed
    (structurally unreachable under force-use); FAIL_AGENT_ISSUE
    renamed to FAILURE_SKILL_NOT_USED.
    """
    assert "success_no_skill_seen" in ATTRIBUTION_PROMPT
    assert "failure_skill_not_used" in ATTRIBUTION_PROMPT


def test_attribution_prompt_empty_default_is_clear():
    """The prompt must explicitly say 'Empty string otherwise'
    so the LLM doesn't fabricate a gap description on irrelevant
    success paths."""
    assert "Empty string otherwise" in ATTRIBUTION_PROMPT


# ---------------------------------------------------------------------------
# Edit 3 — BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT
# ---------------------------------------------------------------------------
def test_failure_extract_prompt_requires_checklist():
    """Synthesized skills must include a Diagnostic checklist
    section so the agent has testable checks before committing."""
    assert "Diagnostic checklist" in BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT


def test_failure_extract_prompt_requires_stop_signal():
    """Synthesized skills must include a Stop signal section so
    the agent bails out of debug spirals after N failures (the
    2026-06-24 circuit-fibsqrt agent wrote 7 versions of gen.py
    without resetting)."""
    assert "Stop signal" in BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT


def test_failure_extract_prompt_prefers_gap_seed():
    """The prompt must explicitly prefer library_gap_skill_description
    over knowledge_to_extract as the seed. The literal "primary seed"
    may be split across line boundaries — match the joined form."""
    normalized = BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT.replace("\n", " ")
    assert "library_gap_skill_description" in normalized
    assert "primary seed" in normalized
    assert "Preferred seed" in BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT


def test_failure_extract_prompt_cites_circuit_fibsqrt():
    """The prompt must reference the case study so future
    editors understand WHY these sections are required."""
    assert "circuit-fibsqrt" in BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT


def test_success_extract_prompt_unchanged():
    """The success-path prompt must NOT adopt the gap-seed
    pattern — successes don't signal library gaps, and adding
    the field would create noise in the LLM's output schema."""
    assert "library_gap_skill_description" not in BATCHED_EXTRACT_SKILL_PROMPT


# ---------------------------------------------------------------------------
# Schema — TrialAttribution must round-trip the new field
# ---------------------------------------------------------------------------
def test_trial_attribution_accepts_gap_field():
    """The Pydantic model must accept the new field with default ''."""
    a = TrialAttribution(
        overall_attribution="failure_skill_not_used",
        overall_rationale="agent chose wrong architecture",
        knowledge_to_extract="synchronous state machine debug spiral",
        library_gap_skill_description=(
            "a skill whose description names 'hardware-circuit-synthesis' "
            "and includes a sanity-test checklist for N=0, 1, 4"
        ),
    )
    assert a.library_gap_skill_description.startswith("a skill whose description")


def test_trial_attribution_gap_field_defaults_to_empty():
    """The Pydantic model must default the new field to '' so
    older LLM outputs (or stub backends) don't fail validation."""
    a = TrialAttribution(
        overall_attribution="success_skill_used",
        overall_rationale="a skill was used",
        knowledge_to_extract="followed the seed skill",
    )
    assert a.library_gap_skill_description == ""