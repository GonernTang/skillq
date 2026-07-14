"""Tests for the strict Hard Gate (2026-06-25).

Default ``sim_gate_floor`` flipped from 1 to 0. The previous default
("keep at least 1 candidate even if all are below threshold") let
irrelevant skills reach the agent's context and the Q-table's
n_retrievals++ counter. Strict mode (floor=0) returns an empty
top-k and the hook emits a "no relevant skills" deny message.

These tests cover:
  1. format_top_k returns the explicit empty-case text when top_k=[]
  2. format_top_k still formats the ranked list for non-empty case
  3. score_skills with sim_gate_floor=0 + all sim<threshold → []
  4. score_skills with sim_gate_floor=0 + some sim>=threshold → only those
  5. score_skills with sim_gate_floor=1 (legacy) → at least 1 candidate
  6. MethodConfig default for sim_gate_floor is 0
"""
from __future__ import annotations
import numpy as np
import pytest


def _make_skills(n: int, sims: list[float] | None = None) -> list[dict]:
    """Build n dummy skill dicts. If sims given, used as cosine output
    by stubbing the emb cache lookup; we test via the actual hook path."""
    skills = []
    for i in range(n):
        skills.append({
            "skill_id": f"skill-{i}",
            "description": f"skill {i}",
            "n_retrievals": 0,
            "n_uses": 0,
            "n_success": 0,
        })
    return skills


def testformat_top_k_empty_explicit_message():
    """Empty top-k → 'no relevant skills' text (strict mode)."""
    from skillq.layers.l1_retrieval.force_use_text import format_top_k

    msg = format_top_k([])
    assert "No skills" in msg
    assert "below" in msg and "0.7" in msg
    assert "Solve this directly" in msg or "solve" in msg.lower()
    # The old "Top-0 ... Re-call Skill with one of these" wording
    # should NOT appear.
    assert "Top-0" not in msg
    assert "Re-call Skill with one of these" not in msg


def testformat_top_k_non_empty_uses_must_call():
    """Non-empty top-k gets the ranked list + MUST-call closing line.

    2026-06-26 (force-use): the previous advisory closing "Re-call
    Skill with one of these, or skip if none fit." was sharpened to
    "You MUST call Skill() with one of these — re-issue the Skill()
    call before continuing." This test now asserts the new text.
    """
    from skillq.layers.l1_retrieval.force_use_text import format_top_k

    msg = format_top_k([("skill-A", 0.42), ("skill-B", 0.18)])
    assert "Top-2" in msg
    assert "skill-A" in msg
    assert "skill-B" in msg
    assert "You MUST call Skill() with one of these" in msg
    # Old advisory wording is gone.
    assert "or skip if none fit" not in msg


def testscore_skills_strict_floor_zero_no_survivors():
    """sim_gate_floor=0 + every sim<0.7 → empty top-k.

    Strict mode (2026-06-25): no fallback candidate. Empty result
    is the expected behavior — agent sees 'no relevant skills'.
    """
    from skillq.layers.l1_retrieval.scoring import score_skills

    skills = _make_skills(3)
    # All candidates have null embedding → sim=0.0 for all
    emb_cache = {}  # empty
    subtask_emb = np.array([0.1, 0.2, 0.3], dtype=np.float32)

    top_k = score_skills(
        subtask_emb=subtask_emb,
        skills=skills,
        q_table={},
        emb_cache=emb_cache,
        lambda_=0.5,
        c_ucb=0.0,
        top_k=3,
        sim_gate_threshold=0.7,
        sim_gate_floor=0,    # strict
        sim_gate_min_score=0.7,
        score_mode="multiplicative",
    )
    assert top_k == []


def testscore_skills_strict_floor_zero_some_above_threshold():
    """sim_gate_floor=0 + some sim>=0.7 → only those pass through."""
    from skillq.layers.l1_retrieval.scoring import score_skills

    skills = _make_skills(3)
    # Embed cache where skill-0 is highly similar, skill-1/2 are orthogonal
    emb_cache = {
        "skill-0": np.array([1.0, 0.0, 0.0], dtype=np.float32),
        "skill-1": np.array([0.0, 1.0, 0.0], dtype=np.float32),
        "skill-2": np.array([0.0, 0.0, 1.0], dtype=np.float32),
    }
    subtask_emb = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    # sim(skill-0, query) = 1.0, sim(skill-1) = 0.0, sim(skill-2) = 0.0

    top_k = score_skills(
        subtask_emb=subtask_emb,
        skills=skills,
        q_table={},
        emb_cache=emb_cache,
        lambda_=0.5,
        c_ucb=0.0,
        top_k=3,
        sim_gate_threshold=0.7,
        sim_gate_floor=0,    # strict
        sim_gate_min_score=0.7,
        score_mode="multiplicative",
    )
    # Only skill-0 should pass the 0.7 gate; skill-1/2 are at sim=0.
    assert len(top_k) == 1
    assert top_k[0][0] == "skill-0"


