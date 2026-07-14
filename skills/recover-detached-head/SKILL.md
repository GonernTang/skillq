---
name: recover-detached-head
description: Recover commits lost after a detached HEAD checkout by finding them via reflog, inspecting them, and cherry-picking them onto a target branch. Use when the user reports missing commits after checking out a commit/tag/branch, or when HEAD is detached and recent work is not on any branch.
---

# Recover Lost Commits from Detached HEAD

When a user notices their recent commits are missing — typically because they ran `git checkout` on a commit hash, tag, or remote branch and the working tree is now on a detached HEAD — recover the work and land it on a real branch.

## When to use

- User says "my commits are gone", "I lost my work", "detached HEAD", "checked out the wrong thing".
- `git status` shows `HEAD detached at ...` and the expected branch does not contain the new commits.
- The user has not yet run `git reset --hard` or otherwise garbage-collected the reflog entries.

## Procedure

1. **Inspect reflog to locate the lost commit(s).**
   ```
   git reflog -20
   ```
   Look for the most recent entry pointing at the user's expected tip. Note the short hash and the relative time.

2. **Confirm the contents match what the user expects.**
   ```
   git show <hash>
   ```
   Verify the diff matches the work the user thinks they lost. Do not proceed if `git show` does not match.

3. **Identify a safe target branch to land the work on.**
   ```
   git branch -a
   git status
   ```
   Prefer an existing local branch the user names; otherwise create one at the current detached HEAD before continuing. If the user only says "recover", ask which branch they want it on before cherry-picking.

4. **Cherry-pick the lost commit onto the target branch.**
   ```
   git checkout <target-branch>
   git cherry-pick <hash>
   ```

5. **Handle conflicts if cherry-pick stops mid-way.**
   - Open each conflicted file and decide between the user's intended change (`--theirs` relative to the picked commit) and the existing branch content (`--ours`).
   - Edit the file to the desired final content, removing all conflict markers.
   - Stage it: `git add <file>`
   - Continue: `git cherry-pick --continue --no-edit`

6. **Verify and inform the user.**
   - Run `git log --oneline -5` on the target branch and confirm the new tip contains the recovered commit.
   - Tell the user the new commit hash and the branch it now lives on.

## Notes

- Reflog entries expire (default ~90 days) and can be lost after aggressive gc, so recover promptly.
- Prefer `git cherry-pick` over `git reset --hard` or rewriting an existing branch — cherry-pick leaves an audit trail and is reversible.
- If multiple commits were lost, cherry-pick them in chronological order; use `git cherry-pick <hash1> <hash2> ...` or a range `git cherry-pick <oldest>..<newest>`.
- If the target branch already contains a divergent version of the same change, surface that to the user instead of silently overwriting.