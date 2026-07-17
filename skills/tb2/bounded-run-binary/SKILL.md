---
name: bounded-run-binary
description: Guard-rail for cross-compiling interactive/long-running programs (games, VMs, servers, simulators) to unfamiliar environments. Ensures the binary terminates cleanly within a verifier-imposed budget, that syscalls/stdlib are functional in the target, and that any artifact it emits is structurally valid before submission.
---

When you build an interactive or long-running program for a sandboxed or custom
runtime (custom ISA, JavaScript-based VM, cross-compile target, embedded
firmware, CI verifier, etc.), the binary **must terminate on its own** with a
defined exit code. The most common silent failure is a main loop that runs
forever, causing the verifier to kill the process by timeout — which counts as
a failure even if the program was otherwise correct.

This skill is the pre-submission guard-rail for that class of bug.

---

## Diagnostic checklist

Run these checks **before** declaring the port done. Each one is a concrete
yes/no test, not a vibe check.

1. **Bounded main loop.** Locate the main event/render/simulation loop. Confirm
   there is a frame counter (or wall-clock timer) that calls `exit(0)` after N
   iterations, where N is small enough to finish well under the verifier's
   time budget. If the loop has no termination condition, the port is not
   shippable.
2. **Stdlib syscalls actually work.** In the target environment, exercise every
   syscall the program relies on (typically `write`, `open`/`close`, `read`,
   `brk`/`mmap`, `exit`). A common failure mode: the program runs under a
   custom libc that returns success without doing anything, so `write` "works"
   but emits nothing, or `open` silently fails and the artifact never lands.
   Verify by running the binary end-to-end and inspecting its side effects
   (stdout, output file, exit code).
3. **Emitted artifacts are structurally valid.** If the program produces a file
   (image, frame, dump, log), validate the header end-to-end on the target:
   magic bytes, declared dimensions vs. actual byte length, expected pixel
   block layout, version fields. A "we wrote some bytes" check is not enough —
   parse the artifact the same way a downstream consumer would.
4. **Expected initialization output is present.** Capture stdout at the target
   and confirm the program's first-run messages (banner, version, "starting…",
   "frame 0/n", etc.) appear in order. Missing or reordered output usually
   points to a stdout buffering or syscall-ordering bug, not a logic bug.

## Stop signal

- **Stop and refactor the loop** the moment you realize the main loop is
  unbounded in a non-interactive verifier context. Do not "test and see."
  Threshold rule: if `N frames` or `T seconds` is not written down *before*
  the first run, treat the build as unsafe and do not submit. Reset action:
  add an explicit `if (frame >= N) exit(0);` (or equivalent) at the top of the
  loop, default `N` to a conservative small value (e.g. 30 frames or ~2 s of
  wall time), and re-run the diagnostic checklist above.

- **Stop and fix the syscall layer** if any output (stdout or file) is empty
  or shorter than expected when the program clearly tried to produce it. Do
  not patch around it by adding retries; reset to the syscall stub and verify
  each call returns the documented error/success code on a smoke test before
  re-running the full program.