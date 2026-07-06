---
name: fix-ocaml-runtime
description: Diagnose and repair bugs in the OCaml runtime (GC, memory allocator, interpreter). Inspect HACKING/INSTALL docs, locate the suspicious runtime C file via git diff or mtime, reason about the failing algorithm (e.g. run-length compressed sweep), fix the logic, rebuild with the autotools flow, and run a basic testsuite to verify.
---

# Fix an OCaml runtime bug

Use this procedure when a bug surfaces inside the OCaml runtime itself (GC sweep/compact, freelist, major heap, minor heap, interpreter loops, signal handling) — i.e. code under `runtime/` rather than user-level OCaml libraries.

## 1. Orient yourself in the codebase

1. Read `HACKING.adoc` and `INSTALL.adoc` from the repo root. They describe the supported build entry points and any required configure flags.
2. Locate the runtime source directory (typically `runtime/`). The files you will care about most for memory-management bugs:
   - `memory.c` — page allocation, heap pools.
   - `freelist.c` — free-list / pool / huge-block bookkeeping.
   - `major_gc.c` — major heap, marking, sweeping, compaction triggers.
   - `minor_gc.c` — minor heap collections.
   - `compact.c` — compactor (final phase, runs after sweep when `compaction_trigger` fires).
   - `shared_heap.c` / `domain.c` — multicore domains.
3. Read `byterun/`-style symbols or `runtime/intern.c` only if the failure looks like an interpreter/interning bug; otherwise stay in the GC files.

## 2. Localise the regression

Prefer **git** to bisect, fall back to **mtime** when the tree is not a git checkout:

1. `git log --oneline -- runtime/<suspect>.c` to see recent commits.
2. `git diff HEAD~N -- runtime/<suspect>.c` (or `git log -p -- runtime/<suspect>.c | less`) to read the actual change.
3. If not a git repo, sort runtime files by modification time (`ls -lt runtime/`) and read the most-recently-changed files first.

The change that introduced the bug is almost always small and recent. Read it line by line before touching anything.

## 3. Reason about the algorithm, not just the symptom

For the common "major-heap sweep corrupted free space" class of bug:

- The major heap sweep walks live blocks and rebuilds the free pool from dead blocks. Many implementations encode free space as **run-length compressed**: one header per contiguous dead run, not one per block.
- Common mistakes to look for when a sweep corrupts the pool:
  - **Off-by-one** in the run-length calculation (subtract `Whsize_hd(hd)` vs `Whsize(wosize)` vs the size in *bytes*; mixing units is the #1 cause).
  - **State transitions** in the sweep loop that skip a case (e.g. handling `Not_infix` but not `Infix` continuation headers, or treating a `GC_end` mark as a real block).
  - **Pointer advancement** using the wrong stride after writing a pool header.
  - Forgetting to update a cursor (`pool_head`, `pool_cur`, `pool_tail`) after consuming from or appending to a pool.
- Reproduce the failure mode mentally by stepping the loop on a tiny heap of 2–3 blocks including one dead run. If the invariant ("pool total = sum of free sizes") doesn't hold at loop end, the bug is in the loop, not elsewhere.

For other GC bugs (minor collection, compaction, freelist refill) the same principle applies: identify the invariant the code is supposed to maintain, then prove it holds at every loop boundary.

## 4. Apply the fix

- Make the smallest possible change that restores the invariant.
- Preserve the existing code style: tab indentation, brace placement, comment density. Match surrounding code.
- Do not refactor unrelated code while you're there.
- If the fix is non-obvious, leave a short `//` comment explaining *why* the old code was wrong.

## 5. Rebuild

From the repo root, the canonical sequence is:

```
./configure
make -j$(nproc)            # or `make -j4` if you don't know nproc
```

If only the runtime changed, `make -C runtime` followed by a top-level `make` is faster, but a full rebuild is safer when in doubt.

## 6. Run the basic testsuite

```
make -C testsuite one DIR=tests/basic
```

- If a focused test exists for the failing feature (e.g. `tests/basic-or-not/heap.ml`), run that first — it's faster feedback.
- Watch for: assertion failures, segfaults, non-zero exit codes, and "skip" lines (those usually mean a prerequisite is missing, not that the fix is broken).
- For GC bugs specifically, `OCAMLRUNPARAM` flags like `v=0x400` (verbose GC) and `s=4096` (smaller heap to trigger collections sooner) accelerate repro.

## 7. Verify and report

1. State plainly that the fix is verified by the basic testsuite, naming the run command.
2. If tests fail, quote the failing assertion and the file:line it points at — don't summarise.
3. If a step was skipped (e.g. no git history available, fell back to mtime), say so.

## Common pitfalls

- Editing `byterun/`-symlinked copies instead of the real sources under `runtime/` — both can exist; confirm with `readlink -f`.
- Mixing `Wosize_hd` / `Whsize_hd` / `Bsize_hd` — these are different units (words vs blocks vs bytes).
- Forgetting to rerun `./configure` after editing `configure.ac` or `Makefile` templates.
- Assuming the testsuite is "passing" when only some test groups ran; check the summary line.