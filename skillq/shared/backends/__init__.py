"""LLM / embedder backends (Step 1 of 2026-06-26 refactor).

Re-exports the unified LiteLLM-backed primitives from
:mod:`skillq.shared.backends.litellm`. The legacy
``skillq.shared.backends.litellm`` module consolidates the former ``_litellm``, ``retrieval``, and ``editor_backend`` backends
are now thin shims that point here; Step 7 deletes them.
"""
from skillq.shared.backends.litellm import *  # noqa: F401,F403
from skillq.shared.backends.litellm import (  # noqa: F401
    LiteLLMCompletion,
    LiteLLMEditBackend,
    Embedder,
    StubEmbedder,
    LiteLLMEmbedder,
)

__all__ = [
    "LiteLLMCompletion",
    "LiteLLMEditBackend",
    "Embedder",
    "StubEmbedder",
    "LiteLLMEmbedder",
]