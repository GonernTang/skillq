---
name: recover-lost-commit
description: Recover a lost or missing commit from a Git repository by using reflog, cherry-pick, and resolving conflicts. Use when commits appear missing after branch checkouts, rebases, or detached HEAD operations.
---

# Recover a Lost Commit in Git

When a commit seems to disappear (e.g., after `git checkout master` from a feature branch, a rebase, or a detached HEAD), the commit is usually still reachable via the reflog. This procedure walks through locating, verifying, and re-applying it.

## When to use

- Commits are missing from the current branch after a checkout/switch.
- A feature branch's work vanished and you need it back on the current branch.
- You suspect the commit is floating on a detached HEAD.

## Procedure

### 1. Locate the lost commit

```bash
git reflog
```

Scan the output for the commit hash associated with the lost work. Look for entries referencing the branch you were on, or recent commits whose message matches what you're looking for.

### 2. Verify the commit contents

```bash
git show <commit-hash>
```

Confirm the commit message, author, and the files/diffs match the work you expected to lose. Do not skip this step — cherry-picking the wrong commit is hard to undo cleanly.

### 3. Cherry-pick onto the current branch

```bash
git cherry-pick <commit-hash>
```

This applies the commit's changes as a new commit on the current branch.

### 4. Handle merge conflicts (if any)

If git reports conflicts:

1. Open each conflicted file and inspect the conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`).
2. Resolve by keeping the desired version — typically the **incoming** cherry-pick (the change from `<commit-hash>`), unless context dictates otherwise.
3. Remove the conflict markers so the file is valid.
4. Stage the resolved file:

   ```bash
   git add <resolved-file>
   ```

5. Complete the cherry-pick:

   ```bash
   git cherry-pick --continue
   ```

   Or, to reuse the original commit message without opening an editor:

   ```bash
   git cherry-pick --continue --no-edit
   ```

### 5. Verify the recovery

Confirm three things:

- The commit hash now appears in the branch's log:

  ```bash
  git log --oneline -n 5
  ```

- The branch contains the expected files/changes:

  ```bash
  git show HEAD
  ```

- No diff remains between the original (lost) commit and the new HEAD:

  ```bash
  git diff <commit-hash> HEAD
  ```

  An empty diff means the cherry-pick exactly reproduced the original change set.

## Notes

- The reflog is local and pruned after long periods of inactivity — act sooner rather than later.
- If multiple commits were lost, cherry-pick each one in chronological order (oldest first) to preserve history.
- If the cherry-pick produces a *different* commit hash but identical contents, that's expected — cherry-pick always creates a new commit; verify with `git diff` instead of comparing hashes.
- Avoid `git reset --hard` until you have confirmed the commit is back, since hard resets can be difficult to reverse.