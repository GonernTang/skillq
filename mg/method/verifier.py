"""Informationally isolated verifier (Sec. 3.2 of the paper).

The verifier is a separate LLM session that:

1. observes only the pre-task skill, the post-task skill, and the task;
2. does **not** observe the agent's generation trace, prompt, or any
   other skill in the library;
3. returns a score delta as the learning reward ``r_learning``.

The information isolation prevents the verifier from inheriting the
generator's biases (a design principle lifted from CoEvoSkills).

This module is the mg-side rewrite of
``implementation_guide/lqrl/verifier.py:IndependentVerifier`` and
``OpenAIVerifierBackend``, with the latter replaced by a LiteLLM backend
(:class:`LiteLLMVerifierBackend`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol, Sequence

from mg.method.prompts import VERIFIER_PROMPT
from mg.method.types import Skill, Verdict


class VerifierBackend(Protocol):
    """Protocol for the underlying LLM call (kept abstract for testability)."""

    def __call__(self, prompt: str, model: str) -> str: ...


class StubVerifierBackend:
    """Deterministic stub used in unit tests (no API calls)."""

    def __init__(self, old_score: float = 0.5, new_score: float = 0.7) -> None:
        self._old = old_score
        self._new = new_score

    def __call__(self, prompt: str, model: str) -> str:
        return json.dumps(
            {
                "old_score": self._old,
                "new_score": self._new,
                "improved": self._new > self._old,
                "rationale": "stub: deterministic scores",
            }
        )


class LiteLLMVerifierBackend:
    """Default backend: LiteLLM ``completion()``.

    Each call uses a fresh client request — no conversation history is
    shared with the generator or previous verifier calls. This is the
    *information isolation* the paper requires.
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


@dataclass
class IndependentVerifier:
    """Informationally isolated verifier (Sec. 3.2)."""

    backend: VerifierBackend
    model: str = "openai/gpt-4o"

    def score(
        self,
        task: str,
        old_skill: Skill,
        new_skill: Skill,
    ) -> Verdict:
        """Return a :class:`Verdict` for the content delta ``(old, new)``."""
        prompt = VERIFIER_PROMPT.format(
            task=task,
            old_skill=old_skill.body,
            new_skill=new_skill.body,
        )
        raw = self.backend(prompt, self.model)
        return self._parse(raw)

    def _parse(self, raw: str) -> Verdict:
        """Parse the verifier response, robust to slight formatting drift."""
        # 1) Try direct JSON parse
        try:
            obj = json.loads(raw)
            return self._build_verdict(obj)
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            pass

        # 2) Fall back: extract a JSON block from prose
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group())
                return self._build_verdict(obj)
            except Exception:
                pass

        # 3) Final fallback: conservative no-improvement verdict
        return Verdict(
            old_score=0.5,
            new_score=0.5,
            improved=False,
            rationale="verifier parse failed; default no-improvement",
        )

    @staticmethod
    def _build_verdict(obj: dict) -> Verdict:
        return Verdict(
            old_score=float(obj["old_score"]),
            new_score=float(obj["new_score"]),
            improved=bool(obj["improved"]),
            rationale=str(obj.get("rationale", "")),
        )


def batch_score(
    verifier: IndependentVerifier,
    task: str,
    deltas: Sequence[tuple[Skill, Skill]],
) -> list[Verdict]:
    """Convenience: score multiple (old, new) pairs in sequence.

    Each call uses a fresh prompt; the verifier is still information
    isolated on a per-delta basis.
    """
    return [verifier.score(task, old, new) for old, new in deltas]
