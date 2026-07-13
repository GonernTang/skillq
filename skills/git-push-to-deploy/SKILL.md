---
name: git-push-to-deploy
description: Set up a multi-branch Git push-to-deploy system where each pushed branch is automatically extracted to its own deployment directory and served over HTTPS by Nginx.
---

# Git Push-to-Deploy with Multi-Branch Nginx Serving

Configure a bare Git repo served over SSH such that `git push <remote> <branch>` extracts each branch into a dedicated web root, then serve those roots via Nginx on HTTPS.

## Steps

### 1. Create a dedicated Git user
- Create a system user (e.g. `git`) with a home directory and a known password.
- Ensure the SSH daemon allows password auth for this user.

### 2. Enable password auth in sshd
- Edit the SSH server config (`/etc/ssh/sshd_config`):
  - `PasswordAuthentication yes`
  - Confirm `Port` matches the port you intend to expose.
- Restart `sshd`.

### 3. Initialize a bare repository
- Switch to the Git user and run `git init --bare <repo>.git` inside their home (e.g. `~/site.git`).
- Confirm push URLs work: `ssh://git@host:<port>/~/site.git`.

### 4. Create per-branch deployment directories
- For each branch you intend to serve (e.g. `main`, `dev`), create a target directory under the web root (e.g. `/var/www/main`, `/var/www/dev`).
- Own them with the web server user/group so Nginx can read them (e.g. `chown -R www-data:www-data /var/www`).

### 5. Install the post-receive hook
- In `<repo>.git/hooks/post-receive` (executable), read each updated ref and extract its tree into the matching deployment directory. Pattern:

```sh
#!/bin/sh
while read oldrev newrev refname; do
  branch=${refname#refs/heads/}
  case "$branch" in
    main) target=/var/www/main ;;
    dev)  target=/var/www/dev  ;;
    *)    continue ;;
  esac
  git archive --format=tar "$branch" | tar -x -C "$target"
done
```

- Make sure the Git user can write to the deployment directories (group write + setgid, or run as a user that owns them).

### 6. Generate a self-signed SSL certificate
- Use `openssl req -x509 -nodes -newkey rsa:2048 -keyout /etc/ssl/private/site.key -out /etc/ssl/certs/site.crt -days 365` (fill a common name or use `-subj`).

### 7. Write the Nginx config
- One server block per branch, sharing the same listen port (e.g. `8443 ssl`) but distinguished by `server_name` or path.
- Each block sets `root` to the branch's deploy directory and enables SSL with the cert/key from step 6.
- Example:

```nginx
server {
  listen 8443 ssl;
  server_name main.example.com;
  ssl_certificate     /etc/ssl/certs/site.crt;
  ssl_certificate_key /etc/ssl/private/site.key;
  root /var/www/main;
  index index.html;
}

server {
  listen 8443 ssl;
  server_name dev.example.com;
  ssl_certificate     /etc/ssl/certs/site.crt;
  ssl_certificate_key /etc/ssl/private/site.key;
  root /var/www/dev;
  index index.html;
}
```

### 8. Start / reload Nginx and verify
- `nginx -t` then start or reload.
- From a client, push to each branch and `curl https://host:8443/` (with `-k` if using a self-signed cert) to confirm each branch's tree is served.

## Common pitfalls
- Post-receive hook must be executable and run as a user that can write the deploy dirs.
- Nginx `root` must point at the directory containing the branch files, not at the bare repo.
- If using a non-standard HTTPS port, open it in the firewall.
- Self-signed certs require clients to use `-k` / trust the CA explicitly.
- Ensure SELinux/AppArmor policies allow Nginx to read the chosen web roots.