---
name: slot-allocator-sweep-fix
description: Diagnose and fix pointer-misalignment bugs in fixed-size slot allocator pool traversal (e.g., shared-heap sweep, compaction, finalisation, verification routines). When a block header in a slot pool may store a run-length count rather than the slot's true width, advancing the cursor by the header's size corrupts every subsequent block.
---

# Slot Allocator Pool Traversal — Misalignment Fix

## When to use

A GC or memory pool walks a fixed-size-slot region (a pool of identically-sized slots grouped together) and the cursor lands on the wrong boundary after processing a free block. Symptoms include: heap corruption far from the actual write, segfaults inside `verify_pool` / `pool_finalise`, crashes only under heavy allocation pressure, or strange "free block size" assertions that fire inconsistently.

## Root cause pattern

Pool-traversal functions that walk a slot-based heap often look like:

```c
hd = *(pool + ofs);          // block header at current offset
... do work on block ...
ofs += Whsize_hd(hd);        // ← BUG: advances by the header's *recorded* size
```

For an **occupied** block, `Whsize_hd(hd)` equals the slot width — the walk is correct. For a **free** block, the header field may be reused as a **run-length** count (RLE-style: encode "N consecutive free slots" in one header) that is unrelated to the slot width. Advancing by it jumps an arbitrary number of slots ahead, misaligning every subsequent pointer read.

## Fix procedure

1. **Identify the slot width.** Find the constant or lookup that gives the slot's actual width for this pool. Common forms:
   - `wh` / `wsize_sizeclass[sz]` — the per-class slot width
   - `POOL_SLOT_WOSIZE` — the global per-pool slot width when the pool is homogeneous

2. **Replace the advancement expression** in the buggy traversal so the cursor always moves by the slot width, not the header's recorded size:
   ```c
   ofs += wh;                 // or: wsize_sizeclass[sz]
   ```
   Do **not** use `Whsize_hd(hd)` for advancement in any pool-walk loop.

3. **Audit every other pool-traversal function** in the same module. The same bug almost always exists in siblings — fix them in one pass:
   - `pool_sweep` / `sweep_slice` (the function that triggered the symptom)
   - `calc_pool_stats`
   - `verify_pool` (this is where the corruption usually *surfaces* as an assertion)
   - `pool_finalise`
   - `compact_update_pools`
   - Any other function whose loop body reads `p[ofs]` then increments `ofs` by `Whsize_hd(...)`

   For each, replace the increment with the slot-width constant.

4. **Reason about free-list linkage.** Confirm that free-block *linkage* (next/prev pointers stored inside the block body) is still updated correctly when the header is repurposed — only the *advancement in the walk* should change, not how individual blocks are linked.

## Verification

1. **Clean rebuild.** Delete prior build artifacts for the compiler/runtime and rebuild from scratch — stale object files mask the fix.
   ```
   make clean && make -j
   ```

2. **Run the basic testsuite** as a smoke check that the allocator invariants hold under load:
   ```
   make -C testsuite one DIR=tests/basic
   ```

3. **Stress-test allocation-heavy paths** if a basic run passes but the original symptom was intermittent — programs that churn the heap (large list/array builds, `Gc.alot`) tend to expose residual misalignment.

4. **Inspect `verify_pool` output** after the fix: it should now walk every slot without tripping the "block at misaligned offset" assertion that originally surfaced the bug.

## Common pitfalls

- Fixing only the function that crashed. The bug pattern is structural; sibling traversals will corrupt data silently until they, too, misalign.
- Using `Wosize_hd(hd)` / `Whsize_hd(hd)` *inside* a per-block computation (legitimate — it describes the block being processed) but using it for `ofs += ...` (illegitimate — describes the wrong thing once the header is a run-length count).
- Forgetting to clean before rebuilding — old `.o` files can keep the broken code path alive.
- Assuming a passing basic-testsuite run proves the fix. The misalignment is data-dependent; targeted allocation-stress work is the real proof.