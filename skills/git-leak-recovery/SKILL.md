---
name: git-leak-recovery
description: Recover a secret (or other content) that was committed to a git repository and then removed by history rewriting (reset, rebase, force-push), and fully sanitize the repository of all traces. Use when a task asks to extract a value from removed/hidden git history and then ensure no copies remain in refs, reflog, or unreachable objects.
---

# Recover a secret from rewritten git history and sanitize the repo

## Procedure

1. **Locate the removed commit**
   - Inspect all reflogs to find commits that were orphaned by a reset/rebase/force-push:
     `git reflog --all`
   - For branches/tags that were force-overwritten, also check `git fsck --unreachable --no-reflogs --lost-found` to find dangling commits.

2. **Extract the secret content**
   - Show the full content of the candidate commit(s): `git show <commit-hash>`
   - Diff the candidate against its parent to isolate the added lines if the secret is small: `git diff <parent>^..<commit>`
   - Write the recovered value to the required output location.

3. **Sanitize the repository**
   - Expire every reflog entry immediately so they are no longer reachable:
     `git reflog expire --expire=now --all`
   - Repack and prune all unreachable objects, including packed ones:
     `git gc --prune=now --aggressive`
   - If a filter-branch or replace-object was ever used, drop it: `git replace -d --batch` (after listing with `git replace -l`).

4. **Verify no traces remain**
   - Reflog is empty: `git reflog --all` should output nothing.
   - No dangling/unreachable objects: `git fsck --unreachable --no-reflogs` should report no commits/blobs/trees.
   - No content match anywhere in the working tree or any reachable ref: `git grep -I -i <secret-pattern> $(git rev-list --all)` (or `git rev-list --all | xargs git grep -I <pattern>`).
   - Working tree and existing branch history are untouched — the sanitization must not alter HEAD, branches, tags, or tracked files; only remove unreachable objects.

5. **Report**
   - State the recovered value and its destination file.
   - State the verification commands and their (empty) outputs as evidence of cleanup.
   - Confirm that HEAD/branch history is unchanged (`git status` clean, `git log` unchanged).

## Key principles

- **Recover first, then sanitize.** Reading the value and removing the traces are separate steps; do not run `gc --prune=now` before extracting, or the object may be deleted.
- **Reflog + gc together.** Either alone leaves traces — reflog keeps unreachable commits alive for the expire window; `gc` alone cannot prune objects still referenced by reflog.
- **Preserve reachable history.** Never run `git filter-branch`, `git filter-repo`, or destructive rebases on existing branches. Only operate on unreachable state.
- **Verify with `grep`, not just `fsck`.** `fsck` confirms no dangling objects, but a partial clone, worktree, or stash can still hold the content; `git grep` over all reachable revisions is the definitive check.