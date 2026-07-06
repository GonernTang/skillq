"""L1 retrieval: Eq. 4 scoring + Hard Gate (SINGLE source of truth).

Step 2 of the 2026-06-26 refactor extracted this from
``skillq.layers.l1_retrieval.scoring.score_skills`` (the container-side
inline implementation). From Step 3 onward the same algorithm is
re-used by:

- :mod:`skillq.services.ranking_service` — the host-side ``/rank``
  HTTP endpoint called from the container hook.
- The host-side pull-mode CLAUDE.md renderer (re-ranks cached skills
  before injecting the additionalContext reminder).

Container-side use: the container hook (Step 5's new ``runtime/hook.py``)
does NOT reimplement Eq.4 — it calls ``/rank`` and gets the scored top-k
back as JSON. The legacy hook that did inline Eq.4 is preserved as a
parity reference and a rollback target; see
:mod:`skillq.layers.l1_retrieval.scoring` for the canonical
implementation and :file:`tests/l1_retrieval/test_scoring_parity.py`
for the bit-exact contract test.

Two scoring formulas (controlled by ``score_mode``):

- ``"additive"`` (legacy Eq.4):
      score = (1-λ)·sim_z + λ·q_z + c_ucb·√(log N/(n+1))
  sim_z / q_z are z-scored within the (post-gate) batch. After
  z-scoring, a low-sim skill can still rank high if its Q is above
  mean — irrelevant skills occasionally reach Top-K.

- ``"multiplicative"`` (2026-06-24, Fix 2):
      score = sim·(1 + β·Q_norm) + γ·UCB
  using RAW (non-z-scored) cosine. Critical property: when sim=0
  the entire sim term vanishes and the skill can only rank by its
  UCB exploration bonus — Q cannot promote an irrelevant skill.

Hard Gate (Fix 1): if ``sim_gate_threshold > 0``, candidates with
raw cosine < ``sim_gate_min_score`` are dropped before any z-scoring
or formula application. ``sim_gate_floor`` is the minimum number of
survivors — if the gate would leave fewer, the top-N by raw sim are
retained (so Top-K is never empty on early trials with poor embedding
coverage). With ``sim_gate_floor=0`` (the 2026-06-25 strict default),
no fallback is kept and an empty top-k means "no relevant skills".

If ``subtask_emb`` is None (embedding failed), every candidate gets
sim=0.0 and the gate drops all of them (strict mode); the result is
an empty top-k so the agent sees "no relevant skills" instead of a
Q+UCB-only ranking that has no relevance signal at all.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity between two equal-length vectors.

    Returns 0.0 when either vector is empty (the legacy hook's
    ``len(a) == 0 or len(b) == 0`` short-circuit). Uses a ``+1e-9``
    floor on the per-vector norm so the denominator is never zero —
    bit-exact with the legacy container-side inline implementation
    (which the parity test pins).

    Tolerates numpy arrays (the emb cache stores float32 vectors);
    the legacy hook comment ``'not a' raises on ndarray. Use
    len-based check`` still applies — we use ``len()`` not truthiness.
    """
    if len(a) == 0 or len(b) == 0:
        return 0.0
    na = math.sqrt(sum(x * x for x in a)) + 1e-9
    nb = math.sqrt(sum(x * x for x in b)) + 1e-9
    n = min(len(a), len(b))
    # Pin return type to Python ``float``. The pure-Python loop
    # already produces float when ``a`` / ``b`` are lists, but
    # ``emb_cache`` stores numpy.float32 vectors — without this cast
    # callers receive ``numpy.float32`` and Pydantic v2's serializer
    # chokes on it (Bug #1, 2026-06-30:
    # ``PydanticSerializationError: Unable to serialize unknown type:
    # <class 'numpy.float32'>`` at /rank → 500 → hook fails open).
    return float(sum(a[i] * b[i] for i in range(n)) / (na * nb))


_cosine = cosine  # legacy private alias used by the inline hook


