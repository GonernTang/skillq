"""L1 force-use text — the user-facing Top-K reminder.

Step 2 of the 2026-06-26 refactor extracted these formatters from
:mod:`skillq.runtime.hook`. They are pure (no I/O, no LLM
calls); the host-side ``ranking_service`` uses them to build the
Top-K JSON the agent sees and the container-side hook's deny-reason
string in the new ``runtime/hook.py`` (Step 5) reuses them too.
"""

from __future__ import annotations

from typing import Any

# Sentinel message when the strict Hard Gate (sim_gate_floor=0) drops
# every candidate. Sharper than a confusing "Top-0 skills" header —
# the agent gets explicit "skip Skill() and solve directly" guidance.
NO_RELEVANT_SKILLS_DENY = (
    "No skills in the library are relevant to this sub-task "
    "(every candidate is below the sim=0.7 similarity gate). "
    "Skip the Skill() call and solve this directly."
)
NO_RELEVANT_SKILLS_PULL = (
    "No skills in the library are relevant to this task "
    "(every candidate is below the sim=0.7 similarity gate). "
    "Don't invoke the Skill tool for this turn — solve directly."
)


def format_top_k(top_k: list[tuple[str, float]]) -> str:
    """Format the deny-reason text the agent sees after a blocked Skill() call.

    Two cases:
      1. ``top_k`` non-empty — list the gated+scored candidates and
         tell the agent it MUST re-issue Skill() with one of them.
         The hook is fail-open at the protocol level (the agent can
         technically ignore the deny), but the text now sharpens the
         contract: the agent is required to call Skill() before
         continuing with other tools.
      2. ``top_k`` empty (sim_gate_floor=0 + all sim<threshold) —
         emit an explicit "no relevant skills" message. This is the
         strict-gate design (2026-06-25): if every candidate is below
         ``sim_gate_min_score`` AND there's no floor to keep fallbacks,
         we DO NOT hand the agent an irrelevant list. Irrelevant
         skills would otherwise pollute both the agent's context
         ("maybe I should try one of these?") and the Q-table's
         per-trial UCB update (n_retrievals++ for skills that should
         never have been retrieved). Tell the agent to solve directly.
    """
    if not top_k:
        return NO_RELEVANT_SKILLS_DENY
    lines = [f"Top-{len(top_k)} relevant skills (re-rank by Eq. 4 global-Q):"]
    for i, (sid, score) in enumerate(top_k, 1):
        lines.append(f"  {i}. {sid}   score={score:+.3f}")
    lines.append("")
    lines.append(
        "You MUST call Skill() with one of these — re-issue the "
        "Skill() call before continuing."
    )
    return "\n".join(lines)


_format_top_k = format_top_k  # legacy private alias


def format_pull_context(
    top_k: list[tuple[str, float]],
    skills: list[dict[str, Any]],
) -> str:
    """Compact reminder text injected via SessionStart additionalContext.

    Shows skill_id (used by the Skill tool) and description (truncated to
    120 chars). Body is intentionally excluded — at full lib size 1000
    bodies would blow the agent's context budget.

    2026-06-25 (strict Hard Gate): when ``top_k`` is empty (no skill
    above the sim gate), we DO NOT emit a confusing "Top-0 skills"
    list. Instead the agent gets an explicit "no relevant skills"
    message so it doesn't burn turns trying to invoke Skill() with
    nothing useful to choose from.
    """
    if not top_k:
        return NO_RELEVANT_SKILLS_PULL
    by_id = {s["skill_id"]: s for s in skills}
    lines = [
        f"Top-{len(top_k)} skills available for this task "
        "(invoke via the Skill tool, e.g. Skill(skill=\"<id>\")):"
    ]
    for i, (sid, score) in enumerate(top_k, 1):
        sk = by_id.get(sid, {})
        desc = (sk.get("description") or "").replace("\n", " ").strip()
        if len(desc) > 120:
            desc = desc[:117] + "..."
        lines.append(f"  {i}. {sid}   score={score:+.3f}")
        if desc:
            lines.append(f"     {desc}")
    # 2026-06-26 (force-use): sharpen the contract. When the gate
    # produced candidates, the agent is required to call Skill()
    # with one of them before using other tools. The hook itself
    # remains fail-open at the protocol level (UserPromptSubmit
    # additionalContext is advisory), but the closing reminder
    # makes the contract explicit.
    lines.append("")
    lines.append(
        "You MUST call Skill() with one of these before using other tools."
    )
    return "\n".join(lines)


_format_pull_context = format_pull_context  # legacy private alias


__all__ = [
    "format_top_k",
    "format_pull_context",
    "NO_RELEVANT_SKILLS_DENY",
    "NO_RELEVANT_SKILLS_PULL",
]