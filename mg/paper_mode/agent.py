"""``PaperClaudeCodeAgent`` — a thin subclass of lqrl's
``SkillsVoteClaudeCode`` that appends a UCB re-rank breakdown to the
instruction before delegating to ``super().run()``.

Design intent:

- All of lqrl's lifecycle (skill discovery, environment prep, CLI
  invocation) is reused as-is. We only prepend a small
  ``[mg UCB re-rank breakdown]`` block.
- The :class:`mg.paper_mode.config.PaperRetrievalArgs` can be passed
  via the agent's ``kwargs`` in the Job YAML as ``paper_retrieval``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from skills_vote.harbor.claude_code import SkillsVoteClaudeCode

from mg.paper_mode.config import PaperRetrievalArgs
from mg.paper_mode.retrieval_step import rerank_with_ucb

if TYPE_CHECKING:  # pragma: no cover
    from harbor.environments.base import BaseEnvironment
    from harbor.models.agent.context import AgentContext


class PaperClaudeCodeAgent(SkillsVoteClaudeCode):
    """Lqrl's SkillsVoteClaudeCode with an mg-side UCB re-rank header."""

    @staticmethod
    def name() -> str:
        return "PaperClaudeCodeAgent"

    def __init__(self, *args: Any, paper_retrieval: dict | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._paper_args = PaperRetrievalArgs.model_validate(paper_retrieval or {})

    async def run(
        self,
        instruction: str,
        environment: "BaseEnvironment",
        context: "AgentContext",
    ) -> None:
        # The skills lqrl will copy into $CLAUDE_CONFIG_DIR/skills live in
        # agent.skills_dir (set by the base __init__). We do not need to
        # know the exact runtime location; the retrieval_step reads it
        # from ``self.skills_dir`` at call time.
        if self._paper_args.enabled:
            instruction = await rerank_with_ucb(self, instruction, self._paper_args)
        await super().run(instruction, environment, context)
