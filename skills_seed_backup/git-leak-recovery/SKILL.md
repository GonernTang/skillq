---
name: git-leak-recovery
description: Recover a secret that was committed and then removed by history rewriting (e.g. force-push, reset, rebase), then permanently purge the dangling commit so the secret cannot be reconstructed. Use when a sensitive value was briefly present in a commit but is no longer reachable from any branch — but the user still needs the value before it is destroyed. Triggers on phrases like "recover secret from git", "find dangling commit", "rewritten history recovery", "purge leaked secret from git".
---

# Git Leak Recovery

Recover a leaked secret from an unreachable commit, then purge the commit so the secret cannot be recovered by anyone else.

## When to use

A sensitive value (API key, token, password, private key) was accidentally committed, then removed via `git reset`, `git rebase`, `git commit --amend`, or force-push. The commit is no longer reachable from any branch but still lives in the object database until garbage-collected. You need the value **and** you need it gone.

## Procedure

### 1. Locate the dangling commit

The removed commit is unreachable but still referenced by the reflog until it expires.

```
git reflog --all
git fsck --lost-found   # look for "dangling commit" lines
git fsck --no-reflogs --unreachable --dangling
```

Note the full commit hash of the dangling commit (or its tree/blob if the secret was added without a commit).

### 2. Extract the secret

```
git show <commit-hash>            # full diff + message
git show <commit-hash>:<path>     # a single file from the commit
```

If the secret lived in a single file and the commit is gone but the blob survives:

```
git fsck --dangling              # may list dangling blobs
git cat-file -p <blob-hash>
```

Capture the secret to the user's required output destination (stdout, a file, a secret manager). **Do not print it to logs** unless the user explicitly asks.

### 3. Purge the dangling commit and its objects

Removing it from branches is not enough — the reflog and loose objects still hold it. Do all three:

```
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

`--aggressive` deep-packs and is not always needed; use it when the repo is large and you want to be certain no loose copies remain. For small repos, plain `git gc --prune=now` is sufficient.

If the repo has been pushed or cloned anywhere, treat those copies as compromised — the purge only affects the local repo.

### 4. Verify the purge

```
git fsck --lost-found            # should report no dangling commits/blobs
git show <commit-hash>           # should fail with "unknown revision"
git rev-list --objects --all | grep <commit-hash>   # should be empty
```

For paranoia on packed repos, also check the packfiles:

```
git verify-pack -v .git/objects/pack/*.idx | grep <commit-hash>
```

If any verification still finds the hash, repeat step 3 or try `git repack -ad`.

### 5. Advise the user

After recovery, treat the secret as compromised regardless of how complete the purge looks: rotate it, revoke it, audit its use. Git history rewriting on a shared repo never erases what was already fetched, cloned, or scraped.

## Gotchas

- **`git filter-repo` / `git filter-branch`** rewrite reachable history but do **not** delete dangling reflog entries or unreachable objects by themselves — always run `reflog expire` + `gc --prune=now` afterward.
- **BFG Repo-Cleaner** rewrites reachable history and prunes backups in `.git`, but does not clear the local reflog — same caveat.
- **Forks, clones, CI caches, GitHub forks, archive mirrors** all retain the original commit. No local purge can reach them.
- A blob can outlive its commit. If you find the secret in a dangling blob, target that blob for the purge check, not just the commit hash.
- `git push --force` does **not** remove anything from other clones; it only moves the remote's branch pointer.