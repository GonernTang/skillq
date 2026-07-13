---
name: vm-boot-verification
description: Avoid declaring a VM installation/boot successful based on infrastructure signals alone (listening ports, QMP socket responsive, process running). Verify the guest OS is actually booted and interactive by polling framebuffer/VNC for real screen content with a timeout.
---

# VM Boot Verification Guard-Rail

When a task involves launching a QEMU (or similar) VM and installing or booting a guest OS, the failure mode is **declaring success on infra liveness** rather than on **actual guest readiness**. The VM can be running, QMP can answer, VNC can listen — and the guest can still be stuck at BIOS, a bootloader prompt, a kernel panic, or mid-install. Do not ship this as "done" until the guest itself is provably up.

## Diagnostic checklist (run BEFORE declaring boot success)

Run each in order. Any failure blocks declaring success.

1. **Process + monitor check** — QEMU process exists and the QMP socket (or monitor) accepts commands. This is *necessary* but not *sufficient*. Record it, then keep going.
2. **Display liveness check** — VNC/RFB port is open. Same caveat: a listening port does not mean a rendered frame exists.
3. **Framebuffer content check** — capture the framebuffer (via VNC screenshot, QEMU screendump, or screen comparison) and confirm it contains actual rendered content: non-blank pixels, a recognizable desktop/wallpaper color, or a known shell/UI signature. A black/blank/uniform screen that does not change across captures is a stall, not a boot.
4. **Interactive-state check** — query QMP `query-status` for `running`, or observe a window title / shell prompt via guest agents or screen OCR. The guest must be past bootloader and into a usable state.

## Stop signal

- **Threshold**: poll with a bounded loop of **60–120 seconds** (longer for legacy OS installs like Windows 3.11, DOS, etc.). If the framebuffer does not transition from blank/bootloader to recognizable interactive content within that window, **stop and report failure** — do not retry blindly, do not mark complete.
- **Reset action on stop**: capture and save the last framebuffer + QEMU log lines for diagnostics, then either re-launch with corrected boot args (e.g. `-boot order=`, disk image path) or surface the failure to the caller. Never infer success from a green process tree.

## Anti-patterns to refuse

- "QMP responded to `query-status` → booted." ❌ QMP answers even during BIOS/bootloader.
- "VNC port 5900 is open → booted." ❌ The server can listen before any frame is drawn.
- "No errors in the QEMU stderr → booted." ❌ A guest hung at a prompt emits no errors.
- "It's been 30 seconds, looks fine." ❌ No timeout-with-evidence = guessing.

## What success looks like

A framebuffer capture that shows a recognizable, non-blank, *changing* guest UI (desktop, installer dialog, shell prompt) **plus** a confirmed interactive state (QMP `running`, or a screen feature that requires user-mode execution). Both signals together.