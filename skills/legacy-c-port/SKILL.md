---
name: legacy-c-port
description: Build or port legacy C source code (pre-ANSI, K&R, or 1990s-era) on modern 64-bit Linux toolchains. Use when an agent is asked to compile old C programs that fail with implicit-declaration errors, missing obsolete flags (e.g. -m386), or undefined references to BSD/libbsd functions like strdup or strnicmp.
---

# Porting legacy C to a modern toolchain

Legacy C projects (POV-Ray 2.x, Mesa 1.x, gcc 1.x, etc.) were written
when compilers were lenient and glibc was smaller. Modern GCC and
clang enforce what those programs assumed. Most "I followed the
README and it won't build" failures trace back to the same handful of
gaps.

## Diagnostic checklist (run BEFORE the first `make`)

Run these checks against the source tree, not against an imagined
problem:

1. **Compiler flags sweep.** `grep -RnE -- '-m(386|486|686)|-fno-strength-reduce|-fomit-frame-pointer' Makefile* *.mak unix/` and remove or rewrite anything that targets 32-bit x86 or pre-GCC-2 optimizers. If the original Makefile sets `-O6` or `-O7`, downgrade to `-O2`.
2. **Implicit-declaration audit.** Compile a single .c file with `-Wall -Werror=implicit-function-declaration` and note every undeclared call. Common culprits: `strdup`, `strnicmp`, `stricmp`, `bcopy`, `index`, `rindex`, `bzero`, `bcmp`, `alloca`. Decide the fix per case — alias to the POSIX name via a compat header, link `-lbsd`, or wrap with a tiny static function.
3. **Header absence scan.** `grep -RnE '#include\s*<(malloc\.h|values\.h|sys/dir\.h|sys/param\.h)'` and remap: `malloc.h` → `stdlib.h`; `values.h` → `limits.h`/`float.h`; BSD `sys/dir.h` → `dirent.h`.
4. **Missing-data / resource check.** Programs that ship fonts, palettes, or config in a separate archive (e.g. `*.def`, `*.inc`, `*.dat`) often require that file to be present at build *or* runtime. Verify every referenced file actually exists; if not, decide whether to synthesize a minimal stub or fetch the missing archive before proceeding.

## Stop signal

If after applying the patches above the binary still produces output
that disagrees with a reference (different pixel hash, different file
size, different image dimensions), STOP iterating on flags. The cause
is no longer compilation — it is floating-point behavior. Reset by:

1. Recompiling with `-ffloat-store` (forces stores after every op,
   matching 32-bit `double` excess-precision behavior on x87).
2. If still wrong, link with `-lmpatrol` or run under `valgrind` to
   catch uninitialized memory, since legacy code frequently relied on
   zero-initialized globals that a modern loader no longer guarantees.
3. Compare reference and actual at a single pixel in a debugger
   before adding more `-O` or `-f` flags — guesses here cost hours.

Do not keep adding compiler flags hoping for a match. Each new flag
adds a degree of freedom without evidence.