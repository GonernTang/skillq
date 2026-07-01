---
name: alpine-qemu-ssh
description: Boot an Alpine Linux ISO in QEMU with user-mode networking and a host port-forward, then install and configure openssh-server so the VM is reachable from the host over SSH. Use when the task is "boot Alpine in QEMU and expose SSH" or any variant (live ISO, fresh VM, headless access). Covers the exact QEMU flags, in-VM package install, sshd_config edits, root password, and service start.
---

# Boot Alpine in QEMU and Enable SSH

## 1. Launch QEMU with port forwarding

Start the VM with user-mode networking and forward a host TCP port to the VM's SSH port (22):

```sh
qemu-system-x86_64 \
  -cdrom <alpine.iso> \
  -m 512 \
  -netdev user,id=net0,hostfwd=tcp::<HOST_PORT>-:22 \
  -device e1000,netdev=net0 \
  -nographic
```

Notes:
- Increase `-m` (e.g. 512–1024) if `apk add` or the SSH daemon fails to start.
- `<HOST_PORT>` is what the host connects to (commonly 2222); the guest always sees port 22.
- `-nographic` is optional — drop it if you want the GUI.

## 2. Log in inside the VM

The Alpine live ISO logs in as `root` with no password. Run everything below as root (or prefix with `sudo`).

## 3. Install and configure the SSH server

```sh
apk add openssh-server
```

Edit `/etc/ssh/sshd_config` and ensure these directives are set (uncomment or add):

```
PermitRootLogin yes
PasswordAuthentication yes
```

Set a known root password (the live image has none):

```sh
echo 'root:<your-password>' | chpasswd
```

Generate host keys if they are missing (first boot on a live ISO often has none):

```sh
ssh-keygen -A
```

## 4. Start the SSH service and persist it across reboots

```sh
service sshd start       # or: /etc/init.d/sshd start
rc-update add sshd default
```

## 5. Connect from the host

```sh
ssh -p <HOST_PORT> root@localhost
```

If the connection is refused, wait a few seconds (sshd takes a moment to bind) and retry. Confirm port forwarding is live with `ss -ltn` inside the VM (look for `:22`) and `nc -zv localhost <HOST_PORT>` on the host.

## Common failure modes

- **"Connection refused" on host** — sshd not running, or `hostfwd` port wrong. Re-check with `service sshd status` inside the VM.
- **`apk add` fails / OOM** — bump `-m`; 256 MB is often too tight for openssh-server's dependencies.
- **Permission denied after connecting** — root password not set, or `PermitRootLogin no` left in sshd_config.
- **Keys missing on first start** — `ssh-keygen -A` before `service sshd start`.