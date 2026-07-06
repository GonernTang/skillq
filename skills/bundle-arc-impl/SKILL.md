---
name: bundle-arc-impl
description: End-to-end procedure for fetching two git bundles into separate branches, merging them with conflict resolution, and implementing a target function (e.g. `map`) whose signature is fixed but whose body must be deduced from input/output examples. Guard rail against partial completion of the pipeline. Triggers on tasks that combine git bundle operations with example-driven code synthesis (e.g. ARC-style tasks).
---

## When to use

Use this skill when a task requires ALL of the following steps:

1. Initialising a repo and fetching two (or more) git bundles into separate branches.
2. Merging one branch into another and resolving conflicts (often trivial `<<<<<<<` markers or near-identical files).
3. Producing a source file at a fixed path with a fixed function name / signature.
4. Deducing the function body from a JSON / structured set of input→output examples.
5. Verifying the implementation against **every** example (not just one or two).

If any step is skipped, the task is considered failed.

## Procedure

### 1. Bundle fetching

- Confirm `git` is installed (`command -v git`); install if missing.
- Create the target repo directory if absent.
- For each bundle: `git clone <bundle> <workdir>` or `git fetch <bundle> <ref>:<branch>` — record the branch name (`branch1`, `branch2`, …).
- Keep a one-line manifest of branch → bundle path mapping so later steps can reference them.

### 2. Merge with conflict resolution

- Checkout the base branch (typically the one that already contains the target file path).
- `git merge <other-branch>` — expect conflicts. For typical ARC-style tasks, conflicts are markers inside an obvious template; resolve by **preferring the side that contains the function signature / scaffold**, or by concatenating unique regions of both.
- After resolving, `git add` the resolved file and complete the merge commit. Verify `git status` is clean and the target file exists with a syntactically valid skeleton.

### 3. Example-driven implementation

- Locate the examples file (commonly `examples.json`, `*.json`, or similar near the repo root or in a known data directory).
- Read **all** examples — count them and note the I/O shape (dimensions, dtype, edge cases like empty arrays, single-cell arrays).
- Form hypotheses about the transformation: shape-preserving vs shape-changing; per-element rule vs neighbour/global rule; constant output vs computed.
- Pick the simplest hypothesis that fits every example; reject any hypothesis that fails even one case.
- Write the function so it handles the smallest example shape first, then generalises.

### 4. Verification (must loop until clean)

- For each example `(inp, out)` in the dataset:
  - Call the function with `inp`.
  - Compare result to `out` element-wise; on mismatch, print both and stop.
- Zero mismatches across **all** examples is the only acceptable state.

## Diagnostic checklist

Before declaring completion, run ALL of the following:

1. `git log --oneline --all` — confirm both branches are present and the merge commit exists.
2. `ls <target-path>` — confirm the implementation file actually exists at the required path.
3. `python -c "from <module> import <func>"` (or equivalent) — confirm the function imports without error.
4. Programmatically run the function on **every** example in the dataset and assert exact match — do not stop after one passing example.

## Stop signal

If the diagnostics above reveal problems:

- Missing branches → re-fetch bundles; do not start coding.
- Merge conflict unresolved / file missing → re-run merge step before writing code.
- Function fails import → fix signature first, do not chase example logic.
- ≥3 examples fail with the **same** mismatch pattern → the hypothesis is wrong; rewrite from scratch using the examples as the only ground truth (do NOT keep iterating small edits to a wrong hypothesis).
- Implementation passes all diagnostics → task is complete; do not keep editing.

## Common pitfalls

- Stopping after one or two passing examples instead of verifying against the full dataset.
- Resolving merge conflicts by accepting one side wholesale, deleting the function signature.
- Writing the function in the wrong file path or under the wrong name (the task usually specifies both exactly).
- Confusing `numpy` array equality with nested-list equality — convert to a canonical form before comparing.
- Treating the task as one big step ("implement it") instead of five distinct sub-steps.