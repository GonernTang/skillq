---
name: gcov-build-c-project
description: Build a C/C++ project from source with gcov code coverage instrumentation. Use when asked to compile a project for code coverage analysis, generate .gcno/.gcda files, or instrument binaries for coverage tracking.
---

# Build C/C++ Project with Gcov Coverage

## When to use
Use this skill when you need to compile a C or C++ project from source so that the resulting binaries produce gcov code-coverage data at runtime. This applies to autotools-based projects (SQLite, GCC, binutils, etc.), Makefile-based projects, or any project whose build can be influenced through CFLAGS/LDFLAGS.

## Steps

### 1. Verify the toolchain
Confirm a working GCC toolchain is available before extracting anything:
- `gcc --version`
- `g++ --version`
- `make --version`

If any are missing, install via the system package manager (e.g. `apt install build-essential`, `dnf install gcc gcc-c++ make`, `brew install gcc make`).

### 2. Extract the source
Unpack the source archive into a working directory:
- `tar -xzf <archive>.tar.gz` (or `.tar.bz2`, `.zip`, etc.)
- `cd` into the resulting source tree.

### 3. Configure with coverage instrumentation
Two paths — try the project-native one first:

**Preferred — autotools projects with a built-in flag:**
Many projects (SQLite, GCC, etc.) expose a convenience flag:
```
./configure --gcov
```
Inspect `./configure --help` first; if `--gcov` exists, use it. It typically wires `-fprofile-arcs -ftest-coverage` into CFLAGS and `-lgcov` (or `-fprofile-arcs`) into LDFLAGS automatically.

**Fallback — manual flag injection:**
If no `--gcov` flag exists, pass coverage flags directly to `configure` (or set them in the environment for plain Makefile builds):
```
CFLAGS="-fprofile-arcs -ftest-coverage" \
LDFLAGS="-fprofile-arcs" \
./configure
```
For C++ as well, also pass `CXXFLAGS="-fprofile-arcs -ftest-coverage"`. Some projects additionally need `-lgcov` linked explicitly; if unresolved symbols appear at link time, append `-lgcov` to LDFLAGS.

### 4. Build
```
make -j"$(nproc)"
```
Use parallel jobs to speed up; `-k` to keep going past non-fatal errors when debugging.

### 5. Install (if the binary must be on PATH)
```
make install
```
Or copy the specific binary into a directory already on PATH. Skip this step if the build tree's path is sufficient for the task.

### 6. Verify static coverage notes were emitted
After compilation, `.gcno` files must exist alongside the object files (one per translation unit that was compiled). Sanity-check:
```
find . -name '*.gcno' | head
```
If none appear, the configure step did not actually enable coverage — re-check CFLAGS or rerun `./configure` with explicit flags.

### 7. Run the instrumented binary to generate `.gcda` files
`.gcda` files are produced at runtime, not build time. Execute the binary (or its test suite) once so coverage data is written:
```
<binary> <args...>
# or: make check
```
After execution, verify:
```
find . -name '*.gcda' | head
```

### 8. Confirm the binary is functional and on PATH
```
which <binary>
<binary> --version
```
A passing `--version` (or any known-good invocation) confirms the instrumented build runs correctly and links without runtime errors.

## Troubleshooting
- **No `.gcno` files after build** → coverage flags never reached the compiler; verify CFLAGS survived `configure` by running `make V=1` and inspecting the gcc command lines.
- **Linker errors referencing `__gcov_*` symbols** → add `-lgcov` to LDFLAGS (older GCC profiles) or `-fprofile-arcs` to LDFLAGS (newer GCC).
- **No `.gcda` files after running** → binary either wasn't actually instrumented, or the working directory at runtime differs from the build directory. Run the binary from inside the build tree, or set `GCOV_PREFIX`/`GCOV_PREFIX_STRIP` to redirect `.gcda` output.
- **`configure` doesn't exist** → project isn't autotools-based; skip configure and inject CFLAGS/LDFLAGS into the Makefile or build invocation directly.

## Reporting results
When done, summarize:
- Configure flags used
- Build success/failure
- Number of `.gcno` files produced
- Number of `.gcda` files produced after running
- Whether the binary is installed and on PATH