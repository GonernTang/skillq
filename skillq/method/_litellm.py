"""Shared LiteLLM completion wrapper.

The four skillq-method LLM backends (verifier, editor, sub-task
verifier, attribution) all wrap a single ``litellm.completion`` call
with a different temperature / model / ``response_format``. The
duplicated ``__call__(prompt, model)`` body was identical in all of
them.

This module exposes :class:`LiteLLMCompletion` — the common
implementation — and the four paper backends are thin subclasses
that only set their own defaults.

Why subclasses instead of one class with parameters? The call site
already has four named classes; the design intent (per the original
``editor_backend.py`` comment) is to make the **boundary** between
verifier and editor visible at the call site, even when the runtime
behavior is identical. Subclasses are 6 lines each and preserve the
naming the bridge uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
