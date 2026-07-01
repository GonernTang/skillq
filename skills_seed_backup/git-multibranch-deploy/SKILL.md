---
name: git-multibranch-deploy
description: Deploy multiple Git branches to separate HTTPS endpoints via a bare repo, post-receive hook, and Nginx. Use when the task is to expose different branches of one Git repository at distinct HTTPS URLs (e.g. /main and /dev served from separate web roots), typically on a single Linux host with Nginx.
---

# Deploy Multiple Git Branches as Separate HTTPS Endpoints

## When to use

The user wants one Git repository whose different branches are served at distinct HTTPS URLs from a single host. Common shape: push to branch `main` → serves at `https://host/main/`; push to branch `dev` → serves at `https://host/dev/`. Each branch maps to its own web-root directory.

## Procedure

### 1. Provision a Git user and bare repo

Create a dedicated Unix user (e.g. `git`), enable SSH password auth in `/etc/ssh/sshd_config` (`PasswordAuthentication yes`) if pushers will use password auth, then restart sshd. Initialise a bare repo at the user's home:

```
sudo -u git git init --bare /home/git/<repo>.git
```

### 2. Map each branch to a web root via post-receive

Create `/home/git/<repo>.git/hooks/post-receive` (executable) that checks out each tracked branch into its own work tree. Example mapping:

```
#!/bin/sh
git --work-tree=/var/www/main checkout -f main
git --work-tree=/var/www/dev  checkout -f dev
```

`checkout -f` overwrites the working tree so stale files from a previous branch don't linger. Create the target directories and chown them to the git user (or grant write access) so the hook can update them.

### 3. Generate a self-signed SSL certificate

```
openssl req -x509 -nodes -days 365 \
  -newkey rsa:2048 \
  -keyout /etc/ssl/private/selfsigned.key \
  -out /etc/ssl/certs/selfsigned.crt \
  -subj "/CN=localhost"
```

### 4. Configure Nginx for HTTPS

Place a server block listening on the HTTPS port. Point the document root (or use `location` aliases) at the per-branch web roots created in step 2. Set `ssl_certificate` and `ssl_certificate_key` to the files from step 3. Typical shape:

```
server {
    listen 443 ssl;
    server_name _;
    ssl_certificate     /etc/ssl/certs/selfsigned.crt;
    ssl_certificate_key /etc/ssl/private/selfsigned.key;

    location /main/ { alias /var/www/main/; }
    location /dev/  { alias /var/www/dev/;  }
}
```

Reload: `sudo nginx -t && sudo systemctl reload nginx`.

### 5. Verify

Clone locally, push the relevant branches, then `curl -k https://<host>/main/` and `curl -k https://<host>/dev/` to confirm each endpoint returns the expected branch contents. The `-k` flag accepts the self-signed cert.

## Reusable template: post-receive hook

```sh
#!/bin/sh
# Add one line per (branch, web-root) pair.
git --work-tree=/var/www/<branch-a-dir> checkout -f <branch-a>
git --work-tree=/var/www/<branch-b-dir> checkout -f <branch-b>
```

## Pitfalls

- Work-tree dirs must be writable by the user running the hook (usually the git user). A failed checkout here silently breaks deploys.
- `alias` (not `root`) inside `location` is needed when the URL prefix doesn't equal the directory name verbatim.
- Reload Nginx after every cert or config change; `nginx -t` first to catch syntax errors.
- For multi-branch support, every branch you want exposed must have a corresponding line in the hook AND a `location` in Nginx — keep the two lists in sync.
- Self-signed certs require `curl -k` (or browser trust import); don't enable this in production without a real CA-signed cert.