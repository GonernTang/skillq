"""Unit tests for :class:`SubTaskVerifier` body-visibility contract.

The verifier prompt must:
- contain both ``skill_description`` (the contract) and ``skill_body``
  (the implementation reference);
- truncate ``skill_body`` to ``max_body_chars`` so a long SKILL.md
  does not blow the LLM's token budget.

These tests use the :class:`StubSubTaskVerifierBackend` so no LLM
is called — we inspect the prompt that the backend receives.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.method.sub_task_verifier import (  # noqa: E402
    StubSubTaskVerifierBackend,
    SubTaskVerifier,
)


class _CapturingBackend:
    """Like StubSubTaskVerifierBackend but records the prompt it was called with."""

    def __init__(self, success: bool = True) -> None:
        self._success = success
        self.last_prompt: str | None = None

    def __call__(self, prompt: str, model: str) -> str:
        self.last_prompt = prompt
        import json
        return json.dumps({"success": self._success, "rationale": "captured"})

    async def acall(self, prompt: str, model: str) -> str:
        return self(prompt, model)


def test_verifier_passes_body_to_prompt() -> None:
    """The skill body is included in the verifier prompt."""
    backend = _CapturingBackend(success=True)
    v = SubTaskVerifier(backend=backend, model="test-model")

    body = "# nginx logging\n\nUse the access log directive `log_format`."
    v.score(
        task="set up nginx with custom logging",
        skill_id="nginx-logging",
        skill_description="Configure Nginx with custom request logging.",
        skill_body=body,
        sub_task_trace="assistant: ran nginx -t\n",
    )

    assert backend.last_prompt is not None
    assert "Configure Nginx with custom request logging." in backend.last_prompt
    assert body in backend.last_prompt
    assert "Skill body (full implementation" in backend.last_prompt


def test_verifier_truncates_body_to_max_body_chars() -> None:
    """A body longer than ``max_body_chars`` is sliced to fit."""
    backend = _CapturingBackend(success=True)
    v = SubTaskVerifier(
        backend=backend,
        model="test-model",
        max_body_chars=2000,
    )

    long_body = "X" * 5000  # 5000 chars; max_body_chars=2000 → truncated to 2000
    v.score(
        task="t",
        skill_id="x",
        skill_description="d",
        skill_body=long_body,
        sub_task_trace="trace",
    )

    assert backend.last_prompt is not None
    # The body slice should appear in the prompt with exactly
    # max_body_chars of the X character.
    assert "X" * 2000 in backend.last_prompt
    # The truncated tail (5 chars) should NOT appear — that signals
    # we did not paste the full 5000-char body verbatim.
    assert "X" * 5000 not in backend.last_prompt


def test_verifier_handles_empty_body() -> None:
    """An empty body (e.g. evicted skill) does not crash and formats fine."""
    backend = _CapturingBackend(success=True)
    v = SubTaskVerifier(backend=backend, model="test-model")

    v.score(
        task="t",
        skill_id="x",
        skill_description="d",
        skill_body="",
        sub_task_trace="trace",
    )

    assert backend.last_prompt is not None
    # The skill body section is still present in the template
    # (the placeholder renders as an empty string).
    assert "Skill body (full implementation" in backend.last_prompt


def test_stub_backend_returns_deterministic_verdict() -> None:
    """Sanity check on the existing StubSubTaskVerifierBackend contract."""
    backend = StubSubTaskVerifierBackend(success=False)
    v = SubTaskVerifier(backend=backend, model="test-model")

    verdict = v.score(
        task="t",
        skill_id="x",
        skill_description="d",
        skill_body="b",
        sub_task_trace="trace",
    )

    assert verdict.success is False
    assert verdict.rationale.startswith("stub")