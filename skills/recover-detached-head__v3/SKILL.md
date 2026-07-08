---
name: recover-detached-head
description: Recover lost commits after a branch checkout by finding dangling commits via reflog, identifying the divergence point, dry-running a merge, resolving conflicts, and committing.
---

# Recover Commits After a Detached-HEAD Checkout

When a user reports that work disappeared after `git checkout <branch>`, the changes usually still exist as dangling commits reachable only from the reflog. Use this procedure to find, inspect, and merge them safely.

## 1. Inspect the reflog

```bash
git reflog
```

Identify the most recent entries. Look for:
- A `checkout: moving from <branch> to <commit>` that lost the work.
- The commit hash that was checked out (the detached HEAD).
- The commit/branch HEAD pointed to **before** that checkout — that is the last safe point and the likely merge-base with the target branch.

## 2. Diff the dangling commit against the merge-base

For each candidate dangling commit `<X>`:
```bash
git diff <merge-base>..<X>
```
Compare this against `git diff <merge-base>..<target-branch>` to understand what each side changed. This tells you whether a merge will combine cleanly or conflict.

## 3. Dry-run the merge

```bash
git checkout <target-branch>
git merge --no-commit --no-ff <X>
```

`--no-commit --no-ff` stages a merge commit without finalizing it, so you can inspect conflicts before committing. If there are no conflicts, Git stops with a merge-in-progress state and you can commit directly.

## 4. Resolve conflicts

If conflicts appear:
1. For each file marked "Unmerged", read it to see the `<<<<<<<`, `=======`, `>>>>>>>` markers.
2. Decide which version(s) to keep — often a combination of both sides plus any manual edits needed.
3. Edit the file to produce the desired content, removing all conflict markers.
4. Stage the resolved file: `git add <file>`.
5. Repeat for every conflicted file until `git status` shows no unmerged paths.

## 5. Finalize the merge

```bash
git commit -m "Merge recovered work from <X>"
```

Verify with `git log --oneline -5` and `git status` that the working tree is clean and the recovered changes are present.

## Safety rules

- Never run `git reset --hard` or `git stash drop` until you have confirmed the recovered commit exists where you expect it.
- Prefer `--no-commit --no-ff` over a direct merge so you can abort with `git merge --abort` if something looks wrong.
- If the dangling commit is already on a feature branch you control, you can also `git reset --hard <X>` on that branch instead of merging — but only after confirming the diff matches the lost work.