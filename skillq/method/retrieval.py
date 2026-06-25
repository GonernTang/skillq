"""Embedder backends used by the SkillQ host-side bridge.

The runtime retrieval algorithm lives in
``skillq/skillq_runtime/hook.py:_score_skills`` (Hard Gate + multiplicative
scoring + UCB exploration), which runs inside the agent container where
only pure-Python stdlib is available. This module provides the embedder
implementations the host uses for:

  - Pre-dumping skill description embeddings to ``emb_cache.json``
    (``LiteLLMEmbedder``).
  - Computing the Q-update cosine weight on the host
    (``skillq/method/vector_table.py:sync_lib_to_vector_table``).
  - Tests (``StubEmbedder``).

The paper's Eq. 4 retrieval (TwoStageRanker, Phase A cosine recall + Phase B
z-scored UCB re-rank) is the historical reference implementation that was
superseded by the runtime hook; it was removed in 2026-06-25.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np


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
        import os
        import litellm

        # Read EMBEDDING_* env vars and translate to the OpenAI-
        # compatible equivalents litellm expects. The base class
        # used to read OPENAI_API_KEY / OPENAI_API_BASE only, which
        # forced callers to mirror the same env under a different
        # name. We now prefer EMBEDDING_* and fall back to OPENAI_*
        # so the existing SkillsVote / paper smoke configs that
        # already set EMBEDDING_BASE_URL keep working.
        kwargs: dict = {"encoding_format": "float"}
        emb_key = os.environ.get("EMBEDDING_API_KEY")
        emb_base = os.environ.get("EMBEDDING_BASE_URL")
        openai_key = os.environ.get("OPENAI_API_KEY")
        openai_base = os.environ.get("OPENAI_API_BASE")
        if emb_key:
            kwargs["api_key"] = emb_key
        elif openai_key:
            kwargs["api_key"] = openai_key
        if emb_base:
            kwargs["api_base"] = emb_base
        elif openai_base:
            kwargs["api_base"] = openai_base

        # DashScope's text-embedding-v3/v4 endpoints reject batch
        # sizes > 10. Some OpenAI-compatible endpoints do too. We
        # chunk into EMBED_BATCH_SIZE windows (default 10) to stay
        # under the cap. The default matches the DashScope limit
        # specifically; users on a different provider can bump
        # EMBED_BATCH_SIZE to push more per call.
        batch_size = int(os.environ.get("EMBED_BATCH_SIZE", "10"))
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            chunk = list(texts[i : i + batch_size])
            response = litellm.embedding(
                model=self.model,
                input=chunk,
                **kwargs,
            )
            all_vectors.extend(item["embedding"] for item in response.data)
        return np.asarray(all_vectors, dtype=np.float32)


__all__ = [
    "Embedder",
    "StubEmbedder",
    "LiteLLMEmbedder",
]