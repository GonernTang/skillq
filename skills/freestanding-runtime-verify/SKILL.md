---
name: freestanding-runtime-verify
description: Avoid silent failure when porting a program (game, app) to a freestanding cross-compile target (custom ISA emulator, bare-metal MIPS, etc.). Forces end-to-end runtime verification: BSS zeroing, hostcall plumbing, multiple-frame output, and emulator-driven smoke checks before declaring success.
---

When cross-compiling a non-trivial program onto a freestanding / custom-emulator target, the build can link cleanly yet never execute the user's loop. The most common silent failures are: BSS is uninitialised, hostcalls are unimplemented, the binary jumps to `main` and falls off the end, or the verifier expects multiple output artefacts (frames, ticks) — not just one. Use this skill as a pre-flight guard before declaring the port "done".

## Diagnostic checklist (run BEFORE claiming the port works)

1. **BSS init check.** Confirm the toolchain / target does NOT zero BSS on your behalf. If it doesn't, your `crt0` must explicitly clear `_bss_start .. _bss_end` before any global constructor or `main` runs. A single missing `.bss` zero pass turns every global into garbage.
2. **Hostcall / syscall check.** Enumerate every host call the program emits (I/O, time, exit, file ops, alloc if no host heap). For each, prove the stub is wired into the emulator's trap/hostcall table and reachable from the compiled binary (e.g. `objdump -d` shows a real `syscall`/`ecall` to that vector, not an undefined reference).
3. **Output-progress check.** Identify what the verifier looks at: frame files, console lines, exit code, log markers. Produce **at least two** iterations of that output during the smoke test. One frame is indistinguishable from "ran the prologue and died".
4. **Crash-on-entry check.** Run the emulator under a short timeout. If it returns before the expected number of ticks/frames, or the binary traps on the first hostcall, treat that as a hard failure regardless of a clean `ld` exit.

## Stop signal

If any of the following holds, **STOP and reset** — do not patch around it:

- The binary links without warnings but the emulator exits in <1s of simulated time, or produces 0–1 output artefacts.
- `objdump` shows unresolved `R_MIPS_*` relocations, missing `__start`/`_start`, or a `.bss` section that the entry path never touches.
- More than two hostcalls the program needs are still stubs returning `-1`/abort.

Reset means: re-audit the four checklist items in order, then rebuild from `crt0` up. Do not iterate on a single subsystem in isolation while the rest may be broken.

## Worked success criteria

The port is accepted only when, in one emulator invocation:

- At least N (≥2, task-dependent) artefacts of the chosen kind appear on disk **or** the console contains ≥2 expected init/progress markers.
- The binary runs continuously past the first hostcall until a normal exit or the timeout — never traps, never jumps to address zero.
- `readelf -s` shows the entry point is `_start` (or equivalent), not `main`.

## Anti-patterns to refuse

- "It compiles, ship it." Compilation is necessary, not sufficient.
- Trusting toolchain defaults for `freestanding` targets. Most don't zero BSS; many don't pull in a real `crt0`.
- Declaring victory after one frame / one log line. Verifiers check for sustained, observable execution.