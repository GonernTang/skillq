---
name: recover-detached-head
description: Recover lost commits made on a detached HEAD after checking out another branch. Use when commits seem to have "disappeared" because they were made without a branch attached.
---

# Recover Lost Commits from a Detached HEAD

When you make commits while in detached HEAD state (e.g., after `git checkout <sha>` or `git checkout origin/main`) and then check out another branch, those commits appear to vanish because no branch points to them. Git's reflog retains them and they can be restored.

## Procedure

1. **Find the lost commit in the reflog**
   ```
   git reflog
   ```
   Look for the entry showing your commit on the detached HEAD. Note its short SHA (the `HEAD@{n}` selector or the commit hash both work).

2. **Create a branch at the lost commit**
   ```
   git branch <recovery-branch> <commit-hash>
   ```
   This creates a branch pointing at the lost work so it cannot be garbage-collected.

3. **Merge the recovery branch into your current branch**
   ```
   git merge <recovery-branch>
   ```
   A fast-forward is most likely (your branch was likely behind the lost commit). If Git cannot fast-forward, it produces a merge commit. If conflicts occur, resolve them by editing the conflicted files, then `git add` each resolved file and run `git merge --continue` (or repeat `git add` and `git commit` if prompted).

4. **Verify and clean up**
   ```
   git log --oneline -5
   git branch -d <recovery-branch>
   ```
   Confirm the recovered commits are now on your branch, then delete the temporary recovery branch.

## Notes

- The reflog is local to the repository and expires after the default gc window (90 days for reachable commits, 30 for unreachable). Act promptly.
- `git fsck --lost-found` is an alternative if the reflog has already been pruned — it surfaces dangling commits by hash.
- If the recovery branch cannot be merged (e.g., unrelated history), you may instead `git cherry-pick <commit-hash>` or `git rebase --onto` to transplant the work.