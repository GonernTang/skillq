---
name: query-optimize
description: >-
  Diagnose and fix slow database queries (SQL: Postgres, MySQL, SQLite, and
  similar engines). Use when a query is slow, a page/endpoint times out, the DB
  shows high CPU or I/O, an ORM emits N+1 queries, or someone asks to "speed up",
  "optimize", "add an index", or "read the query plan". Covers measuring,
  reading EXPLAIN plans, indexing, rewriting queries, and verifying the win.
---

# Query Optimize

Optimize slow database queries methodically: **measure → read the plan → form one hypothesis → change one thing → re-measure**. Never guess-and-add indexes.

## The iron rule: measure first

Do not optimize a query until you have a reproducible measurement of how slow it is and *why*. Optimizing by intuition wastes time and often makes things worse (extra indexes slow writes, "clever" rewrites break correctness).

1. **Confirm the query is actually the bottleneck.** Get the real SQL (from logs, `pg_stat_statements`, slow query log, or ORM logging). An endpoint may be slow because of N+1 round-trips, not one slow query — check the *count* of queries first.
2. **Reproduce with representative data.** A query is fast on 100 rows and fatal on 10M. Test against production-scale data or a realistic copy. Row counts and data distribution (cardinality, skew) drive the plan.
3. **Capture a baseline number** (wall-clock and/or plan cost) so you can prove the change helped.

## Step 1 — Read the execution plan

The plan is the ground truth. Get it *with real execution stats*, not just the estimate:

- **Postgres:** `EXPLAIN (ANALYZE, BUFFERS, VERBOSE) <query>;`
  - `ANALYZE` actually runs it and shows real timings/rows.
  - `BUFFERS` shows shared hits vs. reads (memory vs. disk).
  - Compare **estimated rows vs. actual rows** — a large gap means stale statistics (`ANALYZE <table>;`) or a bad estimate, which is the root of most bad plans.
- **MySQL:** `EXPLAIN ANALYZE <query>;` (8.0+) or `EXPLAIN FORMAT=JSON <query>;`.
- **SQLite:** `EXPLAIN QUERY PLAN <query>;`.

### What to look for (the usual culprits)

| Symptom in plan | Likely meaning | Typical fix |
|---|---|---|
| **Seq Scan / Full Table Scan** on a large table with a selective filter | No usable index for the `WHERE`/`JOIN` | Add an index on the filter/join column(s) |
| **Rows Removed by Filter** is huge | Reading many rows then throwing them away | Index the filter; make it sargable |
| **Nested Loop** over many outer rows | Join amplification; missing index on inner side | Index the inner join key; or force hash/merge join by fixing stats |
| Estimated rows ≫/≪ actual rows | Stale or missing statistics | `ANALYZE`; increase stats target |
| **Sort** / **Hash** spilling to disk (`external merge`, low `BUFFERS` hits) | Not enough `work_mem`; sorting large sets | Add index to avoid the sort, or raise `work_mem` for the session |
| Same table scanned once **per row** | N+1 from the app/ORM | Batch into one query (`IN`, join, or eager load) |

Read plans **bottom-up and inside-out**: the deepest/most-indented node runs first, and its output feeds the parent. Focus on the node with the largest `actual time` × `loops`, not the biggest cost estimate.

## Step 2 — Fix it (in rough order of leverage)

Apply **one change at a time** and re-run EXPLAIN ANALYZE after each.

### a. Add the right index

- Index columns used in `WHERE`, `JOIN ... ON`, `ORDER BY`, and `GROUP BY`.
- **Composite index column order matters:** equality columns first, then the range/sort column. For `WHERE a = ? AND b > ? ORDER BY c`, consider `(a, b, c)`. A composite `(a, b)` also serves queries filtering on `a` alone (leftmost-prefix rule) — so don't add a redundant single-column `(a)` index.
- **Covering index:** include the selected columns so the query is answered from the index alone (Postgres `INCLUDE (...)`, MySQL secondary index covering) — avoids the heap/table lookup.
- **Partial index** for a common filtered subset: `CREATE INDEX ... WHERE status = 'active';` — smaller and faster.
- **Expression index** when you filter on a function: `CREATE INDEX ... ON t (lower(email));` matching `WHERE lower(email) = ?`.
- Build big indexes without locking writes: Postgres `CREATE INDEX CONCURRENTLY`.

