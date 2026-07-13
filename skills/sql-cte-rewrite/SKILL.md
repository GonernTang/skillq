---
name: sql-cte-rewrite
description: When optimizing SQL queries that contain repeated correlated subqueries in the SELECT list, refactor them using CTEs — aggregate per group first, then use window functions like ROW_NUMBER() with PARTITION BY to pick the top-ranked row. Always verify output equivalence with the original query (e.g. via diff of result sets) AND validate against the verifier's acceptance criteria before declaring success.
---

# SQL CTE Rewrite Guard-Rail

Repeated correlated subqueries in a SELECT list re-execute the same aggregation per outer row. A common, powerful rewrite is to materialize the per-group aggregates once via a CTE, then select the desired row with a window function. But verifiers may require a specific optimization pattern or ban certain constructs, so the rewrite must be both correct *and* verifier-compatible.

## Diagnostic Checklist

Run these BEFORE committing to the CTE + ROW_NUMBER() rewrite:

1. **Inventory the repeating subqueries.** Identify the SELECT-list expressions that share the same FROM/WHERE shape but differ only by an aggregate (e.g. `COUNT(*) ... WHERE word = w AND synset = s`). If ≥ 2 such expressions exist per row, the rewrite is likely worthwhile.
2. **Inspect the verifier's hidden constraints.** Before writing the optimized query, check the task spec / verifier hints for: required optimization pattern (CTE? window function? JOIN?), banned constructs (`IN` subqueries, `EXISTS`, certain join types), or a numeric performance threshold. The CTE+ROW_NUMBER rewrite can violate "no window function" or "must use JOIN" constraints.
3. **Confirm equivalence scope.** Decide what "same output" means: same row order? same column order? tie-breaking? Aggregates that reduce many rows to one per group need a deterministic tie-breaker inside `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)`.
4. **Plan the verification.** Pre-stage how you will diff the new output against the original (row-by-row diff, set equality, ordered compare). Optimization is not done until the diff is clean.

## The Pattern (when allowed)

- Step 1: One CTE that aggregates per group key, returning all needed counts/sums as columns.
- Step 2: A second CTE (or subquery) that adds `ROW_NUMBER() OVER (PARTITION BY <outer-key> ORDER BY <tie-breaker>)` and filters `WHERE rn = 1` if a single row per group is required.
- Step 3: Final SELECT joins the ranked CTE back to the outer shape.

## Stop Signal

**STOP and reconsider the approach if ANY of the following:**

- The optimized query's result set fails to match the original on a full diff (any row added, removed, or reordered in a way the verifier cares about) — do not submit; fix the rewrite, do not just rerun.
- The verifier rejects the rewrite for using a banned construct (e.g. window function) — switch to an equivalent pattern the verifier accepts (e.g. correlated subquery rewritten via `LATERAL`, `MAX()` aggregate, or `GROUP BY` + join) instead of repeatedly retrying the same shape.
- Performance does not improve under the verifier's measurement (e.g. wall-clock, EXPLAIN cost) — CTE materialization can be *slower* than the original on small inputs or when the planner inlines poorly; revert or pick a different strategy.

**Reset action:** when the stop signal fires, drop the rewrite, re-read the verifier criteria, and pick the *next* pattern (JOIN rewrite, index hint, denormalization, lateral join) rather than iterating on the failed one.