---
name: debian-headless-build
description: Build a C program from Debian source on a headless server by stripping X11/graphics dependencies from the Makefile, then install and verify the binary has no graphical linkage.
---

# Build a C Program from Debian Source Without X11

Use this procedure when you need to compile a Debian-packaged C program on a headless server (no X11, no display libraries) where the upstream Makefile conditionally enables X11/graphics support.

## When to use

- Building a TUI or CLI tool from a Debian source package
- The package's Makefile has an X11/graphics branch you cannot satisfy
- You have root and can install `dpkg-dev` and related build tooling
- A graphical or windowing dependency would otherwise fail the link

## Steps

1. **Enable source repositories.** Edit `/etc/apt/sources.list` (or `/etc/apt/sources.list.d/*.list`) so every `deb` line has a matching `deb-src` line. Re-run `apt-get update`.

2. **Install build prerequisites.**
   ```
   apt-get install -y dpkg-dev build-essential
   ```
   Add any other `-dev` packages the package's `Build-Depends` field lists in `debian/control`.

3. **Fetch the source.** From a writable working directory:
   ```
   apt-get source <package-name>
   ```
   This produces a `pkg-version/` directory with the upstream tarball already unpacked and Debian patches applied. If `dpkg-source` complains about a signature or format, fall back to manually downloading the upstream `.tar.gz` from the package's homepage and extracting it.

4. **Inspect the Makefile.** Open the top-level `Makefile` and look for X11-related markers. Common patterns:
   - Compile-time defines: `-DXWINGRAPHX`, `-DGRAPHX`, `-DX11`, `-DUSE_X11`
   - Linker flags: `-lX11`, `-L/usr/X11R6/lib`
   - Header includes guarded by `#ifdef GRAPHX` / `#ifdef XWINGRAPHX`
   - Source files that #include `<X11/Xlib.h>` or `<X11/Xutil.h>`

5. **Strip the X11 branch.** Edit the Makefile to remove or comment out the X11 flags, defines, and the corresponding object/source files. Typical fixes:
   - Remove `-DXWINGRAPHX` (or whichever define gates the X11 code) from `CFLAGS`.
   - Remove `-lX11` from `LIBS`.
   - Exclude the X11 driver `.c` file from the `OBJS` list (or wrap its build rule in a guard that no longer fires).
   - If a top-level "build with X" target exists, switch to the non-X target.

6. **Build.**
   ```
   make clean && make
   ```
   Warnings about unused X11 helpers are acceptable; unresolved symbols for `XOpenDisplay`, `XCreateWindow`, etc. mean you missed a file — re-grep the Makefile.

7. **Install the binary.**
   ```
   install -m 0755 <binary> /usr/local/bin/
   ```
   Or use `make install` if the Makefile's install target was not broken by your edits.

8. **Verify no X11 linkage.**
   ```
   ldd /usr/local/bin/<binary>
   ```
   The output must not list `libX11.so` or any other `libX*.so`. If it does, return to step 5.

9. **Smoke-test functionality.** Run the program's intended invocation (e.g. the debugger, the CLI front-end, a self-test flag). Confirm it produces the expected output and exits cleanly without trying to open a display.

## Failure modes to expect

- **`apt-get source` fails on signature**: `gpg --recv-keys <keyid>` then retry, or skip and download the tarball manually.
- **Linker still asks for `-lX11`**: an object file from the X11 driver is still in `OBJS`. Look for a non-obvious second Makefile (e.g. `src/Makefile`) and patch it too.
- **`Xlib.h` not found at compile time**: a non-driver `.c` file includes X11 headers under the same `-D` guard. Either remove the include or keep the define but provide stub headers.
- **Build-Depends missing**: `debian/control` lists `-dev` packages you don't have. Install them with `apt-get build-dep <package-name>`.

## Verification checklist

- [ ] `ldd` on the installed binary shows no `libX*.so`
- [ ] Binary runs to completion on a real input
- [ ] Binary is in the system `PATH` (e.g. `/usr/local/bin`)
- [ ] Source directory left in place for reproducibility, or removed if the sandbox is ephemeral