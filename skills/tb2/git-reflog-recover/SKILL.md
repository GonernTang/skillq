---
name: git-reflog-recover
description: Use when a user reports lost git changes after a checkout, reset, or branch switch. Drive the recovery end-to-end via git reflog, verify the lost commit, and EXECUTE the merge back to the target branch — do not stop at proposing commands.
---

# Recover lost git work via reflog

When a user says their work disappeared after a checkout, reset, or branch
switch, the commits usually still exist in the reflog. The trap is to stop
after describing the recovery commands and ask the user to run them — by
then you've already lost the thread. Drive the recovery to completion
yourself and verify before reporting back.

## Diagnostic checklist

Before touching the working tree, run these four checks. If any fail,
state what you found and ask before mutating.

1. **Reflog has a candidate commit.** Run `git reflog` and confirm a
   `commit:` entry exists after the user's last `checkout:` / `reset:`
   line. If the reflog is empty or pruned, stop and tell the user the
   commits are unrecoverable.
2. **Candidate hash verified.** Run `git log <hash> -1 --stat` and
   `git diff <target-branch>..<hash>` (or between the two hashes) to
   confirm the lost commit actually contains the user's reported
   changes. Show the diff summary before merging.
3. **Target branch identified.** Confirm which branch the user wants
   the work on (usually the branch they accidentally left). Check it
   out and run `git status` — refuse if the working tree is dirty.
4. **Merge plan chosen.** Pick the safer of the two paths:
   - Cherry-pick: `git cherry-pick <hash>` — single commit, minimal
     surface for conflicts.
   - Recovery branch: `git checkout -b recovery-<hash> <hash>` then
     `git merge --no-ff recovery-<hash>` into the target, then delete
     the recovery branch.
   Prefer cherry-pick when the lost work is a single commit; use the
   branch path when the user lost multiple commits or a tip.

## Stop signal

**Threshold:** the task is not done until (a) the merge has been
executed — not just described — and (b) `git status` is clean on the
target branch and `git diff <target-branch>^..<target-branch>` (or
equivalent) shows the recovered changes are present.

**Reset action:** if the cherry-pick or merge halts with conflicts, do
NOT abort and ask. Run `git status` to see the conflict scope, attempt
a resolution only when the conflict is mechanical (e.g. same-line
edit), and otherwise `git cherry-pick --abort` (or `git merge --abort`)
and report back with the conflict hunks so the user can resolve
manually. Never leave the repo in a half-merged state.

After a successful merge, run `git log --oneline -5` on the target
branch and report the new HEAD so the user can see the recovery landed.