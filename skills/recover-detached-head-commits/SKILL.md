---
name: recover-detached-head-commits
description: Recover commits lost after checking out a branch while in detached HEAD, then restore them onto the current branch via cherry-pick. Use when working in a repo and discovering that earlier changes sit on an orphaned commit that is no longer reachable from the current branch.
---

# Recover Commits from a Detached HEAD

A detached HEAD lets you move around freely, but any commits you make on it become orphaned the moment you check out another branch — git keeps them in the reflog, but they vanish from the branch graph and look "lost" to ordinary log/history commands. This procedure brings them back onto the branch you are now on.

## When to use

Use this when:
- You made commits in a detached HEAD and checked out (or were moved to) a branch, and those commits no longer appear in `git log`.
- A teammate, script, or tool moved HEAD off a commit you had been building on, and you want those changes back on the active branch.
- You want a safe recovery workflow that preserves the original commit (so retry is possible if anything goes wrong).

Do NOT use this when:
- The lost work is in the working tree only and was never committed — use `git stash` or simply re-stage the files.
- The branch was force-pushed or rewritten and the commits are truly pruned from reflog (e.g. after `git gc --prune=now`); recovery is then unlikely.

## Procedure

1. **Survey what is reachable.**
   Run `git reflog` to see recent HEAD movements. Look for a line where HEAD was detached at a commit hash you care about — note that hash.
   If the change happened in this session, the orphaned commit is usually the most recent reflog entry ending at the commit you now want back.

2. **Confirm the orphaned commit is the right one.**
   Show its contents against the branch tip to verify it really contains the changes you want to recover:
   ```bash
   git diff <branch-or-commit-before-change>..<orphaned-commit-hash>
   ```
   Sanity-check the diff matches what you intended (not a stale or unrelated commit).

3. **Apply the commit onto the current branch.**
   With the target branch already checked out, cherry-pick the orphaned commit:
   ```bash
   git cherry-pick <orphaned-commit-hash>
   ```
   This produces a new commit on the branch with the same changes. The original orphaned commit is left untouched in reflog, so you can retry with a different strategy if cherry-pick fails.

4. **Resolve conflicts if they appear.**
   Cherry-pick may stop with conflicts when the branch has diverged from the detached state. Resolve each conflicted file manually (edit the conflict markers, choosing the incoming/their side when it represents the intended change), then:
   ```bash
   git add <file>
   git cherry-pick --continue
   ```
   To abandon instead: `git cherry-pick --abort` — the branch is untouched and the orphaned commit is still in reflog.

5. **Verify the result.**
   Confirm the new commit landed where you expected:
   ```bash
   git log --oneline -n 5
   git log -p -n 1           # diff of the latest commit, to double-check it is your change
   ```

6. **(Optional) Clean up.**
   Once satisfied, no further action is required — the reflog entries age out naturally after ~90 days. If you want to keep them longer (e.g. for repeated restores across sessions), leave reflog pruning at its default.

## Tips and pitfalls

- Cherry-pick replays a single commit. If the orphaned state is a multi-commit sequence, prefer `git rebase --onto <new-base> <old-base>` or cherry-pick each commit in order — but only after step 2 confirms the whole set is what you want.
- After a successful cherry-pick, the original detached commits still appear in reflog; that is expected and harmless.
- If the working tree now differs from the recovered commit (e.g. partial files were already on the branch), expect conflicts and resolve in favor of the changes you actually want on the branch.
- Resist `git reset --hard` until you have verified the recovered commit — resetting can destroy the very state you just restored.