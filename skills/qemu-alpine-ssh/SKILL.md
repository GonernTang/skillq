---
name: qemu-alpine-ssh
description: Boot Alpine Linux ISO in QEMU with port-forwarded SSH (host:2222 → guest:22). Use when asked to stand up an Alpine VM reachable over SSH, run commands inside Alpine via SSH, or verify a QEMU-launched Alpine image is remotely accessible. Covers serial-console boot, in-guest setup-alpine automation, root password set, sshd enable, and end-to-end SSH connectivity check from host.
---

# QEMU Alpine boot + SSH setup

When a task needs an Alpine Linux VM reachable over SSH from the host, do not just inspect the ISO — actually launch QEMU, drive the in-guest setup, and verify SSH.

## Diagnostic checklist (run BEFORE committing to a launch approach)

1. **Confirm tooling.** Run `qemu-system-x86_64 -version` and `expect -v`. If either is missing, install (apt/apk) before continuing.
2. **Confirm assets.** The Alpine ISO must exist locally and be readable; extract or locate the `vmlinuz-*` and `initramfs-*` (or use `-cdrom` with `-boot d` and let the ISO kernel boot itself).
3. **Confirm port 2222 is free** on the host (`ss -ltn | grep 2222` or `lsof -i :2222`). If occupied, pick another free host port and use it consistently in the `hostfwd` rule.
4. **Confirm SSH client is installed** on the host (`ssh -V`). You will need it for the final verification.

If any check fails, fix it before launching QEMU — a half-launched VM with missing tooling wastes more time than a clean retry.

## Procedure

1. **Launch QEMU with the Alpine ISO, serial console, and port forwarding.** Always include a serial console so headless automation is possible, and forward host:2222 → guest:22:
   ```
   qemu-system-x86_64 \
     -m 512 -nographic \
     -cdrom /path/to/alpine.iso \
     -boot d \
     -netdev user,id=net0,hostfwd=tcp::2222-:22 \
     -device virtio-net,netdev=net0 \
     -serial mon:stdio
   ```
   On Apple Silicon / arm hosts use `qemu-system-aarch64` with a matching aarch64 Alpine ISO and `-M virt -cpu cortex-a57`.

2. **Drive the in-guest setup via `expect` (or a serial-console script).** Alpine's default root login has **no password**; the serial console is your keyboard. A minimal expect flow:
   - Wait for the `login:` prompt, send `root`.
   - Run `setup-alpine` (answer keyboard/layout/US, hostname, DHCP `eth0`, DNS, no proxy, `chrony` for NTP).
   - Set a known root password: `passwd root` → use a fixed value (e.g. `password123`) so the agent can SSH back in non-interactively.
   - Enable SSH: `rc-update add sshd default` then `rc-service sshd start`. Confirm with `rc-service sshd status` and `netstat -lnt | grep :22`.
   - Type `poweroff` to shut down cleanly when done, or leave running for the SSH check.

3. **Verify SSH connectivity from the host.** From the host shell:
   ```
   ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
       -p 2222 root@127.0.0.1 'uname -a; cat /etc/alpine-release'
   ```
   A successful login + command output proves the full chain works. Do NOT skip this step — "sshd was started inside the guest" is not the same as "host can reach it on the forwarded port".

4. **Record the working incantation.** Save the exact `qemu-system-*` command and the expect script to disk so they can be replayed without re-derivation.

## Pitfalls to avoid

- **Exploring the ISO instead of booting it.** `isoinfo`, `mount -o loop`, `unsquashfs` — these are reconnaissance, not progress. Boot the ISO.
- **Using `-display none` without `-serial mon:stdio`.** The guest will boot and you will see nothing; you cannot drive setup-alpine.
- **Forwarding host:2222 → guest:2222 instead of → guest:22.** sshd listens on 22 inside Alpine; the hostfwd target must be `22`.
- **Setting an unknown root password.** If you script `passwd root` with a random value you cannot reproduce, the SSH verification step fails. Use a fixed known value.
- **Forgetting `rc-update add sshd default`.** `rc-service sshd start` starts it now, but it won't survive a reboot. Add the default runlevel entry.
- **Verifying with `ssh localhost` instead of `ssh -p 2222 127.0.0.1`.** The port-forward is what you are testing.

## Stop signal

If you have written **2 different QEMU launch commands** and both fail to produce a working SSH login from the host on port 2222, **stop varying QEMU flags**. Instead:
1. Run `ss -ltn` inside the guest (via serial console) and confirm sshd is bound to `:22`.
2. From the host, run `nc -vz 127.0.0.1 2222` — if this fails, the port-forward itself is wrong (check `hostfwd=tcp::2222-:22` syntax and that no prior QEMU holds the port).
3. If both look correct but SSH still fails, kill all QEMU processes (`pkill -9 qemu-system-*`), free the port, and relaunch with the canonical command above. Do not iterate flag combinations past attempt 2.