---
name: git-recover-detached-commits
description: Recover lost commits after a branch checkout that left the user on a detached HEAD. Use `git reflog` to surface recent commits, inspect each one with `git show`, then reapply onto the current branch with `git cherry-pick` (resolving conflicts as needed), and verify with `git log` / `git diff`.
---

# Recovering Lost Commits from a Detached HEAD

When a user reports that changes have disappeared after checking out a branch
or moving to a detached HEAD, recover the work by walking the reflog and
replaying any recently-made commits onto the current branch.

## When to use

- A user says work "vanished" after `git checkout`, `git switch`, `git reset`,
  or any operation that moved HEAD.
- The current HEAD is detached or the expected commits are not visible on
  any branch tip.
- Files appear reverted or missing in the working tree.

## Procedure

1. **Survey recent history with reflog.**
   ```bash
   git reflog
   ```
   Identify the most recent commit(s) on the detached HEAD that are not
   reachable from any current branch. Note their short SHAs and the action
   that orphaned them (e.g. `checkout: moving from ...`).

2. **Confirm what each candidate commit contains.** For each suspicious
   commit:
   ```bash
   git show <sha>
   ```
   Read the diff. Confirm the commit really holds the user's lost work before
   replaying it.

3. **Reapply onto the target branch.** Switch to (or stay on) the branch that
   should hold the work, then apply each recovered commit in the order it
   was originally made:
   ```bash
   git checkout <target-branch>
   git cherry-pick <sha1> <sha2> ...
   ```

4. **Resolve conflicts if cherry-pick stops.**
   - Edit the conflicted files to the correct combined content.
   - `git add <resolved-files>`.
   - `git cherry-pick --continue` to move on to the next commit.
   If the recovery should abandon the attempt, run `git cherry-pick --abort`
   to leave the working tree as it was before the cherry-pick.

5. **Verify the final state.** Before declaring success:
   ```bash
   git log --oneline -n <count>
   git diff <previous-branch-tip>..HEAD
   ```
   Confirm the user's changes appear in the log and that the diff against
   the prior branch tip matches the work they expected to keep.

6. **Optionally preserve the recovered SHA as a safety branch.** If the user
   wants belt-and-suspenders, create a backup branch pointing at the commit
   before cherry-picking:
   ```bash
   git branch recovered/<descriptive-name> <sha>
   ```
   This guarantees the commit survives even if cherry-pick is later undone.

## Pitfalls

- Do **not** run `git gc` or prune before reflog inspection — reflog entries
  persist only ~90 days by default, but aggressive pruning can drop them
  earlier.
- Cherry-pick reproduces the commit **content** but creates **new** SHAs. The
  original reflog entry remains valid as a backup but is no longer part of
  the new branch's history.
- If multiple squashed or merge commits are mixed in the reflog, prefer
  `git show --stat` first to decide whether to cherry-pick, replay, or
  re-create them.
- Verify with `git status` and `git diff` at every step so a half-applied
  state does not look like success.