"""Two-stage retrieval with UCB bonus (Sec. 3.1, Eq. 4 of the paper,
global-Q variant).

Phase A: cosine-similarity recall (top-$k_1$).
Phase B: re-rank by

    score(s, m) = (1 - lambda) * sim_z + lambda * q_z
                + c_ucb * sqrt(log N / (n_m + 1))

**Global-Q refactor (per user design 2026-06-11)**:

- The Q-value read in Phase B is the **single global Q** per skill
  (``mgr.q_table[skill_id]``), not a per-(intent, skill) entry.
- ``rank`` and ``retrieve_for_intent`` no longer take ``intent_hash`` or
  a ``q_for(intent_hash, skill_id)`` callable; they take a plain
  ``Dict[str, float]`` Q-table (or a one-arg ``q_for(skill_id)`` callable).
- z-scoring is still done over the Phase-A pool for normalisation, but
  across the single dimension (skill_id).

The UCB bonus guarantees $\\Theta(\\log N)$ exploration of every skill and
prevents the cold-start trap (Sec. 3.3).

This module is the mg-side rewrite of
``skillsvote/src/skills_vote/retrieval.py``. Renamed ``TwoPhaseRetriever`` →
``TwoStageRanker``; z-score and cosine helpers extracted as public functions;
embedder pluggable via a :class:`Embedder` protocol with a deterministic
:class:`StubEmbedder` for tests and a :class:`LiteLLMEmbedder` for production.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Protocol, Sequence

import numpy as np

from skillq.method.types import RetrievalResult, Skill


class Embedder(Protocol):
    """An embedding backend (e.g., text-embedding-3-large via LiteLLM)."""

    def __call__(self, texts: Sequence[str]) -> np.ndarray: ...


class StubEmbedder:
    """Deterministic hash-based embedder for unit tests (no API calls).

    Limited to the first 16 characters of each input — for unit tests
    only. Use :class:`LiteLLMEmbedder` for production.
    """

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

    Default model: ``text-embedding-3-small`` (1536 dim). The companion
    ``paper/method/embedding_service.py`` is the FastAPI wrapper that
    exposes this embedder to the container-side hook over HTTP.
    """

    model: str = "openai/text-embedding-3-small"
    dim: int = 1536

    def __call__(self, texts: Sequence[str]) -> np.ndarray:
        import litellm

        response = litellm.embedding(
            model=self.model,
            input=list(texts),
            encoding_format="float",
        )
        vectors = [item["embedding"] for item in response.data]
        return np.asarray(vectors, dtype=np.float32)


# Callable signature for the global-Q refactor: skill_id → raw Q-value.
QValueLookup = Callable[[str], float]


@dataclass
class TwoStageRanker:
    """Two-stage retrieval: similarity recall, then UCB-augmented re-rank.

    Reads a single global Q value per skill (Eq. 4 of the paper, global
    variant). z-scoring is done across the Phase-A pool for sim and Q
    separately before the linear combination.
    """

    embedder: Embedder
    k1: int = 10
    k2: int = 3
    lambda_: float = 0.5
    c_ucb: float = 0.5

    def _score_pool(
        self,
        skills: List[Skill],
        sims: np.ndarray,
        q_value_lookup: QValueLookup,
        total_retrievals: int,
        top_k1_idx: np.ndarray,
    ) -> List[RetrievalResult]:
        """Score the Phase-A pool and return the top-k2 as RetrievalResults."""
        if len(top_k1_idx) == 0:
            return []
        sims_pool = sims[top_k1_idx]
        sims_z = zscore(sims_pool)
        raw_q = np.array(
            [q_value_lookup(skills[int(i)].skill_id) for i in top_k1_idx]
        )
        q_z = zscore(raw_q)

        scored: list[tuple[int, float]] = []
        for phase_b_rank, idx in enumerate(top_k1_idx):
            skill = skills[int(idx)]
            sim_norm = float(sims_z[phase_b_rank])
            q_norm = float(q_z[phase_b_rank])
            ucb = self.c_ucb * math.sqrt(
                math.log(max(total_retrievals, 2)) / (skill.n_retrievals + 1)
            )
            score = (1.0 - self.lambda_) * sim_norm + self.lambda_ * q_norm + ucb
            scored.append((int(idx), score))

        scored.sort(key=lambda pair: -pair[1])
        top_k2 = scored[: self.k2]
        # Build a phase_a_rank lookup for the top_k2 entries
        phase_a_rank_of = {int(idx): r for r, idx in enumerate(top_k1_idx)}
        results: list[RetrievalResult] = []
        for phase_b_rank, (idx, score) in enumerate(top_k2):
            results.append(
                RetrievalResult(
                    skill=skills[idx],
                    score=score,
                    phase_a_rank=phase_a_rank_of[idx],
                    phase_b_rank=phase_b_rank,
                )
            )
        return results

    def rank(
        self,
        query: str,
        skills: List[Skill],
        q_value_lookup: QValueLookup,
        total_retrievals: int,
    ) -> List[RetrievalResult]:
        """Return the top-$k_2$ skills by Eq. 4 (global-Q variant)."""
        if not skills:
            return []

        q_emb = self.embedder([query])
        s_emb = self.embedder([s.body for s in skills])
        sims = cosine(q_emb, s_emb).flatten()

        top_k1_idx = np.argsort(-sims)[: self.k1]
        return self._score_pool(
            skills=skills,
            sims=sims,
            q_value_lookup=q_value_lookup,
            total_retrievals=total_retrievals,
            top_k1_idx=top_k1_idx,
        )

    def retrieve_for_intent(
        self,
        query: str,
        lib,
        q_table: Mapping[str, float] | None = None,
        q_for: QValueLookup | None = None,
    ) -> List[RetrievalResult]:
        """Convenience: rank against a live :class:`Qlib` and a global Q-table.

        Either ``q_table`` (a ``Dict[str, float]``) or ``q_for`` (a
        ``Callable[[str], float]``) must be supplied. ``q_for`` wins if
        both are given.

        z-scores both sim and Q across the Phase-A pool before applying
        Eq. 4.
        """
        skills = list(lib.skills.values())
        if not skills:
            return []

        if q_for is not None:
            lookup = q_for
        elif q_table is not None:
            table = q_table
            lookup = table.get  # type: ignore[assignment]
        else:
            raise ValueError("retrieve_for_intent: supply q_table or q_for")

        q_emb = self.embedder([query])
        s_emb = self.embedder([s.body for s in skills])
        sims = cosine(q_emb, s_emb).flatten()
        top_k1_idx = np.argsort(-sims)[: self.k1]
        total_retrievals = sum(s.n_retrievals for s in skills) + 1

        return self._score_pool(
            skills=skills,
            sims=sims,
            q_value_lookup=lookup,
            total_retrievals=total_retrievals,
            top_k1_idx=top_k1_idx,
        )


__all__ = [
    "Embedder",
    "StubEmbedder",
    "LiteLLMEmbedder",
    "TwoStageRanker",
    "QValueLookup",
    "zscore",
    "cosine",
]
