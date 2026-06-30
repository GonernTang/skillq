"""Tests for the 2026-06-25 L4 quality gates on MethodConfig.

Field on ``MethodConfig``:
  - ``enforce_failure_skill_structure`` (default True) — gates whether
    ``_collect_skill`` rejects failure-mode skills missing the
    "Diagnostic checklist" / "Stop signal" sections.

(2026-06-30: ``semantic_dedup_threshold`` removed along with the
cosine-based semantic dedup block.)
"""
from __future__ import annotations

import pytest


def test_enforce_failure_skill_structure_default_true():
    from skillq.config import MethodConfig

    assert MethodConfig().enforce_failure_skill_structure is True


def test_enforce_failure_skill_structure_can_be_disabled():
    from skillq.config import MethodConfig

    assert MethodConfig(enforce_failure_skill_structure=False).enforce_failure_skill_structure is False


def test_method_config_q_alpha_unchanged():
    """Sanity: pre-existing q_alpha still has its old default of 0.3."""
    from skillq.config import MethodConfig

    assert MethodConfig().q_alpha == pytest.approx(0.3)