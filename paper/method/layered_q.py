"""β-layered Q-learning (Sec. 3.2, Eq. 6 of the paper).

Standard Q-learning (Eq. 5):

    Q_new(s, m) = Q_old(s, m) + α * (r_task - Q_old(s, m))

LQRL update (Eq. 6, the core contribution):

    Q_new(s, m) = Q_old(s, m) + α * [
        (1 - β) * r_task + β * r_learning - Q_old(s, m)
    ]

where ``r_learning ∈ [-1, 1]`` is the *learning reward* supplied by the
informationally isolated verifier (:class:`paper.method.verifier.IndependentVerifier`).
"""

from __future__ import annotations

from dataclasses import dataclass

from paper.method.types import Verdict


@dataclass
class BetaLayeredQ:
    """Computes the β-layered Q-learning increment.

    Wraps Eq. 6 of the paper. Default ``alpha=0.3, beta=0.5`` match the
    Sec. 4.1 + 4.5 recommended values; ``beta=0`` reduces to standard
    Q-learning (Eq. 5).
    """

    alpha: float = 0.3
    beta: float = 0.5
    # Safety guard: cap each update magnitude to this range. The paper
    # does not require this, but the implementation_guide skeleton has
    # ``Verdict.r_learning`` already clamp to [-1, 1]; this guard catches
    # the Q_old drift case where ``α * (target - Q_old)`` becomes large.
    increment_clip: float = 1.0

    def compute_increment(self, q_old: float, r_task: float, r_learning: float) -> float:
        """Compute the Q-value increment ΔQ (Eq. 6)."""
        layered = (1.0 - self.beta) * r_task + self.beta * r_learning
        increment = self.alpha * (layered - q_old)
        if self.increment_clip is not None:
            increment = max(-self.increment_clip, min(self.increment_clip, increment))
        return increment

    def apply(self, q_old: float, r_task: float, r_learning: float) -> float:
        """Apply the update and return the new Q-value."""
        return q_old + self.compute_increment(q_old, r_task, r_learning)

    def apply_verdict(
        self,
        q_old: float,
        r_task: float,
        verdict: Verdict,
    ) -> float:
        """Convenience: apply using a verifier verdict for r_learning."""
        return self.apply(q_old, r_task, verdict.r_learning)


# ---------------------------------------------------------------------------
# Theoretical sanity helpers (mirrors of the paper's three theorems).
# ---------------------------------------------------------------------------
def check_improvement_penalty_resolution(
    q_old: float,
    r_task: float,
    r_learning: float,
    beta: float,
) -> bool:
    """Return ``True`` if the LQRL update gives a positive ΔQ for a failed
    task with content improvement (Theorem 3).

    Conditions: ``r_task == 0`` and ``r_learning > 0`` and
    ``β > Q_old / r_learning``.
    """
    if r_task != 0.0 or r_learning <= 0.0:
        return False
    threshold = q_old / r_learning
    return beta > threshold


def expected_variance(
    alpha: float,
    var_task: float,
    var_learning: float,
    cov: float,
    beta: float,
) -> float:
    """Variance of the layered reward signal.

    Var((1-β) r_task + β r_learning)
        = (1-β)^2 Var(r_task) + β^2 Var(r_learning)
          + 2 β (1-β) Cov(r_task, r_learning)
    """
    return (
        (1.0 - beta) ** 2 * var_task
        + beta ** 2 * var_learning
        + 2.0 * beta * (1.0 - beta) * cov
    )


def variance_bound(alpha: float, sigma_sq: float) -> float:
    """Variance bound from Theorem 1: ``α / (2 - α) * σ²``."""
    if alpha <= 0 or alpha >= 2:
        return float("inf")
    return alpha / (2.0 - alpha) * sigma_sq


def improvement_penalty_threshold(q_old: float, q_improvement: float) -> float:
    """β* from Theorem 3.

    The LQRL update is positive on a failed task with content improvement
    $q > 0$ iff ``β > Q_old / q``.
    """
    if q_improvement <= 0:
        return float("inf")
    return q_old / q_improvement
