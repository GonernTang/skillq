---
name: legacy-source-build
description: Avoid common pitfalls when building legacy C projects from split source/header archives. Use when a legacy codebase ships in multiple tarballs, has outdated compiler flags, manual function prototypes instead of standard headers, or requires careful verification with non-default include paths. Captures the guard-rail for archival build tasks where naive compilation fails.
---

# Building Legacy Source from Split Archives

Legacy C projects (especially late-80s/early-90s software) frequently ship as
separate source and header tarballs, contain outdated GCC flags, and rely on
manual `malloc`/`free` prototypes instead of `<stdlib.h>`. They also tend to
ship a `povdoc` or sibling documentation/include directory that must be
referenced on the include path. Building them blindly wastes a cycle and
produces a binary that "looks installed" but cannot render or verify.

## Diagnostic checklist

Before compiling, confirm each of the following:

1. **Both archives extracted to the right subdirectories.** Source goes under
   the project's source tree; headers go under a sibling `include/` directory.
   Verify the header tarball actually populated `include/` — a common failure
   is leaving headers in a flat directory where the Makefile doesn't look.
2. **Compiler flags are modernized.** Strip obsolete flags (e.g. `-m386`,
   `-fcaller-saves`) and add suppressions for warnings that modern GCC
   promotes to errors (`-Wno-implicit-function-declaration`,
   `-Wno-int-conversion`, `-Wno-incompatible-pointer-types`). Update install
   paths (`INSTALL_BIN`/`INSTBIN`) to a writable system location.
3. **Standard headers replace hand-written prototypes.** Search the config
   header for manual declarations of libc functions (especially
   `malloc`/`free`) and replace them with `#include <stdlib.h>`. Modern GCC
   will reject implicit declarations.
4. **Verification render writes to a real, non-`/dev/null` path.** Use the
   exact include path the spec calls for (e.g. `+L/path/to/include`) and a
   writable output path (e.g. `+O/tmp/output.tga`). After rendering,
   confirm the file exists and is non-empty before declaring success.

## Stop signal

If the compiled binary installs cleanly but a verification render produces no
output file (or a zero-byte file), do **not** re-run the same command. Stop,
re-check that: (a) the include path matches the spec literally, (b) the
output path is writable and not `/dev/null`, and (c) the header archive was
actually extracted into the directory the Makefile searches. Reset by
re-extracting the header archive into the expected `include/` location, then
re-rendering with the corrected `+L` and `+O` flags before attempting further
build changes.