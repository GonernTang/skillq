---
name: build-legacy-c
description: Build legacy C software from old source archives (.tar.Z, .tgz) on Unix systems. Use when an old C project's source must be downloaded from FTP archives, extracted with obsolete compression utilities, and compiled with vintage Makefiles or config headers that often need minor fixes.
---

# Build Legacy C Software from Source Archives

Use this procedure when an old C project (pre-autotools era, often 1980s–1990s) must be compiled from a source archive obtained from an FTP site or "Old-Versions" directory.

## Steps

### 1. Locate the source distribution
- Search the project's official FTP server or web archive, typically under a directory named `Old-Versions/`, `legacy/`, or `pub/`.
- Identify the exact version requested. Older releases are sometimes only available in obscure compressed formats (`.tar.Z`, `.tar.gz`, `.tgz`).

### 2. Download the archive
- Use `curl` or `wget` to fetch from the FTP/HTTP URL.
- If multiple archives are required (e.g., separate source and include files), download all of them into the same working directory.

### 3. Decompress and extract
- For `.Z` (LZW compress): use `uncompress <file>` to produce a `.tar` file.
- For `.tgz` or `.tar.gz`: use `tar xzf <file>`.
- For `.tar` (uncompressed): use `tar xf <file>`.
- If `uncompress` is not installed, install the `ncompress` package or use `gzip -d` followed by renaming — but prefer the canonical tool for the format.

### 4. Survey the build system
- Look for a `Makefile`, `makefile`, `unix.mak`, `Makefile.unix`, or a `configure` script.
- Old C projects often ship a `config.h` (sometimes `unix/config.h`) with `#define` toggles for platform-specific features.
- Read the top-level `README` or `INSTALL` file for build instructions — they may name the exact Makefile target.

### 5. Patch configuration if needed
- Inspect `config.h` for `#define`s that reference function names or symbols. Common mismatches:
  - Casing: header declares `unix_init_povray` while source defines `unix_init_POVRAY` (or vice-versa).
  - Stale prototypes when source has been renamed.
- Fix the spelling/casing so the symbol referenced in the `#define` or function pointer matches the actual definition in the `.c` files.
- Also check that any required feature-test macros (e.g., `_POSIX_SOURCE`) are set if the build fails on missing declarations.

### 6. Compile
- Run `make` with the platform-specific Makefile:
  ```
  make -f unix.mak          # or whatever the project ships
  ```
- Address warnings pragmatically but treat link errors (undefined references) as real bugs requiring source or config fixes.
- If the build expects a specific compiler flag (e.g., `-DUNIX`, `-Iunix`), make sure it is present in the Makefile.

### 7. Install
- Copy the resulting binary to a directory on `$PATH`, typically `/usr/local/bin/`:
  ```
  cp <binary> /usr/local/bin/
  ```
- If the project ships separate data files (include paths, scene files, fonts), note their install location for the verification step.

### 8. Verify
- Run a minimal test invocation that exercises the binary's primary function (e.g., a small scene render, a short file conversion).
- Supply any required include path or data directory flags the binary expects.
- Confirm a sensible output (file produced, no crash, exit code 0).

## Common pitfalls
- **Archive format confusion**: a `.tar.Z` is *not* a gzip file. Use `uncompress`, not `gunzip`.
- **Case-sensitivity in symbols**: legacy C was less consistent about naming conventions; symbol mismatches between `config.h` and source files are routine.
- **Missing system headers**: very old code may assume header locations from an older libc; adding `-D_GNU_SOURCE` or equivalent is often enough.
- **Multiple archive parts**: if a README says "extract part 1 then part 2", do so in order — concatenated archives need `cat part1 part2 | tar x`.