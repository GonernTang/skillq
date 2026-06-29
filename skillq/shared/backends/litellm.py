"""Unified LiteLLM-backed LLM + embedder backends.

Merges three legacy modules into one:

- :mod:`skillq.shared.backends.litellm` (Step 1, 2026-06-26)
- :mod:`skillq.shared.backends.litellm` (embedders)
- :mod:`skillq.shared.backends.litellm` (edit proposal)

Attribution backends (:class:`AttributionBackend`,
:class:`LiteLLMAttributionBackend`, :class:`StubAttributionBackend`)
stay in :mod:`skillq.layers.l3_attribution` for now; Step 2 of
the refactor moves that file to :mod:`skillq.layers.l3_attribution`.
Here we only consolidate the cross-cutting LLM call wrapper plus
the embedder + edit proposal backends.

Design intent (unchanged from legacy): one
:class:`LiteLLMCompletion` per LLM-call category, so the bridge
code can name the boundary between verifier / editor / attribution
even when the runtime behaviour is identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

import numpy as np


# ---------------------------------------------------------------------------
# LiteLLMCompletion — the single LLM-call primitive
# ---------------------------------------------------------------------------
@dataclass
class LiteLLMCompletion:
    """One call to ``litellm.completion``; default settings in the dataclass."""

    model: str = "openai/gpt-4o"
    temperature: float = 0.0
    # When non-None, passed as ``response_format`` to ``litellm.completion``.
    # Used by the attribution backend to force JSON output.
    response_format: dict[str, str] | None = None

    def __call__(self, prompt: str, model: str | None = None) -> str:
        import litellm

        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
        }
        if self.response_format is not None:
            kwargs["response_format"] = self.response_format
        response = litellm.completion(**kwargs)
        return response.choices[0].message.content or ""


class LiteLLMEditBackend(LiteLLMCompletion):
    """LiteLLM-backed edit-proposal backend (Sec. 3.4, Layer 4).

    Kept as a named class (rather than instantiating
    :class:`LiteLLMCompletion` directly at the call site) so the bridge
    code makes the editor / verifier boundary explicit, as called
    out in Sec. 3.2 of the paper. Today the runtime behaviour is
    identical to :class:`LiteLLMCompletion` (no overrides); a future
    per-backend tweak (max_tokens, reasoning_effort, ...) goes here
    without touching the bridge.
    """


# ---------------------------------------------------------------------------
# Embedder protocol + LiteLLM-backed impl + stub for tests
# ---------------------------------------------------------------------------
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
    ``skillq.services.ranking_service`` FastAPI wrapper exposes this
    embedder to the container-side hook over HTTP.
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
    "LiteLLMCompletion",
    "LiteLLMEditBackend",
    "Embedder",
    "StubEmbedder",
    "LiteLLMEmbedder",
]