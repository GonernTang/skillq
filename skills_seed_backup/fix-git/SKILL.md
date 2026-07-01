---
name: fix-git
description: >-
  Diagnose and safely recover from common Git problems: detached HEAD, wrong
  branch commits, bad merges/rebases, accidental resets, lost commits, dirty
  working trees, push rejections, and broken/corrupt repo state. Use when the
  user says git is "broken", "stuck", "messed up", reports a scary git error,
  asks to undo a commit/merge/rebase/reset, recover lost work, or fix a failed
  push/pull. Emphasizes non-destructive recovery and confirming before any
  history-rewriting or destructive command.
---

# Fixing Git

A diagnose-first playbook for recovering from common Git trouble without losing
work. The guiding principle: **understand the current state before changing it,
and prefer reversible moves over destructive ones.**

## Golden rules

1. **Diagnose before acting.** Always run the read-only triage commands first.
   Never run a fix until you know the actual state.
2. **`git reflog` is your safety net.** Almost nothing is truly lost for ~90
   days. Before despairing over "lost" commits, check the reflog.
3. **Confirm before destructive or history-rewriting commands.** `reset --hard`,
   `clean -f`, `push --force`, `checkout -- <file>`, `branch -D`, `rebase`, and
   `commit --amend` on pushed commits can destroy work or other people's work.
   State what will happen and get explicit user approval first.
4. **Never force-push shared branches** (`main`/`master`/`develop` or anything
   others pull) without the user explicitly confirming. Prefer
   `--force-with-lease` over `--force` when a force-push is genuinely needed.
5. **Preserve, don't discard.** If you find unexpected files, branches, or
   stashes, investigate — they may be the user's in-progress work.

## Step 1 — Triage (always run these, read-only)

```bash
git status              # working tree + staged state, current branch
git log --oneline -10   # recent history on current branch
git branch -vv          # branches + their upstream tracking
git reflog -20          # the safety net: where HEAD has been
git remote -v           # remotes, to understand push/pull targets
```

From these you can identify which scenario below applies.

## Step 2 — Match the symptom, apply the fix

### Detached HEAD
Symptom: `git status` says "HEAD detached at <sha>". Commits made here are not on
any branch and can be lost on checkout.
- To keep work made while detached: `git switch -c <new-branch>` (or
  `git branch <name> <sha>` then switch).
- To discard and go back: `git switch -` or `git switch <branch>` (warns if
  there are unreferenced commits — capture the sha from reflog first if unsure).

### Committed to the wrong branch
- Move the last commit(s) to a new/other branch:
  ```bash
  git branch <correct-branch>      # mark current commit
  git reset --hard HEAD~1          # remove from wrong branch (CONFIRM: drops local changes)
  git switch <correct-branch>
  ```
- Safer if you have uncommitted changes mixed in: use `git reset --soft HEAD~1`
  to keep changes staged, then move them.

### Undo the last commit
- Keep the changes (most common, safe): `git reset --soft HEAD~1` (staged) or
  `git reset HEAD~1` (unstaged).
- Already pushed and shared: `git revert <sha>` (creates a new inverse commit —
  no history rewrite, safe for shared branches).
- Discard the commit and its changes entirely: `git reset --hard HEAD~1`
  (CONFIRM — destroys the work).

### Bad merge or rebase to undo
- Mid-conflict, want out: `git merge --abort` or `git rebase --abort`.
- Already completed but wrong: find the pre-operation state in the reflog and
  reset to it:
  ```bash
  git reflog                       # find entry like "HEAD@{3}: ... before rebase"
  git reset --hard HEAD@{N}        # CONFIRM: recovers prior state
  ```

### Lost commits after a hard reset / branch delete
- Recover via reflog:
  ```bash
  git reflog                       # locate the dangling sha
  git branch recovered <sha>       # or: git cherry-pick <sha>
  ```
- Also check `git fsck --lost-found` for truly dangling commits.

### Accidental `git reset --hard` (lost uncommitted changes)
- Committed work is recoverable via reflog (above). Uncommitted, unstaged
  changes that were never added are generally NOT recoverable — set expectations
  honestly. Staged-but-not-committed blobs may be found via
  `git fsck --lost-found` and inspected with `git show <blob>`.

### Dirty working tree blocking checkout/pull/rebase
- Temporarily shelve: `git stash push -m "wip"`; restore later with
  `git stash pop`.
- List/inspect existing stashes first: `git stash list` (don't clobber prior
  work).

### Push rejected (`! [rejected] ... fetch first` / non-fast-forward)
- Remote has commits you don't. Integrate first:
  ```bash
  git fetch origin
  git rebase origin/<branch>       # or: git merge origin/<branch>
  ```
  then push. Resolve any conflicts (see below).
- If history diverged because you rewrote local history intentionally and the
  branch is yours alone, a `git push --force-with-lease` may be appropriate —
  CONFIRM, and never on a shared branch.

### Merge conflicts
- `git status` lists conflicted files. Edit to resolve the `<<<<<<<`/`=======`/
  `>>>>>>>` markers, then `git add <file>` and continue:
  `git rebase --continue` / `git merge --continue` / `git commit`.
- Prefer resolving over discarding a side; only use `--ours`/`--theirs` when you
  understand which side you want.

### Wrong remote / can't push or pull
- Inspect and fix: `git remote -v`, then
  `git remote set-url origin <url>`.
- Set upstream for a new branch: `git push -u origin <branch>`.

### `.gitignore` not taking effect (already-tracked files)
- `.gitignore` only affects untracked files. Stop tracking but keep on disk:
  `git rm --cached <path>` then commit.

### Corrupt repo / index errors
- Stale lock: if a process crashed, an `index.lock` may remain. Verify no git
  process is running, then remove `.git/index.lock` (investigate before
  deleting — don't kill a legitimately running operation).
- Integrity check: `git fsck --full`.
- Rebuild a broken index: `rm .git/index && git reset` (re-reads from HEAD;
  CONFIRM — re-stage as needed afterward).

## Step 3 — Verify

Re-run `git status` and `git log --oneline -5` to confirm the repo is in the
intended state before declaring done.

## Quick reference

| Goal | Safe command | Notes |
|------|--------------|-------|
| Undo last commit, keep work | `git reset --soft HEAD~1` | local only |
| Undo a pushed commit | `git revert <sha>` | safe for shared branches |
| Recover lost commit | `git reflog` → `git branch <name> <sha>` | ~90-day window |
| Abort in-progress merge/rebase | `git merge/rebase --abort` | clean exit |
| Shelve dirty tree | `git stash push -m "..."` | `stash pop` to restore |
| Integrate before push | `git fetch` → `git rebase origin/<b>` | fixes rejection |
| Untrack ignored file | `git rm --cached <path>` | keeps file on disk |

## Commands that require explicit confirmation

`git reset --hard`, `git clean -f[d]`, `git push --force` (prefer
`--force-with-lease`), `git checkout -- <file>` / `git restore <file>`,
`git branch -D`, `git stash drop/clear`, `git rebase` and `git commit --amend`
on already-pushed commits, and deleting anything under `.git/`. State the
consequence and the alternative, then wait for approval.