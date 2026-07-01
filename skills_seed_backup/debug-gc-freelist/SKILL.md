---
name: debug-gc-freelist
description: Diagnose OCaml garbage-collector free-list corruption crashes — typically triggered after edits to the major heap's run-length-encoded free list, merge/split paths, or `runtime/major_gc.c` sweep/allocation. Use when `ocamlc.byte`/`ocamlopt` bootstrap crashes, when the failure points inside the GC sweep or allocator, or when asserts about freelist invariants start firing. The procedure: re-state invariants, audit merge/split code, instrument with temporary assertions, rebuild, run the basic testsuite, and bisect if needed.
---

# Debug OCaml GC Free-List Corruption

## When to use

- Bootstrap of the OCaml compiler crashes after a change to the major heap free list or any code under `runtime/` that touches the heap.
- Crash stack or failure message points into `major_gc.c` (sweep / allocate / commit) or into the freelist helpers.
- You have a regression whose `git bisect` lands on a free-list merge, split, allocate, or pool-commit change.
- Heap-corruption symptoms: segfault during allocation, "freelist corrupted", assertion failure inside the runtime.

## Procedure

1. **Locate the free-list data structures.** Read the relevant runtime files (`runtime/major_gc.c`, any free-list helper files, and the headers that define the per-pool free list). Identify the on-heap metadata: pool header, free-block header (size, `next`, `prev`), and any per-size-class counters or bumps.

2. **Write the invariants down on paper before reading code.** Examples:
   - Every free block is reachable from the pool's `freelist` head.
   - Adjacent free blocks are always merged into a single larger block — no two free blocks touch.
   - A free block's recorded size (in words) equals the distance to the next block's header.
   - `next->prev == self` and `prev->next == self` for every linked free block.
   - Per-size counters are non-negative and equal to the number of free blocks of that size class.

3. **Audit merge and split paths against the invariants.** For every place a block is inserted, removed, split, or merged:
   - Recompute size from the new boundaries — do not trust the previous size field.
   - Update `next`/`prev` links in the correct order (typically unlink-then-relink, or relink-then-unlink depending on local conventions).
   - Update per-size counters in the same path; never let a counter and the actual list diverge.
   Trace a tiny example by hand (allocate one block → free → allocate-from-freelist) before claiming the code is correct.

4. **Add temporary assertions at the boundaries that touched the crash.** Use `CAMLassert` (or plain `assert` guarded by `DEBUG`):
   - After each merge: assert the merged size equals the sum of the two parts and the new block is properly linked.
   - After each split: assert the residual block's size is correct and it has been inserted into the free list.
   - On entry to `sweep` and on each allocation: walk the free list once and check every invariant from step 2.
   - Keep these checks diagnostic — they exist to localize corruption, not to ship.

5. **Rebuild runtime and compiler, then validate.**
   ```
   make -C runtime
   make -C testsuite one DIR=tests/basic
   ```
   If the basic testsuite passes but a fresh bootstrap still crashes, rebuild with the assertions enabled and run the bootstrap — the first failing assertion names the violated invariant and the offending line.

6. **Bisect if the regression is not obviously in the changed function.** Bisect against the basic testsuite, or against a minimal bootstrap, to localize the offending commit. Once localized, repeat steps 3–5 on that commit's diff.

## Common pitfalls

- Updating a block's size but forgetting to update its neighbor's `prev` (or vice versa).
- Merging with the *next* free block on commit but forgetting to merge with the *previous* one (or the other way around).
- Trusting a block's stored size during a merge instead of recomputing it from the actual boundaries.
- Off-by-one on the block-header boundary (header inside vs. outside the user-visible block).
- Updating only one of: the list links, the size field, or the per-size counter — leaving the other two stale.
- Forgetting that a pool-commit or pool-grow may split or merge blocks across the boundary, not just within a single pool.

## Notes

- This skill is about the *diagnostic loop*: invariant → audit → assert → rebuild → test. Skip the assertions only if you can prove correctness by inspection, which is rarely safe with run-length-encoded structures.
- When the fix is in, decide explicitly for each added assertion whether to keep, gate behind `DEBUG`, or remove — do not leave debug asserts in production runtime code.