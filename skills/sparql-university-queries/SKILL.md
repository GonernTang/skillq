---
name: sparql-university-queries
description: Build SPARQL queries on university knowledge graphs that filter by professor role (full professor vs. assistant/associate), EU country codes, and aggregation-based constraints (e.g. departments with >N currently enrolled students), then aggregate distinct values with GROUP_CONCAT.
---

# Building SPARQL Queries on University Knowledge Graphs

Use this skill when constructing SPARQL queries against a RDF/OWL
university ontology that ask for people (typically professors) along
with counts and country groupings subject to multiple constraints.

## When to apply

- The query must distinguish **full professors** from assistant /
  associate / emeritus / honorary titles stored as a literal role string.
- A constraint requires filtering by **EU member-state countries**.
- A constraint requires selecting departments (or similar units) that
  have **more than N currently enrolled students** at a given reference
  date.
- The final result must be aggregated by an entity (e.g. professor) and
  emit a **comma-separated list of distinct countries**.

## Step-by-step procedure

### 1. Identify full professors from a role string

Faculty roles are commonly stored as a single literal that combines
keywords. To isolate full professors:

```
FILTER(CONTAINS(LCASE(STR(?role)), "professor"))
FILTER(!CONTAINS(LCASE(STR(?role)), "assistant"))
FILTER(!CONTAINS(LCASE(STR(?role)), "associate"))
```

Guard rails:
- Apply `LCASE(...)` so matching is case-insensitive.
- Use `STR(...)` when the value comes from `rdfs:label` or a typed
  literal, so `CONTAINS` receives a plain string.
- Exclude every lower-ranked title present in the data (assistant,
  associate, adjunct, visiting, emeritus, honorary). Negating one is not
  enough — re-check the corpus and add every prefix you find.

### 2. Filter by EU countries using ISO 3166-1 alpha-2 codes

Build a literal list inside `FILTER(?x IN ( ... ))`:

```
FILTER(?country IN (
  "AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR",
  "DE","GR","HU","IE","IT","LV","LT","LU","MT","NL",
  "PL","PT","RO","SK","SI","ES","SE"
))
```

Guard rails:
- Use the **current** EU-27 list (post-2020, post-Brexit). Don't trust
  memory — verify against an authoritative source if the reference
  date is far from today.
- Compare against the predicate that actually carries the ISO code (it
  may be a country URI ending in the code, a `dbo:iso2Region` /
  similar property, or a string literal). If `?country` is a resource,
  convert to its label/code with `STRAFTER(STR(?country), "/")`.

### 3. Filter departments by current enrollment count

Wrap the count in a subquery and apply the threshold with `HAVING`:

```
{
  SELECT ?department (COUNT(DISTINCT ?student) AS ?n)
  WHERE {
    ?student a :Student ;
             :enrolledIn ?course ;
             :enrollmentDate ?enroll .
    ?course :offeredBy ?department .
    OPTIONAL { ?student :graduationDate ?grad . }
    FILTER(?enroll <= ?referenceDate)
    FILTER(!bound(?grad) || ?grad > ?referenceDate)
  }
  GROUP BY ?department
  HAVING(COUNT(DISTINCT ?student) > 10)
}
```

Guard rails:
- Reference dates are inclusive on the start side (`<=`) and exclusive
  on the end side (`>`), since a student who graduated *on* the
  reference date is no longer enrolled.
- Use `OPTIONAL` + `!bound(...)` for graduation date so students who
  haven't graduated still match.
- Count *currently* enrolled students, not historical totals — a naive
  `COUNT` over all enrollments double-counts re-enrollments.
- A subquery is required because `HAVING` cannot reference patterns
  outside its own `GROUP BY` block.

### 4. Link the main entity to a qualifying unit with `EXISTS`

When the main subject (the professor) must be related to *at least one*
qualifying unit, use `EXISTS` rather than a join — it keeps the outer
solution sequence flat:

```
FILTER(EXISTS {
  ?dept a :Department ;
        :worksFor ?professor .
  # ... department-qualifying subquery or pattern ...
})
```

Guard rails:
- `EXISTS` does not bind variables to the outer query; if you need the
  department URI in the outer query, use a regular pattern instead.
- Pair `EXISTS` with the subquery from step 3 when "at least one
  department with >N students" is the criterion.

### 5. Aggregate distinct values into one comma-separated cell

For output shapes like "Professor X (DE, FR, IT)", use:

```
GROUP_CONCAT(DISTINCT ?country; separator=", ")
```

Guard rails:
- `DISTINCT` is mandatory — without it, one country per work-affiliation
  row is emitted, inflating the list.
- The `separator` argument requires SPARQL 1.1; verify the endpoint
  (Apache Jena, Blazegraph, Virtuoso, GraphDB) supports it.
- Always `GROUP BY` the entity you are aggregating over (e.g. the
  professor URI and label) so each row corresponds to one person.

## Complete skeleton

```
PREFIX : <http://example.org/univ#>

SELECT ?professor ?name
       (GROUP_CONCAT(DISTINCT ?country; separator=", ") AS ?countries)
WHERE {
  ?professor a :Professor ;
             :name ?name ;
             :role ?role ;
             :worksIn ?dept .
  ?dept :country ?country .

  FILTER(CONTAINS(LCASE(STR(?role)), "professor"))
  FILTER(!CONTAINS(LCASE(STR(?role)), "assistant"))
  FILTER(!CONTAINS(LCASE(STR(?role)), "associate"))

  FILTER(?country IN (
    "AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR",
    "DE","GR","HU","IE","IT","LV","LT","LU","MT","NL",
    "PL","PT","RO","SK","SI","ES","SE"
  ))

  FILTER(EXISTS {
    ?dept :hasStudent ?student .
    ?student :enrollmentDate ?enroll .
    OPTIONAL { ?student :graduationDate ?grad . }
    FILTER(?enroll <= ?referenceDate)
    FILTER(!bound(?grad) || ?grad > ?referenceDate)
    { SELECT ?dept (COUNT(DISTINCT ?student) AS ?n)
      WHERE { ?student :enrollmentDate ?enroll ;
                        :enrolledIn/:offeredBy ?dept }
      GROUP BY ?dept
      HAVING(COUNT(DISTINCT ?student) > 10) }
  })
}
GROUP BY ?professor ?name
ORDER BY ?name
```

## Self-check before submitting

1. The role filter excludes every junior/honorary title present in the
   corpus, not just "assistant".
2. The EU list matches the reference date's membership (EU-27 since
   2020).
3. Date comparisons use `<=` for enrollment start and `>` for
   graduation end so graduation-on-reference-date excludes the student.
4. `HAVING` lives inside a subquery, not on the outer `SELECT`.
5. `GROUP_CONCAT` uses `DISTINCT` and the correct separator.
6. `EXISTS` is used only when the inner variable does not need to be
   bound in the outer query.