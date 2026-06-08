---
name: paper-method
description: Use when the user wants the agent to follow the LQRL paper's four-layer skill governance (UCB retrieval → β-Q update → library management → near-miss edit). Different from skills-vote / skills-vote-local: the paper method uses a Q-table, an informationally isolated verifier, and a 20%-cap near-miss editor.
metadata:
  version: "0.1.0"
---

# Paper Method (LQRL)

Read only this file first. Do **not** read `scripts/` or any other files
in this skill unless this file or a script output explicitly tells you
to do so.

Use this skill when the current task should follow the LQRL paper's
four-layer method:

1. Two-stage retrieval (cosine + UCB re-rank).
2. β-layered Q-learning (Eq. 6 with informationally isolated verifier).
3. Q-driven library management (admission / eviction / rejuvenation).
4. Near-miss-aware incremental editing (20% token cap).

Skip this skill if the user only wants vanilla Codex / Claude
behaviour, or if `mg lqrl` mode is in use (in which case use the
`skills-vote` / `skills-vote-local` skills instead).

All paths mentioned in this file are relative to this skill root.

## Preconditions

- `OPENAI_API_KEY` is set in the environment (used by the embedder /
  verifier / editor backends).
- `uv` is available on `PATH`.
- The `mg paper` mode is being used (not `mg lqrl`).

## Discover

Run once at the start of a task:

```bash
uv run -qq scripts/route_prompt.py --role main
```

The script will:

1. Read the working skills directory (mounted by Harbor).
2. Embed each skill body + the current task description.
3. Re-rank by the paper's Eq. 4 score (similarity + z-scored Q + UCB).
4. Print the top-$k_2$ skill names plus the score breakdown.

Use the printed list as your authoritative "which skills are
relevant" signal for this task.

## Feedback (audit only)

The paper method does **not** require a per-step feedback prompt. The
informationally isolated verifier scores the (old, new) skill content
delta after each trial end. To inspect the verifier's rationale for a
recent verdict:

```bash
uv run -qq scripts/route_prompt.py --role explain --verdict <verdict_id>
```

## Style

- When you say "I'm using skill X", cite the Eq. 4 score breakdown
  that the route script printed.
- When you decide not to use a high-similarity skill, mention the
  UCB bonus in the explanation.
- After a failed task, do not invent new skills yourself; the
  paper method's near-miss editor will rewrite an existing skill
  if the failure qualifies.
