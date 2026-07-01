---
name: debian-build-nox
description: Build a Debian source package on a headless/X11-less host when the upstream build defaults to optional X11 support. Covers enabling deb-src sources, fetching/building the source, disabling the X11 code path at configure or Makefile level, installing the binary, and verifying no X11 linkage remains.
---

# Build a Debian source package without X11

Use this when you need to compile a Debian-packaged program whose build system
optionally pulls in X11, but the target environment is headless and X libraries
are unavailable.

## Procedure

1. **Enable source packages in APT.**
   - Copy the active `sources.list` entry to a `*.src` file (or append `-src`
     components) and change the `Types:` field from `deb` to `deb-src`.
   - Run `apt-get update` so apt knows about the source index.

2. **Fetch the source.**
   - `apt-get build-dep <package>` (if available) to pull build dependencies.
   - `apt-get source <package>` to download the source tarball and `.dsc` into
     the current directory.
   - Install the toolchain: `apt-get install -y dpkg-dev build-essential`.

3. **Extract and inspect the source tree.**
   - `dpkg-source -x <package>.dsc` to unpack.
   - `cd` into the unpacked directory.
   - Inspect the build system:
     - `configure.ac` / `Makefile.am` → autotools (uses `./configure`).
     - `CMakeLists.txt` → CMake (`cmake` then `make`).
     - Bare `Makefile` → hand-written make rules; flags live in variables like
       `LIBS`, `CFLAGS`, `OBJS`, or per-target rules.

4. **Disable the X11 code path.**
   - **Autotools:** look for `--with-x` / `--without-x`, `--enable-x11` /
     `--disable-x11`, or a `--without-<feature>` toggle. Run
     `./configure --without-x` (or the project's canonical disabling flag).
   - **CMake:** look for `-DWITH_X11=OFF`, `-DENABLE_X11=OFF`, or similar
     option; pass the `=OFF` variant to `cmake`.
   - **Hand-written Makefile:** find X11 references (`-lX11`, `-lXt`, `-lXpm`,
     `INCLUDES` with `/usr/include/X11`, target rules that build `x*` or
     `*X11*` objects). Either:
     - Drop X11 libs from the `LIBS` / `XLIB` variable.
     - Comment out or `.skip`-guard the X11-only target/objects.
   - If the project has both a CLI/Curses backend and an X11 frontend, ensure
     the non-X11 target is the one being built (often `src/<prog>` or
     `<prog>` while X11 lives in a separate `<prog>x` or `x<prog>` target).

5. **Compile.**
   - `make -j"$(nproc)"`. Watch for unresolved-symbol errors referencing
     `XOpenDisplay`, `XtAppCreate`, `XpmReadFileToPixmap`, etc. — those mean
     the X11 code path wasn't fully disabled; revisit step 4.

6. **Install the binary.**
   - If `make install` exists and honors `DESTDIR`/`PREFIX`, prefer it.
   - Otherwise copy the produced executable directly:
     `install -m 0755 src/<prog> /usr/local/bin/<prog>` (or `cp`).

7. **Verify no X11 linkage.**
   - `ldd /usr/local/bin/<prog> | grep -i 'x11\|xt\|xpm'` should return nothing.
   - Optionally run `nm` / `objdump -p` on the binary as a deeper check.

## Heuristics

- The package's `debian/rules` is also authoritative — if it sets
  `DEB_CONFIGURE_EXTRA_FLAGS` or similar, that may already disable X11 when
  built the Debian way. Building outside `dpkg-buildpackage` (as here) usually
  means you re-implement that decision manually.
- `--without-x` is the autotools convention; many projects alias it to
  `--disable-x`, `--without-x11`, or a project-specific name — always
  `./configure --help | grep -i x` first.
- A trailing `x` in a binary name (`pmars` vs `pmarsx`, `corewar` vs
  `corewarx`) often signals the X11 frontend; the bare name is usually the
  non-X11 build.