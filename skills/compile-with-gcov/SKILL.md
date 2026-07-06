---
name: compile-with-gcov
description: Build a C project with gcov code-coverage instrumentation. Use when asked to compile, build, or install a C/C++ project with coverage enabled, or when preparing a project to produce .gcno/.gcda files for coverage analysis.
---

# Compile a C Project with gcov Coverage

## Overview
Enable `gcov` instrumentation in a C project so that compiled translation units
emit `.gcno` (notes) files at build time and `.gcda` (data) files at runtime.
The same `--coverage` flag is used at both compile and link steps so the final
binary writes coverage counters to disk.

## Procedure

1. **Verify or install the toolchain.** Confirm `gcc` and `make` are available.
   If not, install them with the system package manager (e.g.
   `apt-get install -y gcc make`).

2. **Obtain the source.** If the project is vendored as a tarball or zip,
   extract it first. Otherwise `cd` into the existing source tree.

3. **Configure with coverage flags.** Run the project's configure step
   (typically `./configure`) with both `CFLAGS` and `LDFLAGS` set to
   `--coverage`. This single flag enables instrumentation in `gcc` for both
   compilation and linking:
   ```
   CFLAGS="--coverage" LDFLAGS="--coverage" ./configure
   ```
   If the project uses a non-autotools build (CMake, plain Makefile, etc.),
   add `--coverage` to the equivalent compile/link variables in the same way.

4. **Build.** Run the build tool with the generated configuration:
   ```
   make -j"$(nproc)"
   ```

5. **Verify instrumentation at build time.** After the build, check that
   `.gcno` files were produced next to the object files. Their presence
   indicates the compile step was instrumented:
   ```
   find . -name '*.gcno' | head
   ```

6. **Install the binary.** Put the built executable on `PATH` so it can be
   invoked for coverage runs:
   ```
   make install
   # or, when no install target exists:
   cp <binary> /usr/local/bin/
   ```

7. **Smoke-test the binary and verify runtime data.** Run a small workload
   against the installed binary, then confirm `.gcda` files were emitted
   alongside the source/object files:
   ```
   <binary> <smoke-test-args>
   find . -name '*.gcda' | head
   ```
   The appearance of `.gcda` files proves the linked binary is writing
   counters to disk.

8. **Confirm coverage reporting works.** Invoke `gcov` on one source file
   and inspect the resulting `*.gcov` text file to ensure line/branch
   coverage data is being produced correctly:
   ```
   gcov <source-file>.c
   cat <source-file>.gcov | head
   ```

## Notes
- `--coverage` is equivalent to `-fprofile-arcs -ftest-coverage` for compile
  and `-lgcov` for link; passing it in both `CFLAGS` and `LDFLAGS` covers
  both phases.
- If the project has no `./configure`, add the flags directly to the build
  system's compile/link variables (e.g. `EXTRA_CFLAGS`, `CXXFLAGS`).
- To reset coverage counters between runs, delete the existing `.gcda` files
  before re-running the binary.