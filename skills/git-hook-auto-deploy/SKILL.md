```
---
name: git-hook-auto-deploy
description: Configure Mailman3 with Postfix for mailing lists, including domain setup, transport maps, list creation, subscription policy, and verification.
---

# Mailman3 + Postfix Setup

**Scope:** This skill automates the configuration of Mailman3 with Postfix as the MTA. It covers setting the domain, enabling LMTP transport, creating a mailing list, opening subscription, and verifying delivery.

## Procedure

1. **Verify packages** – Ensure both `mailman3` and `postfix` are installed.

2. **Configure Mailman** – Edit `/etc/mailman3/mailman.cfg`:
   - In `[mailman]`, set `domain: <your-domain>` and optionally `site_owner: <admin-email>`.
   - Verify the `[mta]` section has `incoming: mailman.mta.postfix.LMTP`.

3. **Configure Postfix** – Edit `/etc/postfix/main.cf`:
   - Add the domain to `mydestination`.
   - Add `transport_maps = hash:/var/lib/mailman3/data/postfix_lmtp`.
   - Set `smtpd_reject_unlisted_recipient = no` (so Postfix accepts mail for list addresses, which are not local Unix users).

4. **Create a mailing list** – Run `mailman create <listname>` (e.g., `mailman create reading-group`).

5. **Set subscription policy** – Run `mailman conf -s <listname> subscription_policy open` to allow anyone to subscribe without approval.

6. **Generate transport map** – Run `mailman generate postfix map` to create the `postfix_lmtp` database file.

7. **Reload Postfix** – Run `postfix reload` to apply the new configuration.

8. **Verify** – Use `mailman members <listname>` to confirm the list exists, and test sending an email to `<listname>@<domain>` and subscribing via `<listname>-join@<domain>`.

## Task-Specific Package Handling

- When the task explicitly mentions a specific package (e.g., `mteb`) and provides its version, the agent must use that package's retrieval interface (e.g., the MTEB class, model loading functions) rather than generic alternatives like `sentence_transformers`. The package may preprocess inputs or load models with different defaults (e.g., normalization, query instruction prefixes) that affect cosine similarity scores.
- Always inspect the package's API first and adapt the retrieval pipeline accordingly. Prefer the task-specified package over generic alternatives.

## Verification

- Send an email to the list address and check that the message is delivered to all subscribed members.
- Send a subscription request (e.g., to `<listname>-join@<domain>`) and follow the confirmation flow to ensure automated subscription works.
- Use `mailman members <listname>` to confirm the new member appears.

## Common Pitfalls

- **Missing `transport_maps` entry** – If `transport_maps` is not set or the map file is missing, Postfix will reject or defer mail to list addresses. Regenerate the map and reload Postfix.
- **Forgotten `postfix reload`** – Configuration changes are not applied until Postfix is reloaded.
- **`smtpd_reject_unlisted_recipient` not set to `no`** – Postfix will reject mail to list addresses because they are not local Unix accounts.
- **Incorrect path to `postfix_lmtp`** – The hash map is located at `/var/lib/mailman3/data/postfix_lmtp`. Verify the path matches the one used in `transport_maps`.
- **Firewall or SELinux** – Ensure the LMTP port (127.0.0.1:8024) is accessible and that SELinux policies allow Postfix to connect to it (if applicable).
```