---
name: port-c-to-mips
description: Port a large C application to a custom bare-metal MIPS VM. Use when the target environment exposes only raw syscalls (no libc, no kernel) and you must cross-compile, build a minimal libc, write assembly startup, and produce a flat binary that runs on the VM. Covers toolchain setup, syscall mapping, linker script, header wrapping, fatal-error handling, and iterative symbol resolution.
---

# Porting a C Application to a Bare-Metal MIPS VM

When the target is a custom VM that exposes only raw syscalls (open/read/write/close/sbrk/exit, etc.) and no libc, follow this procedure.

## 1. Toolchain
- Install a MIPS cross-toolchain (e.g. `mipsel-linux-gnu-gcc`, `binutils-mipsel-linux-gnu`). Confirm endianness matches the VM.
- Verify with `mipsel-linux-gnu-gcc --version` and `mipsel-linux-gnu-readelf -h` on a hello-world.

## 2. Minimal libc
- Implement only the C functions the application actually uses (malloc, printf, fwrite, memcpy, strlen, memset, sin/cos/sqrt, etc.).
- Each function should be a thin wrapper around the VM's syscall interface. Examples:
  - `write` → syscall(fd, buf, len)
  - `sbrk`/`brk` → syscall to grow the heap
  - `exit` → syscall to terminate
- Keep the libc in its own directory so it can be linked as a single object/archive.

## 3. Assembly startup
- Write a `.S` file that:
  - Sets up the stack pointer (typically at the top of a known RAM region, e.g. `0x7fffe000`).
  - Clears `.bss` (zero-fill loop).
  - Calls `main`, then an `exit` syscall with main's return value.
- This replaces the host's `crt0`.

## 4. Linker script
- Place `.text`, `.rodata`, `.data`, `.bss` at the VM's load address (commonly `0x400000` for `.text`, with stack/heap at higher addresses).
- Define a `_stack_top` symbol consumed by the startup file.
- Make sure the script matches the VM's memory map exactly; wrong addresses are the #1 cause of silent crashes.

## 5. System headers
- Many standard headers (`signal.h`, `time.h`, `errno.h`, ...) reference kernel/libc internals the VM doesn't have.
- Either provide minimal compatible headers under a custom include path, or stub them out (empty `typedef`s, dummy macros).
- Compile application code with `-nostdinc -I<your-headers>`.

## 6. Link line
- Link with `-nostdlib -nostartfiles -static`.
- Explicitly provide: your startup `.o`, your libc objects, the application objects, and `-T<your-script.ld>`.
- Do NOT let the toolchain pull in its own `crt0` or `libc.so`.

## 7. Fatal-error calls
- The application likely has abort/exit-on-error paths (`I_Error`, `abort`, `assert`, `exit(-1)`).
- A bare-metal VM with no recovery will hard-halt on these. Decide per-call:
  - Replace with a non-fatal `fprintf(stderr, ...)` so the program can continue past the error.
  - Or replace with a clean VM-exit syscall so you can still observe the message.
- Search the codebase for `abort(`, `exit(`, `assert(`, and any domain-specific error helpers.

## 8. Iterative symbol resolution
- Build, parse unresolved symbols, implement them, repeat. Common cycles:
  - Missing `memcpy`/`memset` → trivial byte loops.
  - Missing `printf` → format-float is the hard part; consider writing only `%s %d %x %c %f` and stubbing the rest.
  - Missing math (`sin`, `cos`, `sqrt`) → small table-based or polynomial approximations are usually enough.
  - Missing `errno` → a single `int` global.

## 9. Verification
- Run the binary on the VM with a known input (a sample WAD for DOOM, a fixed seed for a game, etc.).
- Verify expected side-effects:
  - Stdout text matches expectations.
  - Output frame/files are produced and non-empty.
  - No unexpected VM exits before the program completes.
- Iterate on both missing symbols and runtime mismatches.

## Common pitfalls
- Wrong endianness in the toolchain vs the VM.
- Forgetting to clear `.bss` — gives non-zero globals.
- Heap collisions with `.bss`/stack — pick a heap base far from both.
- Float ABI mismatch (`-msoft-float` vs `-mhard-float`) — must match VM.
- Linking against host libc accidentally because `-nostdlib` was omitted on one translation unit.

## Deliverables checklist
- [ ] Cross-toolchain installed and verified.
- [ ] Startup assembly + linker script committed.
- [ ] Minimal libc covers every symbol the app references.
- [ ] Stubs/wrappers for headers under `-nostdinc`.
- [ ] Fatal-error paths converted to non-fatal or to VM-exit.
- [ ] Build produces a flat MIPS binary at the VM's load address.
- [ ] Smoke test on VM produces expected I/O.