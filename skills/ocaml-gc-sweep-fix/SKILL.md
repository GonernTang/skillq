---
name: ocaml-gc-sweep-fix
description: Debug and fix OCaml runtime GC pool-sweeping pointer-advancement bugs in runtime/shared_heap.c. Apply when the major-heap sweep misaligns slot iteration, causing memory corruption, segfaults, or basic-testsuite failures after changes to pool_sweep or size-class iteration logic.
---

# Fixing OCaml GC pool-sweep pointer advancement

The OCaml major heap is divided into pools, each pool is split into fixed-size slots determined by the pool's size class (`wh` = words per slot). Sweeping iterates slot-by-slot using a single `p` pointer, and getting the stride wrong corrupts the heap.

## When to suspect this bug

- Crashes / segfaults during or shortly after a major GC cycle.
- Testsuite failures that look like memory corruption (bad header, bad magic, "heap overflow") rather than assertion logic errors.
- A recent edit touched `pool_sweep`, `pool_finalise`, or any loop that walks a pool with a `p = ...` / `p += ...` pattern.
- Failures appear only when objects of a particular size class are alive (suggests one class's stride is wrong).

## The rule

When walking a pool, advance `p` by the **slot width** `wh`, NOT by the block's own size `Whsize_hd(hd)`.

- `wh` is the fixed slot size for the pool's size class.
- `Whsize_hd(hd)` is the *current block's* size in words.
- Block headers are always aligned to slot boundaries, so blocks of size > 1 slot occupy multiple consecutive slots. A live single-slot block is exactly `wh` words; a free block spanning `n` slots spans `n * wh` words.

## Correct stride patterns

Inside the sweep loop, after processing block at `p` with header `hd`:

- **Live block** (single slot): `p += wh;`
- **Live block** spanning N slots: `p += wh * N;`  (compute N from the header, e.g. `Wosize_hd(hd) + 1` for the size-class' slot unit, or the equivalent size-class multiplier)
- **Free block** of size W words: `p += wh * (Wosize_hd(hd) + 1);`  — the `+1` accounts for the header word

The common mistake is writing `p += Whsize_hd(hd);` for a free block without the slot-width multiplier, which under-advances `p` and lands it on the middle of a slot.

## Verification checklist

1. Rebuild the runtime and compiler: `make -j$(nproc)`.
2. Run the basic testsuite: `make -C testsuite one DIR=tests/basic` (or `make -C testsuite all` for a broader sweep).
3. All basic tests must pass. Any failure of a test that allocates and triggers a major GC is a strong signal the stride is still wrong.
4. If only one size class is failing, audit *that* class's branch in the loop — other size classes are independent and may be correct.

## Audit procedure

1. Open the pool-sweep loop in `runtime/shared_heap.c`.
2. For each branch (live/free, per size class), confirm `p` advances by a multiple of `wh`.
3. Search for `Whsize_hd(hd)` usages inside the loop and verify each is multiplied by `wh` (or is computing the block's word count for a non-advance purpose like copying).
4. If the loop uses a switch on size class, check every `case` — a single missing `wh *` in one case causes size-class-specific corruption.