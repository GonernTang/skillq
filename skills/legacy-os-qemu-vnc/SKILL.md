---
name: legacy-os-qemu-vnc
description: Launch a legacy OS (Windows 3.11/9x, DOS, etc.) VM in QEMU with VNC display, snapshot mode, programmatic keyboard support, and nginx reverse-proxy for web-based access. Use when the task is to install or run a legacy OS in QEMU and expose it over the web via VNC.
---

# Legacy OS in QEMU + VNC + nginx web proxy

## Why this skill exists
Agents attempting to spin up a legacy OS VM (e.g. Windows 3.11) for web access routinely miss one or more of the four moving parts: the QEMU binary + flags, the VNC display, the programmatic input device, and the nginx stream proxy. Missing any one means the VM does not appear at the web URL. Treat the four parts as a single integrated procedure — do not improvise.

## Procedure

### 1. Pre-flight (host prerequisites)
- Confirm the disk image exists and is a valid raw/qcow2 file (file `<image>` or `qemu-img info <image>`).
- Confirm `qemu-system-i386` (or `qemu-system-x86_64` for 64-bit legacy) is installed.
- Confirm `nginx` is installed and `nginx -t` parses its config.
- Confirm port 5901 (or chosen display) and 80 are free (`ss -lntp`).

### 2. Launch QEMU
Use the exact flag set below — these four flags together are what most agents get wrong:

```
qemu-system-i386 \
  -hda <image>.img \
  -snapshot \                              # keep disk immutable
  -m 64 \                                  # legacy OSes need small RAM
  -vnc :1 \                                # VNC on port 5901
  -k en-us \                               # keyboard layout
  -usb -device usb-kbd                     # programmatic keyboard input
  -daemonize                               # or append `&`
```

Notes:
- `-snapshot` is critical when you do not want writes to persist across restarts.
- `-usb -device usb-kbd` (or `-device piix3-usb-uhci -device usb-kbd`) is required for scripted keyboard injection via QEMU monitor / VNC.
- Use `:1` for display 1 (port 5901), `:0` for port 5900, etc.
- If the host CPU lacks certain features, add `-cpu pentium` or `-cpu 486` for very old OSes.

### 3. Expose VNC over the web with nginx stream proxy
A VNC client cannot be served by `http{}` — you need a **TCP stream proxy**:

```nginx
stream {
    server {
        listen 80;
        proxy_pass 127.0.0.1:5901;
        proxy_timeout 1h;
        proxy_buffer_size 16k;
    }
}
```

Place this in `/etc/nginx/nginx.conf` (or include it). Validate with `nginx -t`, then `systemctl reload nginx` (or `nginx -s reload`).

If you want a real browser-based VNC viewer instead of a raw TCP proxy, deploy **noVNC** as a WebSocket-to-VNC bridge and serve it as a normal `http{}` block — but that requires a second component (`websockify`).

### 4. Verify end-to-end
- `ss -lntp | grep -E '5901|:80 '` — both ports must be listening.
- Connect with `vncviewer localhost:5901` from the same host first.
- Then test from outside: `nc -vz <host> 80` and a VNC client against port 80 through nginx.
- If the VM is non-interactive on first boot (BIOS, setup screens), use QEMU monitor (`-monitor stdio` or telnet to `localhost:4444`) to send key events: `sendkey ret`, `sendkey tab`.

## Diagnostic checklist — run BEFORE the main approach
1. Does `qemu-system-i386 -version` succeed? If not, install it (`apt install qemu-system-x86`) before touching nginx.
2. Is the disk image non-empty and not corrupt? `qemu-img info <image>` must report a sane virtual size.
3. Can a local `vncviewer` reach `localhost:5901` *before* you add nginx in the middle? If not, fix QEMU first — the proxy cannot rescue a broken VM.
4. Does `nginx -t` pass with your stream block? If it fails, fix the config; do not proceed to reload.

## Stop signal
If you have rewritten the QEMU command line **2 times** and the VM still does not respond on port 5901 (no VNC handshake, no monitor prompt), stop adding flags. Switch architecture:
- Try `qemu-system-x86_64 -cpu pentium` instead of `qemu-system-i386` if i386 is missing.
- Drop `-usb -device usb-kbd` and use `-nographic` + a serial console if VNC display is the problem.
- As a last resort, run the VM with `-display none -daemonize` and rely solely on QEMU monitor on a telnet socket — abandon the web-proxy path and document it as a known limitation.

Do not iterate on the same nginx config more than 3 times. If the stream block still fails `nginx -t`, the config syntax (not the topology) is wrong — re-read the nginx stream docs and start the block from scratch.

## Common pitfalls
- **Missing `-snapshot`** → the image gets mutated on first boot and subsequent boots differ.
- **Wrong port** → `:1` means 5901, not 5900. Confirm with `ss -lntp`.
- **Forgetting to daemonize/background** → the shell session blocks and the VM exits when the session ends.
- **http{} instead of stream{}** → nginx will return 502/504 because VNC is TCP, not HTTP.
- **Using `-k en-us` without `-usb -device usb-kbd`** → keys arrive as wrong scancodes for programmatic input.