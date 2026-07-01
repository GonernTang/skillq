---
name: git-push-deploy
description: Set up a git server that automatically deploys pushed branches to a web server via a post-receive hook. Use when you need a lightweight, self-hosted git-to-web deployment pipeline without third-party CI.
---

# Git Push-to-Deploy

Wire a bare git repository to a static web server so every push publishes the branch's tree to a served directory.

## Prerequisites

Verify (install if missing):

- `git` — version control and hooks engine.
- A static-file HTTP server runtime (e.g., `python3` for `http.server`, or `nginx`, `caddy`, `busybox httpd`).

Pick two directory paths before starting:

- **REPO_DIR** — where the bare repository lives (e.g., `/srv/git/<project>.git`).
- **WEB_ROOT** — the directory the web server serves from (e.g., `/var/www/<project>`).

## Step 1 — Create the bare repository

```
git init --bare "$REPO_DIR"
```

A bare repo has no working tree; the hook will fill `WEB_ROOT` on each push.

## Step 2 — Ensure the web root exists and is writable

```
mkdir -p "$WEB_ROOT"
```

The hook user (the one that receives pushes) must be able to write here. If `WEB_ROOT` is owned by another user, chown/chmod accordingly, or run the receiver under that user (SSH user matches the web-server user).

## Step 3 — Write the post-receive hook

Create `$REPO_DIR/hooks/post-receive`:

```
#!/bin/sh
# Deploy every pushed branch to WEB_ROOT.
while read oldrev newrev refname; do
    branch=$(echo "$refname" | sed 's|^refs/heads/||')
    # Only act on branch pushes; ignore tags and delete-only pushes.
    if [ -z "$newrev" ] || echo "$newrev" | grep -q '^0\{40\}$'; then
        continue
    fi
    GIT_WORK_TREE="$WEB_ROOT" git checkout -f "$branch" -- .
done
```

Key behaviors of this hook:

- Iterates over each ref pushed (one per branch in a multi-branch push).
- Switches `GIT_WORK_TREE` so `git checkout -f` writes directly into the web root.
- Drops tag updates and branch deletes (no work to publish).

Adapt the script if you need: per-branch subdirectories, build steps, cache busting, or notifications. Keep it executable.

## Step 4 — Make the hook executable

```
chmod +x "$REPO_DIR/hooks/post-receive"
```

Git will not run a hook that lacks the executable bit — verify with `ls -l`.

## Step 5 — Start the web server

Pick a port (e.g., 8080) and serve `WEB_ROOT`:

```
# python3 example
cd "$WEB_ROOT" && python3 -m http.server 8080 --bind 0.0.0.0
```

For a persistent setup, run under a process manager (`systemd`, `supervisord`, `nohup`+`tmux`) so the server survives shell exits.

## Step 6 — End-to-end verification

1. Clone the bare repo as a remote: `git clone "$REPO_DIR" /tmp/check`.
2. Add an `index.html` (or any marker file), commit, `git push origin main`.
3. Curl the server: `curl -s http://localhost:<port>/ | head`. The pushed file must appear.
4. Confirm exit code from the push was 0 and the hook produced no errors on stderr.

## Troubleshooting checklist

- **Push succeeds but files don't appear** — hook not executable (`chmod +x`) or hook path misnamed (must be `post-receive`, not `post-receive.sample`).
- **Permission denied writing to WEB_ROOT** — push user cannot write; align UIDs or add the push user to the web-root group.
- **Web server returns 404** — wrong `--directory` / `root`; point the server at `WEB_ROOT`, not the parent.
- **Old content from previous branches lingers** — expand the hook to `git clean -fdx "$WEB_ROOT"` before checkout, or maintain per-branch subdirs.
- **Pushes from non-fast-forward are rejected** — expected for shared bare repos; clients must `git pull --rebase` first.

## Variations

- **SSH access**: expose `REPO_DIR` via the user's `~/.ssh/authorized_keys`-style git-shell, or set `ReceivePack` if using a custom transport.
- **HTTPS server**: replace the `python3 -m http.server` line with your preferred server's static-site config.
- **Build step**: prepend a build command (e.g., `npm run build`) inside the hook's while-loop before the checkout, output to a subdirectory of `WEB_ROOT`.