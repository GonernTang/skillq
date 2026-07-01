---
name: recover-detached-commit
description: Recover a commit that was made in detached HEAD mode and is now lost after checking out another branch. Use when a user reports losing work after switching branches, says their "commit disappeared" or "HEAD detached" state is gone, or asks how to get back a commit that isn't on any branch. Procedure: (1) `git reflog` to locate the lost commit hash, (2) check out the target branch (e.g. main/master), (3) `git cherry-pick <hash>` to apply the lost commit, (4) if a merge conflict occurs, the incoming (cherry-picked) side typically contains the intended changes — edit to keep the desired content, `git add` the resolved file, then `git cherry-pick --continue`. No `merge` or `rebase` is required.
---

# Recovering a Lost Commit from Detached HEAD

Use this procedure when a commit was created while in detached HEAD state and appears lost after the user checked out a different branch.

## When to use

- User reports a commit "disappeared" after switching branches.
- A commit exists in reflog but not on any branch.
- The user was in detached HEAD, made a commit, then moved away.

## Procedure

1. **Find the lost commit.**
   ```
   git reflog
   ```
   Locate the commit hash corresponding to the lost work. Reflog entries show the action (e.g. `commit: ...`) alongside the short hash.

2. **Move to the branch that should hold the commit.**
   ```
   git checkout <target-branch>
   ```
   Use the branch where the user wants the recovered changes (commonly `main` or `master`).

3. **Cherry-pick the lost commit onto the branch.**
   ```
   git cherry-pick <hash>
   ```
   This replays the lost commit's changes as a new commit on top of the target branch.

4. **Handle conflicts (if any).**
   - Inspect the conflict markers in the affected file(s).
   - The "incoming" side (the cherry-picked commit) is generally the intended content.
   - Edit the file to keep the desired final state, removing the conflict markers.
   - Stage the resolved file:
     ```
     git add <resolved-file>
     ```
   - Finish the cherry-pick:
     ```
     git cherry-pick --continue
     ```

## Notes

- Cherry-pick creates a **new** commit hash on the target branch; the original detached-HEAD commit remains reachable only via reflog until it expires.
- Do **not** use `git merge` or `git rebase` for this scenario — they are unnecessary and riskier than cherry-pick for a single lost commit.
- If the user wants the original commit *identity* preserved (same hash, message, author), cherry-pick alone cannot do that; the commit object itself is unchanged in reflog, but a new commit will be added on the branch.