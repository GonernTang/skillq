"""Tests for the 2026-06-25 L4 quality gates on MethodConfig.

Two new fields on ``MethodConfig``:
  - ``enforce_failure_skill_structure`` (default True) — gates whether
    ``_collect_skill`` rejects failure-mode skills missing the
    "Diagnostic checklist" / "Stop signal" sections.
  - ``semantic_dedup_threshold`` (default 0.85, range [0, 1]) —
    cosine threshold above which a new skill's description embedding
    is treated as a duplicate of an existing skill's.
"""
from __future__ import annotations

import pytest


def test_enforce_failure_skill_structure_default_true():
    from skillq.skillq_runtime.config import MethodConfig

    assert MethodConfig().enforce_failure_skill_structure is True


def test_enforce_failure_skill_structure_can_be_disabled():
    from skillq.skillq_runtime.config import MethodConfig

    assert MethodConfig(enforce_failure_skill_structure=False).enforce_failure_skill_structure is False


def test_semantic_dedup_threshold_default_is_0_85():
    from skillq.skillq_runtime.config import MethodConfig

    assert MethodConfig().semantic_dedup_threshold == pytest.approx(0.85)


def test_semantic_dedup_threshold_zero_disables():
    from skillq.skillq_runtime.config import MethodConfig

    cfg = MethodConfig(semantic_dedup_threshold=0.0)
    assert cfg.semantic_dedup_threshold == 0.0


def test_semantic_dedup_threshold_one_is_maximum():
    from skillq.skillq_runtime.config import MethodConfig

    cfg = MethodConfig(semantic_dedup_threshold=1.0)
    assert cfg.semantic_dedup_threshold == pytest.approx(1.0)


def test_semantic_dedup_threshold_rejects_negative():
    from skillq.skillq_runtime.config import MethodConfig

    with pytest.raises(ValueError):
        MethodConfig(semantic_dedup_threshold=-0.01)


def test_semantic_dedup_threshold_rejects_above_one():
    from skillq.skillq_runtime.config import MethodConfig

    with pytest.raises(ValueError):
        MethodConfig(semantic_dedup_threshold=1.01)


def test_method_config_q_alpha_unchanged():
    """Sanity: pre-existing q_alpha still has its old default of 0.3."""
    from skillq.skillq_runtime.config import MethodConfig

    assert MethodConfig().q_alpha == pytest.approx(0.3)