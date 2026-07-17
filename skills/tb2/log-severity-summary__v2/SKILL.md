---
name: log-severity-summary
description: Count severity-tagged log lines across predefined date ranges from date-prefixed log files. Use when given a directory of `YYYY-MM-DD_*.log` files and asked to produce a per-period/per-severity count report (e.g. today / last 7 days / last 30 days / month-to-date / total).
---

# Log severity summary across date ranges

Given a directory containing log files named `YYYY-MM-DD_*.log`, produce a CSV report counting occurrences of severity tags (`[ERROR]`, `[WARNING]`, `[INFO]`) across several predefined time windows relative to a reference date.

## Inputs (collect or confirm before running)

- **Log directory** — folder containing the date-prefixed `.log` files.
- **Reference date** — the "today" to anchor relative ranges. If the user does not specify, use the current date.
- **Severity tags** — default `ERROR`, `WARNING`, `INFO` written as `[ERROR]`, `[WARNING]`, `[INFO]`. Confirm if the user's logs use a different convention.
- **Output format** — CSV with header `period,severity,count`, one row per (period × severity) combination.

## Procedure

1. **List the files.** Glob for `YYYY-MM-DD_*.log` in the log directory. Sort for stable output.

2. **Extract the date from each filename.** Take the leading `YYYY-MM-DD` portion. Files that do not match the pattern are out of scope.

3. **Define date ranges as epoch-day boundaries (inclusive on both ends):**
   - `today` — the single epoch-day matching the reference date.
   - `last_7_days` — `[reference_date - 6 days, reference_date]` (7 days inclusive, "last 7" includes today).
   - `last_30_days` — `[reference_date - 29 days, reference_date]` (30 days inclusive).
   - `month_to_date` — `[first day of reference_date's month, reference_date]` (inclusive).
   - `total` — every file, no date filter.

   Convert each file's date to the same epoch-day representation before comparing.

4. **Bin each file into its applicable ranges.** A file belongs to every range whose inclusive bounds contain its date. Ranges are not mutually exclusive — `today` files are also in `last_7_days`, `last_30_days`, `month_to_date`, and `total`.

5. **Count severities per file.** For each file, count lines matching each severity tag exactly (include the brackets). Use a fixed-string/literal match, not a regex with character classes, so brackets don't get reinterpreted. A line containing multiple tags should be counted once per tag it carries.

6. **Aggregate per (range, severity).** Sum the per-file counts across every file that fell into that range.

7. **Emit the CSV.** Header `period,severity,count`, then one row per combination. Order: periods in the order listed above, severities in `ERROR`, `WARNING`, `INFO` order. Include rows with count `0` so the schema is uniform.

## Output

A single CSV file with rows like:

```
period,severity,count
today,ERROR,3
today,WARNING,5
today,INFO,12
last_7_days,ERROR,18
...
total,INFO,142
```

## Edge cases to handle

- **No files in a range** — still emit the rows with count `0`.
- **Files outside every relative range but inside `total`** — counted only in `total`.
- **Files with no matching severity tags** — contribute `0` to every severity, which is fine; do not skip them.
- **Future-dated files** (date > reference_date) — exclude from all relative ranges but include in `total`.
- **Malformed filenames** — skip and continue; do not crash the run.
- **Tag casing** — match the literal tag the user specifies; if uncertain, default to uppercase with brackets and confirm before running on large corpora.

## Quick sanity checks before delivering

- `total` counts are `≥` every other range's counts for the same severity.
- `today` counts are `≤` `last_7_days` counts `≤` `last_30_days` counts `≤` `total` counts.
- Sum of files included in `total` equals the number of matched filenames.