---
name: sql-query-optimization
description: Optimize SQL queries by rewriting correlated subqueries with CTEs and window functions. Use when a query contains per-row re-execution patterns, nested ORDER BY ... LIMIT 1 top-N-per-group subqueries, or performance issues traceable to repeated scan/aggregate work.
---

## When to Apply
- A SQL query contains correlated subqueries that re-execute per outer row.
- A query uses nested `ORDER BY col LIMIT 1` patterns (top-1 per group).
- Performance issue traces to repeated scan/aggregate work in the plan.
- You need to preserve identical output while reducing runtime.

## Procedure

1. **Analyze the query.**
   - Identify subqueries that reference outer-query columns (correlated).
   - Identify subqueries that re-execute per outer row (those in SELECT/WHERE).
   - Identify nested `ORDER BY ... LIMIT 1` patterns (top-1-per-group).

2. **Plan the rewrite.**
   - Replace correlated subqueries with CTEs that precompute the aggregate once.
   - Replace nested `ORDER BY ... LIMIT 1` with `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)` and filter `rn = 1`.
   - Restrict CTEs to the filtered row set (JOIN with the WHERE-filtered table) so aggregates are computed only over matching rows.

3. **Write the optimized query.**
   - Emit a single statement built from WITH clauses (CTEs) + a final SELECT.
   - No comments, semicolon-terminated, dialect-matching (e.g., SQLite-compatible if that is the target).

4. **Verify correctness.**
   - Run the original query against the real data; capture output.
   - Run the optimized query against the same data; capture output.
   - `diff` the two outputs — they must be identical (consider sorting/hash-stabilizing if order is allowed to drift).

5. **Benchmark.**
   - Time both queries on representative data.
   - Confirm the optimized version is faster (often orders of magnitude for correlated subqueries).

## Key Patterns

**Correlated aggregation → CTE**
```sql
-- Before: subquery re-executes per outer row
SELECT t1.*, (SELECT SUM(x) FROM t2 WHERE t2.id = t1.id) AS s FROM t1;

-- After: precompute once, join
WITH agg AS (SELECT id, SUM(x) AS s FROM t2 GROUP BY id)
SELECT t1.*, agg.s FROM t1 LEFT JOIN agg ON agg.id = t1.id;
```

**Top-1-per-group → ROW_NUMBER**
```sql
-- Before: nested ORDER BY ... LIMIT 1
SELECT * FROM t t1 WHERE id = (SELECT id FROM t t2 WHERE t2.grp = t1.grp ORDER BY val DESC LIMIT 1);

-- After: window function with rn = 1
WITH ranked AS (
  SELECT t.*, ROW_NUMBER() OVER (PARTITION BY grp ORDER BY val DESC) AS rn FROM t
)
SELECT * FROM ranked WHERE rn = 1;
```

**Restrict CTE to filtered set**
```sql
-- Pre-aggregate only over rows that match the outer filter
WITH filtered AS (SELECT * FROM big WHERE flag = 1),
     agg AS (SELECT id, SUM(x) AS s FROM filtered GROUP BY id)
SELECT filtered.*, agg.s FROM filtered LEFT JOIN agg USING (id);
```

## Output Format
Produce a single SQL statement (CTEs + final SELECT) that:
- Matches the target dialect (e.g., SQLite: single statement, no comments, ends with `;`).
- Preserves every column and row of the original output.
- Returns rows in an order consistent with the original (or sort both sides before diff if order is flexible).

## Definition of Done
- Optimized query runs in the target dialect without syntax errors.
- Output is byte-identical (or row-set identical after stable sort) to the original.
- Runtime on real data is measurably lower than the original.