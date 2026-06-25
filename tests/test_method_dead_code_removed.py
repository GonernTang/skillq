"""Verify the 2026-06-25 dead-code purge is complete.

After the purge:
  - ``skillq/method/layered_q.py`` and ``skillq/method/verifier.py``
    no longer exist.
  - ``BetaLayeredQ`` / ``IndependentVerifier`` / ``TwoStageRanker` /
    ``Verdict`` / ``RetrievalResult`` / ``VERIFIER_PROMPT`` /
    ``forgetting_rate_upper_bound`` / theorem helpers are not
    importable.
  - ``MethodConfig`` no longer carries ``alpha`` / ``beta`` /
    ``increment_clip`` (those were the Eq. 6 ``BetaLayeredQ`` knobs).
  - ``experiments/run/kappa_sweep.py`` is gone.
"""
from __future__ import annotations

import pytest


DEAD_MODULES = [
    "skillq.method.layered_q",
    "skillq.method.verifier",
]

DEAD_SYMBOLS = [
    "BetaLayeredQ",
    "IndependentVerifier",
    "TwoStageRanker",
    "RetrievalResult",
    "Verdict",
    "LiteLLMVerifierBackend",
    "StubVerifierBackend",
    "VerifierBackend",
    "batch_score",
    "VERIFIER_PROMPT",
    "increment_clip",
    "check_improvement_penalty_resolution",
    "expected_variance",
    "variance_bound",
    "improvement_penalty_threshold",
    "forgetting_rate_upper_bound",
    "QValueLookup",
    "zscore",
]


def test_dead_modules_unimportable():
    """Whole-file dead modules must raise ModuleNotFoundError on import."""
    for mod in DEAD_MODULES:
        with pytest.raises(ModuleNotFoundError):
            __import__(mod)


def test_dead_symbols_not_in_method_init():
    """None of the dead symbols is re-exported by skillq.method."""
    import skillq.method as m

    for sym in DEAD_SYMBOLS:
        assert not hasattr(m, sym), (
            f"skillq.method.{sym} should be deleted but is still importable"
        )


def test_method_config_alpha_beta_increment_clip_removed():
    """Eq. 6 BetaLayeredQ knobs were only consumed by the deleted class;
    MethodConfig no longer carries them."""
    from skillq.skillq_runtime.config import MethodConfig

    cfg = MethodConfig()
    assert not hasattr(cfg, "alpha"), (
        "MethodConfig.alpha was the BetaLayeredQ learning rate; deleted"
    )
    assert not hasattr(cfg, "beta"), (
        "MethodConfig.beta was the Eq. 6 r_learning blend; deleted"
    )
    assert not hasattr(cfg, "increment_clip"), (
        "MethodConfig.increment_clip was the BetaLayeredQ safety guard; deleted"
    )


def test_method_config_q_alpha_preserved():
    """The runtime Eq. 5 learning rate is still here."""
    from skillq.skillq_runtime.config import MethodConfig

    cfg = MethodConfig()
    assert hasattr(cfg, "q_alpha")
    assert 0.0 < cfg.q_alpha <= 1.0


def test_kappa_sweep_removed():
    """experiments/run/kappa_sweep.py was the only consumer of
    IndependentVerifier; it is gone."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    kappa_path = repo_root / "experiments" / "run" / "kappa_sweep.py"
    assert not kappa_path.exists(), (
        f"experiments/run/kappa_sweep.py should be deleted; found at {kappa_path}"
    )


def test_live_symbols_still_present():
    """Sanity check: the symbols runtime actually uses are still
    importable from skillq.method."""
    import skillq.method as m

    expected = [
        "Skill", "Qlib",
        "LibManager",
        "QlibState",
        "VectorTable", "sync_lib_to_vector_table",
        "SkillExtractor",
        "EditRefiner",
        "AttributionAnalyzer", "LiteLLMAttributionBackend",
        "LiteLLMEmbedder",
        "mirror_skill_to_host_dir",
        "sync_embed",
        "LiteLLMEditBackend",
        "qhash",
    ]
    for sym in expected:
        assert hasattr(m, sym), f"skillq.method.{sym} should still be importable"


def test_method_init_docstring_mentions_purge():
    """The module docstring should explicitly note the 2026-06-25 purge
    so future readers understand why the surface is smaller than the
    paper describes."""
    import skillq.method

    doc = skillq.method.__doc__ or ""
    assert "2026-06-25" in doc
    assert "dead-code purge" in doc.lower() or "dead-code" in doc.lower()