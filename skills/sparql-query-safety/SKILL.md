---
name: sparql-query-safety
description: Guard-rail for SPARQL query construction — enforce GROUP BY/aggregate pairing, temporal validity predicates, multi-hop join continuity, and precise filter expressions before submitting a query.
---

# SPARQL Query Safety

When constructing SPARQL queries (especially those using aggregates, temporal joins, multi-hop chains, or role/status filters), four structural pitfalls silently corrupt results. This skill enforces a pre-submission review against those pitfalls.

## Diagnostic checklist

Before finalizing any SPARQL query, run these four checks. Every one is testable against the query text; fail any of them and the query is not ready.

1. **Aggregate / GROUP BY pairing.**
   If the SELECT or HAVING clause uses `COUNT`, `SUM`, `GROUP_CONCAT`, `SAMPLE`, or any other aggregate, verify that every projected non-aggregate variable appears in a `GROUP BY` clause. A missing group variable produces one aggregated row (or a syntax error) instead of a per-entity row — the classic silent collapse.

2. **Temporal validity predicate.**
   For any "currently X as of reference date" filter, the predicate must be a conjunction of *both* bounds: `start ≤ ref_date` AND (`end IS NULL` OR `end > ref_date`). A bare `start ≤ ref_date` accepts already-ended rows; a bare `end > ref_date` rejects ongoing rows that have no end yet. Either half alone is wrong.

3. **Join-chain continuity.**
   For any chain of the form `A → B → C` (e.g. department → course → enrollment), every intermediate variable must appear in at least one triple pattern that connects it to both neighbours. Walk each intermediate variable: does it have a predicate linking it to its predecessor? And to its successor? A variable introduced with `?x a :Foo` but never re-bound downstream is a dead hop and silently drops results.

4. **Filter precision.**
   Filter predicates should match the data shape exactly: explicit IRI / enumeration values, regex with full pattern, or property paths. Prefer a precise role/value enumeration (`VALUES ?role { :Full :Associate }`) over a broad `CONTAINS(LCASE(?label), "full")` — substring matching on human-readable strings under-filters when role labels vary in form ("Full Professor" vs "Professor, Full").

## Stop signal

If any of the four checks above is unresolved — i.e. you cannot point to the specific clause in the query that satisfies it — **stop and reset**. Do not submit or report results. Reset by:

1. Re-listing the variables in the SELECT clause and tagging each one as `aggregate` or `group-by-var`; fix GROUP BY until coverage is exact.
2. Re-stating the temporal validity condition in plain English and re-writing the FILTER clause from that statement; do not edit incrementally — rewrite the whole conjunction.
3. Drawing the join graph (nodes for variables, edges for triple patterns) and confirming every intermediate node has degree ≥ 2 (except endpoints).
4. Replacing any `CONTAINS`/`REGEX` over free-text with explicit `VALUES` or a property-path over the role/type predicate.

Resume construction only when all four checks resolve to a concrete clause in the query.