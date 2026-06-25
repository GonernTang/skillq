"""Trial-level attribution step for the mg paper method.

Lives in ``paper/method`` because it is consumed by the paper-mode
bridge in :mod:`skillq.skillq_runtime.bridge`. The schema is intentionally
**narrower** than the upstream ``lqrl`` ``FeedbackOutputPayload``: we
do not need a per-subtask 11-class taxonomy, just a small enum that
drives the two create-vs-edit-vs-bump decisions the bridge needs.

Design notes (see ``docs/integration_plan.md`` §3 for the full
rationale):

- One LLM call per trial, reading the agent's session jsonl and a
  list of "available skills" (paths the lqrl-side recommend step
  copied into ``$CODEX_HOME/skills`` / ``$CLAUDE_CONFIG_DIR/skills``).
- Output is a :class:`TrialAttribution` containing:
    - a list of :class:`SubtaskOutcome` (used by future per-subtask
      credit assignment — currently we aggregate to a single
      ``overall_attribution``);
    - a free-text ``knowledge_to_extract`` field that is the
      **primary input** to :class:`paper.method.extractor.SkillExtractor`
      when the bridge decides to create a new skill.
- The attribution is *not* the same as :class:`paper.method.verifier.Verdict`
  (the informationally isolated 4-axis scorer used for ``r_learning``).
  Those two LLM calls answer different questions:

      attribution   = "what procedural knowledge did the agent use?"
      verdict       = "did the skill's content quality change?"

  Keeping them separate is by design (Sec. 3.2 of the paper requires
  the verifier to be information-isolated; the attribution is allowed
  to read the trace).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field

from skillq.method._litellm import LiteLLMCompletion
from skillq.method.prompts import ATTRIBUTION_PROMPT


class Attribution(str, Enum):
    """Six-class trial-level attribution enum.

    Mirror of lqrl's main six classes; we drop the rarer
    ``uncertain_*`` / ``fail_*_env`` variants that lqrl has because
    the paper method only branches on the success/fail split and
    the viewed/no-skill split.
    """

    SUCCESS_SKILL_USED = "success_skill_used"
    SUCCESS_VIEWED_SKILL_BUT_NOT_USED = "success_viewed_skill_but_not_used"
    SUCCESS_NO_SKILL_SEEN = "success_no_skill_seen"
    FAIL_SKILL_ISSUE = "fail_skill_issue"
    FAIL_AGENT_ISSUE = "fail_agent_issue"
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

    ``library_gap_skill_description`` (2026-06-25) is the
    actionable "what skill SHOULD have been in the library"
    statement. Populated when the attribution enum signals a
    missing-skill scenario (see ATTRIBUTION_PROMPT). The
    failure-path extract prompt uses this field as the
    *primary seed* for synthesized SKILL.md files; the
    ``knowledge_to_extract`` field is the agent's diagnosis
    of what went wrong. Empty by default.
    """

    model_config = ConfigDict(extra="forbid")

    overall_attribution: Attribution
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
    Thin subclass of :class:`paper.method._litellm.LiteLLMCompletion`;
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
# Top-level analyser
# ---------------------------------------------------------------------------
@dataclass
class AttributionAnalyzer:
    """Reads a trial's session trace and produces a :class:`TrialAttribution`."""

    backend: AttributionBackend
    model: str = "openai/gpt-4o"
    trace_max_chars: int = 6000

    def analyze(
        self,
        *,
        task: str,
        trial_dir: Path,
        skills_root: Path | None = None,
        r_task: int,
    ) -> TrialAttribution:
        """Run the attribution step for one trial.

        Reads ``trial_dir / "agent" / "sessions" / "projects" / "*.jsonl"``
        (Claude Code's session log) and a list of "available skills"
        (the directory the lqrl-side recommend step copied skills into,
        e.g. ``$CLAUDE_CONFIG_DIR/skills``). Falls back to
        :class:`TrialAttribution` with empty subtasks if the trace
        file is missing.

        ``r_task`` is the ground-truth trial reward (1 = succeeded,
        0 = failed) from the harbor verifier. It is interpolated
        into ``ATTRIBUTION_PROMPT`` as a hard constraint and is
        also enforced post-parse by :meth:`_enforce_consistency` as
        a safety net.
        """
        trace = self._load_session_trace(trial_dir)
        available_skills = self._list_available_skills(skills_root) if skills_root else {}
        prompt = ATTRIBUTION_PROMPT.format(
            task=task,
            trial_dir=str(trial_dir),
            cwd=str(trial_dir),
            available_skills=json.dumps(available_skills, ensure_ascii=False, indent=2),
            trace=trace[: self.trace_max_chars],
            r_task=r_task,
        )
        raw = self.backend(prompt, self.model)
        att = self._parse(raw)
        return self._enforce_consistency(att, r_task)

    @staticmethod
    def _load_session_trace(trial_dir: Path) -> str:
        session_root = trial_dir / "agent" / "sessions" / "projects"
        if not session_root.exists():
            return ""
        candidates = sorted(
            (p for p in session_root.rglob("*.jsonl") if "subagents" not in p.parts),
            key=lambda p: p.stat().st_mtime_ns,
        )
        if not candidates:
            return ""
        # Use the most recent session file.
        return _render_jsonl(candidates[-1])

    @staticmethod
    def _list_available_skills(skills_root: Path) -> dict[str, str]:
        """Return ``{relative_skill_name: absolute_path}`` for all
        ``SKILL.md`` files under ``skills_root``. Mirrors lqrl's
        ``format_available_skills`` shape.
        """
        if not skills_root.exists():
            return {}
        out: dict[str, str] = {}
        for skill_md in sorted(skills_root.rglob("SKILL.md")):
            try:
                rel = skill_md.parent.relative_to(skills_root).as_posix()
            except ValueError:
                continue
            out[rel] = str(skill_md.resolve())
        return out

    @staticmethod
    def _parse(raw: str) -> TrialAttribution:
        """Parse the LLM JSON output, robust to prose-wrapped JSON.

        Empty / unparseable responses fall back to a conservative
        default of ``FAIL_AGENT_ISSUE`` with no extracted knowledge,
        so the bridge can still update Q-tables without crashing.
        """
        candidates: list[dict[str, Any]] = []
        # Direct parse
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                candidates.append(obj)
        except (json.JSONDecodeError, TypeError):
            pass
        # Find JSON block in prose
        if not candidates:
            import re

            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                try:
                    obj = json.loads(match.group())
                    if isinstance(obj, dict):
                        candidates.append(obj)
                except Exception:
                    pass
        # Try YAML as last resort
        if not candidates:
            try:
                obj = yaml.safe_load(raw)
                if isinstance(obj, dict):
                    candidates.append(obj)
            except Exception:
                pass

        if not candidates:
            return TrialAttribution(
                overall_attribution=Attribution.FAIL_AGENT_ISSUE,
                overall_rationale="attribution parse failed; defaulting to FAIL_AGENT_ISSUE",
            )

        obj = candidates[0]
        try:
            return TrialAttribution.model_validate(obj)
        except Exception:
            return TrialAttribution(
                overall_attribution=Attribution.FAIL_AGENT_ISSUE,
                overall_rationale="attribution validation failed; defaulting to FAIL_AGENT_ISSUE",
            )

    @staticmethod
    def _enforce_consistency(
        att: TrialAttribution, r_task: int
    ) -> TrialAttribution:
        """Safety net for the prompt's hard constraints.

        If the LLM returned an ``overall_attribution`` inconsistent
        with ``r_task`` (e.g. ``FAIL_AGENT_ISSUE`` despite a successful
        trial), coerce the enum to a consistent value rather than
        crash the bridge. The ``[consistency-clamp]`` marker in the
        rationale makes coercion events greppable in logs.

        ``knowledge_to_extract`` is passed through unchanged — we
        never fabricate knowledge (fake knowledge would let the
        extractor synthesize low-quality SKILL.md files, which is
        worse than skipping extraction).
        """
        success_enums = {
            Attribution.SUCCESS_SKILL_USED,
            Attribution.SUCCESS_VIEWED_SKILL_BUT_NOT_USED,
            Attribution.SUCCESS_NO_SKILL_SEEN,
        }
        fail_enums = {
            Attribution.FAIL_SKILL_ISSUE,
            Attribution.FAIL_AGENT_ISSUE,
            Attribution.FAIL_ENV_ISSUE,
        }
        if r_task == 1 and att.overall_attribution in fail_enums:
            return att.model_copy(update={
                "overall_attribution": Attribution.SUCCESS_NO_SKILL_SEEN,
                "overall_rationale": (
                    f"[consistency-clamp] r_task=1 but LLM returned "
                    f"{att.overall_attribution.value}; coerced to "
                    f"success_no_skill_seen. {att.overall_rationale}"
                ),
            })
        if r_task == 0 and att.overall_attribution in success_enums:
            return att.model_copy(update={
                "overall_attribution": Attribution.FAIL_SKILL_ISSUE,
                "overall_rationale": (
                    f"[consistency-clamp] r_task=0 but LLM returned "
                    f"{att.overall_attribution.value}; coerced to "
                    f"fail_skill_issue. {att.overall_rationale}"
                ),
            })
        return att


