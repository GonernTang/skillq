---
name: qemu-legacy-boot
description: Guard-rail for booting legacy OS images (Windows 3.1x, DOS, etc.) under QEMU. Prevents silent boot failures by enforcing version/image compatibility and end-to-end verification of the boot → display → input pipeline before claiming success.
---

## Why this skill exists

When QEMU launches a legacy OS image, the QEMU process can exit cleanly, the VNC port can be open, and `query-status` can return `running` — yet the guest never actually reaches a usable desktop. Likewise, sending keystrokes via QMP can succeed at the protocol level while producing zero observable effect. Assuming any one of those signals equals "it works" causes silent failures in legacy OS automation.

## Diagnostic checklist (run BEFORE claiming the VM is ready)

Before driving any user-space interaction, confirm each of the following. If any item fails, fix it and re-check before proceeding.

1. **Version ↔ machine-type compatibility.** Identify the QEMU version (`qemu-system-i386 --version` or equivalent) and pick a `-machine` type whose release date predates the image. Newer QEMU drops support for older machine types and CPUs; legacy images often need an explicit fallback such as `pc-i440fx-5.2` (or older) and a matching CPU model. Do not rely on defaults.
2. **Guest actually reached a desktop.** After launch, do not trust `query-status` alone. Wait until the VNC framebuffer changes (poll a region; if it stays static for >30s with no progress, treat as boot failure) or until `query-status` returns `running` AND a screendump shows a recognizable shell/desktop.
3. **VNC is genuinely serving pixels.** Connect with a real VNC client (or `vncsnapshot`/`ssvncviewer -grab`) and verify the framebuffer updates in response to guest activity. An open port does not mean the display backend is rendering.
4. **Programmatic input produces a visible effect.** When validating a QMP/`send-key` path, send a key that should produce an unambiguous on-screen change (e.g., NumLock toggle indicator, a menu-open accelerator, `Alt+F` to open the File menu). Then take a screendump and confirm the indicator moved. Silent "command accepted" responses are not evidence of success.

## Stop signal

**Stop and reset when any of the following holds:**
- `query-status` is `running` but the screendump is identical to the post-BIOS black screen for more than 30 seconds.
- VNC connections succeed but no framebuffer updates appear regardless of guest activity.
- Three consecutive `send-key` calls produce no observable change in the framebuffer.

**Reset action:** stop the QEMU process, re-verify the machine-type and CPU flags against the image's era, relaunch with explicit `-machine`, `-cpu`, and a conservative `-vga` (e.g., `std` for DOS/Win3.x), and re-run the checklist from item 2.

## Anti-patterns to avoid

- Treating "process started" or "port listening" as "VM ready."
- Sending keys without verifying the guest has focus and the display is rendering.
- Using the default `-machine` type for images older than the installed QEMU.
- Validating input by reading QMP return values instead of inspecting the framebuffer.