---
name: nginx-site-config
description: Configure an Nginx web server with a custom site — custom log formats, rate limiting zones, server block on a non-default port, custom error pages, and basic document root setup. Use when provisioning a new Nginx vhost that needs structured request logging and request-rate protection.
---

# Configure a custom Nginx site with logging and rate limiting

## When to use

Use this skill when you need to stand up an Nginx site from scratch that requires:
- A custom access-log format (beyond the default `combined`).
- Request rate limiting by client IP.
- Listening on a non-default port (e.g. 8080).
- A custom error page (e.g. 404).
- Isolated config files (so it can be enabled/disabled without touching other sites).

## Procedure

1. **Install Nginx if missing.**
   - Debian/Ubuntu: `sudo apt-get install nginx`.
   - Confirm the binary: `nginx -v`.

2. **Add a custom log format and rate-limit zone in the `http {}` block.**
   Edit the main config (typically `/etc/nginx/nginx.conf`). Inside `http {}`, add:
   ```nginx
   log_format <format_name> '"$time_local" "$request_method" "$status" "$http_user_agent"';
   limit_req_zone $binary_remote_addr zone=<zone_name>:10m rate=<N>r/s;
   ```
   - `<format_name>`: short identifier used by `access_log` (e.g. `benchmark`).
   - `<zone_name>`: identifier used by `limit_req` (e.g. `mylimit`).
   - `<N>r/s`: requests-per-second threshold per IP (e.g. `10r/s`).
   - The zone must live in `http {}` — server blocks cannot define it.

3. **Create a dedicated server-block file** under the conf include directory (e.g. `/etc/nginx/conf.d/<site>.conf`). Inside:
   - `listen <port>;` (e.g. `8080`).
   - `server_name _;` (catch-all) or a real hostname.
   - `root <docroot>;` (e.g. `/var/www/html`).
   - `access_log <path> <format_name>;`
   - `error_log <path>;`
   - `limit_req zone=<zone_name> burst=<B> nodelay;` inside `location /`.
     - `burst=<B>` allows short spikes above the rate before returning 503.
   - `error_page 404 /404.html;` and a matching `location = /404.html { internal; }` if the page lives under the docroot.

4. **Prepare the document root.**
   - Create the directory: `sudo mkdir -p <docroot>`.
   - Add `index.html` and the custom error page (e.g. `404.html`).
   - Ensure Nginx can read them: ownership `www-data:www-data` (Debian) or `nginx:nginx` (RHEL), mode `644`.

5. **Disable the default site** to avoid port/listen conflicts on 80:
   - Debian/Ubuntu: `sudo rm /etc/nginx/sites-enabled/default`.

6. **Test and reload.**
   - Validate syntax: `sudo nginx -t`.
   - Apply: `sudo systemctl reload nginx` (preferred) or `sudo nginx -s reload`.
   - Verify with `curl -i http://localhost:<port>/` and inspect the access log.

## Common pitfalls

- Forgetting to put `limit_req_zone` in `http {}` — directive is not valid inside `server` or `location`.
- Leaving the default site enabled while also listening on 80 in the new block — Nginx picks the first matching `listen 80 default_server;` and may bind-fail.
- Custom error page returning 404 because `error_page` points to a path outside the docroot or without `internal`.
- Reloading before `nginx -t` passes — a syntax error in the new block will silently stop the reload and leave the old config running.
- `burst` set without `nodelay` causes requests to queue, producing latency spikes instead of immediate 503s — pick the behavior you actually want.

## Verification checklist

- `nginx -t` reports `syntax is ok` and `test is successful`.
- `curl -i http://localhost:<port>/` returns `200` and the response body matches `index.html`.
- `curl -i http://localhost:<port>/missing` returns the custom 404 page body.
- `<access_log>` shows entries in the custom format (check that fields are quoted as configured).
- A burst of >`N` requests/sec from one IP returns `503` once `burst` is exceeded.