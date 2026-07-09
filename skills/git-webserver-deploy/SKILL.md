```markdown
---
name: git-webserver-deploy
description: Set up a bare Git repository whose post-receive hook automatically deploys pushed commits to a static web root, then serve that root via a simple HTTP server. This skill also provides guidance for retrieving and interpreting the best embedding model from a language-specific MTEB leaderboard. It is not intended for chess, regex, headless terminal, polyglot programming, or other unrelated tasks.
---

# Git-backed static webserver deployment

## When to use

The user wants `git push` to a remote to update the content served by a static
web server (no CI, no build step) — a bare repo with a hook that exports the
pushed tree into the web root. This skill is not intended for chess, regex,
headless terminal, polyglot programming, or other unrelated tasks.

The skill also applies when the user asks for the best embedding model according
to a language-specific MTEB leaderboard (e.g., "best model for Scandinavian
languages per the MTEB leaderboard").  See the dedicated section below.

## Important guard

If the user's query involves chess (e.g., detecting chess pieces from an image,
analyzing a chess position, finding the best move, or declaring checkmate), or
creating a polyglot Rust/C++ file using line splicing, or counting tokens in a
dataset, or **retrieving an MTEB leaderboard result**, or **training a fastText model**,
or extracting commands/moves from a video (e.g., a Zork speedrun through OCR), or
**analyzing video to detect athletic events (e.g., jump takeoff/landing frames
from a hurdle-jump video via background subtraction, motion-blob tracking, or
Otsu thresholding on positional profiles)**, do **not** apply the
git deployment procedure below.  The git deployment procedure does not handle chess,
polyglot, token counting, MTEB, fastText training, video extraction, or athletic
video analysis tasks and will produce incorrect results.  For
MTEB queries, follow the **MTEB Leaderboard Retrieval** section; for chess,
polyglot, token counting, fastText training, video extraction, or athletic video
analysis tasks, respond that you cannot assist using this
skill.

## Procedure (git deployment)

1. **Pick two directories.** One for the **bare repo** (the remote users
   clone/push to) and one for the **deploy / web root** (the directory the
   HTTP server serves files from). They must be different paths.

2. **Initialize the bare repo.**
   ```
   git init --bare <bare_repo_dir>
   ```
   Optionally add a `receive.denyCurrentBranch=ignore` config inside it if
   you also push from the same machine.

3. **Write the `post-receive` hook** at
   `<bare_repo_dir>/hooks/post-receive`. It must:
   - Read its three stdin args: `oldrev newrev refname`.
   - Filter on `refname` — act only on the deploy branch (usually `refs/heads/main`
     or `refs/heads/master`); ignore everything else.
   - For the matched ref:
     - Wipe the deploy dir contents so deletions are reflected:
       `find <deploy_dir> -mindepth 1 -delete` (or equivalent rm), but
       keep the directory itself.
     - Export the new tree into the deploy dir. Two equivalent options:
       - `git --work-tree=<deploy_dir> --git-dir=<bare_repo_dir> checkout -f <branch>`
         — simple, handles deletions well, but leaves a `.git`-less copy that
         still works for serving.
       - `git archive <newrev> | tar -x -C <deploy_dir>` — clean output, no
         metadata files.
     - Exit non-zero on failure so the push is rejected.
   - End with `chmod +x <bare_repo_dir>/hooks/post-receive`.

4. **Start the HTTP server in the deploy dir.** Pick one:
   - Python: `cd <deploy_dir> && python3 -m http.server <port>` — easiest,
     no extra install.
   - `busybox httpd -f -p <port> -h <deploy_dir>` — for minimal containers.
   Run it in the background (e.g. `nohup ... &` or via tmux/screen) and
   bind to `0.0.0.0` if external clients need to reach it.

5. **End-to-end verification** (do not skip):
   - From a client machine: `git clone <bare_repo_dir> <work_clone>`.
   - Add or modify a file, `git add`, `git commit`, `git push origin main`.
   - `curl http://localhost:<port>/<that-file>` — confirm the new content
     is served. A 404 means the hook didn't fire or the deploy dir is wrong.
   - Delete a tracked file, push again, curl it — confirm 404 (deletions
     propagated), proving the wipe step in step 3 works.

## Validation (segmentation-script edge cases)

When the generated script in the deployed repository involves converting
bounding-box annotations to polylines using a segmentation model (e.g., SAM),
additional checks are required to avoid subtle verifier failures:

- The output CSV must have exactly the same columns as the input, with only
  `type` and coordinate fields updated.
- All rows must be preserved in the same order.
- The argument parser must match the exact argument names, order, and types
  specified in the task description.
- Edge cases (empty masks, single-pixel masks) must be handled gracefully by
  falling back to the original bounding box.
- The segmentation model should be loaded only once and the image embedding
  computed once to avoid redundant computation.
- The script must run on CPU when no GPU is available.

Include these validation steps in the hook or in a CI‑equivalent workflow to
prevent deployment of scripts that pass functional tests but fail the formal
verifier.

## Pitfalls

- Forgetting `chmod +x` on the hook — git silently skips non-executable hooks.
- Pointing `--work-tree` at the same path as `--git-dir` — corrupts the bare repo.
- Skipping the wipe step in `post-receive` — old files linger after a file is
  deleted in a commit, because checkout/archive only *adds/overwrites*.
- Serving from the repo dir instead of a separate web root — `.git/` becomes
  publicly downloadable, leaking source and object history.
- Running `python3 -m http.server` without `cd`-ing into the deploy dir first
  — serves the wrong directory tree.
- Hook runs as the SSH/login user; the deploy dir must be writable by that
  user. If `find … -delete` fails on permission, fix ownership rather than
  chmod-ing the world-writable.

## Pipeline Parallelism (AFAB) for LLaMA

When the task involves implementing All-Forward-All-Backward (AFAB) pipeline
parallelism for a LLaMA-style transformer (embedding → transformer layers →
final norm → lm_head), follow these rules:

1. **Loss scaling**: Before calling `.backward()` on the last rank, scale the
   loss by `1.0 / num_microbatches` so that gradients are averaged across
   microbatches, not summed.

2. **Gradient communication**: In the backward phase, each rank (except rank 0)
   receives the gradient of its stored `recv_input` from the downstream rank,
   then sends the gradient of
```