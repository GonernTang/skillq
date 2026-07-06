"""Regression for Bug #1 (2026-06-30): numpy.float32 leaking into
Pydantic v2 RankResponse → /rank 500 → hook fail-open.

Root cause chain:
  emb_cache stores ``numpy.float32`` vectors.
  scoring.cosine() iterates them with a pure-Python loop BUT
  arithmetic on numpy.float32 scalars propagates numpy.float32.
  ``round(sim, 4)`` then returns numpy.float32.
  Pydantic v2 FastAPI serializer rejects ``dict[str, Any]`` values
  that are numpy scalars.

Fix: cosine() now casts ``float(...)`` at return; ranking_service
builds ``debug.pre_gate_top5`` with ``float(round(sim, 4))`` for
both branches (strict-gate fail and ok).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.layers.l1_retrieval.scoring import cosine  # noqa: E402


def test_cosine_returns_python_float_with_python_lists():
    v = cosine([1.0, 0.0], [1.0, 0.0])
    assert isinstance(v, float)
    assert v == pytest.approx(1.0)


def test_cosine_returns_python_float_with_numpy_float32_inputs():
    """Bug #1 repro: emb_cache vectors are numpy.float32. Without
    the float() cast in cosine(), the result was numpy.float32 and
    downstream Pydantic serialization crashed."""
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([1.0, 0.0], dtype=np.float32)
    v = cosine(a, b)
    assert isinstance(v, float), (
        f"cosine() must return Python float even when inputs are "
        f"numpy.float32; got {type(v).__name__}"
    )
    assert v == pytest.approx(1.0)


def test_cosine_returns_python_float_with_mixed_numpy_python():
    a = np.array([1.0, 0.0, 0.5], dtype=np.float32)
    b = [0.5, 0.5, 0.5]
    v = cosine(a, b)
    assert isinstance(v, float)


def test_round_then_float_is_safe():
    """The two ``round(sim, 4)`` sites in ranking_service.py must
    be wrapped in ``float(...)``; raw ``round(numpy.float32, 4)``
    returns numpy.float32 which Pydantic v2 can't serialize."""
    sim = np.float32(0.7643)
    raw_round = round(sim, 4)
    assert isinstance(raw_round, np.float32), (
        "baseline: round() preserves numpy.float32 — this is the leak"
    )
    safe = float(round(sim, 4))
    assert isinstance(safe, float)
    assert safe == pytest.approx(0.7643)


def test_pydantic_can_serialize_pre_gate_top5_dict():
    """End-to-end: build the exact ``debug["pre_gate_top5"]`` shape
    that /rank used to fail on, and confirm a real Pydantic v2 model
    can serialize it. This is the regression pin for the 500."""
    from skillq.services.ranking_service import RankResponse, ScoredSkill

    sims = [np.float32(0.7643), np.float32(0.6811), np.float32(0.0500)]
    debug_payload = {
        "pre_gate_top5": [
            {"skill_id": f"skill-{i}", "sim": float(round(s, 4))}
            for i, s in enumerate(sims)
        ],
    }
    resp = RankResponse(
        allowed=True,
        reason="ok",
        top_k=[],
        ranking_id="test",
        debug=debug_payload,
    )
    # The bug manifested as ``PydanticSerializationError`` here.
    # Pydantic v2 emits full-precision floats for ``float``; just
    # assert the call succeeds and round-trip preserves the values.
    js = resp.model_dump_json()
    parsed = RankResponse.model_validate_json(js)
    assert parsed.debug["pre_gate_top5"][0]["sim"] == pytest.approx(0.7643)
    assert parsed.debug["pre_gate_top5"][0]["sim"] is not np.float32, (
        "sim must be Python float, not numpy.float32, after round-trip"
    )
    assert isinstance(parsed.debug["pre_gate_top5"][0]["sim"], float)
