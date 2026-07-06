---
name: build-debian-source
description: Build a C/C++ project from its Debian source package with optional feature flags disabled (e.g. no X11, no GUI). Use when a target binary is only available as a Debian source package and must be compiled locally without unwanted optional dependencies.
---

# Build from Debian Source Without Optional Features

Reusable procedure for compiling a Debian source package locally while disabling optional feature flags (such as GUI/X11 support) and verifying the result.

## When to use

- The target program is not in the default binary repos, or the binary package pulls in unwanted optional dependencies (X11, GUI toolkits, etc.).
- You can `apt-get source` the upstream tarball but need a headless / minimal build.
- The upstream build system is autotools (or a simple Makefile) that supports `--without-FEATURE` or has obvious feature-flag variables.

## Procedure

1. **Enable source repositories.**
   Edit `/etc/apt/sources.list.d/debian.sources` (or the equivalent sources file) so it includes a `Types:` line with `deb-src` enabled, then run `apt-get update`.

2. **Fetch the source package.**
   ```
   apt-get source <package-name>
   ```
   This drops an upstream tarball (`*.orig.tar.xz`), a Debian diff, and a `.dsc` into the current directory.

3. **Install build toolchain.**
   ```
   apt-get install -y build-essential xz-utils
   ```
   Add other `-dev` packages only if `configure`/`make` reports a missing header.

4. **Extract the upstream tarball** (skip if it auto-extracted):
   ```
   tar -xJf <package>_*.orig.tar.xz
   cd <package>-*/
   ```

5. **Configure with optional features off.**
   - If autotools is present: `./configure --without-<feature>` (e.g. `--without-x`).
   - If only a `Makefile`: inspect it for feature flags (`X11FLAGS`, `HAVE_X11`, etc.) and either remove those lines, set the flag to empty/0, or override via `make CFLAGS="..."`.
   - If the package is a Debian source with `debian/rules`: you can still `cd` into the upstream source dir and run its own build, or use `dpkg-buildpackage` with environment overrides.

6. **Build.**
   ```
   make -j"$(nproc)"
   ```

7. **Install the binary** to a stable path:
   ```
   cp src/<binary-name> /usr/local/bin/<binary-name>
   ```
   Adjust the source path by inspecting `ls src/` or the `Makefile`'s install target.

8. **Verify the disabled feature is really absent.**
   Use `ldd` on the installed binary and grep for the unwanted library:
   ```
   ldd /usr/local/bin/<binary-name> | grep -i <feature-lib>
   ```
   An empty result confirms the feature was successfully excluded.

9. **Smoke test** with a non-interactive invocation that exercises core functionality. Pick a flag combination known to produce a short, predictable line of output (a "results" line, a version string, or a help summary) so you can assert success.

## Pitfalls

- Forgetting `deb-src` in the sources file → `apt-get source` fails immediately. Always re-run `apt-get update` after editing sources.
- Building inside the Debian diff directory instead of the unpacked upstream source → configure/make may pick up Debian patches unintentionally. Prefer the plain upstream tree.
- The `Makefile` may hard-code `-lX11` even with `configure --without-x`. Grep the build output for the library name if verification fails.
- Some libraries are linked dynamically only when the relevant headers exist at build time. Removing the `-dev` package for the unwanted feature is a reliable belt-and-braces step.

## Verification checklist

- [ ] `which <binary>` resolves to `/usr/local/bin/<binary>`
- [ ] `ldd` shows no link to the disabled feature's library
- [ ] Smoke test command exits 0 and produces expected output