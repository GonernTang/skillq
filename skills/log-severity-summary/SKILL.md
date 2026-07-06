---
name: log-severity-summary
description: Summarize log files by severity level across multiple date ranges. Use when asked to count ERROR/WARNING/INFO (or similar severity tokens) in dated log files and produce a CSV/table grouped by time period (today, last 7 days, last 30 days, month-to-date, all-time).
---

# Log Severity Summary Across Date Ranges

Produce a per-severity count table for a directory of dated log files, bucketed
into several predefined time periods relative to a reference date.

## When to use

- A directory contains many log files whose **filename encodes the date** of
  their contents (typical pattern: `YYYY-MM-DD_<source>.log` or
  `YYYY-MM-DDTHH-MM-SS_<source>.log`).
- The user wants counts of one or more severity tokens (e.g. `ERROR`,
  `WARNING`, `INFO`, `CRITICAL`, `DEBUG`) broken out by time period.
- Output is a flat table: `period,severity,count`.

## Inputs to confirm first

Before writing any code, settle these with the requester (or pick sensible
defaults and state them):

1. **Directory** of log files.
2. **Reference date** — usually "today". Make it explicit; never assume.
3. **Severity tokens** to count — exact strings, case-sensitive. The skill
   defaults to `ERROR`, `WARNING`, `INFO`; users may want `CRITICAL`, `DEBUG`,
   or domain-specific labels.
4. **Period definitions** (defaults below; configurable):
   - `today` — only the reference date
   - `last_7_days` — reference date and the 6 prior days (7-day window)
   - `last_30_days` — reference date and the 29 prior days (30-day window)
   - `month_to_date` — first day of the reference date's calendar month
     through the reference date (inclusive)
   - `total` — every file in the directory
5. **Output format** — CSV with header `period,severity,count` is the default;
   one row per (period, severity) pair, even when count is 0.

## Procedure

1. **List files** in the target directory and filter to the log naming
   convention in use. Don't assume the suffix; match by regex on the leading
   `YYYY-MM-DD` prefix.

2. **Define the period set** from the reference date. Examples in Python:

   ```python
   from datetime import date, timedelta

   today = reference_date                        # e.g. date(2026, 7, 1)
   p_today        = {today}
   p_7d           = {today - timedelta(days=i) for i in range(7)}
   p_30d          = {today - timedelta(days=i) for i in range(30)}
   p_mtd          = {date(today.year, today.month, 1) + timedelta(days=i)
                     for i in range((today - date(today.year, today.month, 1)).days + 1)}
   p_total        = None                         # sentinel: every file matches
   ```

   `p_total = None` is the cleanest way to express "no filter".

3. **Extract the date from each filename**, not from line timestamps. A file
   named `2026-06-15_app.log` represents 2026-06-15 regardless of what the
   in-line timestamps say. Split on the first separator (`_` or `T`), parse
   with `datetime.strptime(..., "%Y-%m-%d")`, skip on `ValueError`.

4. **Assign each file to periods.** Build a `dict[period -> set[date]]`
   (or a `set` of dates per period) and add the file's date to every period
   whose member set contains it. For `total`, add to a flat set that always
   includes the file.

5. **Read each file line-by-line**, matching the severity tokens with a
   regex of anchored whole tokens. Distinguish substring matches from word
   matches carefully:

   - `ERROR` and `INFO` appear as substrings of other tokens (`ERRORS`,
     `INFO_FOO`). A word-boundary regex prevents double counting:
     `r'\b(ERROR|WARNING|INFO)\b'`.
   - Case-sensitive matching is the default. If the logs mix cases, choose
     one strategy (usually case-insensitive) and apply it consistently.

6. **Aggregate counts** with a `defaultdict(int)` keyed by `(period,
   severity)`. For each matching line in a file dated `d`, increment
   `counts[(p, s)] += 1` for **every period p whose date set contains d**.
   This is the key generalization: one line contributes to *all* overlapping
   periods, not just one.

7. **Emit the output.** For each `period` in a fixed display order
   (`today`, `last_7_days`, `last_30_days`, `month_to_date`, `total`) and
   each severity in a fixed display order, write one row. Always emit a row
   even when the count is 0 — empty rows are signal, not noise.

   ```csv
   period,severity,count
   today,ERROR,3
   today,WARNING,12
   today,INFO,87
   last_7_days,ERROR,17
   ...
   ```

8. **Performance note.** For large directories, do the whole pass in a
   single Python invocation rather than shelling out per file. `pathlib`,
   `re.compile`, and `defaultdict` keep it well under a second for tens of
   thousands of files.

## Pre-flight checklist

- [ ] Reference date confirmed (and documented in the output).
- [ ] Severity tokens confirmed; the regex has `\b` boundaries on each side.
- [ ] Filename date pattern confirmed (one regex that matches the prefix).
- [ ] Period list matches what the requester asked for; `total` is included.
- [ ] Output includes all (period, severity) pairs, even count=0.
- [ ] The CSV header is exactly `period,severity,count`.

## Verification

After producing the CSV, sanity-check by:

1. Picking one file at random and computing its severity counts manually;
   the `today` row (or whichever single-day period applies) should match.
2. Confirming `today` counts ≤ `last_7_days` counts ≤ `last_30_days` counts
   ≤ `total` counts for each severity (monotonicity is a strong invariant).
3. Confirming `month_to_date` counts ≤ `last_30_days` counts (when both
   windows overlap on the reference date).