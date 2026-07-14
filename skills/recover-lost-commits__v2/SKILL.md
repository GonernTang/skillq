---
name: recover-lost-commits
description: Recover seemingly lost git commits (e.g., after branch checkout that left a detached HEAD) by using reflog, inspection, and cherry-pick onto a target branch.
---

# Recover Lost Commits with Reflog + Cherry-Pick

When work appears to vanish after checking out a branch or switching contexts (often leaving a detached HEAD), the commits are usually still in the repository — just not reachable from any branch. Use reflog to find them and cherry-pick to restore them onto the current branch.

## When to use

- A commit's changes are missing from the working tree after a branch checkout.
- HEAD shows "(detached)" or the expected branch no longer contains the work.
- You suspect a commit was made on a detached HEAD, an unrelated branch, or before a destructive operation (`reset`, `rebase`, branch deletion).

## Procedure

1. **List recent HEAD movements with reflog.**
   ```
   git reflog
   ```
   Look for entries showing the commit hash, a short message, and the action (e.g., `commit:`, `checkout:`). The lost commit is the most recent `commit:` entry not on the current branch.

2. **Inspect the candidate commit before applying it.**
   ```
   git show <commit-hash>
   ```
   Confirm the diff matches the lost work. Note the parent commit to anticipate potential conflicts.

3. **Cherry-pick onto the current branch.**
   ```
   git cherry-pick <commit-hash>
   ```
   This replays the commit's changes onto the current branch as a new commit, preserving authorship and message.

4. **Resolve conflicts if they occur.**
   - Open the conflicting file(s) and edit to the desired content.
   - Remove every conflict marker (`<<<<<<<`, `=======`, `>>>>>>>`).
   - Stage the resolved file(s):
     ```
     git add <file>
     ```
   - Finalize the cherry-pick:
     ```
     git cherry-pick --continue
     ```
     Add `--no-edit` to keep the original commit message instead of being prompted to edit it.

5. **Verify recovery.**
   ```
   git log --oneline -5
   git status
   ```
   Confirm the new commit is present on the current branch and the working tree matches expectations.

## Notes

- Reflog is local and per-repository; it survives resets, rebases, and branch deletion but not repository deletion. It is your safety net for "where did my commit go?"
- If the same changes were already partially applied to the current branch, cherry-pick will produce empty commits — abort with `git cherry-pick --abort` and inspect with `git show` first.
- For multiple lost commits, cherry-pick each in order, or use `git rebase --onto <new-base> <old-base>` to move a range of commits.