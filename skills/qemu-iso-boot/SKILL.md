---
name: qemu-iso-boot
description: Boot a QEMU VM from an ISO image with the serial console exposed over telnet, including parameter selection, backgrounding, and readiness-check logic for headless/cloud agents.
---

# Boot a QEMU VM from an ISO over telnet serial console

Use this procedure when an agent or test harness must launch a bootable
ISO (Linux distro, installer, live image, custom image) inside QEMU
without a graphical display, and interact with the guest's serial
console over a TCP/telnet port.

## When to use

- Headless or non-graphical environment where a VGA/display window is unavailable.
- The caller needs scripted, programmatic interaction with the guest (login, command execution, log scraping).
- The ISO is bootable and provides a serial console (most Linux installer/live ISOs do).

## Prerequisites

1. Verify the emulator is installed and on `$PATH`:
   ```sh
   command -v qemu-system-x86_64 || command -v qemu-system-x86_64.exe
   ```
   Install it via the platform package manager if missing.
2. Pick an architecture that matches the ISO (commonly `qemu-system-x86_64`
   for x86 ISOs, `qemu-system-aarch64` for ARM). Mismatches fail to boot.
3. Pick a **free localhost TCP port** for the serial channel (e.g., 4444
   or any unused port > 1024). Verify it is free before launching.
4. Optionally inspect the ISO to confirm it is bootable and what boot
   loader / kernel it ships:
   ```sh
   isoinfo -R -f -i /path/to/image.iso | head
   # Look for /boot, /isolinux, /EFI, vmlinuz, etc.
   ```

## Launch command

Run QEMU in the background, redirecting the guest's first serial port
to a telnet socket and disabling the graphical display:

```sh
ISO=/path/to/image.iso
PORT=4444            # pick an unused port
MEM=512              # MiB; raise for installer/live images (>=1024)
ARCH=qemu-system-x86_64

$ARCH \
  -cdrom "$ISO" \
  -serial "telnet:127.0.0.1:${PORT},server,nowait" \
  -nographic \
  -m "$MEM" \
  -no-reboot \
  > /tmp/qemu.log 2>&1 &

echo $! > /tmp/qemu.pid
```

Key flag notes:

- `-nographic` disables the VGA window; required for headless operation.
- `-serial telnet:...,server,nowait` makes QEMU listen on the port and
  accept a telnet connection without blocking the emulator; without
  `nowait` QEMU blocks on first connect.
- `server` makes QEMU act as the telnet listener (vs. dialing out).
- `-no-reboot` prevents auto-reboot loops when the guest halts.
- Capture the PID and stdout/stderr to files so the process can be
  killed and logs inspected later.

## Readiness check

The guest takes seconds-to-minutes to boot. Block the calling agent
until the serial port is actually open and the guest has produced
console output:

```sh
# Wait for the telnet port to accept connections.
while ! timeout 1 bash -c "echo > /dev/tcp/127.0.0.1/${PORT}" 2>/dev/null; do
  sleep 1
done
```

Then verify the guest is responsive by connecting, waiting for a
prompt, and sending a no-op command:

```sh
# Open the telnet session with a tool like busybox/nc/telnet, read bytes
# until a prompt pattern (e.g., "login:", "#", "$") is seen, then exit
# non-destructively. Keep this verification short — the main workflow
# will reconnect as needed.
```

If the port opens but no console output ever appears, the guest likely
isn't routing console output to serial — re-check the ISO (some
distros require `console=ttyS0` on the kernel command line) or the
emulator's `-serial` configuration.

## Interaction model

Subsequent steps should open a new telnet connection per session
(lazy-disconnect semantics), send commands, and read replies. Keep
the VM running between steps unless explicitly tearing it down.

## Teardown

When finished, stop the VM cleanly:

```sh
kill "$(cat /tmp/qemu.pid)" 2>/dev/null && rm -f /tmp/qemu.pid
# Add a SIGKILL fallback if the guest is unresponsive:
kill -9 "$(cat /tmp/qemu.pid)" 2>/dev/null
```

## Troubleshooting checklist

- **Port already in use** → pick another port or kill the prior listener.
- **Connection refused** → emulator likely failed to start; check
  `/tmp/qemu.log` for KVM/missing-firmware errors.
- **Connection accepted but no output** → guest is not configured for
  serial console; check the ISO or boot with `console=ttyS0`.
- **Very slow readiness on macOS/ARM** → consider `qemu-system-aarch64`
  with a matching ISO, and bump `-m` higher (slow emulation).
- **Permission denied on the port** → choose a port > 1024 or run as
  a user with binding rights.