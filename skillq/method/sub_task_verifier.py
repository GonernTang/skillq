"""Sub-task verifier — LLM-as-judge that scores a single sub-task
triggered by a Skill tool call.

**Binary 0/1 reward (per user design 2026-06-14)**:
- Inputs: (task, skill_description, sub_task_log_slice)
- Output: :class:`SubTaskVerdict` with a single binary ``success`` flag
  plus an optional ``rationale`` for debugging.
- The judgment focuses on **whether the sub-task itself completed**,
  not on whether the skill was useful. (We already have Q-value
  reward shaping for that; the verifier just judges the goal.)
- The skill's body is intentionally NOT passed in — the prompt
  passes only the **description** as the skill's "promise". The
  judge evaluates whether the agent's actions achieved the goal
  implied by the description.
- ``r_subtask`` is purely {0, 1} — 1 if the sub-task succeeded, 0
  otherwise. No confidence term; the LLM is asked to give a single
  yes/no decision.
- Multiple Skill calls per trial are aggregated by mean
  (``r_subtask_mean`` ∈ [0, 1]) in the bridge, not here. This is
  the per-skill success rate within the trial.

This module is intentionally simple. No information isolation (the
judge is allowed to see the agent's full sub-task trace) — the
isolation only matters for the *content* of the skill, which we
don't pass in.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from skillq.method._litellm import LiteLLMCompletion
from skillq.method.types import Skill

logger = logging.getLogger("paper.method.sub_task_verifier")


#: Maximum concurrent LLM-as-judge calls per trial. Bounded by an
#: :class:`asyncio.Semaphore` inside :meth:`SubTaskVerifier.ascore` so a
#: trial with N unique skills × M calls finishes in roughly
#: ``max_single_call_latency × ceil(N*M / 8)`` instead of
#: ``N*M × latency``. Module-level constant (not a ``MethodConfig``
#: field) keeps the surface small; promote to config if anyone
#: complains about rate-limiting.
MAX_CONCURRENT_JUDGES = 8

#: Process-wide semaphore (lazy). Created on first :func:`_get_sem`
#: call to defer binding to the running event loop.
_JUDGE_SEM: asyncio.Semaphore | None = None


def _get_sem() -> asyncio.Semaphore:
    """Lazily-returned process-wide judge semaphore.

    Created lazily because :class:`asyncio.Semaphore` binds to the
    running event loop at construction time (Python 3.10+). The
    semaphore lives for the lifetime of the process; it is just a
    counter, so the memory cost is negligible.
    """
    global _JUDGE_SEM
    if _JUDGE_SEM is None:
        _JUDGE_SEM = asyncio.Semaphore(MAX_CONCURRENT_JUDGES)
    return _JUDGE_SEM


@dataclass
class SubTaskVerdict:
    """Per-sub-task verdict (LLM-as-judge output).

    Binary reward: ``success`` is the only thing that matters for
    the Q-update. ``rationale`` is kept for debugging / logging.
    """

    skill_id: str
    success: bool
    rationale: str = ""

    @property
    def r_subtask(self) -> float:
        """Binary {0, 1} reward signal.

        - success=True  → 1.0
        - success=False → 0.0

        This is the per-sub-task reward. All skills called within
        the same sub-task share the same ``r_subtask`` (in the
        current data model there is one skill per sub-task, so the
        "shared" constraint is vacuous — but the data shape allows
        for multi-skill sub-tasks in the future).
        """
        return 1.0 if self.success else 0.0


class SubTaskVerifierBackend(Protocol):
    """Backend protocol — same shape as the existing :class:`VerifierBackend`.

    Both sync (``__call__``) and async (``acall``) variants are required
    so :class:`SubTaskVerifier` can use whichever fits the call site.
    """

    def __call__(self, prompt: str, model: str) -> str: ...

    async def acall(self, prompt: str, model: str) -> str: ...


class StubSubTaskVerifierBackend:
    """Deterministic stub for unit tests — never calls an LLM."""

    def __init__(self, success: bool = True) -> None:
        self._success = success

    def __call__(self, prompt: str, model: str) -> str:
        return self._payload()

    async def acall(self, prompt: str, model: str) -> str:
        return self._payload()

    def _payload(self) -> str:
        return json.dumps(
            {
                "success": self._success,
                "rationale": "stub: deterministic verdict",
            }
        )


class LiteLLMSubTaskVerifierBackend(LiteLLMCompletion):
    """Default backend for the per-sub-task LLM-as-judge.

    Thin subclass of :class:`paper.method._litellm.LiteLLMCompletion`;
    no temperature or response_format overrides.
    """


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
{{"success": <true|false>, "rationale": "<1-2 sentences>"}}

A binary decision is required. Do not hedge — if the final state
is "probably correct" or "the right thing is on disk", that's a
success. If the agent gave up, errored out, or produced the wrong
output, that's a failure.
"""


