---
name: git-leak-recovery
description: Recover a secret accidentally committed to a git repo and then purged via history rewrite, then verify the purge is complete.
---

# Recovering a Leaked Secret After History Rewrite

When a secret is accidentally committed and then "removed" via `git reset` /
`git commit --amend` / rebase, it usually still lives in reflog and dangling
objects. This procedure salvages the secret from those dangling objects and
then guarantees the purge holds.

## 1. Locate the dangling commit

```bash
git reflog --all | head -50        # find the commit that introduced the secret
git fsck --lost-found              # list dangling blobs / commits / trees
```

Pick the SHA of the commit that originally contained the secret.

## 2. Extract the secret before pruning

```bash
git show <commit-sha>                       # inspect files in that commit
git show <commit-sha>:<path/to/secret>      # print only the secret file
```

Save the recovered content to a **safe location outside the repo** (e.g.
`~/.local/recovered/<repo>-<date>/`). Never write it back into the working
tree.

## 3. Force every reachable ref to forget the dangling objects

```bash
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

`--expire=now` rewrites reflog entries so the original SHAs are no longer
reachable; `--prune=now` plus `--aggressive` deletes the now-unreferenced
objects. Run them in this order — `gc` alone does not prune reflog-protected
objects.

## 4. Verify the purge

Run **all** of these — any single check can miss something:

```bash
# (a) The original commit is gone
git cat-file -p <commit-sha>          # expect: Not a valid object

# (b) Sweep every reachable object for the secret pattern
git rev-list --all --objects | \
  xargs -I{} sh -c 'git cat-file -p {} 2>/dev/null' | \
  grep -F '<secret-pattern>'           # expect: no output

# (c) No dangling objects survive
git fsck --lost-found                 # expect: clean output

# (d) Unchanged files (README, configs) still match their original content
git diff HEAD~1 -- README             # or compare against a known-good copy
```

If step 4(b) still hits, the secret is reachable from a ref you didn't expire
(branch, tag, stash, remote ref, worktree). Track it down with
`git log --all --oneline -- <path>` and repeat step 3.

## 5. Rotate the secret

Purging git history does **not** invalidate a secret that was already pushed,
cloned, scraped, or cached. After recovery + purge, rotate the credential
out-of-band.

## Pitfalls

- `git gc` without `--prune=now` keeps recently-deleted objects for ~2 weeks
  (the default `gc.pruneExpire`).
- `git reflog expire --expire=now --all` only affects local reflog; force-
  pushed branches on remotes still hold the old objects until they're
  rewritten and re-gc'd on the remote.
- `--aggressive` is slow on large repos; on huge repos you can drop it after
  the first run — the secret blob will already be pruned.
- Packs (`*.pack` / `objects/pack/`) must be re-checked; a `git repack -ad`
  after gc eliminates any pack that still referenced the blob.