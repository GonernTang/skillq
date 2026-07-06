---
name: sql-correlated-rewrite
description: Step-by-step procedure for detecting correlated subqueries in SQL (especially top-N-per-group or per-group aggregate patterns) and rewriting them using CTEs combined with window functions (ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)). Includes EXPLAIN QUERY PLAN inspection, the CTE transformation, equivalence verification by diffing full result sets, and benchmarking before/after to quantify speedup.
---

# Rewrite Correlated Subqueries as CTE + Window Functions

## When to apply

Use this procedure when you encounter SQL that:
- Uses a **correlated subquery** (subquery references columns from an outer query), AND
- Computes a per-group result such as **top-N per group**, **ranked row per group**, or **per-group aggregate comparison** (e.g. "give me the latest order per customer", "the highest-scoring item per category", "rows where a value beats the group average").

Correlated subqueries force the inner query to re-execute for every outer row, producing nested-loop scans. Replacing them with a single pass + window function typically yields 100x-500x speedups.

## Procedure

### 1. Confirm the pattern

Scan the query for subqueries that reference outer-table columns. Symptom in plans: `EXPLAIN QUERY PLAN` shows repeated scans of the same table inside a loop, or many `SEARCH ... USING ...` entries per outer row.

### 2. Read the plan

Run `EXPLAIN QUERY PLAN <original_query>` and capture the output. Note:
- The order of table access
- Any nested-loop or "USING ... SUBQUERY" markers
- Estimated vs. actual row counts if available

This is your baseline.

### 3. Design the rewrite as a CTE pipeline

Decompose the original logic into staged CTEs:

**CTE 1 — source/aggregation:** Isolate whatever summary or filtered set feeds the per-group decision. This is the data each group needs once, not per-row.

**CTE 2 — ranking:** Apply `ROW_NUMBER() OVER (PARTITION BY <group_key> ORDER BY <ranking_columns> DESC) AS rn` over the rows you want ranked. Pick the `PARTITION BY` key from the original correlation column(s), and the `ORDER BY` key from the original subquery's comparison (e.g. `MAX`, `MIN`, or `LIMIT 1`).

**Final SELECT — join/filter:** Join the CTEs back to the base table (or each other) on the group key, then filter `WHERE rn = 1` (or whichever rank you need). Preserve every column the original selected, in the same order, with the same expressions.

### 4. Apply deterministic ordering for ties

If multiple rows in a group tie on the ranking column, add a tiebreaker to `ORDER BY` (e.g. a unique column like an id or timestamp) so `ROW_NUMBER` assigns a deterministic winner. Otherwise the rewrite may return a different row than the original for tied groups.

### 5. Verify output equivalence

Do not trust the rewrite without proof. Run both queries and diff the results:

1. Wrap each query so equivalent rows sort identically (e.g. add an explicit `ORDER BY` over the full output, or materialise results then sort).
2. Capture both result sets.
3. `diff` them, or compare row-by-row.
4. Only proceed if the diff is empty (or differences are documented and justified).

### 6. Benchmark

Measure wall-clock (or `EXPLAIN ANALYZE` total time) for both queries on representative data. Record:
- Original: ___ ms
- Rewritten: ___ ms
- Speedup factor: ___ x

Repeat the measurement (queries are subject to cache effects). Report the median or stable result.

### 7. Sanity-check the plan

Re-run `EXPLAIN QUERY PLAN` on the rewritten query. Confirm:
- No correlated subquery remains (no repeated scans of the same table).
- A single scan + window computation over each partition.
- Index usage looks reasonable (or that a supporting index would help if not).

## Shape of the transformation

Before:
```sql
SELECT t.*
FROM orders t
WHERE t.created_at = (
  SELECT MAX(created_at) FROM orders WHERE customer_id = t.customer_id
);
```

After:
```sql
WITH ranked AS (
  SELECT *,
         ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at DESC) AS rn
  FROM orders
)
SELECT * FROM ranked WHERE rn = 1;
```

(The original correlation — re-scanning per outer row — disappears; one window pass does the work.)

## Common pitfalls

- **Dropping columns.** The original SELECT list must survive the rewrite; use `SELECT *` from the ranked CTE only if every column needed.
- **NULL-handling differences.** `MAX` ignores NULLs in some dialects; `ROW_NUMBER ... ORDER BY col DESC` puts NULLs first. Match the original semantics.
- **Forgetting ties.** Without a unique tiebreaker, repeated runs of the rewritten query can return different rows for tied groups.
- **Skipping equivalence check.** "Looks right" is not "is right". Always diff full result sets before declaring victory.