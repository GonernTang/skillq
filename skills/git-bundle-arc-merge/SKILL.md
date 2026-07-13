---
name: git-bundle-arc-merge
description: Recover state from git bundles, merge branches with conflict resolution, and solve ARC-AGI grid transformation puzzles by detecting anti-diagonal cycle patterns.
---

# Git Bundle + ARC-AGI Merge Task

Use this procedure when a task involves: (a) one or more git bundles to unpack, (b) merging branches that produce a conflict, and (c) producing a transformed grid output that satisfies ARC-AGI-style input/output examples.

## Step 1 — Bootstrap the working repo

1. Confirm `git` is installed (`git --version`); install it if missing.
2. Create a working directory and run `git init` inside it.
3. Configure a user identity (`git config user.name` / `user.email`) so commits succeed.

## Step 2 — Inspect and fetch bundles

1. List the bundle's heads: `git bundle list-heads /path/to/bundle.bundle`. Note each `HEAD <ref>` line — the right-hand side is the ref name.
2. Fetch each head into a named local branch in one step:
   `git fetch /path/to/bundle.bundle <ref>:refs/heads/<branch-name>`
   Repeat for every head you need.
3. Verify with `git branch -a` and `git log --oneline --all`.

## Step 3 — Merge and resolve the conflict

1. `git checkout <target-branch>` and `git merge <other-branch>`.
2. If a conflict appears, open the conflicting file, decide the intended final content (combine sides by intent, not by literal concatenation), edit it, then `git add <file>` and `git commit`.
3. After the merge, confirm the required artifact file exists on the merged branch (e.g., `ls`/`git show HEAD:<path>`).

## Step 4 — Analyze the ARC-AGI examples

For each training (input, output) pair:

1. Print both grids with row/column indices so you can eyeball structure.
2. Look for invariants: shapes, symmetry axes, row/column sums, diagonals, anti-diagonals, repeating cycles, color/value permutations.
3. Form a hypothesis, then verify it against **every** example before committing to it. Reject hypotheses that fit one example but break another.

## Step 5 — Implement the anti-diagonal cycle transform

A common ARC pattern: each anti-diagonal (cells with the same `i + j`) carries a cycle of non-zero "seed" values, and the full output fills every cell along that diagonal by repeating the cycle.

Procedure:

1. For each anti-diagonal index `d` in the input, collect the non-zero values in row-major order along `i + j == d`.
2. Identify the cycle length `L` — the smallest period that explains the seeds (often the total non-zero count, or a divisor of it).
3. Build the output grid (same dimensions as the input unless the task specifies otherwise).
4. For every cell `(i, j)`, if the input is non-zero, copy it; otherwise compute the cycle index `k = d % L` (where `d = i + j`) and fill with `cycle[k]`.

## Step 6 — Verify against all examples

1. Run your implementation against every training input.
2. Compare the produced output grid to the expected output cell-by-cell.
3. Only finalize the implementation once **all** examples match exactly.

## Step 7 — Finalize

1. Write the final implementation to the required file path on the merged branch.
2. `git add` and `git commit` so the file is reachable from `HEAD`.
3. Re-run verification one last time to confirm the committed version still produces the correct grids.

## Common pitfalls

- Fetching a bundle without naming the local ref leaves you with `FETCH_HEAD` only; always use `<ref>:<local-branch>`.
- "Merge" of two branches that diverged on the same file requires a real edit — `git checkout --theirs/--ours` alone is rarely correct.
- An ARC hypothesis that works on one example but not others is wrong; keep iterating until all examples match.
- Don't forget the `i + j` modulo: off-by-one in the cycle index is the most frequent bug.