---
name: sparql-multi-condition-query
description: Write SPARQL queries with multi-condition filtering, aggregation thresholds, and entity membership lists (e.g., EU country lists). Use when querying Turtle/RDF data with role-based filtering, geographic grouping, and HAVING-style aggregation.
---

# SPARQL Multi-Condition Query Procedure

When tasked with writing a SPARQL query that combines several filters (role/title matching, geographic membership, aggregation thresholds across entities), follow this procedure.

## 1. Schema Discovery

Parse the Turtle/RDF data first to identify:
- **Classes** (e.g., `Person`, `Department`, `Country`, `Student`)
- **Object properties** (e.g., `worksIn`, `belongsTo`, `locatedInCountry`, `isEnrolledIn`)
- **Datatype properties** (e.g., `hasRole`, `hasName`, `hasEnrollmentDate`, `hasGraduationDate`)
- **Reference dates / thresholds** stated in the problem

Build a mental graph: `Person → worksIn → Department → locatedInCountry → Country`, and `Student → isEnrolledIn → Department`.

## 2. Decompose Conditions

Break the question into independent boolean predicates:
- **Title/role match**: `FILTER(CONTAINS(?role, "X") && !CONTAINS(?role, "Y"))` for "is but not is not" phrasing.
- **Set membership**: `FILTER(?code IN (..., ...))` for ISO codes, statuses, or enumerated categories.
- **Temporal window**: enrollment `≤` reference date AND (no graduation OR graduation `>` reference date). Use `BOUND(?grad) = false || ?grad > ?ref`.
- **Aggregation threshold**: requires a subquery with `GROUP BY` + `HAVING(COUNT(DISTINCT ...) > N)`.

## 3. Structure the Query

Use this skeleton:

```sparql
SELECT ?person ?name (GROUP_CONCAT(DISTINCT ?country; separator=", ") AS ?countries)
WHERE {
  # Main pattern: professor → department → country
  ?person a :Person ; :hasName ?name ; :hasRole ?role ; :worksIn ?dept .
  ?dept :locatedInCountry ?country .
  FILTER(CONTAINS(?role, "Professor") && !CONTAINS(?role, "Assistant"))
  FILTER(?country IN ("AT","BE","BG",...))

  # Subquery for department load threshold
  {
    SELECT ?dept (COUNT(DISTINCT ?student) AS ?cnt)
    WHERE {
      ?student a :Student ; :isEnrolledIn ?dept ;
               :hasEnrollmentDate ?enroll .
      OPTIONAL { ?student :hasGraduationDate ?grad . }
      FILTER(?enroll <= "REF_DATE"^^xsd:date)
      FILTER(!BOUND(?grad) || ?grad > "REF_DATE"^^xsd:date)
    }
    GROUP BY ?dept
    HAVING(COUNT(DISTINCT ?student) > N)
  }
}
GROUP BY ?person ?name ?cnt
```

## 4. Apply the Joins Correctly

- Join the busy-department subquery to the main pattern via `?dept` (the grouped variable).
- The `COUNT` subquery isolates the threshold logic so it isn't entangled with `GROUP_CONCAT`.
- Use `DISTINCT` in `GROUP_CONCAT` to avoid duplicate countries when a department spans multiple countries.
- If the subquery's aggregated value is needed in the outer query, bind it to a variable and `GROUP BY` it.

## 5. Verify by Manual Simulation

Before finalizing:
1. Pick 2–3 sample individuals by hand (one matching each branch: EU professor, non-EU professor, assistant).
2. Trace each through the FILTER chain and the subquery `HAVING` count.
3. Confirm the expected rows match the question's intent (e.g., "full professors in EU departments with >N students").

## 6. Common Pitfalls

- `COUNT(*)` vs `COUNT(DISTINCT ?student)`: students may have multiple enrollments; always `DISTINCT` for the headcount.
- Confusing temporal direction: "currently enrolled" means enrolled **and not yet graduated at the reference date**, not "graduated before reference".
- Forgetting to bind the threshold result (`?cnt`) before `GROUP_CONCAT` — non-grouped variables cause errors or silent drops.
- Membership list spelling: EU uses ISO alpha-2 (`GR` for Greece, not `EL`).