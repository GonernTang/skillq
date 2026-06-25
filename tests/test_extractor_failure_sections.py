"""Tests for the 2026-06-25 structural validation in ``_collect_skill``.

Failure-mode skills (produced by
``BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT``) must contain both a
"Diagnostic checklist" section and a "Stop signal" section. The prompt
advertises this as a contract — "a skill missing either section is
incomplete and will be rejected by the bridge". This test file
verifies the bridge-side enforcement.

The check is gated on:
  - ``SkillExtractor.prompt_mode == "failure"`` (success-mode skills
    have no such requirement)
  - ``SkillExtractor.enforce_failure_skill_structure == True`` (set
    to ``False`` to opt out)
"""
from __future__ import annotations

from pathlib import Path


def _make_skill_sandbox(tmp_path: Path, body: str, skill_name: str = "fix-x") -> Path:
    """Write a sandbox dir shaped like claude --print's ``create/<name>/SKILL.md``."""
    skill_dir = tmp_path / "create" / skill_name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")
    return tmp_path


_VALID_BODY = (
    "# Fix-X\n\n"
    "## Diagnostic checklist\n"
    "1. Run pytest\n"
    "2. Verify exit 0\n\n"
    "## Stop signal\n"
    "If pytest hangs >60s, kill -9 and reset cache.\n"
)
# Pad to meet body_min_tokens=50 default (3 tokens/line × 12 lines = 36 + ~24 base = ~60).
_VALID_BODY = _VALID_BODY + ("\nAdditional context paragraph.\n" * 12)


def test_failure_skill_with_both_sections_accepted(tmp_path: Path):
    """Failure-mode skill with both required sections → Skill returned."""
    from skillq.method.extractor import SkillExtractor

    sandbox = _make_skill_sandbox(tmp_path, _VALID_BODY, "fix-x")
    ext = SkillExtractor(prompt_mode="failure")
    skill = ext._collect_skill(sandbox, intent_hash=0, task="fix-x")
    assert skill is not None
    assert skill.skill_id == "fix-x"


def test_failure_skill_missing_diagnostic_checklist_rejected(tmp_path: Path):
    """Missing 'Diagnostic checklist' → None."""
    from skillq.method.extractor import SkillExtractor

    body = (
        "# Fix-X\n\n"
        "## Stop signal\n"
        "If hangs >60s, kill -9 and reset cache.\n\n"
        + ("Additional context paragraph.\n" * 12)
    )
    sandbox = _make_skill_sandbox(tmp_path, body, "fix-x")
    ext = SkillExtractor(prompt_mode="failure")
    assert ext._collect_skill(sandbox, intent_hash=0, task="fix-x") is None


def test_failure_skill_missing_stop_signal_rejected(tmp_path: Path):
    """Missing 'Stop signal' → None."""
    from skillq.method.extractor import SkillExtractor

    body = (
        "# Fix-X\n\n"
        "## Diagnostic checklist\n"
        "1. Run pytest\n\n"
        + ("Additional context paragraph.\n" * 12)
    )
    sandbox = _make_skill_sandbox(tmp_path, body, "fix-x")
    ext = SkillExtractor(prompt_mode="failure")
    assert ext._collect_skill(sandbox, intent_hash=0, task="fix-x") is None


def test_failure_skill_missing_both_sections_rejected(tmp_path: Path):
    """Both missing → None (first failure hits Diagnostic, returns)."""
    from skillq.method.extractor import SkillExtractor

    body = (
        "# Fix-X\n\n"
        "Just some prose, no structural sections.\n"
        + ("Additional context paragraph.\n" * 15)
    )
    sandbox = _make_skill_sandbox(tmp_path, body, "fix-x")
    ext = SkillExtractor(prompt_mode="failure")
    assert ext._collect_skill(sandbox, intent_hash=0, task="fix-x") is None


def test_success_skill_no_section_requirement(tmp_path: Path):
    """Success-mode skills do NOT need Diagnostic/Stop sections."""
    from skillq.method.extractor import SkillExtractor

    body = (
        "# Fix-Y\n\n"
        "Reusable procedure: do step 1, then step 2, then step 3.\n"
        + ("Detailed paragraph with more than fifty tokens here.\n" * 12)
    )
    sandbox = _make_skill_sandbox(tmp_path, body, "fix-y")
    ext = SkillExtractor(prompt_mode="success")
    skill = ext._collect_skill(sandbox, intent_hash=0, task="fix-y")
    assert skill is not None
    assert skill.skill_id == "fix-y"


def test_enforce_false_opt_out(tmp_path: Path):
    """enforce_failure_skill_structure=False bypasses the check
    (useful for legacy prompts that don't write the structural
    sections but were already accepted)."""
    from skillq.method.extractor import SkillExtractor

    body = (
        "# Fix-X\n\n"
        "No structural sections, just a procedure.\n"
        + ("Detailed paragraph with more than fifty tokens here.\n" * 12)
    )
    sandbox = _make_skill_sandbox(tmp_path, body, "fix-x")
    ext = SkillExtractor(
        prompt_mode="failure",
        enforce_failure_skill_structure=False,
    )
    assert ext._collect_skill(sandbox, intent_hash=0, task="fix-x") is not None


def test_case_insensitive_section_match(tmp_path: Path):
    """Section match is case-insensitive — prompts sometimes render
    the headings in different casings."""
    from skillq.method.extractor import SkillExtractor

    body = (
        "# Fix-X\n\n"
        "diagnostic CHECKLIST\n1. Run pytest\n\n"
        "STOP signal\nIf hangs, kill -9.\n\n"
        + ("Additional paragraph for token count.\n" * 12)
    )
    sandbox = _make_skill_sandbox(tmp_path, body, "fix-x")
    ext = SkillExtractor(prompt_mode="failure")
    assert ext._collect_skill(sandbox, intent_hash=0, task="fix-x") is not None


def test_token_count_guard_still_runs_first(tmp_path: Path):
    """Body token guard (existing behaviour) must still fire before
    the structural check — i.e., a too-short failure-skill body is
    rejected even if it accidentally contains the section markers."""
    from skillq.method.extractor import SkillExtractor

    # 10 tokens, well below body_min_tokens=50 default.
    body = "## Diagnostic checklist\n## Stop signal\n"
    sandbox = _make_skill_sandbox(tmp_path, body, "fix-x")
    ext = SkillExtractor(prompt_mode="failure")
    assert ext._collect_skill(sandbox, intent_hash=0, task="fix-x") is None


def test_default_enforce_flag_is_true():
    """SkillExtractor default sets enforce_failure_skill_structure=True."""
    from skillq.method.extractor import SkillExtractor

    assert SkillExtractor(prompt_mode="failure").enforce_failure_skill_structure is True
    assert SkillExtractor(prompt_mode="success").enforce_failure_skill_structure is True


def test_method_config_enforce_failure_skill_structure_default_true():
    """MethodConfig default for the corresponding flag is True."""
    from skillq.skillq_runtime.config import MethodConfig

    cfg = MethodConfig()
    assert cfg.enforce_failure_skill_structure is True