"""LiteLLM-backed edit-proposal backend for :class:`paper.method.edit.EditRefiner`.

Thin subclass of :class:`paper.method._litellm.LiteLLMCompletion`.
Kept as a named class (rather than instantiating
``LiteLLMCompletion`` directly at the call site) so the bridge code
makes the editor / verifier boundary explicit, as called out in
Sec. 3.2 of the paper.
"""

from __future__ import annotations

from skillq.method._litellm import LiteLLMCompletion


class LiteLLMEditBackend(LiteLLMCompletion):
    """LiteLLM-backed edit-proposal backend (Sec. 3.4, Layer 4)."""
