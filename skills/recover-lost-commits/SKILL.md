---
name: recover-lost-commits
description: Recover commits that seem lost after a branch checkout or detached HEAD by using git reflog and git cherry-pick. Use when a user reports missing changes, an unexpected detached HEAD, or commits that appear to have vanished after switching branches.
---

# Recover Lost Commits After Branch Checkout

## When to use

Use this skill when:
- A user reports that recent work/changes are missing after `git checkout` of another branch.
- `git status` shows a detached HEAD with work that is "gone".
- The user wants to bring commits from a detached HEAD back onto a current branch.

## Procedure

1. **Inspect the reflog** to find the missing commit:
   ```
   git reflog
   ```
   Look for entries where the user was previously checked out and made commits. Note the commit hash (short or full) of the commit that holds the lost work.

2. **Confirm what that commit contains** (optional but recommended):
   ```
   git show <hash>
   ```
   Verify the diff matches what the user expects to recover.

3. **Ensure you are on the target branch** where the work should land:
   ```
   git checkout <target-branch>
   ```
   If the branch is not yet created, create it first from the current commit: `git switch -c <new-branch>`.

4. **Cherry-pick the lost commit** onto the current branch:
   ```
   git cherry-pick <hash>
   ```
   This replays the commit's changes on top of the current branch.

5. **Handle conflicts if they appear**:
   - List conflicted files:
     ```
     git diff --name-only --diff-filter=U
     ```
   - Open each file, remove the conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`), and keep the desired content.
   - Stage each resolved file:
     ```
     git add <file>
     ```
   - Complete the cherry-pick:
     ```
     git cherry-pick --continue
     ```
   - If the user decides they do not want the commit after all: `git cherry-pick --abort`.

6. **Verify the recovery**:
   ```
   git log --oneline
   git diff <previous-branch-tip>..HEAD
   ```
   Confirm the new commit appears in the log and the diff shows the expected changes.

## Key tips

- The reflog is the source of truth for "lost" work — git rarely deletes commits immediately; they are usually just unreachable from the current branch.
- Cherry-pick copies the commit (it does not move the original), so it is safe to use even when the original reflog entry will eventually expire.
- If multiple commits need to be recovered, cherry-pick them in chronological order, or use `git rebase --onto <target> <old-base> <reflog-tip>` to replay a range.
- Always verify with both `git log` and `git diff` before declaring success — the user should see the recovered content explicitly.