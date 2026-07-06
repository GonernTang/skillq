---
name: git-webserver-deploy
description: Set up a bare Git repository whose post-receive hook automatically deploys pushed commits to a static web root, then serve that root via a simple HTTP server. Use when the user asks to configure a git-based web deployment, a git auto-deploy hook, or a push-to-serve static site pipeline.
---

# Git-backed static webserver deployment

## When to use

The user wants `git push` to a remote to update the content served by a static
web server (no CI, no build step) — a bare repo with a hook that exports the
pushed tree into the web root.

## Procedure

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