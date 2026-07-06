---
name: sqlite-query-optimize
description: Step-by-step method for rewriting SQL queries (especially SQLite) that contain repeated correlated subqueries or multiple DISTINCT aggregations into window functions and CTEs, using EXPLAIN QUERY PLAN to guide the rewrite and equivalence testing to verify it.
---

# SQLite Query Optimization: Correlated Subqueries & DISTINCT Aggregations

## When to apply
A query is slow and its plan shows one or both of:
- Repeated correlated scans (the same subquery re-executed per outer row).
- Temp B-trees built for `DISTINCT` / `GROUP BY` over already-large joins.
- Top-N-per-group patterns expressed as `IN (SELECT ...)` or self-joins.

## Procedure

### 1. Diagnose with EXPLAIN QUERY PLAN
Run `EXPLAIN QUERY PLAN <query>` before any rewrite. Note:
- Where correlated loops appear (e.g. `SEARCH ... USING AUTOMATIC ...` repeated per outer row).
- Where temp B-trees are materialized (`USE TEMP B-TREE FOR ...`).
- Total estimated cost vs. a hand-computed lower bound (one full scan + one rank).

### 2. Classify the hotspots
- **Repeated correlated subquery** → candidate for a single window-function pass.
- **Top-N-per-group (e.g. pick one row per partition)** → candidate for `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)` then filter `WHERE rn = 1`.
- **Several `COUNT(DISTINCT col)` / aggregate columns over the same join** → candidate for one `GROUP BY` + one CTE.

### 3. Rewrite in this order
1. **CTEs for aggregations**: compute each aggregate column once in a `GROUP BY` CTE, not as correlated subqueries.
2. **Window function for top-N per group**:
   ```sql
   SELECT *, ROW_NUMBER() OVER (PARTITION BY group_key ORDER BY rank_col DESC) AS rn
   FROM base
   ```
   Then `WHERE rn = 1` in the outer query.
3. **Collapse multiple `COUNT(DISTINCT ...)`** into a single `GROUP BY` producing all needed counts side-by-side.
4. **Join the CTEs** on stable keys; avoid re-scanning the fact table more than once.

### 4. Verify equivalence rigorously
Output equivalence is *not* row-order equivalence. Verify:
- **Row count**: `SELECT COUNT(*) FROM original` vs rewritten must match exactly.
- **Sample values**: compare on at least 2–3 representative `LIMIT` slices (small `LIMIT`, large `LIMIT`, and an unfiltered `COUNT`).
- **Boundary cases**: empty partition, ties in the rank column, NULLs in partition keys.
- If row order matters to the caller, preserve it with `ORDER BY` or wrap in a final sort.

### 5. Re-measure
Re-run `EXPLAIN QUERY PLAN` on the rewrite. Confirm:
- The repeated correlated scan is gone (look for a single `SCAN`/`SEARCH` of the fact table).
- Temp B-trees for `DISTINCT` are eliminated or moved into a CTE that materializes once.
- Wall-clock / `sqlite_stat4`-estimated cost drops; if it does not, the rewrite has not removed work — reconsider.

## Anti-patterns
- **Swapping one correlated subquery for another** without changing the scan count.
- **Adding indexes as a substitute** when the structural problem is repeated work, not seeks.
- **Trusting `LIMIT` equivalence** — it hides aggregate drift; always check the unfiltered count.
- **Using `DISTINCT` in the outer SELECT** to paper over duplicated join rows instead of fixing the join key.

## Worked skeleton (top-N per group + multi-aggregate)
```sql
-- Aggregates once
WITH agg AS (
  SELECT key,
         COUNT(*)                                AS total_rows,
         COUNT(DISTINCT col_a)                   AS distinct_a,
         COUNT(DISTINCT col_b)                   AS distinct_b
  FROM fact
  GROUP BY key
),
-- Top row per group via window function
ranked AS (
  SELECT key, payload,
         ROW_NUMBER() OVER (PARTITION BY key ORDER BY score DESC) AS rn
  FROM fact
)
SELECT a.key, a.total_rows, a.distinct_a, a.distinct_b, r.payload
FROM agg a
LEFT JOIN ranked r ON r.key = a.key AND r.rn = 1;
```
Both `agg` and `ranked` scan `fact` once; the outer join is a hash/merge on `key`. Compare row-for-row against the original.