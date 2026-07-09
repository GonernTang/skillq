---
name: recover-detached-head
description: Recover work lost when checking out a branch from a detached HEAD state using git reflog, cherry-pick, and conflict resolution.
---

# Recover Detached HEAD Changes

When you make commits in a detached HEAD state and then check out a branch (or do something that moves HEAD elsewhere), your commits can appear "lost" because no branch points to them. This skill recovers them onto the current branch.

## When to use

- Commits were made while HEAD was detached and seem to disappear after `git checkout` or other HEAD movements.
- User reports work missing after a branch/checkout operation.
- You see `HEAD detached at <hash>` in `git status` and worry about losing changes.

## Recovery steps

1. **Locate the lost commits with reflog**
   ```
   git reflog
   ```
   Look for entries like `commit: <message>` and the `checkout: moving from <hash> to <branch>` line just after it. The hash *before* the checkout is the tip of your detached-HEAD work.

2. **Inspect to confirm the right commit**
   ```
   git show <hash> --stat
   git show <hash>             # full diff
   ```
   Verify the files and content match the "lost" work. If there are multiple, the latest detached-HEAD hash is the one to recover (it transitively contains the earlier ones).

3. **Cherry-pick onto the current branch**
   ```
   git cherry-pick <hash>
   ```
   This reapplies the commit's changes on top of whichever branch you're on now.

4. **Resolve conflicts if they arise**
   - Read the conflicted file(s). Conflict markers look like:
     ```
     <<<<<<< HEAD
     ...current-branch version...
     =======
     ...cherry-picked version...
     >>>>>>> <hash> ...commit message...
     ```
   - Decide which side to keep. For "recover lost work," usually the `>>>>` side (the cherry-picked change) is the intent — but read both sides and pick a semantically correct result.
   - Edit the file to the desired final state, removing all `<<<<`, `====`, `>>>>` lines.
   - Stage the resolved file: `git add <file>`
   - Continue: `git cherry-pick --continue --no-edit`
     (use `--no-edit` to accept the original commit message; drop it to amend)

   To abort instead: `git cherry-pick --abort`.

5. **Verify the result**
   ```
   git log --oneline -5
   ```
   Confirm the recovered commit now appears on the branch. Then read the modified files to ensure the content is correct and complete.

## Tips

- Reflog is your safety net — `git reflog` shows every HEAD movement, so detached commits are almost always recoverable as long as they were committed (or stashed).
- If the user only had unstaged/uncommitted changes (not commits), reflog won't help. Look for `git stash list` instead, or check `git fsck --lost-found` for dangling blobs.
- After recovery, consider creating a branch at the recovered commit to avoid the same situation: `git branch recovered-work <hash>` (only useful if the reflog entry might age out before the next step).
- For multiple lost commits, cherry-pick them in chronological order (oldest first), or cherry-pick the range: `git cherry-pick <oldest>..<newest>`.