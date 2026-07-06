---
name: recover-detached-head
description: Recover commits lost when a detached HEAD was left behind by a branch checkout. Use when work appears missing after switching branches, after a "git checkout" left HEAD detached, or when the user says "my commits are gone" / "I lost my work" / "detached HEAD recovery". Triggers on `git status` showing "HEAD detached", a reflog entry pointing at expected work, or a branch that does not contain an expected commit. Procedure: reflog → identify lost commit → confirm absence on target branch → cherry-pick → resolve any conflicts.
---

# Recover Lost Commits from a Detached HEAD

When a user checks out a branch while in a detached-HEAD state (or any commit becomes unreachable from a branch tip), the work is not deleted — it is still reachable via the reflog. Apply the procedure below to restore it.

## Procedure

1. **Show the reflog.** The reflog records every movement of HEAD, including commits that are no longer on any branch.
   ```
   git reflog
   ```
   Look for entries showing the expected commit message or a recognizable hash. Note the hash of the lost commit (the commit the user was last on while detached).

2. **List all branches** to see where work might already exist:
   ```
   git branch -a
   ```

3. **Confirm the commit is not on the target branch.** From the branch the user wants the work on (e.g. `master` / `main`):
   ```
   git log --oneline <branch>..<lost-commit-hash>
   ```
   - Empty output → the commit is reachable from `<branch>`, no action needed (just `git checkout <branch>` if HEAD is detached).
   - Non-empty output → the commit is *not* on `<branch>`; proceed to cherry-pick.

4. **Cherry-pick the lost commit onto the target branch.** First make sure you are on the target branch:
   ```
   git checkout <target-branch>
   git cherry-pick <lost-commit-hash>
   ```

5. **Resolve conflicts if they occur.** Cherry-pick stops with `UU` (both modified) markers on conflicting files.
   - Open each conflicted file. Git inserts conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`).
   - Choose the correct content (often the incoming changes from the lost commit, or a manual merge of both sides).
   - Save the file.
   - Stage it:
     ```
     git add <conflicted-file>
     ```
   - Continue the cherry-pick:
     ```
     git cherry-pick --continue
     ```
   - Git opens the editor for a merge message; accept the default (or edit) and save.

6. **Verify.** Confirm the commit is now part of the branch's history:
   ```
   git log --oneline -n 5
   git log --oneline <lost-commit-hash>^..<target-branch>
   ```

## Notes

- The reflog is local; it is not pushed to remotes. If the user committed on a different clone, recover from that clone's reflog.
- Reflog entries expire (default 90 days for reachable, 30 for unreachable). Act quickly.
- If multiple commits were made on the detached HEAD, cherry-pick each in chronological order (oldest first), or use `git rebase --onto <target-branch> <parent-of-first-lost-commit> <lost-tip>`.
- If the user is currently on a detached HEAD and wants to *keep* the work on a new branch instead of merging into an existing one: `git switch -c <new-branch-name>` (or `git checkout -b <new-branch>`) — this attaches the detached commits to the new branch directly, no cherry-pick needed.