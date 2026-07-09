---
name: optimize-sql-aggregates
description: Avoid correlated scalar subqueries in grouped SQL aggregations — replace with CTEs and window functions (ROW_NUMBER OVER PARTITION BY), delay auxiliary joins until after aggregation, verify output equivalence, and use EXPLAIN to compare plans before adding indexes on FK columns.
---

## Diagnostic checklist

Run these BEFORE committing to a query plan with grouped aggregates:

1. **Scan for correlated scalar subqueries** — does the query contain `WHERE x = (SELECT ... FROM ... WHERE outer.col = inner.col)` patterns? Each one re-executes per outer row and explodes row volume.
2. **Check join ordering** — are auxiliary/detail tables (e.g., names, descriptions, lookup dimensions) joined BEFORE aggregation? If yes, they multiply row counts before the GROUP BY prunes them.
3. **Identify ranking/filtering needs** — does the query need "top N per group" or "first match per key"? Window functions (ROW_NUMBER, RANK, FIRST_VALUE) compute this in a single pass; correlated subqueries cannot.
4. **Verify output equivalence up front** — before rewriting, snapshot row counts and a checksum/hash of the original result so the rewrite can be validated deterministically.

## Stop signal

**If** the query plan still shows correlated subquery execution (e.g., `EXPLAIN` reveals nested-loop re-evaluation, or row counts grow multiplicatively across joins), **STOP and refactor** to:

- Extract each correlated subquery into a CTE that computes its rank/filter once via `ROW_NUMBER() OVER (PARTITION BY <group_key> ORDER BY <criteria>)`, then filter to `rn = 1`.
- Move auxiliary-table JOINs to AFTER the aggregation step, so they operate on the already-reduced row set.
- Re-run `EXPLAIN QUERY PLAN` (or equivalent) and confirm: no nested-loop subquery nodes, lower total row counts, and identical output row set vs. the original.

Only after equivalence is confirmed should you consider adding explicit indexes on FK columns — and prefer to validate that the engine is NOT already auto-indexing them (don't pay write-amplification cost for redundant indexes).

## Anti-patterns this skill guards against

- ❌ Correlated scalar subquery for "best match per group" — forces per-row re-execution.
- ❌ Joining wide/dim tables before GROUP BY — inflates working set.
- ❌ Trusting output equivalence from "looks the same" — always compare row counts + a deterministic hash.
- ❌ Adding indexes as the first move — fix query shape first; redundant indexes cost writes and rarely fix a structural rewrite need.