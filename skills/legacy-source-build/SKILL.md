---
name: legacy-source-build
description: Build legacy C/C++ software distributed as multiple separate archives (source, includes, docs, scenes) from before the modern package-manager era. Triggers when a task names a specific old version of a tool, requires manual extraction of several tarballs, asks for platform-specific Makefile adjustments (e.g. machine.h, config.h), or needs verification via a CLI invocation with explicit include/library paths. Apply for POV-Ray, classic DOOM source ports, old graphics renderers, pre-1.0 compilers, and similar vintage projects.
---

## When to apply

Use this skill when the target is software from the late-1980s to mid-1990s era that:

- Is distributed as **multiple coordinated archives** (source / headers / docs / data / scenes), not a single tarball.
- Comes with a **platform-specific header** (e.g. `machine.h`, `config.h`, `platform.h`) that must be edited before compilation.
- Is built by a single `make` invocation with no `./configure` step.
- Has no package-manager presence (no apt/brew/pacman package, no `pip install`, no `npm install`).

## Procedure

1. **Inventory the archives first.** Before downloading anything, list every archive the project requires (source + headers + docs + data + scenes). Most vintage projects have a `README` or `INSTALL` that names them; if not, check the project's official "distribution" or "downloads" page on a legacy mirror. Treat any archive you miss as a guaranteed build failure.

2. **Extract into a single target directory.** All archives must unpack into the same root so that `#include` paths and `+L`/`+I` library paths resolve. Use one of:
   - `for a in *.tar.gz; do tar xzf "$a"; done` into the target dir, or
   - a Makefile target like `make all` if the project ships one.
   Do NOT scatter extractions across separate directories.

3. **Inspect and patch the platform header before running `make`.** Open `machine.h` / `config.h` / equivalent and set the OS/architecture defines (e.g. `MACHINE = "unix"`, `#define UNIX`, `#define BYTE_ORDER`, `#define IEEE_FLOAT`). Skipping this step is the single most common cause of "compiles but produces a broken binary."

4. **Compile in the source subdirectory.** `cd` into where the `Makefile` lives (often the same dir as `machine.h`) and run `make`. If the Makefile assumes a non-standard `CC`, set it explicitly. Do not run `make install` until the binary verifies.

5. **Install the binary.** Copy the produced executable into a directory on `PATH` (e.g. `/usr/local/bin/`). Preserve execute permission.

6. **Verify with explicit include/library paths.** Legacy binaries do not auto-discover their bundled `.h`/`.inc` files. Invoke the binary with the paths the project documents (e.g. `+L<doc-dir>/include +I<test-input>`). If verification fails:
   - Re-check step 3 (platform defines).
   - Re-check step 2 (extraction root).
   - Check for missing system libs (`libc`, `libm`) and link with `-lm` if needed.

## Diagnostic checklist

Run ALL of these before committing to a full build. If any fails, fix it before proceeding — these are the cheap tests that prevent the expensive debugging spiral:

1. **Archive manifest complete?** Confirm the names and versions of every required archive against the project's `README`/`INSTALL` or official mirror page. Count them; the number must match the documented distribution.
2. **Single extraction root?** After extracting all archives, `ls` the target directory and verify that the includes, docs, and source files all live under one common parent.
3. **Platform header present and editable?** `grep` for the OS/arch macro (`UNIX`, `MACHINE`, `BYTE_ORDER`) in the platform header. Confirm the value is settable to the current OS before invoking `make`.
4. **Smoke render / smoke run on a trivial input?** Before scaling to real workloads, run the binary with the include paths on a one-line or trivial test file (e.g. a scene with one primitive, or a `--version` / `--help` if it supports one). Confirm a clean exit code and expected output file.

## Stop signal

If you have:
- Tried **two** different extraction layouts (e.g. parallel subdirs vs. merged root) and the binary still fails to find its includes, OR
- Edited the platform header **twice** with different OS/arch defines and the build still produces a broken or non-functional binary,

then **stop iterating on the build itself** and instead verify the archive manifest against the upstream project page. The most likely cause is a missing archive (e.g. the headers or docs were not downloaded), not a build-system issue. Re-download from a different legacy mirror before attempting a third build.

## Common pitfalls

- **Treating "source archive" as the whole project.** Almost never true for vintage software — you also need the headers, docs, and data archives.
- **Assuming `make` will figure out paths.** It will not. Include and library paths must be set in the Makefile or passed at invocation.
- **Skipping the platform header.** `make` succeeds but the binary crashes on the first input that exercises float endianness or word size.
- **Installing before verifying.** Always smoke-test with the include paths before `cp` to `/usr/local/bin`.
- **Using a "modern" mirror.** The current homepage may only host binaries or a newer version; find the legacy archive directory (often under `/pub/linux/apps/...` or `/pub/mirrors/...`).