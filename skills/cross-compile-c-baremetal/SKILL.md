---
name: cross-compile-c-baremetal
description: Cross-compile a C program to a bare-metal MIPS (or similar embedded) ELF target that runs on a custom VM. Use when porting an existing C codebase (e.g. a game, library, or syscall-based app) to a foreign ISA like MIPS32 with `-static -nostdlib -nostartfiles`, providing custom syscall stubs and platform callbacks that match the VM's ABI.
---

# Cross-compile C to a bare-metal target for a custom VM

Reusable procedure when porting a C program to a non-hosted MIPS (or other embedded ISA) environment that has its own syscall convention and minimal runtime — for example a JavaScript-implemented MIPS VM, a teaching emulator, or a firmware simulator.

## When to use

- Target is a foreign ISA (MIPS32, RISC-V, etc.) running on a custom VM, not Linux.
- The VM exposes a small set of syscall numbers (open, read, write, exit, etc.) with a specific calling convention.
- The C program expects libc/startup but the VM has none — you must ship a freestanding build.
- The program has a platform abstraction layer (e.g. `DG_*` callbacks for Doom) that needs to be implemented against the VM.

## Procedure

### 1. Identify the VM's ABI

Before writing any code, extract from the VM source/docs:

- **Instruction set & endianness**: MIPS32 little/big-endian, RISC-V, ARM, etc.
- **Syscall convention**: how is a syscall issued? Common patterns:
  - `addiu $v0, $zero, N; syscall` (MIPS)
  - `li a7, N; ecall` (RISC-V)
  - `mov r7, #N; swi 0` (ARM)
- **Syscall numbers**: assign numeric codes to `exit`, `write`, `read`, `open`, `brk`, etc.
- **Argument & return registers**: typically `$a0-$a3` for args, `$v0` for return on MIPS.
- **Stack setup**: does the VM push argc/argv? Almost certainly not — `main()` is yours to define.

Write this down as a header (e.g. `syscalls.h`) so every other file can reuse the constants.

### 2. Implement platform callbacks

The program to port will declare a set of platform hooks (graphics init, frame draw, sleep, input, file I/O, etc.). Create a single `platform_<target>.c` that:

- Implements every callback the program requires (read its headers to enumerate them).
- Routes each callback through the VM's syscalls: e.g. draw-frame writes a framebuffer blob via syscall `write` to fd 1; sleep loops on a `clock` syscall; input reads keys via a `getkey` syscall.
- Provides a `main()` that calls the program's entry point (e.g. `D_DoomMain` for Doom).

### 3. Provide freestanding syscall stubs

The C runtime expects `open`, `close`, `read`, `write`, `exit`, `sbrk`, etc. Write these in a small `syscalls.c` (or inline asm) using the VM's convention:

```c
// Example for MIPS VM where syscall N is "write(fd, buf, len) -> ret"
static inline long syscall3(long n, long a, long b, long c) {
    register long _a0 asm("a0") = a;
    register long _a1 asm("a1") = b;
    register long _a2 asm("a2") = c;
    register long _v0 asm("v0") = n;
    asm volatile("syscall"
                 : "=r"(_v0)
                 : "r"(_a0), "r"(_a1), "r"(_a2), "r"(_v0)
                 : "memory", "cc");
    return _v0;
}

long write(int fd, const void *buf, long len) { return syscall3(SYS_write, fd, (long)buf, len); }
void exit(int code)                                { syscall3(SYS_exit, code, 0, 0); while(1); }
```

Use `register long … asm("reg")` + inline asm so the compiler picks the right ABI registers without you having to hand-write assembly for every call.

### 4. Compile and link

Use the matching GNU cross-toolchain (`mips-linux-gnu-gcc`, `riscv64-linux-gnu-gcc`, etc.):

```bash
CC=mips-linux-gnu-gcc
CFLAGS="-mips32 -EL -static -nostdlib -nostartfiles -fno-pie -G 0 \
        -Wl,-T,link.ld -Wl,--no-warn-rwx-segment"
$CC $CFLAGS -o program.elf crt0.S platform_<target>.c syscalls.c <program_sources>.c
```

Key flags and why:

- `-mips32 -EL` — match the VM's ISA and endianness (pick `-EB` for big-endian).
- `-static -nostdlib -nostartfiles` — no libc, no auto `_start`; you provide everything.
- `-fno-pie -G 0` — avoid PIC/GOT complexity that small VMs can't handle.
- `-Wl,-T,link.ld` — flat memory layout: `.text` at `0x00400000`, `.data`/`.bss` after, a single `STACK` region, no dynamic sections.
- Provide a tiny `crt0.S` that sets `$sp`, zeroes `.bss`, then calls `main`.

### 5. Iterate on the VM's quirks

Expect to iterate on:

- **Framebuffer format**: VM may expect ARGB8888, RGBA, RGB565, or a custom palette. Implement a conversion step in the draw callback.
- **Endianness in header blobs**: WAD files, asset headers, etc. — byte-swap on read if the VM is big-endian and the assets are little-endian.
- **Missing syscalls**: `brk`/`sbrk` for malloc — implement a bump allocator if the program needs `malloc`.
- **No filesystem**: embed assets via `incbin` (GNU as) or convert to a C array, then expose them through a fake `open()` that returns a memory-backed fd.

### 6. Run and verify

Load the ELF in the VM. First run will likely fail on the first missing callback or wrong syscall number — read the VM's stdout/log to find which syscall was hit (it usually prints the unhandled syscall number), map it back to your `syscalls.c`, fix, rebuild. Repeat until the program reaches its first frame.

## Common pitfalls

- **Forgetting `-nostartfiles`** → the linker drags in `_start` that calls `__libc_start_main`, which references syscalls you haven't provided, and you get cryptic unresolved-symbol errors. Always check with `nm program.elf | grep U`.
- **Wrong syscall register mapping** → values come back zero or garbage. Print the `$v0` after every `syscall` to confirm the ABI.
- **Stack not 8-byte aligned on MIPS o32** → crashes deep in any function with a `lw` from `$sp`. Set `$sp` to `(_stack_top - 16) & ~0xF` in `crt0.S`.
- **Globals in `.data` not relocated** → the VM doesn't support dynamic relocations; use `-G 0` and avoid pointer-initialized globals.
- **Forget to zero `.bss`** → uninitialized globals contain garbage; `crt0.S` must loop over `__bss_start`/`__bss_end` symbols from the linker script.

## Quick checklist before building

- [ ] VM ABI documented (ISA, endianness, syscall numbers + register mapping).
- [ ] All platform callbacks enumerated from program headers and implemented.
- [ ] `syscalls.c` covers at least: `exit`, `write`, `read`, `open`, `close`, `sbrk`/`brk`.
- [ ] `crt0.S` sets `$sp`, zeros `.bss`, calls `main`.
- [ ] Linker script lays out `.text` / `.data` / `.bss` / `STACK` for the VM's memory map.
- [ ] Compile with `-static -nostdlib -nostartfiles` and the matching `-m<isa>`/`-E[LB]`.
- [ ] `nm program.elf` shows no undefined libc symbols.