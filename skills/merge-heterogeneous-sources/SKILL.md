---
name: merge-heterogeneous-sources
description: Use when merging records from multiple heterogeneous data sources (JSON, CSV, Parquet, etc.) into a single unified dataset. Applies to data integration tasks where sources have different field names for the same concept, may conflict on values, and need a priority-based resolution. Covers alias-based field mapping, priority-ordered conflict resolution, normalization of dates and status fields, and emitting both a merged dataset and a conflict report.
---

# Merge Heterogeneous Data Sources

## When to use
- Two or more sources describe the same entities (e.g., customers, products, accounts) but use different field names, value formats, or both.
- You need a single merged dataset, not just concatenation.
- Sources may disagree on the same field for the same key, and you need a deterministic resolution rule plus an audit trail.

## Procedure

1. **Inventory sources and read into a uniform representation.**
   Load each source (JSON, CSV, Parquet, etc.) into a list of records. Preserve a `source_origin` field on every record (e.g., `"crm"`, `"billing"`, `"analytics"`) so provenance survives the merge.

2. **Build a field-alias mapping.**
   Define a dictionary mapping each unified field name to the list of source field names that may carry it.
   ```
   {
     "customer_id": ["id", "customerId", "cust_id"],
     "email":       ["email", "email_address", "contact_email"],
     "status":      ["status", "state", "account_state"],
     "created_at":  ["created", "created_at", "signup_date"],
     ...
   }
   ```
   Treat a source field as missing if it is absent, null, or an empty string.

3. **Assign a source priority order.**
   Decide an ordered list of sources (highest priority first). Document the rationale (e.g., "CRM is authoritative for identity; billing wins for monetary fields"). The order must be total; tie-break deterministically if needed.

4. **For each unique key, perform priority-based conflict resolution.**
   - For each unified field, iterate sources in priority order.
   - Take the first non-null, non-empty value.
   - Do not silently drop later values — record them.

5. **Maintain a conflict log.**
   For every field where two or more sources provided distinct non-null values, append an entry:
   ```
   {
     "key": "<unified key>",
     "field": "<unified field>",
     "values_by_source": { "crm": "...", "billing": "..." },
     "selected_source": "<highest-priority source with a value>",
     "selected_value": "..."
   }
   ```
   Records where all sources agree (or only one source has the value) need not be logged.

6. **Normalize values as you merge.**
   - **Dates:** parse to a single canonical format (e.g., `YYYY-MM-DD`). Reject or quarantine unparseable values.
   - **Status / boolean-like fields:** collapse variants to a small fixed vocabulary (e.g., `"active" | "inactive" | "unknown"`). Define the mapping explicitly.
   - **IDs:** strip whitespace; preserve case unless a known case-folding rule exists.
   - Apply normalization *after* selecting the winning value, so all sources are compared on raw input.

7. **Emit two artifacts.**
   - The merged dataset in the required output format (commonly Parquet or CSV), one row per unique key, columns = unified fields.
   - The conflict report as JSON, structured for programmatic review and human inspection.

8. **Handle optional / sparse columns.**
   A source may omit a column entirely. Treat that as "no value" for every record in that source; do not error. The merged schema is the union of all unified fields that have at least one value across all sources.

## Guard rails
- Never let a null/empty value beat a real value just because its source has higher priority.
- Never overwrite the conflict log on re-runs unless explicitly told to.
- If a key exists in only one source, still emit the row — partial coverage is normal.
- If *all* sources disagree on a field for a key, pick by priority but flag it; do not fail.
- Validate that at least one source was actually read before emitting output.

## Output contract
- Merged dataset: one record per unique key, schema = union of unified fields with values.
- Conflict report: array of conflict entries as defined in step 5; empty array if no conflicts.
- Both artifacts written to disk; paths returned to the caller.