@dataclass
class SubTaskVerifier:
    """LLM-as-judge for one sub-task.

    Stateless — call :meth:`score` (sync) or :meth:`ascore` (async)
    once per (skill_id, sub_task_trace) pair. The bridge aggregates
    over multiple verdicts for the same skill across the same trial.

    The async path uses a :data:`MAX_CONCURRENT_JUDGES`-bounded
    semaphore (see :func:`_get_sem`) to throttle parallel LLM calls.
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
        """Sync version — kept for callers that haven't gone async."""
        prompt = self._build_prompt(task, skill_id, skill_description, sub_task_trace)
        raw = self.backend(prompt, self.model)
        return self._parse(skill_id, raw)

    async def ascore(
        self,
        task: str,
        skill_id: str,
        skill_description: str,
        sub_task_trace: str,
    ) -> SubTaskVerdict:
        """Async version — throttled by a process-wide semaphore.

        Designed for use inside :func:`asyncio.gather` over many
        (skill, call) tuples; one bad call raises (no
        ``return_exceptions=True``) so the outer try/except can
        record the failure exactly as the sync version does.
        """
        prompt = self._build_prompt(task, skill_id, skill_description, sub_task_trace)
        sem = _get_sem()
        async with sem:
            raw = await self.backend.acall(prompt, self.model)
        return self._parse(skill_id, raw)

    def _build_prompt(
        self,
        task: str,
        skill_id: str,
        skill_description: str,
        sub_task_trace: str,
    ) -> str:
        """Build the SUBTASK_VERIFIER_PROMPT for this sub-task."""
        return SUBTASK_VERIFIER_PROMPT.format(
            task=task[:2000],
            skill_name=skill_id,
            skill_description=skill_description[:500],
            sub_task_trace=sub_task_trace[: self.max_trace_chars],
        )

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
        # 3) Fallback — uncertain defaults to failure
        logger.warning("sub_task_verifier parse failed: %r", raw[:200])
        return SubTaskVerdict(
            skill_id=skill_id,
            success=False,
            rationale="verifier parse failed; default failure",
        )


def _build_verdict(skill_id: str, obj: dict[str, Any]) -> SubTaskVerdict:
    return SubTaskVerdict(
        skill_id=skill_id,
        success=bool(obj.get("success", False)),
        rationale=str(obj.get("rationale", ""))[:500],
    )


def mean_r_subtask(verdicts: Sequence[SubTaskVerdict]) -> float:
    """Mean r_subtask over a list of verdicts (per-(skill, trial) aggregation).

    With binary verdicts this is the **success rate** of the skill
    within the trial, ∈ [0, 1]. E.g. 2 successes + 1 failure → 0.667.

    Returns 0.0 if ``verdicts`` is empty.
    """
    if not verdicts:
        return 0.0
    return sum(v.r_subtask for v in verdicts) / len(verdicts)


__all__ = [
    "MAX_CONCURRENT_JUDGES",
    "SubTaskVerdict",
    "SubTaskVerifier",
    "SubTaskVerifierBackend",
    "StubSubTaskVerifierBackend",
    "LiteLLMSubTaskVerifierBackend",
    "SUBTASK_VERIFIER_PROMPT",
    "mean_r_subtask",
]