# ---------------------------------------------------------------------------
# Internal: simple JSONL → markdown renderer (replaces lqrl's
# parse_claude_session_trace; we do not import lqrl here to keep
# the module-level dependency surface minimal).
# ---------------------------------------------------------------------------
def _render_jsonl(path: Path, per_message_chars: int = 1500) -> str:
    blocks: list[str] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                if payload.get("isMeta"):
                    continue
                ptype = payload.get("type")
                if ptype not in {"user", "assistant", "tool", "system"}:
                    continue
                rendered = _format_message(payload, per_message_chars)
                if rendered:
                    blocks.append(rendered)
    except OSError:
        return ""
    return "\n\n".join(blocks)


def _format_message(payload: dict[str, Any], limit: int) -> str | None:
    role = payload.get("type", "user")
    msg = payload.get("message", {})
    if not isinstance(msg, dict):
        return None
    parts: list[str] = []
    content = msg.get("content")
    if isinstance(content, str):
        parts.append(content[:limit])
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", ""))[:limit])
                elif item.get("type") == "tool_use":
                    name = item.get("name", "tool")
                    inp = item.get("input", {})
                    parts.append(f"[tool_use {name}]: {json.dumps(inp, ensure_ascii=False)[:limit]}")
                elif item.get("type") == "tool_result":
                    content_tr = item.get("content", "")
                    if isinstance(content_tr, list):
                        content_tr = json.dumps(content_tr, ensure_ascii=False)
                    parts.append(f"[tool_result]: {str(content_tr)[:limit]}")
    if not parts:
        return None
    body = "\n".join(parts)
    if len(body) > limit:
        body = body[:limit] + "..."
    return f"[{role}]\n{body}"


# ---------------------------------------------------------------------------
# Convenience: aggregate to a single verdict string for log lines.
# ---------------------------------------------------------------------------
def summarize_for_log(attribution: TrialAttribution) -> str:
    return (
        f"attribution={attribution.overall_attribution.value} "
        f"knowledge_chars={len(attribution.knowledge_to_extract)} "
        f"subtasks={len(attribution.subtasks)}"
    )
