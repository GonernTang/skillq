---
name: freestanding-c-port
description: Port a C program to a freestanding target (custom VM, embedded, bare-metal) by writing a minimal libc wrapper, replacing unsupported features (FPU, glibc-only calls), and linking with -nostdlib -ffreestanding.
---

# Porting C Programs to a Freestanding Target

Use this when compiling a C codebase for a target that lacks a standard C library (custom VM, emulator, embedded firmware, bare-metal). The goal is to produce a working binary without dragging in glibc/newlib.

## 1. Investigate the Target Environment

Before writing code, identify what the target actually provides:
- **Syscall interface**: Read the VM/firmware source or syscall table. Note syscall numbers, register conventions, return semantics.
- **Architecture & ABI**: Word size, endianness, calling convention, stack layout, whether an FPU exists.
- **Available memory regions**: Where `.text`, `.data`, `.bss`, and heap can live. Look for a linker script or memory map.
- **Entry point**: How does execution begin? Does the target expect `_start`, a specific symbol, or a jump from firmware?

Document each finding — they drive every later decision.

## 2. Audit the Source for Host Dependencies

Sweep the codebase for symbols/headers that imply a hosted environment:
- `<stdio.h>`, `<stdlib.h>`, `<string.h>` functions (printf, malloc, memcpy, …)
- `<ctype.h>` (isalpha, isdigit, …)
- `<errno.h>`, locale, setjmp/longjmp
- Any reference to `FILE *`, `stdin`/`stdout`/`stderr`
- Floating-point literals (`1.5f`, `3.14`) if the target lacks an FPU

List every missing symbol so you know what to provide.

## 3. Write a Minimal libc

Create a small library (often a single `libc.c` plus headers) that implements only what the program calls. Typical contents:

- **Syscall wrappers** (e.g. `sys_write(fd, buf, len)`, `sys_exit(code)`, `sys_open`, `sys_read`, `sys_brk`) — thin inline-asm or function wrappers around the target's syscall convention.
- **Memory**: a bump-allocator `malloc`/`free` (often `free` is a no-op), `memcpy`, `memset`, `memmove`, `memcmp`.
- **Strings**: `strlen`, `strcmp`, `strncmp`, `strcpy`, `strncpy`, `strchr`, `strstr`.
- **Formatted output**: a minimal `printf`/`sprintf`/`snprintf` supporting `%d %u %x %s %c %p %%` and width/padding. Integer-only if no FPU — convert `%f` manually or drop it.
- **64-bit helpers**: `udivmoddi4`, `umoddi3`, `__divdi3` etc. (GCC/libgcc-style soft-intrinsics) if the architecture is 32-bit but the code uses 64-bit arithmetic. Linking with `-mno-relax-pic` and supplying these avoids linker errors.
- **ctype stubs**: `isalpha`/`isdigit` returning booleans — don't include glibc tables.
- **No-op stubs**: `abort`, `atexit`, `__assert_fail` (print message + exit), `errno` (a single global int).

Keep it small and self-contained — avoid pulling in additional source files.

## 4. Patch Source for Target Limitations

Edit the program source (or `#define` shims) to remove unsupported features:
- **No FPU**: replace `double`/`float` arithmetic with integer/fixed-point. Rewrite any trig or math functions that assume floats.
- **No hosted libc**: replace `printf` calls you can't easily satisfy with simpler ones, or extend your minimal printf until it covers them.
- **No filesystem**: replace `fopen`/`fread` with direct syscall wrappers.

Prefer small, local edits over rewriting large sections. Iterate — fix one compile error at a time.

## 5. Cross-Compile

Invoke the cross-toolchain with these flags (adjust the prefix to match your toolchain, e.g. `mipsel-linux-gnu-` or `riscv64-unknown-elf-`):

```
<CC> -c -ffreestanding -nostdlib -fno-builtin -fno-pic \
    -O2 -Wall -Wextra -I<your-include-dir> <src.c> -o <src.o>
```

Then link, providing your custom libc and any startup code:

```
<LD> -nostdlib -T <linker-script-if-needed> \
    <objs> <libc.o> <crt0.o> -o <binary>
```

Common linker pitfalls: missing `_start`, missing soft-float helpers, missing alignment of sections, missing stack pointer setup. Supply a crt0 if the target doesn't.

## 6. Iterate on Errors

Expect a long compile-fix loop. Typical sequence:
1. First pass: hundreds of "undefined reference" → fill in libc symbols.
2. Second pass: soft-float / 64-bit intrinsic errors → add GCC helpers.
3. Third pass: `__assert_fail`, `__errno_location` → stub them.
4. Fourth pass: redefinition conflicts (e.g. your `printf` vs a header declaration) → guard headers with `#define` macros or rename.

Each cycle should shrink the error list. Don't try to satisfy every warning in one shot.

## 7. Run and Verify

Execute the binary on the target (or VM) and check observable output:
- Exit code and stdout/stderr match expectations.
- Files or side effects appear (e.g. written frames, log lines).
- For graphics/audio: capture output and inspect — don't trust "no crash" alone.

If output is wrong but the binary runs, suspect floating-point loss, integer overflow, or syscall arg ordering — not the cross-compilation itself.

## Checklist Before Declaring Done

- [ ] All undefined symbols resolved (linker clean)
- [ ] No FPU instructions in the binary (verify with `objdump` if unsure)
- [ ] Entry point reachable from the target's reset/load vector
- [ ] At least one positive end-to-end test passes on the real target