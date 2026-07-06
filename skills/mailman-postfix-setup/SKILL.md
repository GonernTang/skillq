---
name: mailman-postfix-setup
description: Configure a Mailman3 mailing list server with Postfix on a single host. Covers domain/site_owner setup in mailman.cfg, Postfix transport-map wiring so list addresses route to the mailman transport, list creation, open subscription policy, and service restart + smoke test.
---

# Mailman3 + Postfix setup

Use this when Mailman3 and Postfix are both already installed and you need
to wire them together so a mailing list on a chosen domain accepts mail
and lets users self-subscribe/unsubscribe.

## Inputs to confirm first

- **List domain** (e.g. `lists.example.org`) — must resolve in DNS and be
  served by this Postfix instance (`mydestination` or `virtual_mailbox_domains`).
- **Site owner email** — receives errors and admin notifications.
- **Public URL host** — where the web UI is served (optional but usually set).

## Procedure

1. **Configure Mailman core settings** in `/etc/mailman3/mailman.cfg`:
   - Set `domain:` to the list domain (e.g. `domain: lists.example.org`).
   - Set `site_owner:` to the admin email.
   - Set `url_host:` if the public hostname differs from `domain`.

2. **Wire Postfix to deliver list mail to Mailman** via a transport map:
   - In `/etc/postfix/main.cf` add (or extend) `transport_maps`:
     `transport_maps = hash:/etc/postfix/transport`.
   - Create `/etc/postfix/transport` with one line per list domain:
     `<list-domain>  mailman:`.
   - Compile the map: `postmap /etc/postfix/transport`.

3. **Create the list**:
   ```
   mailman create <listname>@<list-domain>
   ```

4. **Open the subscription policy** so users are auto-confirmed after
   replying to the confirmation mail:
   ```
   mailman config -s <listname> subscription_policy open
   ```

5. **Restart both services** so config and transport changes take effect:
   ```
   systemctl restart postfix mailman3
   ```

6. **Smoke test** the round trip:
   - Send mail to `<listname>-join@<list-domain>` from an external mailbox.
   - Reply to the confirmation Mailman sends; verify the address appears
     in the subscriber list (`mailman members <listname>`).
   - Send mail to `<listname>-leave@<list-domain>` and verify removal.
   - Post a message to `<listname>@<list-domain>` and confirm all
     subscribers receive it.

## Pitfalls

- Forgetting `postmap` after editing `/etc/postfix/transport` — Postfix
  will silently keep using the old map.
- `domain` in `mailman.cfg` and the RHS of the transport map line must
  match exactly (no trailing dot, no `www.` prefix).
- Restarting only one of the two services leaves stale config in the
  other; always restart both.
- `subscription_policy` defaults to *confirm* (admin must approve);
  `open` is what makes `-join` self-service.