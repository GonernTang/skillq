---
name: compile-compcert
description: Build CompCert (formally verified C compiler) from source on Linux. Covers dependency installation, Coq compatibility patches, configure/make/install workflow, and verification.
---

# Build CompCert from Source

CompCert is a formally verified C compiler written in OCaml and Coq. This procedure builds it on a Linux x86_64 system from a release tarball.

## 1. Install build dependencies

On Debian/Ubuntu:

```bash
sudo apt update
sudo apt install -y ocaml ocamlbuild ocaml-findlib menhir gcc make wget \
                    coq libcoq-menhirlib-ocaml-dev
```

Required: OCaml, OCaml build tools (ocamlbuild, findlib), Menhir, Coq, menhirLib, GCC, GNU make, wget.

## 2. Download and extract source

Get a release tarball from the official repository (pin a known-good version for reproducibility):

```bash
wget https://github.com/AbsInt/CompCert/archive/refs/tags/v3.13.1.tar.gz
tar -xzf v3.13.1.tar.gz
cd CompCert-3.13.1
```

## 3. Apply Coq compatibility patch (Coq >= 8.18)

Newer Coq versions removed the `Z_div_mod_eq` lemma. In `flocq/Calc/Bracket.v`, replace it with the replacement:

```bash
sed -i 's/Z_div_mod_eq/Z_div_mod_eq_full/g' flocq/Calc/Bracket.v
```

Skip this step if using a CompCert release that already accounts for the newer Coq, or if `Z_div_mod_eq` is still present in your Coq.

## 4. Configure

Target x86_64 Linux, set an install prefix, and bypass strict Coq version matching:

```bash
./configure x86_64-linux -prefix /path/to/install -ignore-coq-version
```

Replace `/path/to/install` with the desired installation directory (e.g., `/usr/local` or a project-local path). The `-ignore-coq-version` flag allows the build to proceed even if Coq's version is newer than what the release was tested against.

## 5. Build

Compile the Coq proofs, extract OCaml code, and build the C runtime in parallel:

```bash
make -j$(nproc)
```

This step is the longest (Coq proof compilation dominates). Expect several minutes to over an hour depending on machine speed.

## 6. Install

Place the `ccomp` binary and supporting files in the prefix:

```bash
make install
```

The binary lands at `<prefix>/bin/ccomp`.

## 7. Make the binary reachable (optional)

If the install prefix is not on `PATH`, or a specific path is required:

```bash
ln -sf /path/to/install/bin/ccomp /desired/path/ccomp
```

## 8. Verify

Confirm the build works:

```bash
ccomp --version
echo 'int main(){return 0;}' > /tmp/t.c
ccomp -o /tmp/t /tmp/t.c && /tmp/t && echo OK
```

Both commands must succeed.

## Notes

- For other targets (AArch64, PowerPC, RISC-V), substitute the target triplet in `./configure` (e.g., `aarch64-linux`).
- If `menhir` is too old, install a newer one via opam or apt.
- Build errors mentioning missing `coq-menhirlib` indicate the `libcoq-menhirlib-ocaml-dev` package was skipped.
- Keep the source tree if you need to rebuild incrementally; `make clean` removes build artifacts but preserves extracted OCaml from Coq.