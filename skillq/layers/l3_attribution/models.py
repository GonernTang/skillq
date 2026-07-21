"""L3 attribution — data models + LLM backend protocol.

Step 2 of the 2026-06-26 refactor extracted this from
``skillq.layers.l3_attribution``. The split:

- :mod:`skillq.layers.l3_attribution.models` — pydantic schemas
  (:class:`Attribution`, :class:`SubtaskOutcome`, :class:`TrialAttribution`),
  the :class:`AttributionBackend` Protocol, the deterministic
  :class:`StubAttributionBackend` for tests, and the
  :class:`LiteLLMAttributionBackend` (JSON-mode LiteLLM wrapper).
- :mod:`skillq.layers.l3_attribution.analyzer` — :class:`AttributionAnalyzer`
  that runs the per-trial attribution step (the orchestration logic).
- :mod:`skillq.layers.l3_attribution.edit` — :class:`EditRefiner` +
  related backends for the Layer 3 in-place edit.

The 5-class enum is **pinned** (test_enum_contract.py asserts the
exact string values); renaming any of the five breaks the runtime
contract because ``skillq.runtime.steps.step_dispatch_evolve`` switches on them.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from skillq.shared.backends.litellm import LiteLLMCompletion


class Attribution(str, Enum):
    """Five-class trial-level attribution enum (renamed 2026-06-26).

    The naming mirrors the action the bridge should take:

      - ``SUCCESS_SKILL_USED`` — agent used a relevant skill and the
        trial succeeded; nothing to do.
      - ``SUCCESS_NO_SKILL_SEEN`` — trial succeeded but no relevant
        skill was available/used; create a new skill from the
        success trajectory.
      - ``FAILURE_SKILL_USED`` — agent used a skill and the trial
        still failed; the skill is at fault, edit it in place.
      - ``FAILURE_SKILL_NOT_USED`` — trial failed and no relevant
        skill was used; the library is missing a relevant skill,
        create a guard-rail one from the failure attribution.
      - ``FAIL_ENV_ISSUE`` — failure is environmental (network,
        dependency), nothing to do.

    The previous ``SUCCESS_VIEWED_SKILL_BUT_NOT_USED`` enum is
    removed because the L1 force-use hook (2026-06-26) makes that
    state structurally unreachable: the agent is told it MUST
    call ``Skill()`` with one of the top-k skills, so it cannot
    "see but not use" a relevant skill.
    """

    SUCCESS_SKILL_USED = "success_skill_used"
    SUCCESS_NO_SKILL_SEEN = "success_no_skill_seen"
    FAILURE_SKILL_USED = "failure_skill_used"
    FAILURE_SKILL_NOT_USED = "failure_skill_not_used"
    FAIL_ENV_ISSUE = "fail_env_issue"


class SubtaskOutcome(BaseModel):
    """Per-subtask attribution. Currently informational; the bridge
    aggregates to :class:`TrialAttribution.overall_attribution`.
    """

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    attribution: Attribution
    skill_linked: str | None = None
    skill_refs: list[dict[str, Any]] = Field(default_factory=list)


class TrialAttribution(BaseModel):
    """Top-level attribution result for one trial.

    ``knowledge_to_extract`` is the free-form procedural knowledge
    the agent used to succeed. It is *only* meaningful when
    ``overall_attribution`` is one of the success cases.

    ``library_gap_skill_description`` (2026-06-25, refined 2026-06-26)
    is the actionable "what skill SHOULD have been in the library"
    statement. Populated when the attribution enum signals a
    missing-skill scenario (see ATTRIBUTION_PROMPT). The
    failure-path extract prompt uses this field as the
    *primary seed* for synthesized SKILL.md files; the
    ``knowledge_to_extract`` field is the agent's diagnosis
    of what went wrong. Empty by default. As of 2026-06-26
    only the two gap-signaling enums
    (``SUCCESS_NO_SKILL_SEEN`` and ``FAILURE_SKILL_NOT_USED``)
    populate this field.
    """

    model_config = ConfigDict(extra="forbid")

    # 2026-07-20: the LLM no longer outputs ``overall_attribution`` —
    # the analyzer derives it in code from ``r_task`` + ``called_skill_ids``.
    # The default keeps ``_parse`` working when the LLM omits the field
    # (and lets ``model_validate`` succeed on older/stub payloads that
    # still include it — the explicit value simply overrides the default).
    overall_attribution: Attribution = Field(
        default=Attribution.SUCCESS_NO_SKILL_SEEN
    )
    overall_rationale: str = Field(min_length=1)
    subtasks: list[SubtaskOutcome] = Field(default_factory=list)
    knowledge_to_extract: str = ""  # empty when nothing reusable was found
    # 2026-06-25 (Bug-fix follow-up): explicit "what skill should
    # the library have contained" signal. Survives as a sibling
    # field on the attribution result so the failure-path extract
    # prompt can prefer it over knowledge_to_extract as the seed.
    library_gap_skill_description: str = ""


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------
class AttributionBackend(Protocol):
    """A backend that takes a prompt and returns parsed JSON text."""

    def __call__(self, prompt: str, model: str) -> str: ...


class StubAttributionBackend:
    """Deterministic stub for unit tests.

    Returns a fixed :class:`TrialAttribution` for every call. The
    ``overall_attribution`` defaults to ``SUCCESS_NO_SKILL_SEEN``;
    tests that need a different value can subclass or pre-set the
    private attributes.
    """

    def __init__(
        self,
        overall_attribution: Attribution = Attribution.SUCCESS_NO_SKILL_SEEN,
        knowledge_to_extract: str = "stub procedural knowledge",
    ) -> None:
        self._attribution = overall_attribution
        self._knowledge = knowledge_to_extract

    def __call__(self, prompt: str, model: str) -> str:
        payload = {
            "overall_attribution": self._attribution.value,
            "overall_rationale": "stub: deterministic attribution",
            "subtasks": [],
            "knowledge_to_extract": self._knowledge,
        }
        return json.dumps(payload, ensure_ascii=False)


class LiteLLMAttributionBackend(LiteLLMCompletion):
    """Default production backend: ``litellm.completion`` with
    JSON-mode output.

    Independent session (fresh messages list each call), temperature 0.
    Thin subclass of
    :class:`skillq.shared.backends.litellm.LiteLLMCompletion`;
    forces ``response_format={"type": "json_object"}`` to make the
    attribution JSON parse robust to prose drift.
    """

    def __init__(self, model: str = "openai/gpt-4o", temperature: float = 0.0) -> None:
        super().__init__(
            model=model,
            temperature=temperature,
            response_format={"type": "json_object"},
        )


# ---------------------------------------------------------------------------
# Convenience: aggregate to a single verdict string for log lines.
# ---------------------------------------------------------------------------
def summarize_for_log(attribution: TrialAttribution) -> str:
    return (
        f"attribution={attribution.overall_attribution.value} "
        f"knowledge_chars={len(attribution.knowledge_to_extract)} "
        f"subtasks={len(attribution.subtasks)}"
    )


__all__ = [
    "Attribution",
    "SubtaskOutcome",
    "TrialAttribution",
    "AttributionBackend",
    "StubAttributionBackend",
    "LiteLLMAttributionBackend",
    "summarize_for_log",
]