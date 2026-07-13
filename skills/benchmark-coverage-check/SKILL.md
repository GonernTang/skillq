---
name: benchmark-coverage-check
description: When answering "which model is best on benchmark X" or ranking models from a leaderboard, verify every candidate has been evaluated on the full required task set before comparing means. Prevents picking a near-perfect score from a model that only ran a small fraction of the benchmark's tasks.
---

# Benchmark Coverage Check

A high mean score is only comparable across models when each model was evaluated on the same task set. Leaderboards that publish both a "Mean (Task)" column and a "Number of Tasks" / coverage column need both readings — not just the mean — before you can rank models fairly. Picking the row with the largest mean and ignoring coverage yields a wrong answer whenever a model with partial submissions outranks one with full submissions.

## Diagnostic Checklist

Run all of the following before committing to a winner or a ranking:

- [ ] **Identify the canonical task set.** Confirm how many tasks the benchmark defines as complete coverage, and whether it has an official "minimum tasks required to be ranked" rule (e.g., all 28 tasks, all 56 tasks, language-specific subsets).
- [ ] **Read the coverage column for every contender.** Locate the "Number of Tasks", "Coverage %", or per-task presence indicator. Treat a model missing entries on a large fraction of tasks as incomparable, regardless of its mean.
- [ ] **Apply the benchmark's official ranking criterion.** If the leaderboard ranks only coverage-filtered means, use that filter. If it publishes multiple rankings (e.g., "overall" vs "per-task submission"), state which definition you used.
- [ ] **Filter-then-rank, then report.** Restrict the candidate set to models meeting the benchmark's coverage threshold FIRST, then pick the highest mean among that filtered set. Always return the model identifier in `organization/model_name` form.

## Stop Signal

**STOP** if you are about to answer "best model on X" while any of the following is true:

- A candidate you considered has coverage below the benchmark's official minimum (for example, fewer tasks than the benchmark defines as complete, or below the leaderboard's stated coverage threshold).
- You cannot locate the coverage / tasks-evaluated column for one or more candidates and are guessing.
- Two or more contenders tie on mean and you have not used coverage or the per-task scores to break the tie.

**Reset action:** Return to the source table; find the coverage column; apply the benchmark's coverage threshold; re-rank only the qualifying models; restate the threshold you applied in the final answer. If no model meets the threshold, say so explicitly rather than relaxing the rule silently.