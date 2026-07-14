"""L3 attribution — analyzer that runs the per-trial attribution step.

Step 2 of the 2026-06-26 refactor extracted this from
``skillq.layers.l3_attribution``. The split:

- :mod:`skillq.layers.l3_attribution.models` — data models + backends.
- :mod:`skillq.layers.l3_attribution.analyzer` — :class:`AttributionAnalyzer`
  (this module).
- :mod:`skillq.layers.l3_attribution.edit` — :class:`EditRefiner`.

The analyzer reads the trial's session jsonl, builds the
ATTRIBUTION_PROMPT, calls the configured backend, and applies the
consistency safety net that coerces enum values inconsistent with
``r_task``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from skillq.layers.l3_attribution.models import (
    Attribution,
    AttributionBackend,
    TrialAttribution,
)
from skillq.layers.l3_attribution.prompts import ATTRIBUTION_PROMPT


@dataclass
class AttributionAnalyzer:
    """Reads a trial's session trace and produces a :class:`TrialAttribution`."""

    backend: AttributionBackend
    model: str = "openai/gpt-4o"
    trace_max_chars: int = 12000

    @staticmethod
    def _truncate_trace(trace: str, max_chars: int) -> str:
        """Smart truncation: full trace when short, head+tail when long.

        Head-tail mode only activates when the skipped middle is
        at least MIN_SKIP chars — avoids splitting when the trace
        is only slightly over the limit.
        """
        if not trace:
            return trace
        MIN_SKIP = 2000
        if len(trace) <= max_chars + MIN_SKIP:
            return trace[:max_chars]
        # Reserve ~60 chars for the separator line.
        half = (max_chars - 60) // 2
        skipped = len(trace) - max_chars
        return (
            trace[:half]
            + f"\n\n--- ({skipped} chars skipped — trace too long) ---\n\n"
            + trace[-half:]
        )

    def analyze(
        self,
        *,
        task: str,
        trial_dir: Path,
        skills_root: Path | None = None,
        available_skill_ids: list[str] | None = None,
        r_task: int,
    ) -> TrialAttribution:
        """Run the attribution step for one trial.

        Reads ``trial_dir / "agent" / "sessions" / "projects" / "*.jsonl"``
        (Claude Code's session log) and a list of "available skills"
        (either from ``available_skill_ids`` or from ``skills_root``).
        Falls back to :class:`TrialAttribution` with empty subtasks if
        the trace file is missing.

        ``r_task`` is the ground-truth trial reward (1 = succeeded,
        0 = failed) from the harbor verifier. It is interpolated
        into ``ATTRIBUTION_PROMPT`` as a hard constraint and is
        also enforced post-parse by :meth:`_enforce_consistency` as
        a safety net.
        """
        trace = self._load_session_trace(trial_dir)
        if available_skill_ids:
            available_skills = {sid: sid for sid in available_skill_ids}
        elif skills_root is not None:
            available_skills = self._list_available_skills(skills_root)
        else:
            available_skills = {}
        prompt = ATTRIBUTION_PROMPT.format(
            task=task,
            trial_dir=str(trial_dir),
            cwd=str(trial_dir),
            available_skills=json.dumps(
                available_skills, ensure_ascii=False, indent=2
            ),
            trace=self._truncate_trace(trace, self.trace_max_chars),
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
        default of ``FAILURE_SKILL_NOT_USED`` with no extracted knowledge,
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
            # 2026-06-26: fallback to FAILURE_SKILL_NOT_USED (the
            # renamed equivalent of the old FAIL_AGENT_ISSUE). This
            # is also the failure-path "create a new skill" trigger
            # in bridge.py, so a parse failure routes into the
            # batched extract path — the LLM error becomes visible
            # in the audit log instead of being silently swallowed.
            return TrialAttribution(
                overall_attribution=Attribution.FAILURE_SKILL_NOT_USED,
                overall_rationale="attribution parse failed; defaulting to FAILURE_SKILL_NOT_USED",
            )

        obj = candidates[0]
        try:
            return TrialAttribution.model_validate(obj)
        except Exception:
            return TrialAttribution(
                overall_attribution=Attribution.FAILURE_SKILL_NOT_USED,
                overall_rationale="attribution validation failed; defaulting to FAILURE_SKILL_NOT_USED",
            )

    @staticmethod
    def _enforce_consistency(
        att: TrialAttribution, r_task: int
    ) -> TrialAttribution:
        """Safety net for the prompt's hard constraints.

        If the LLM returned an ``overall_attribution`` inconsistent
        with ``r_task`` (e.g. ``FAILURE_SKILL_NOT_USED`` despite a
        successful trial), coerce the enum to a consistent value
        rather than crash the bridge. The ``[consistency-clamp]``
        marker in the rationale makes coercion events greppable in
        logs.

        ``knowledge_to_extract`` is passed through unchanged — we
        never fabricate knowledge (fake knowledge would let the
        extractor synthesize low-quality SKILL.md files, which is
        worse than skipping extraction).

        2026-06-26 rename: clamp sets updated to the new 5-enum
        surface (``SUCCESS_VIEWED_SKILL_BUT_NOT_USED`` removed);
        the r_task=0 clamp target is now ``FAILURE_SKILL_USED``
        (the renamed equivalent of the old ``FAIL_SKILL_ISSUE``)
        — chosen because it is the most conservative failure
        enum: "a skill was used and the trial failed", which is
        the natural interpretation when an LLM returned a
        ``SUCCESS_SKILL_USED`` value alongside ``r_task=0``.
        """
        success_enums = {
            Attribution.SUCCESS_SKILL_USED,
            Attribution.SUCCESS_NO_SKILL_SEEN,
        }
        fail_enums = {
            Attribution.FAILURE_SKILL_USED,
            Attribution.FAILURE_SKILL_NOT_USED,
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
                "overall_attribution": Attribution.FAILURE_SKILL_USED,
                "overall_rationale": (
                    f"[consistency-clamp] r_task=0 but LLM returned "
                    f"{att.overall_attribution.value}; coerced to "
                    f"failure_skill_used. {att.overall_rationale}"
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


__all__ = ["AttributionAnalyzer"]