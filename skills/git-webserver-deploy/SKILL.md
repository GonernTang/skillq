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

If the user’s query involves chess (e.g., detecting chess pieces from an image,
analyzing a chess position, finding the best move, or declaring checkmate), or
creating a polyglot Rust/C++ file using line splicing, or counting tokens in a
dataset, or **retrieving an MTEB leaderboard result**, do **not** apply the git
deployment procedure below.  The git deployment procedure does not handle chess,
polyglot, token counting, or MTEB tasks and will produce incorrect results.  For
MTEB queries, follow the **MTEB Leaderboard Retrieval** section; for chess,
polyglot, or token counting tasks, respond that you cannot assist using this
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
     is served. A 404 means the hook didn’t fire or the deploy dir is wrong.
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
   then sends the gradient of the same `recv_input` (after backprop) to the
   upstream rank. Rank 0 only receives.

3. **Model placement**: Place the embedding layer (`model.embed_tokens`) on
   **rank 0** only. Place the final norm and lm_head (`model.norm` and
   `model.lm_head`) on the **last rank** only. The transformer layers are
   partitioned equally (or as evenly as possible) among all ranks.

4. **Intermediate activation storage**: For each microbatch, store the
   received input tensor and the output of your assigned layers (or the
   output before the `send` call) so they are available during the backward
   phase.

5. **Separate forward and backward loops**: The forward phase loops over all
   microbatches sequentially, sending activations downstream. The backward
   phase loops over all microbatches again, recv’ing gradients and calling
   `.backward()` with the stored activations.

6. **World‑size=1 fallback**: When `world_size == 1`, run all layers on the
   single rank and perform a single forward+backward (no communication calls).

7. **Validation** (always verify after coding):
   - Check that the loss tensor on the last rank has `requires_grad=True`.
   - Confirm that all `dist.send` / `dist.recv` calls are guarded by
     `if rank != ...` conditions so that `world_size=1` makes no communication
     calls.
   – Verify that `recv_inputs` and `layer_outputs` lists have length equal
     to `num_microbatches`.
   - Ensure that after backward, gradients for the embedding parameters on
     rank 0 are non‑zero (unless the loss is zero).
   - Test with two ranks and three microbatches to catch shape mismatches.

8. **Common mistakes** (warn the user):
   - Forgetting to zero out gradients between microbatches—use
     `optimizer.zero_grad()` or manually `param.grad.zero_()` after each
     microbatch’s backward.
   - Mismatched tensor shapes between `send` and `recv`—ensure the dtype and
     device are consistent across ranks.
   - Running the backward loop before the forward loop has finished for all
     microbatches—AFAB requires *all* forward passes before *any* backward.
   - Not scaling loss—results in gradients that are `num_microbatches` too
     large, leading to training instability.

Include a cross‑check in the pipeline code to enforce these points, or at
least document them in the source comments.

## MTEB Leaderboard Retrieval

Use this section when the user asks for the best embedding model according to a
language-specific MTEB leaderboard (e.g., "best model for Scandinavian
languages in the MTEB leaderboard as of August 2025").

1. **Identify the exact benchmark name.** Language-specific MTEB benchmarks are
   named with the pattern `MTEB(<language group>, v<version>)`.  For example,
   `MTEB(Scandinavian, v1)`.  Use the exact name; do not guess.

2. **Query the backend API.** The official MTEB leaderboard backend is at
   `https://mteb-leaderboard-backend.hf.space/v1`.  Use the `/v1/benchmarks`
   endpoint to list available benchmarks, then the `/v1/benchmarks/<benchmark_name>/scores`
   endpoint to retrieve scores.

3. **Filter by release date.** When the user specifies "as of <date>", include
   models released **up to and including** that date (not strictly before).
   The API returns a `created` field for each model; use it for filtering.

4. **Rank by `Mean (Task)`.** The primary ranking metric for language-specific
   benchmarks is `Mean (Task)` (not `Mean (Dataset)`).  Sort results descending
   by this column.

5. **Cross-check model details.** For the top candidate(s) verify:
   - The model’s release date (included in the scores response) matches the
     date filter.
   - The model covers a sufficient number of tasks in the benchmark (low task
     coverage may indicate incomplete evaluation).

6. **Caution about language specialization.** The model at the top of the
   leaderboard by `Mean (Task)` may not be the best *for the target languages*.
   Many top models are large, English-centric, or general-purpose.  If the user
   explicitly wants a model optimized for the language group, consider
   additional filtering: check the model’s description, training data, or
   origin.  Mention this caveat in the final answer.

7. **Return the answer.** Write the chosen model’s full Hugging Face name
   (e.g., `Salesforce/SFR-Embedding-2_R`), its `Mean (Task)` score, and a
   brief justification covering the points above.  Write the result to the
   file path specified by the user (typically `/app/result.txt`).