def zscore(values: Sequence[float]) -> list[float]:
    """Population z-score per value: ``(v - mean) / std``.

    Uses a ``+1e-9`` floor on std so the denominator is never zero —
    bit-exact with the legacy container-side inline implementation
    (which the parity test pins). When all values are equal this
    still produces ``(mu / 1e-9)`` for each value, not ``[0] * n``.
    Empty input → ``[]``; single-element input → ``[0.0]``.
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.0]
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    sd = math.sqrt(var) + 1e-9
    return [(v - mean) / sd for v in values]


_zscore = zscore  # legacy private alias


# ---------------------------------------------------------------------------
# Hard Gate (kept separate so the gate rule is auditable in isolation)
# ---------------------------------------------------------------------------
def apply_hard_gate(
    skills: list[dict[str, Any]],
    sims: list[float],
    *,
    threshold: float,
    floor: int,
    min_score: float,
) -> tuple[list[dict[str, Any]], list[float]]:
    """Drop low-sim candidates before any scoring formula runs.

    Parameters
    ----------
    skills, sims : list
        The candidate skills and their raw cosine similarities to the
        query. Must be the same length; one skill per sim.
    threshold : float
        The hard-gate cutoff (0.0 disables the gate). When > 0, any
        candidate with sim < ``min_score`` is dropped.
    floor : int
        The minimum number of survivors. If the gate would leave fewer
        than ``floor`` candidates, the top-``floor`` by raw sim are
        kept instead (so Top-K is never empty on early trials with
        poor embedding coverage). ``floor=0`` (the 2026-06-25 strict
        default) means no fallback — empty top-k is the answer when
        nothing passes the gate.
    min_score : float
        The cosine similarity threshold. Candidates with sim < this
        are dropped when the gate is active. ``threshold`` (the on/off
        switch) is separate from ``min_score`` (the actual cutoff)
        so MethodConfig can disable the gate with ``threshold=0``
        without changing the cutoff value.

    Returns
    -------
    (filtered_skills, filtered_sims) : tuple
        The post-gate candidate list. May be empty when the gate is
        strict and no candidate passes.
    """
    if threshold <= 0.0 or not skills:
        return skills, sims
    gated = [(s, sim) for s, sim in zip(skills, sims) if sim >= min_score]
    if len(gated) >= floor:
        return [s for s, _ in gated], [sim for _, sim in gated]
    # Not enough survivors — keep top-floor by raw sim (descending).
    # floor=0 → kept=[] (strict mode).
    # floor=1 → kept=[best-by-sim].
    sorted_by_sim = sorted(zip(skills, sims), key=lambda pair: -pair[1])
    kept = sorted_by_sim[: max(floor, 0)]
    if not kept:
        return [], []
    return [s for s, _ in kept], [sim for _, sim in kept]


# ---------------------------------------------------------------------------
# Eq. 4 + Hard Gate pipeline (THE single source of truth)
# ---------------------------------------------------------------------------
def score_skills(
    *,
    subtask_emb: Sequence[float] | None,
    skills: list[dict[str, Any]],
    q_table: dict[str, float],
    emb_cache: dict[str, list[float]],
    lambda_: float,
    c_ucb: float,
    top_k: int,
    # 2026-06-24: Hard Gate (Fix 1) — drop low-sim candidates before
    # scoring. sim_gate_threshold is the high-water threshold (≥ this
    # passes the gate). Backward-compat: caller passes the same value as
    # sim_gate_min_score from MethodConfig.
    sim_gate_threshold: float = 0.0,
    sim_gate_floor: int = 1,
    sim_gate_min_score: float = 0.05,
    # 2026-06-24: Multiplicative scoring (Fix 2) — switch formula.
    score_mode: str = "additive",
    mult_beta: float = 0.5,
    mult_gamma: float = 0.2,
    # 2026-06-29 (Phase 10 Bug 2): out-param carrying post-gate sims
    # in top-k order. /rank handler fills this so the calls_log can
    # persist per-trial L1 sims. List is cleared + re-populated.
    sims_out: list[float] | None = None,
) -> list[tuple[str, float]]:
    """Return top-k ``(skill_id, score)`` for a sub-task.

    See module docstring for the two scoring formulas and the
    Hard Gate semantics. The function is the SINGLE source of truth
    for Eq. 4 + Hard Gate; the legacy container-side
    :func:`skillq.layers.l1_retrieval.scoring.score_skills` is now a
    one-line wrapper around this function (kept for parity reference
    and rollback). The ``tests/l1_retrieval/test_scoring_parity.py``
    test pins the bit-exact contract.
    """
    # 1. Raw sim per candidate (Fail-open: missing emb → sim=0)
    sims: list[float] = []
    for s in skills:
        sid = s["skill_id"]
        cached = emb_cache.get(sid)
        if subtask_emb is not None and cached is not None:
            sims.append(cosine(subtask_emb, cached))
        else:
            sims.append(0.0)

    # 2. Hard Gate (Fix 1) — drop low-sim candidates
    skills, sims = apply_hard_gate(
        skills, sims,
        threshold=sim_gate_threshold,
        floor=sim_gate_floor,
        min_score=sim_gate_min_score,
    )
    if not skills:
        return []

    # 3. Q-values per candidate (needed for both modes)
    qs = [q_table.get(s["skill_id"], 0.0) for s in skills]

    # 4. UCB term (used by both modes)
    n_total = max(int(sum(s.get("n_retrievals", 0) for s in skills)), 1) + 1

    scored: list[tuple[str, float]] = []

    if score_mode == "multiplicative":
        # Fix 2: sim·(1 + β·Q) + γ·UCB
        # 2026-06-29 (Phase 10 Bug 1): hard-coded Q clamp to [0, 1]
        # as a numerical guard. Previously callers could customise
        # the clamp range via q_clip_min/q_clip_max knobs, but the
        # only meaningful setting was [0, 1] (matching Q-table's
        # intended range). All caller-facing knobs are removed.
        for s, sim, q in zip(skills, sims, qs):
            sid = s["skill_id"]
            q_used = max(0.0, min(1.0, q))
            n = int(s.get("n_retrievals", 0)) + 1
            ucb = c_ucb * math.sqrt(math.log(max(n_total, 2)) / n)
            score = sim * (1.0 + mult_beta * q_used) + mult_gamma * ucb
            scored.append((sid, float(score)))
    else:
        # Legacy Eq.4: (1-λ)·sim_z + λ·q_z + c_ucb·√(log N/(n+1))
        sims_z = zscore(sims) if len(sims) > 1 else [0.0] * len(sims)
        qs_z = zscore(qs) if len(qs) > 1 else [0.0] * len(qs)
        for s, sim_z, q_z in zip(skills, sims_z, qs_z):
            sid = s["skill_id"]
            n = int(s.get("n_retrievals", 0)) + 1
            ucb = c_ucb * math.sqrt(math.log(max(n_total, 2)) / n)
            score = (1.0 - lambda_) * sim_z + lambda_ * q_z + ucb
            scored.append((sid, float(score)))

    scored.sort(key=lambda x: -x[1])
    top_k_pairs = scored[:top_k]

    # 2026-06-29 (Phase 10 Bug 2): thread post-gate sims back to caller
    # so /rank handler can persist them in calls_log.l1_sims. Sim is
    # keyed by skill_id (not by post-sort index) so the post-truncation
    # list aligns with top_k_pairs in order.
    if sims_out is not None:
        sims_by_id = dict(zip([s["skill_id"] for s in skills], sims))
        sims_out.clear()
        sims_out.extend(sims_by_id.get(sid, 0.0) for sid, _ in top_k_pairs)

    return top_k_pairs


# Legacy private aliases — kept so ``from skillq.layers.l1_retrieval.scoring
# import _score_skills`` (the old container-hook name) still works for
# any parity-test or backward-compat code path.
_score_skills = score_skills


__all__ = [
    "cosine",
    "zscore",
    "apply_hard_gate",
    "score_skills",
]