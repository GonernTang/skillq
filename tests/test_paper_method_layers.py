"""Unit tests for the LQRL paper method's four layers.

This is the mg-side port of ``implementation_guide/lqrl/tests/test_core.py``.
Class names are renamed (``LibraryManager`` → ``LibManager``,
``SkillLibrary`` → ``Qlib``, ``LayeredQUpdate`` → ``BetaLayeredQ``) so
the tests target the mg API.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

# Make the parent layout importable when running ``pytest`` from the
# project root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mg.method.layered_q import (  # noqa: E402
    BetaLayeredQ,
    check_improvement_penalty_resolution,
    expected_variance,
    improvement_penalty_threshold,
    variance_bound,
)
from mg.method.library import (  # noqa: E402
    LibManager,
    forgetting_rate_upper_bound,
)
from mg.method.near_miss import NearMissRefiner, StubEditBackend  # noqa: E402
from mg.method.retrieval import StubEmbedder, TwoStageRanker  # noqa: E402
from mg.method.types import Qlib, Skill, Verdict  # noqa: E402
from mg.method.verifier import IndependentVerifier, StubVerifierBackend  # noqa: E402


# ---------------------------------------------------------------------------
# Layered Q-learning (Layer 2)
# ---------------------------------------------------------------------------
def test_layered_q_reduces_to_standard_q_when_beta_zero():
    """At $\\beta = 0$, the LQRL update must equal standard Q-learning."""
    updater = BetaLayeredQ(alpha=0.3, beta=0.0)
    q_old = 0.7
    r_task = 1.0
    r_learning = 0.5  # any value -- should be ignored
    expected = q_old + 0.3 * (r_task - q_old)
    assert math.isclose(updater.apply(q_old, r_task, r_learning), expected)


def test_layered_q_resolves_improvement_penalty_paradox():
    """Theorem 3: at $\\beta > \\beta^\\star = Q_{\\text{old}} / q$, a failed task
    with content improvement $q$ yields $\\Delta Q > 0$."""
    updater = BetaLayeredQ(alpha=0.3, beta=1.0)
    q_old = 0.3
    r_task = 0.0
    r_learning = 0.5
    # beta* = 0.3 / 0.5 = 0.6; beta=1.0 > 0.6 should give positive delta
    delta = updater.compute_increment(q_old, r_task, r_learning)
    assert delta > 0, f"Expected positive delta, got {delta:.4f}"


def test_improvement_penalty_threshold_formula():
    """$\\beta^\\star = Q_{\\text{old}} / q$ (Theorem 3)."""
    q_old = 0.4
    r_improvement = 0.2
    expected = 0.4 / 0.2  # = 2.0 (so no beta in [0,1] can resolve it alone)
    actual = improvement_penalty_threshold(q_old, r_improvement)
    assert math.isclose(actual, expected)


def test_check_improvement_penalty_resolution_helper():
    # q_old=0.4, r=0.0, r_learning=0.2, beta=0.9; beta* = 0.4/0.2 = 2.0
    # 0.9 < 2.0, so it should NOT resolve
    assert not check_improvement_penalty_resolution(0.4, 0.0, 0.2, 0.9)
    # With r_task = 1, the helper returns False regardless
    assert not check_improvement_penalty_resolution(0.4, 1.0, 0.2, 0.9)
    # Resolve: q_old=0.2 < q=0.4, beta=0.9 > 0.2/0.4 = 0.5
    assert check_improvement_penalty_resolution(0.2, 0.0, 0.4, 0.9)


def test_expected_variance_matches_definition():
    var_task = 0.1
    var_learning = 0.2
    cov = 0.05
    beta = 0.5
    expected = 0.25 * 0.1 + 0.25 * 0.2 + 2 * 0.25 * 0.05
    actual = expected_variance(0.3, var_task, var_learning, cov, beta)
    assert math.isclose(actual, expected)


# ---------------------------------------------------------------------------
# Variance bound (Theorem 1)
# ---------------------------------------------------------------------------
def test_variance_bound_equals_alpha_over_2_minus_alpha():
    alpha = 0.3
    sigma_sq = 0.5
    expected = alpha / (2.0 - alpha) * sigma_sq
    actual = variance_bound(alpha, sigma_sq)
    assert math.isclose(actual, expected)


def test_variance_bound_grows_with_alpha():
    assert variance_bound(0.5, 1.0) > variance_bound(0.1, 1.0)


# ---------------------------------------------------------------------------
# Forgetting-rate bound (Theorem 2)
# ---------------------------------------------------------------------------
def test_forgetting_rate_upper_bound_in_alpha():
    bound_a = forgetting_rate_upper_bound(0.1, 0.1, 1.0, 0.0)
    bound_b = forgetting_rate_upper_bound(0.5, 0.1, 1.0, 0.0)
    # Larger alpha => larger bound (other things equal)
    assert bound_b > bound_a


# ---------------------------------------------------------------------------
# Verifier (Layer 2)
# ---------------------------------------------------------------------------
def test_stub_verifier_returns_consistent_verdict():
    v = IndependentVerifier(backend=StubVerifierBackend(old_score=0.3, new_score=0.7))
    skill = Skill(skill_id="s1", body="body")
    verdict = v.score("task", skill, skill)
    assert math.isclose(verdict.old_score, 0.3)
    assert math.isclose(verdict.new_score, 0.7)
    assert verdict.improved
    assert math.isclose(verdict.r_learning, 0.4)


def test_verifier_handles_garbage_output_gracefully():
    """If the verifier returns non-JSON, we should get a no-improvement verdict."""

    class BadBackend:
        def __call__(self, prompt, model):
            return "I am unable to comply."

    v = IndependentVerifier(backend=BadBackend())
    verdict = v.score("task", Skill(skill_id="s1"), Skill(skill_id="s1"))
    assert not verdict.improved
    assert math.isclose(verdict.r_learning, 0.0)


# ---------------------------------------------------------------------------
# Library manager (Layer 3)
# ---------------------------------------------------------------------------
def test_library_manager_deprecates_low_q_after_exploration():
    lib = Qlib(b_max=50)
    mgr = LibManager(
        b_max=50,
        theta_admit=0.3,
        theta_evict=0.1,
        n_explore=5,
        n_stale=100,
    )
    skill = Skill(skill_id="low")
    lib.add(skill)

    # Simulate n_explore retrievals with low Q
    for _ in range(5):
        mgr.update_q(intent_hash=42, skill_id="low", delta=-0.1)

    events = mgr.maintain(lib, current_step=10)
    assert any("deprecate:low" in e for e in events)
    assert "low" in mgr.deprecation_list


def test_library_manager_evicts_to_maintain_b_max():
    lib = Qlib(b_max=2)
    mgr = LibManager(
        b_max=2,
        theta_admit=0.3,
        theta_evict=0.1,
        n_explore=5,
        n_stale=100,
    )
    # Add three skills with different Q-values
    for sid, q in [("a", 0.8), ("b", 0.2), ("c", 0.5)]:
        lib.add(Skill(skill_id=sid))
        mgr.update_q(intent_hash=1, skill_id=sid, delta=q)

    events = mgr.maintain(lib, current_step=1)
    # One of the lower-Q skills should have been evicted
    assert lib.size == 2
    assert any(e.startswith("evict:") for e in events)


def test_library_manager_marks_stale_skills():
    lib = Qlib(b_max=50)
    mgr = LibManager(
        b_max=50,
        theta_admit=0.3,
        theta_evict=0.1,
        n_explore=5,
        n_stale=10,
    )
    lib.add(Skill(skill_id="old"))
    mgr.mark_retrieved("old", current_step=1)
    # Don't retrieve for 20 steps (exceeds n_stale=10)
    events = mgr.maintain(lib, current_step=21)
    # Need n_explore updates to mark as stale-evict candidate
    for _ in range(5):
        mgr.update_q(intent_hash=1, skill_id="old", delta=0.0)
    events = mgr.maintain(lib, current_step=22)
    assert any("stale:old" in e for e in events) or any("lowq:old" in e for e in events)


# ---------------------------------------------------------------------------
# Verdict.r_learning clamping
# ---------------------------------------------------------------------------
def test_verdict_r_learning_clamped_to_unit_interval():
    v = Verdict(old_score=0.0, new_score=2.0, improved=True, rationale="")
    assert math.isclose(v.r_learning, 1.0)
    v2 = Verdict(old_score=1.0, new_score=-1.0, improved=False, rationale="")
    assert math.isclose(v2.r_learning, -1.0)


# ---------------------------------------------------------------------------
# mg-specific additions: retrieval + near-miss
# ---------------------------------------------------------------------------
def test_two_stage_ranker_returns_top_k2_in_descending_score():
    skills = [Skill(skill_id=f"s{i}", body=f"body {i} " * (i + 1)) for i in range(5)]
    ranker = TwoStageRanker(embedder=StubEmbedder(), k1=5, k2=2, lambda_=0.5, c_ucb=0.5)
    results = ranker.rank(
        query="body 0",
        skills=skills,
        q_value_lookup=lambda _: 0.0,
        total_retrievals=10,
    )
    assert len(results) == 2
    assert results[0].score >= results[1].score


def test_near_miss_refiner_accepts_any_size_edit():
    """The previous 20%-of-original-token cap has been removed: the
    LLM is free to rewrite as much or as little as it judges
    necessary. The stub backend appends a comment, which is
    accepted regardless of size.
    """
    refiner = NearMissRefiner(backend=StubEditBackend(), model="test")
    skill = Skill(skill_id="s1", body="short body here")
    out = refiner.propose_edit(skill, "task", "trace")
    # Accepted (the stub comment is appended; not the same skill).
    assert out.skill_id == skill.skill_id
    assert "NEAR-MISS" in out.body


def test_near_miss_refiner_keeps_original_on_empty_body():
    """Empty LLM response → keep the original skill unchanged."""

    class EmptyBackend:
        def __call__(self, prompt, model):
            return ""

    refiner = NearMissRefiner(backend=EmptyBackend(), model="test")
    skill = Skill(skill_id="s1", body="original body")
    out = refiner.propose_edit(skill, "task", "trace")
    assert out is skill  # same object — original returned


def test_near_miss_refiner_keeps_original_on_no_op_edit():
    """LLM echoes the original unchanged → keep the original skill."""

    class EchoBackend:
        def __call__(self, prompt, model):
            return "original body"

    refiner = NearMissRefiner(backend=EchoBackend(), model="test")
    skill = Skill(skill_id="s1", body="original body")
    out = refiner.propose_edit(skill, "task", "trace")
    assert out is skill
