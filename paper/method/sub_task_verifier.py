"""Sub-task verifier — LLM-as-judge that scores a single sub-task
triggered by a Skill tool call.

**Per user design 2026-06-11**:
- Inputs: (task, skill_description, sub_task_log_slice)
- Output: :class:`SubTaskVerdict` with success / confidence / rationale
- The judgment focuses on **whether the sub-task itself completed**,
  not on whether the skill was useful. (We already have Q-value
  reward shaping for that; the verifier just judges the goal.)
- The skill's body is intentionally NOT passed in — the prompt
  passes only the **description** as the skill's "promise". The
  judge evaluates whether the agent's actions achieved the goal
  implied by the description.
- Multiple Skill calls per trial are aggregated by mean
  (``r_subtask_mean``) in the bridge, not here.

This module is intentionally simple. No information isolation (the
judge is allowed to see the agent's full sub-task trace) — the
isolation only matters for the *content* of the skill, which we
don't pass in.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from paper.method.types import Skill

logger = logging.getLogger("paper.method.sub_task_verifier")


@dataclass
class SubTaskVerdict:
    """Per-sub-task verdict (LLM-as-judge output)."""

    skill_id: str
    success: bool
    confidence: float
    rationale: str

    @property
    def r_subtask(self) -> float:
        """Confidence-gated {-1, 0, +1} reward signal.

        The bridge's Q-update maps this through ``q_r_subtask_success`` /
        ``q_r_subtask_failure`` to the actual update magnitude, but
        the sign is decided here based on:
        - success=True,  confidence >= 0.5 → +1
        - success=False, confidence >= 0.5 → -1
        - confidence < 0.5 (uncertain)   →  0
        """
        if self.confidence < 0.5:
            return 0.0
        return 1.0 if self.success else -1.0


class SubTaskVerifierBackend(Protocol):
    """Backend protocol — same shape as the existing :class:`VerifierBackend`."""

    def __call__(self, prompt: str, model: str) -> str: ...


class StubSubTaskVerifierBackend:
    """Deterministic stub for unit tests — never calls an LLM."""

    def __init__(self, success: bool = True, confidence: float = 0.7) -> None:
        self._success = success
        self._confidence = confidence

    def __call__(self, prompt: str, model: str) -> str:
        return json.dumps(
            {
                "success": self._success,
                "confidence": self._confidence,
                "rationale": "stub: deterministic verdict",
            }
        )


class LiteLLMSubTaskVerifierBackend:
    """Default backend — wraps ``litellm.completion``."""

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


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------
SUBTASK_VERIFIER_PROMPT = """\
You are evaluating a single sub-task executed by an agent in a larger task.

# Original task (high-level)
{task}

# Sub-task context
The agent invoked a skill named "{skill_name}" with the following description:
    "{skill_description}"

The agent's actions during this sub-task are summarised below. They cover
the period from when the agent called the Skill tool until either the
next non-Skill tool call, the end of the agent's main loop, or the
agent re-issued another Skill call.

# Agent's actions (chronological excerpt from the session log)
{sub_task_trace}

# Your job
Decide whether the sub-task implied by the skill description
**completed in a generally correct way** at the end of the trace above.
Focus on the final state, not on every individual step. Examples:

- Description "recover a deleted git commit" → success if a commit
  was recovered and merged; failure if the agent gave up or produced
  the wrong commit.
- Description "extract a file from a 7z archive" → success if the
  archive was extracted and the expected file is on disk; failure
  if extraction failed or produced the wrong file.
- Description "convert a 3D gcode file to text" → success if the
  final text on disk matches what the gcode would print; failure
  otherwise.

Ignore the *quality* of the skill's own body. You're judging whether
the **agent's execution** achieved the goal, not whether the skill
description was well-written.

# Output format
Respond with a single JSON object, no prose:
{{"success": <true|false>, "confidence": <0.0-1.0>, "rationale": "<1-2 sentences>"}}
"""


@dataclass
class SubTaskVerifier:
    """LLM-as-judge for one sub-task.

    Stateless — call :meth:`score` once per (skill_id, sub_task_trace)
    pair. The bridge aggregates over multiple verdicts for the same
    skill across the same trial.
    """

    backend: SubTaskVerifierBackend
    model: str = "openai/gpt-4o"
    max_trace_chars: int = 6000

    def score(
        self,
        task: str,
        skill_id: str,
        skill_description: str,
        sub_task_trace: str,
    ) -> SubTaskVerdict:
        """Return a :class:`SubTaskVerdict` for this sub-task."""
        prompt = SUBTASK_VERIFIER_PROMPT.format(
            task=task[:2000],
            skill_name=skill_id,
            skill_description=skill_description[:500],
            sub_task_trace=sub_task_trace[: self.max_trace_chars],
        )
        raw = self.backend(prompt, self.model)
        return self._parse(skill_id, raw)

    @staticmethod
    def _parse(skill_id: str, raw: str) -> SubTaskVerdict:
        # 1) Direct JSON
        try:
            obj = json.loads(raw)
            return _build_verdict(skill_id, obj)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
        # 2) JSON in prose
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group())
                return _build_verdict(skill_id, obj)
            except Exception:  # noqa: BLE001
                pass
        # 3) Fallback — uncertain
        logger.warning("sub_task_verifier parse failed: %r", raw[:200])
        return SubTaskVerdict(
            skill_id=skill_id,
            success=False,
            confidence=0.0,
            rationale="verifier parse failed; default uncertain",
        )


def _build_verdict(skill_id: str, obj: dict[str, Any]) -> SubTaskVerdict:
    success = bool(obj.get("success", False))
    try:
        confidence = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return SubTaskVerdict(
        skill_id=skill_id,
        success=success,
        confidence=confidence,
        rationale=str(obj.get("rationale", ""))[:500],
    )


def mean_r_subtask(verdicts: Sequence[SubTaskVerdict]) -> float:
    """Mean r_subtask over a list of verdicts (per-(skill, trial) aggregation).

    Returns 0.0 if ``verdicts`` is empty.
    """
    if not verdicts:
        return 0.0
    return sum(v.r_subtask for v in verdicts) / len(verdicts)


__all__ = [
    "SubTaskVerdict",
    "SubTaskVerifier",
    "SubTaskVerifierBackend",
    "StubSubTaskVerifierBackend",
    "LiteLLMSubTaskVerifierBackend",
    "SUBTASK_VERIFIER_PROMPT",
    "mean_r_subtask",
]
