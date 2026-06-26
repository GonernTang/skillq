"""Layer 3 (Edit) — incremental in-place editing of existing skills.

The bridge invokes :meth:`EditRefiner.propose_edit` on every failed
trial (r_task == 0). The previous near-miss gate (Eq. 11
``r_task == 0 AND max_m Q(s, m) >= theta_near_miss``) was removed
on 2026-06-22 because ``q_w_task = -0.5`` structurally drives Q
below ``theta_near_miss`` whenever a trial fails, making the
near-miss condition unreachable in practice. Without the gate,
the editor LLM is invoked for every failure so it can propose a
minimal body edit regardless of Q.

This module is the mg-side rewrite of
``skillsvote/src/skills_vote/near_miss.py:NearMissEditor`` with the
class renamed to ``EditRefiner`` (Layer 3 = "Edit", not "near-miss")
and the prompt replaced by
:data:`paper.method.prompts.EDIT_PROMPT`.

Renamed 2026-06-25 from ``near_miss.py`` + ``NearMissRefiner`` to
match the paper's Layer 3 terminology. The old import paths
worked but the naming muddled L3 (in-place Edit) with L4 (new-skill
Create). See `SKILLQ_RUN_RESULTS_2026-06-25.md` for context.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol

from skillq.method.prompts import EDIT_PROMPT
from skillq.method.types import Skill


def _default_editor_model() -> str:
    """Default to the host's ANTHROPIC_MODEL (deepseek-v4-flash in this
    repo's .env) wrapped with the anthropic/ provider prefix for litellm.

    Hardened 2026-06-25: the previous hard-coded ``openai/gpt-4o``
    default silently broke Layer 3 whenever OPENAI_API_KEY was unset
    (which is every host without OpenAI credentials). The bridge
    swallowed the resulting InternalServerError, so the regression
    was invisible — Layer 4 (batched extract) never got a chance
    to run because the on_ended callback raised at Layer 3 first.
    """
    model = os.environ.get("ANTHROPIC_MODEL", "deepseek-v4-flash")
    return f"anthropic/{model}"


class EditProposalBackend(Protocol):
    """A backend that takes ``(prompt, model)`` and returns the proposed
    skill body as a string.
    """

    def __call__(self, prompt: str, model: str) -> str: ...


class StubEditBackend:
    """Deterministic stub for tests: appends an ``EDIT:`` comment."""

    def __call__(self, prompt: str, model: str) -> str:
        return "\n<!-- EDIT: handle previously-missed edge case. -->\n"


@dataclass
class EditRefiner:
    """Apply Layer 3 (Edit) of the paper: minimal in-place editing of
    an existing skill body.

    Compared to the skillsvote ``NearMissEditor`` the only
    behavioural change is that the prompt comes from
    :data:`paper.method.prompts.EDIT_PROMPT` (own wording).

    The previous 20%-of-original-token cap has been removed
    (``edit_token_cap`` field deleted). The LLM is free to rewrite
    as much or as little as it judges necessary; quality control
    falls entirely on the verifier's ``r_learning`` signal feeding
    back into Eq. 6.
    """

    backend: EditProposalBackend
    model: str = field(default_factory=_default_editor_model)
    # 2026-06-26 (L3-H3): bumped 2000 → 6000 so the new two-slot
    # trace (diagnosis + session_tail, each capped at half) actually
    # fits a meaningful 3-message × 2000-char session tail. The old
    # 2000-char budget was tuned for a single-string trace and would
    # have silently truncated the tail to ~500 chars under the new
    # design.
    trace_truncate_chars: int = 6000

    def propose_edit(
        self,
        skill: Skill,
        task: str,
        failure_diagnosis: str = "",
        session_tail: str = "",
    ) -> Skill:
        """Propose an edit and return the new (post-edit) skill.

        2026-06-26 (L3-H3): the previous ``failure_trace: str``
        argument (which the bridge was filling with
        ``str(trial_dir)`` — a directory path, not a trace) has
        been split into two:

          - ``failure_diagnosis``: the analyzer's
            ``knowledge_to_extract`` + ``library_gap_skill_description``
            (free-form diagnosis of what went wrong).
          - ``session_tail``: the last few assistant messages from
            the trial's session jsonl (rendered markdown).

        Each is capped at ``trace_truncate_chars // 2`` so the
        budget is balanced. ``failure_trace`` is kept for
        backward-compat in callers that already pass it
        positionally; it now lands in the diagnosis slot.

        The previous 20%-of-original-token cap has been removed: the
        LLM is allowed to rewrite as much or as little as it judges
        necessary. The only hard sanity checks are:
            - the new body is non-empty
            - the new body differs from the original (a real edit
              actually happened; otherwise the LLM is just echoing
              the input)

        If the proposed body is empty or unchanged, the original
        skill is returned unchanged. The verifier's ``r_learning`` is
        the *only* quality signal — a bad edit will simply not get
        reinforced by future Q-updates.
        """
        prompt = EDIT_PROMPT.format(
            task=task,
            diagnosis=failure_diagnosis[: self.trace_truncate_chars // 2],
            tail=session_tail[: self.trace_truncate_chars // 2],
            tail_k=3,
            old_skill=skill.body,
        )
        new_body = self.backend(prompt, self.model).strip()

        # Basic sanity: empty or no-op edit → keep the original.
        if not new_body or new_body == skill.body.strip():
            return skill

        return Skill(
            skill_id=skill.skill_id,
            body=new_body,
            n_retrievals=skill.n_retrievals,
            n_uses=skill.n_uses,
            n_success=skill.n_success,
            metadata=skill.metadata,
        )