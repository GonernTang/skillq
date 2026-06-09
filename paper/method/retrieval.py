"""Two-stage retrieval with UCB bonus (Sec. 3.1, Eq. 4 of the paper).

Phase A: cosine-similarity recall (top-$k_1$).
Phase B: re-rank by

    score(s, m) = (1 - lambda) * sim_z + lambda * q_z
                + c_ucb * sqrt(log N / (n_m + 1))

The UCB bonus guarantees $\\Theta(\\log N)$ exploration of every skill and
prevents the cold-start trap (Sec. 3.3).

This module is the mg-side rewrite of
``implementation_guide/lqrl/retrieval.py``. Renamed ``TwoPhaseRetriever`` →
``TwoStageRanker``; z-score and cosine helpers extracted as public functions;
embedder pluggable via a :class:`Embedder` protocol with a deterministic
:class:`StubEmbedder` for tests and a :class:`LiteLLMEmbedder` for production.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, List, Protocol, Sequence

import numpy as np

from paper.method.hash import qhash
from paper.method.types import RetrievalResult, Skill


class Embedder(Protocol):
    """An embedding backend (e.g., text-embedding-3-large via LiteLLM)."""

    def __call__(self, texts: Sequence[str]) -> np.ndarray: ...


class StubEmbedder:
    """Deterministic hash-based embedder for unit tests (no API calls)."""

    def __call__(self, texts: Sequence[str]) -> np.ndarray:
        out = np.zeros((len(texts), 16), dtype=np.float32)
        for i, text in enumerate(texts):
            for j, ch in enumerate(text[:16]):
                out[i, j] = (ord(ch) % 97) / 97.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms


def zscore(values: np.ndarray) -> np.ndarray:
    """Return the z-score of ``values`` with an ``1e-9`` floor on the std."""
    mu = values.mean()
    sd = values.std() + 1e-9
    return (values - mu) / sd


def cosine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Cosine similarity of each row of ``a`` against each row of ``b``."""
    a_n = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)
    b_n = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-9)
    return a_n @ b_n.T


@dataclass
class LiteLLMEmbedder:
    """Production embedder: delegates to ``litellm.embedding``.

    Default model: ``text-embedding-3-large``. Set ``dim`` to the
    expected output dimension; for ``text-embedding-3-large`` this is 3072.
    """

    model: str = "openai/text-embedding-3-large"
    dim: int = 3072

    def __call__(self, texts: Sequence[str]) -> np.ndarray:
        import litellm

        # litellm.embedding accepts a list of strings; one batch call is
        # cheaper than per-text. ``encoding_format="float"`` keeps output
        # as a Python list[float] rather than base64.
        response = litellm.embedding(
            model=self.model,
            input=list(texts),
            encoding_format="float",
        )
        vectors = [item["embedding"] for item in response.data]
        return np.asarray(vectors, dtype=np.float32)


# Callable signature: skill_id → z-scored Q-value (the paper's $\hat{Q}$).
QValueLookup = Callable[[str], float]


@dataclass
class TwoStageRanker:
    """Two-stage retrieval: similarity recall, then UCB-augmented re-rank.

    Renamed from the implementation_guide's ``TwoPhaseRetriever`` so the
    naming is distinct from the upstream ``lqrl`` package, which doesn't
    ship a retriever of its own.
    """

    embedder: Embedder
    k1: int = 10
    k2: int = 3
    lambda_: float = 0.5
    c_ucb: float = 0.5

    def rank(
        self,
        query: str,
        skills: List[Skill],
        q_value_lookup: QValueLookup,
        total_retrievals: int,
    ) -> List[RetrievalResult]:
        """Return the top-$k_2$ skills by Eq. 4 of the paper.

        ``q_value_lookup(skill_id)`` must return the *z-scored* Q-value
        $\\hat{Q}(s, m)$ (already normalised across the candidate set).
        The :class:`paper.method.bridge` glue is responsible for this
        normalisation; here we trust the caller.
        """
        if not skills:
            return []

        q_emb = self.embedder([query])
        s_emb = self.embedder([s.body for s in skills])
        sims = cosine(q_emb, s_emb).flatten()

        # Phase A: top-k1 by raw similarity
        top_k1_idx = np.argsort(-sims)[: self.k1]
        phase_a = [(int(i), float(sims[i])) for i in top_k1_idx]

        # Phase B: re-rank the Phase-A pool with z-scored sim + z-scored Q + UCB
        sims_z = zscore(np.array([s for _, s in phase_a]))
        scored: list[tuple[int, float]] = []
        for rank, (idx, _) in enumerate(phase_a):
            skill = skills[idx]
            sim_norm = float(sims_z[rank])
            q_norm = q_value_lookup(skill.skill_id)
            ucb = self.c_ucb * math.sqrt(
                math.log(max(total_retrievals, 2)) / (skill.n_retrievals + 1)
            )
            score = (1.0 - self.lambda_) * sim_norm + self.lambda_ * q_norm + ucb
            scored.append((idx, score))

        scored.sort(key=lambda pair: -pair[1])
        top_k2 = scored[: self.k2]

        results: list[RetrievalResult] = []
        for phase_b_rank, (idx, score) in enumerate(top_k2):
            phase_a_rank = next(r for r, (i, _) in enumerate(phase_a) if i == idx)
            results.append(
                RetrievalResult(
                    skill=skills[idx],
                    score=score,
                    phase_a_rank=phase_a_rank,
                    phase_b_rank=phase_b_rank,
                )
            )
        return results

    def retrieve_for_intent(
        self,
        query: str,
        lib,
        intent_hash: int,
        q_for: Callable[[int, str], float],
    ) -> List[RetrievalResult]:
        """Convenience: rank against a live :class:`Qlib` and a Q-table getter.

        ``q_for(intent_hash, skill_id)`` should return the *raw* (un-z-scored)
        Q-value; this method z-scores across the Phase-A pool before
        applying Eq. 4.
        """
        skills = list(lib.skills.values())
        if not skills:
            return []

        # Pull the raw Q-values for the Phase-A pool, then z-score them.
        q_emb = self.embedder([query])
        s_emb = self.embedder([s.body for s in skills])
        sims = cosine(q_emb, s_emb).flatten()
        top_k1_idx = np.argsort(-sims)[: self.k1]
        raw_q = np.array([q_for(intent_hash, skills[int(i)].skill_id) for i in top_k1_idx])
        q_z = zscore(raw_q)

        # total_retrievals = sum of all n_retrievals (paper convention)
        total_retrievals = sum(s.n_retrievals for s in skills) + 1

        results: list[RetrievalResult] = []
        for phase_b_rank, (idx, raw_q_value) in enumerate(zip(top_k1_idx, q_z, strict=True)):
            skill = skills[int(idx)]
            sim_norm = float(zscore(sims[top_k1_idx])[phase_b_rank])
            ucb = self.c_ucb * math.sqrt(
                math.log(max(total_retrievals, 2)) / (skill.n_retrievals + 1)
            )
            score = (1.0 - self.lambda_) * sim_norm + float(raw_q_value) * self.lambda_ + ucb
            results.append(
                RetrievalResult(
                    skill=skill,
                    score=score,
                    phase_a_rank=phase_b_rank,
                    phase_b_rank=phase_b_rank,
                )
            )
        results.sort(key=lambda r: -r.score)
        return results[: self.k2]


# Re-export for callers that want to re-use the qhash function.
__all__ = [
    "Embedder",
    "StubEmbedder",
    "LiteLLMEmbedder",
    "TwoStageRanker",
    "QValueLookup",
    "zscore",
    "cosine",
    "qhash",
]
