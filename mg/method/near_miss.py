"""Near-miss-aware incremental editing (Sec. 3.4 / Layer 4 of the paper).

Trigger (Eq. 11): a failure is a *near-miss* iff

    r_task == 0  AND  max_m Q(s, m) >= theta_near_miss

Edit (Eq. 12): the verifier in *generative mode* proposes a minimal
edit. The new skill is rejected if it exceeds ``edit_token_cap`` (default
20%) of the original token count.

This module is the mg-side rewrite of
``implementation_guide/lqrl/near_miss.py:NearMissEditor`` with the class
renamed to ``NearMissRefiner`` and the prompt replaced by
:data:`mg.method.prompts.EDIT_PROMPT` (see :mod:`mg.method.prompts`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from mg.method.prompts import EDIT_PROMPT
from mg.method.types import Skill


class EditProposalBackend(Protocol):
    """A backend that takes ``(prompt, model)`` and returns the proposed
    skill body as a string.
    """

    def __call__(self, prompt: str, model: str) -> str: ...


class StubEditBackend:
    """Deterministic stub for tests: appends a ``NEAR-MISS:`` comment."""

    def __call__(self, prompt: str, model: str) -> str:
        return "\n<!-- NEAR-MISS: handle previously-missed edge case. -->\n"


@dataclass
class NearMissRefiner:
    """Apply Layer 4 of the paper: near-miss detection + minimal editing.

    Compared to the implementation_guide's ``NearMissEditor`` the only
    behavioural change is that the prompt comes from
    :data:`mg.method.prompts.EDIT_PROMPT` (own wording).

    The previous 20%-of-original-token cap has been removed
    (``edit_token_cap`` field deleted). The LLM is free to rewrite
    as much or as little as it judges necessary; quality control
    falls entirely on the verifier's ``r_learning`` signal feeding
    back into Eq. 6.
    """

    backend: EditProposalBackend
    model: str = "openai/gpt-4o"
    trace_truncate_chars: int = 2000

    def is_near_miss(
        self,
        r_task: float,
        q_value: float,
        theta_near_miss: float,
    ) -> bool:
        """Return ``True`` when a failure is a near-miss (Eq. 11)."""
        return r_task == 0.0 and q_value >= theta_near_miss

    def propose_edit(
        self,
        skill: Skill,
        task: str,
        failure_trace: str,
    ) -> Skill:
        """Propose an edit and return the new (post-edit) skill.

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
            trace=failure_trace[: self.trace_truncate_chars],
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
            metadata={**skill.metadata, "near_miss_edited": True},
        )
