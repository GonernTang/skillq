"""LiteLLM-backed edit-proposal backend for :class:`mg.method.near_miss.NearMissRefiner`.

The :class:`LiteLLMEditBackend` is intentionally separate from
:class:`mg.method.verifier.LiteLLMVerifierBackend` because the
information-isolation rule (Sec. 3.2) requires the *editor* to use a
different LLM session than the *verifier* even when both run on the same
provider. A single shared :mod:`litellm` call would technically not
violate the rule, but splitting the class names makes the boundary
explicit at the call site.
"""

from __future__ import annotations

from typing import Protocol


class EditBackend(Protocol):
    def __call__(self, prompt: str, model: str) -> str: ...


class LiteLLMEditBackend:
    """LiteLLM-backed edit-proposal backend.

    ``model`` defaults to ``openai/gpt-4o``. The same model string can
    be used for both verifier and editor in production; we still create
    a distinct class so the call site reads clearly.
    """

    def __init__(self, model: str = "openai/gpt-4o", temperature: float = 0.0) -> None:
        self.model = model
        self.temperature = temperature

    def __call__(self, prompt: str, model: str) -> str:
        import litellm

        response = litellm.completion(
            model=model or self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
        )
        return response.choices[0].message.content or ""
