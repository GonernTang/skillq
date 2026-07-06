---
name: build-compcert
description: Build CompCert (the formally verified C compiler) from source on a Linux x86_64 system. Use when a task requires compiling, installing, or verifying a working `ccomp` binary from a CompCert release tarball.
---

# Build CompCert from source

CompCert is a formally verified C compiler written in OCaml and Coq. To produce a working `ccomp` binary from a release tarball, follow the standard OCaml `./configure && make` flow on Linux.

## 1. Install system dependencies

Install the build toolchain (OCaml compiler, Menhir parser generator, GNU make, and a C compiler used by the runtime):

```
sudo apt-get update
sudo apt-get install -y build-essential ocaml ocaml-native-compilers menhir make gcc
```

On non-Debian systems, substitute the equivalent packages:
- OCaml ≥ 4.10 with the native code compiler
- Menhir
- GNU `make`
- A working C compiler (`gcc` or `clang`)

## 2. Acquire the source

Download the desired CompCert release tarball (e.g., a GitHub release `.tar.gz`). Extract it and `cd` into the resulting directory before continuing.

## 3. Configure for the target

Run the bundled `configure` script with the appropriate target triple for the host platform:

```
./configure <target>
```

Common targets:
- `x86_64-linux` — most Linux x86_64 hosts (typical default)
- `aarch64-linux` — Linux on 64-bit ARM
- `riscv64-linux` — Linux on RISC-V

The script will check for the required OCaml libraries (Menhir, etc.) and report any missing prerequisites.

## 4. Build

```
make -j$(nproc)
```

This compiles the OCaml sources and produces the `ccomp` (and `clightgen`) binaries in the source tree.

## 5. Verify the binary

Smoke-test the resulting compiler before declaring success:

```
./ccomp --version
```

Optionally compile and run a minimal "hello, world" C program to confirm end-to-end behavior.

## Troubleshooting

- **`menhir: command not found`** — install Menhir via the package manager (`apt-get install menhir`) or via `opam install menhir`.
- **OCaml version too old** — CompCert requires a recent OCaml; if the system OCaml is too old, use `opam` to install a newer switch and re-run `./configure`.
- **`coq-compcert` not needed** — only required when building from the Git repository with proofs; release tarballs ship pre-extracted `.vo` files.

## Notes

- The procedure is identical across CompCert versions on the same host; only the tarball URL and version number change.
- Build is fully local; no network access is required after the tarball is downloaded.
- Output stays inside the source tree unless you explicitly `make install`.