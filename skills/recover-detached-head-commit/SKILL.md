---
name: recover-detached-head-commit
description: Recover a lost commit made on a detached HEAD and merge it into a target branch using git reflog, branching, merging, conflict resolution, and cleanup.
---

# Recover a Lost Commit from Detached HEAD

Use this procedure when work was committed on a detached HEAD (no branch pointer) and you need to bring those changes onto a named branch such as `main` or `master`.

## Steps

1. **Locate the lost commit via reflog.**
   - Run `git reflog` to list recent HEAD movements.
   - Identify the entry that corresponds to the lost commit and copy its short or full SHA.

2. **Verify the commit contents.**
   - Run `git show <commit-sha>` to inspect the diff, message, and files changed.
   - Confirm this is the work you intend to recover before continuing.

3. **Create a branch pointing at the recovered commit.**
   - Run `git branch <branch-name> <commit-sha>`.
   - Choose a descriptive name (e.g. `recovered-work`, `fix-<topic>`).
   - Do **not** use `git checkout` here — that would move HEAD again. Branching alone is sufficient and safer.

4. **Switch to the target branch.**
   - Run `git checkout <target-branch>` (e.g. `main` or `master`).
   - Confirm with `git status` that the working tree is clean.

5. **Merge the recovered branch.**
   - Run `git merge <branch-name>`.
   - If the merge is fast-forward, the recovered commit becomes reachable directly on the target branch.
   - If a merge commit is produced, git will open the configured editor for the message — accept the default or write a descriptive one.

6. **Resolve conflicts if any appear.**
   - Run `git status` to list conflicted files.
   - Open each conflicted file and decide per hunk:
     - Keep the target branch's version, **or**
     - Keep the recovered branch's version, **or**
     - Combine both into a coherent result.
   - Delete the conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`).
   - Stage each resolved file with `git add <path>`.
   - Complete the merge with `git commit` (no message needed — git prefills it).

7. **Clean up the temporary branch.**
   - Run `git branch -d <branch-name>` to delete the now-merged branch.
   - If the branch was not fully merged and you are sure it is safe, use `-D` instead.

8. **Verify the final state.**
   - Run `git log --oneline -n 5` to confirm the recovered commit is on the target branch.
   - Run `git status` to confirm a clean working tree.

## Common pitfalls

- **Don't skip `git show`.** Always verify the SHA before branching — reflog entries near each other can look similar.
- **Don't `git checkout` the SHA directly** in step 3; that re-attaches detached HEAD and defeats the purpose.
- **Don't leave conflict markers** in resolved files — the merge commit will still be created but the build/tests may break later.
- **Don't forget cleanup.** An unmerged temporary branch lingers in `git branch -a` output and confuses future reflog triage.

## When to escalate

- The recovered commit's parent is unclear or appears corrupted → investigate with `git fsck --lost-found`.
- The merge produces conflicts that touch generated files (lockfiles, build outputs) → regenerate after resolution rather than hand-merging.