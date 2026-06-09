"""Agent-side UCB re-rank step.

This module computes the *UCB breakdown* (Phase-A rank / Phase-B score)
for the skills lqrl has already selected via its own ``step_recommend``,
and appends the result to the instruction. The skills themselves are
unchanged: lqrl's ``SkillsVoteClaudeCode`` has already copied them into
``$CLAUDE_CONFIG_DIR/skills`` by the time this runs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, List

from paper.method.hash import qhash
from paper.method.retrieval import StubEmbedder, TwoStageRanker
from paper.method.types import Skill
from paper.paper_mode.config import PaperRetrievalArgs

if TYPE_CHECKING:  # pragma: no cover
    from skills_vote.harbor.claude_code import SkillsVoteClaudeCode

logger = logging.getLogger("paper.paper.retrieval_step")


_UCB_HEADER = "\n\n[mg UCB re-rank breakdown]\n"
_UCB_FOOTER = "\n[end mg UCB breakdown]\n"


def _list_installed_skills(skills_dir: str) -> List[Skill]:
    """Read ``$CLAUDE_CONFIG_DIR/skills/`` and return :class:`Skill` objects."""
    root = Path(skills_dir)
    if not root.exists() or not root.is_dir():
        return []
    out: list[Skill] = []
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        body_path = child / "SKILL.md"
        if not body_path.is_file():
            continue
        out.append(
            Skill(
                skill_id=child.name,
                body=body_path.read_text(encoding="utf-8", errors="replace"),
            )
        )
    return out


async def rerank_with_ucb(
    agent: "SkillsVoteClaudeCode",
    instruction: str,
    args: PaperRetrievalArgs,
) -> str:
    """Append a UCB re-rank breakdown of the installed skills to ``instruction``.

    The installed-skill list comes from the environment's skill directory
    (``$CLAUDE_CONFIG_DIR/skills`` by default). We re-rank the top
    ``args.k1`` by cosine similarity and re-order by the Eq. 4 score.
    Because the paper method does not yet have a Q-table when the agent
    first runs, the Q-value term is a constant 0; only the
    similarity + UCB bonus are meaningful in cold start.
    """
    skills_dir = getattr(agent, "skills_dir", None)
    if not skills_dir:
        return instruction
    skills = _list_installed_skills(skills_dir)
    if not skills:
        return instruction

    embedder = StubEmbedder()  # avoid a LiteLLM call in the hot path
    ranker = TwoStageRanker(
        embedder=embedder,
        k1=min(args.k1, len(skills)),
        k2=min(args.k2, len(skills)),
        lambda_=args.lambda_,
        c_ucb=args.c_ucb,
    )

    def _q_zero(_skill_id: str) -> float:
        return 0.0

    retrieved = ranker.rank(
        query=instruction,
        skills=skills,
        q_value_lookup=_q_zero,
        total_retrievals=sum(s.n_retrievals for s in skills) + 1,
    )

    if not retrieved:
        return instruction

    intent_hash = qhash(instruction)
    body = _UCB_HEADER
    body += f"intent_hash: {intent_hash}\n"
    body += f"phase_a_pool_size: {min(args.k1, len(skills))}\n"
    body += f"phase_b_top_k: {len(retrieved)}\n"
    body += "\nRanked skills (by Eq. 4 score):\n"
    for r in retrieved:
        body += (
            f"  - {r.skill.skill_id:<40s}  "
            f"score={r.score:+.3f}  "
            f"phase_a={r.phase_a_rank}  phase_b={r.phase_b_rank}\n"
        )
    body += _UCB_FOOTER
    return instruction + body