def testscore_skills_legacy_floor_keeps_exactly_n_fallbacks():
    """sim_gate_floor=1 (legacy) + all sim<0.7 → keep top-1 by raw sim.

    With the 2026-06-25 fix, when the gate would leave fewer than
    ``sim_gate_floor`` candidates, we keep the top-N by raw sim
    (not the entire pre-gate list). This is a tightening of the
    old fall-through: previously, when 0 skills passed the 0.7
    gate, ALL skills were returned and scored; now we keep
    exactly sim_gate_floor of them. Users who want the old
    behavior can set sim_gate_floor to len(skills).
    """
    from skillq.layers.l1_retrieval.scoring import score_skills

    skills = _make_skills(3)
    emb_cache = {}  # all sim=0
    subtask_emb = np.array([0.1, 0.2, 0.3], dtype=np.float32)

    top_k = score_skills(
        subtask_emb=subtask_emb,
        skills=skills,
        q_table={},
        emb_cache=emb_cache,
        lambda_=0.5,
        c_ucb=0.0,
        top_k=3,
        sim_gate_threshold=0.7,
        sim_gate_floor=1,    # keep top-1 by sim
        sim_gate_min_score=0.7,
        score_mode="multiplicative",
    )
    # Strict: keep EXACTLY 1, not 3.
    assert len(top_k) == 1
    sid, score = top_k[0]
    assert sid in {"skill-0", "skill-1", "skill-2"}
    assert score == 0.0  # γ·UCB only (sim=0), UCB disabled → 0


def test_method_config_default_sim_gate_floor_is_zero():
    """Default flipped from 1 to 0 on 2026-06-25 (strict mode)."""
    from skillq.config import MethodConfig

    cfg = MethodConfig()
    assert cfg.sim_gate_floor == 0


def test_explicit_sim_gate_floor_preserved():
    """User can still set sim_gate_floor=1 for legacy behavior."""
    from skillq.config import MethodConfig

    cfg = MethodConfig(sim_gate_floor=1)
    assert cfg.sim_gate_floor == 1


def test_hook_sim_gate_floor_env_var_default_is_zero():
    """Container-side hook.py:147 reads SKILLQ_SIM_GATE_FLOOR with
    default '1' (legacy). Update to '0' to align with MethodConfig.
    """
    import inspect
    from pathlib import Path

    hook_src = (Path(__file__).resolve().parent.parent
                / "skillq" / "runtime" / "hook.py").read_text()
    # The env var line should now default to "0", not "1"
    assert 'os.environ.get("SKILLQ_SIM_GATE_FLOOR", "0")' in hook_src
    assert 'os.environ.get("SKILLQ_SIM_GATE_FLOOR", "1")' not in hook_src


def testformat_pull_context_empty_explicit_message():
    """Pull-mode (SessionStart) empty top-k → 'no relevant skills' text.

    Pull-mode delivers context as additionalContext, not as a deny
    decision. Strict mode: if no skill is above the sim gate, the
    agent gets the same explicit "don't invoke Skill, solve
    directly" instruction (no confusing "Top-0 skills..." header).
    """
    from skillq.layers.l1_retrieval.force_use_text import format_pull_context

    msg = format_pull_context([], _make_skills(3))
    assert "No skills" in msg
    assert "Don't invoke the Skill tool" in msg
    # Old confusing header should be gone.
    assert "Top-0" not in msg


def testformat_pull_context_non_empty_unchanged():
    """Non-empty top-k still gets the ranked reminder list."""
    from skillq.layers.l1_retrieval.force_use_text import format_pull_context

    skills = [
        {"skill_id": "a", "description": "alpha skill", "n_retrievals": 0},
        {"skill_id": "b", "description": "beta skill", "n_retrievals": 0},
    ]
    msg = format_pull_context([("a", 0.8), ("b", 0.5)], skills)
    assert "Top-2" in msg
    assert "alpha skill" in msg
    assert "beta skill" in msg
