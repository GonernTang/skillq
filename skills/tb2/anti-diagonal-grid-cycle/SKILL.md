---
name: anti-diagonal-grid-cycle
description: Transforms a 2D grid so each cell's value is determined by its anti-diagonal index (i+j) mod K, where K is the number of unique non-zero values in the input. Use for ARC-AGI and similar grid tasks where output patterns repeat along anti-diagonals.
---

# Anti-Diagonal Grid Cycle Transformation

## When to use

Apply this when an ARC-AGI (or similar grid) task shows non-zero values scattered across the input such that the output should extend / replicate those values along the anti-diagonals defined by `i + j`. The defining clue: cells on the same anti-diagonal share a single value, and that value cycles with period K as the diagonal index grows.

## Procedure

1. **Identify non-zero values.** Iterate the input grid and collect the set of unique non-zero values. Let its size be `K`. (If the grid is empty or has no non-zero values, the output is all zeros.)
2. **Build the cycle map.** For every non-zero cell at `(i, j)` with value `v`, set `cycle[(i + j) % K] = v`. If two non-zero cells on the same residue class disagree, prefer the value that appears on the anti-diagonal starting at row 0 (top row) — i.e., the first such observation in scan order wins.
3. **Fill the output.** For every cell `(i, j)` in the output:
   - Compute `idx = (i + j) % K`.
   - If `idx` is in the cycle map, write the mapped value; otherwise write `0`.
   - The output grid typically has the same shape as the input. If the task requires a larger canvas, keep the same `(i, j) % K` lookup; the cycle naturally tiles outward.
4. **Verify.** Sample a few anti-diagonals in the produced output and confirm every cell on a given diagonal holds the same value, and that values advance through the cycle in the expected order across consecutive diagonals.

## Generalizes

- Works for any grid shape (rectangular, square, tall, wide).
- Works for any `K` (K = 1 ⇒ fill entire grid with the single non-zero value).
- Works for inputs where non-zero cells don't fully populate the cycle — unmapped residues render as zero.

## Worked intuition

Think of the grid as a 2D torus that has been "unfolded" along anti-diagonals: cell `(i, j)` belongs to lane `(i + j) mod K`. Each lane carries one value, copied across every cell on that lane. The input's scattered non-zero cells are samples telling you which lane carries which value; the output fills every cell according to that assignment.

## Merging variant notes

When reconciling two solutions for the same task, prefer unifying around the dynamic `(i + j) % K` formulation rather than hard-coding tile dimensions or cell positions — it remains correct whether the test grid is smaller, larger, or rotated relative to the training grids. Keep construction fully vectorized (no Python-level loops over cells) so it scales.

## Pseudocode

```
non_zero = {v for row in grid for (v) if v != 0}
K = len(non_zero)
cycle = {}
for i, row in enumerate(grid):
    for j, v in enumerate(row):
        if v != 0:
            cycle.setdefault((i + j) % K, v)   # first observation wins
out = [[cycle.get((i + j) % K, 0) for j in range(W)] for i in range(H)]
```

## Common pitfalls

- **Forgetting to filter zeros** when computing K — zeros are the background and must not participate in the cycle.
- **Last-write-wins when two cells collide** on the same residue — pick a deterministic order (top-left scan) to stay reproducible.
- **Off-by-one on diagonal index** — using `i + j` (anti-diagonal) vs `i - j` (main diagonal). Confirm visually against one example before generalizing.
- **Assuming the output shape matches the input** when the task shows the output as a square tile — verify by reading the task statement; if sizes differ, the lookup still works, just over a larger `(i, j)` range.