### b. Make predicates sargable (index-usable)

A predicate that wraps the column in a function or arithmetic usually can't use an index:

- `WHERE date_trunc('day', created_at) = ?` → rewrite as a range: `created_at >= ? AND created_at < ?`.
- `WHERE lower(email) = ?` → add an expression index, or store normalized.
- `WHERE col + 1 = ?` → `WHERE col = ? - 1`.
- Leading-wildcard `LIKE '%foo'` can't use a b-tree — use a trigram index (`pg_trgm`) or full-text search.
- Avoid implicit type casts (e.g. comparing a `varchar` column to an integer) — they silently disable index use.

### c. Rewrite the query

- **Kill N+1:** replace per-row queries with a single `JOIN` or `WHERE id IN (...)`; in ORMs use eager loading (`JOIN`/`prefetch`/`include`).
- **Select only needed columns** — `SELECT *` forces wide heap fetches and defeats covering indexes.
- **`EXISTS` vs `IN` vs `JOIN`:** prefer `EXISTS` for "is there at least one" semi-joins; it can short-circuit.
- **Filter before aggregating/joining** — push `WHERE` down; reduce the row set as early as possible.
- **Paginate with keyset (seek) pagination** instead of large `OFFSET`: `WHERE id > :last_id ORDER BY id LIMIT n`. `OFFSET 100000` still reads and discards 100k rows.
- **Batch writes** and use `COPY`/bulk insert instead of row-by-row.
- Replace correlated subqueries with joins or window functions when they run per-row.

### d. Fix the environment / stats

- Run `ANALYZE` (or `ANALYZE VERBOSE`) to refresh planner statistics after big data changes.
- `VACUUM` bloated tables (Postgres) — dead tuples slow scans.
- Raise `work_mem` (session-level) for queries that spill sorts/hashes to disk.
- Check for lock waits / blocking if slowness is intermittent (`pg_stat_activity`, `SHOW PROCESSLIST`).

## Step 3 — Verify and guard against regressions

1. Re-run `EXPLAIN ANALYZE` and confirm the plan changed the way you expected (scan → index scan, loops down, actual time down).
2. Compare against the **baseline number** — quantify the win (e.g. "220ms → 4ms").
3. **Verify correctness:** a rewrite must return the *same rows*. Diff results against the original query, especially around `NULL`s, duplicates (`DISTINCT`), and join fan-out.
4. **Weigh the write cost:** every index slows `INSERT`/`UPDATE`/`DELETE` and uses disk. Don't add an index that duplicates an existing prefix. Drop indexes you added while experimenting that didn't help.
5. Test at scale, not just on the dev row count.

## Guardrails

- **One change, one measurement.** Batching changes hides which one mattered (or hurt).
- **Never add an index blindly.** Justify each with a plan that shows it being used.
- **`EXPLAIN` alone (no `ANALYZE`) only shows estimates** — necessary when you can't run the query (writes, huge cost), but confirm with real execution when you can. Don't `ANALYZE` a destructive query outside a rolled-back transaction.
- **Correctness beats speed.** A fast query returning wrong rows is a bug, not an optimization.
- **Don't tune server-wide config to fix one query** without understanding the blast radius; prefer session-level or targeted fixes.

## Quick checklist

- [ ] Got the real SQL and confirmed it's the bottleneck (not N+1 count)
- [ ] Reproduced at representative scale; captured a baseline time
- [ ] Read `EXPLAIN (ANALYZE, BUFFERS)`; found the costliest node
- [ ] Checked estimated vs. actual rows (stats freshness)
- [ ] Made ONE change (index / sargable rewrite / query rewrite / stats)
- [ ] Re-ran the plan; confirmed the intended change and a real speedup
- [ ] Verified same results; considered write-path and disk cost