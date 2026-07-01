---
name: log-severity-summary
description: Count log severity levels (ERROR/WARNING/INFO) per date range across a directory of log files whose filenames carry a YYYY-MM-DD date prefix, and emit a CSV summary. Use when a user asks for a periodic severity tally, a date-bucketed log overview, or a CSV/table of how many errors/warnings/info events occurred today, over the last N days, or month-to-date.
---

# Log Severity Summary Across Date Ranges

## When to use
The input is a directory of `.log` files where each filename begins with an ISO date prefix (`YYYY-MM-DD-...log` or `YYYY-MM-DD.log`). The user wants counts of severity levels (e.g. `ERROR`, `WARNING`, `INFO`) bucketed by date range (today, last 7 days inclusive, last 30 days inclusive, month-to-date, total), and wants the result as a CSV with header `period,severity,count`.

## Procedure

1. **List log files.** Enumerate every `.log` file in the target directory.

2. **Extract the file date.** For each filename, parse the leading `YYYY-MM-DD` (regex: `^(\d{4}-\d{2}-\d{2})`). Files whose names do not match this pattern are skipped (or counted under a `total` bucket only — see step 5).

3. **Define the reference date.** Pick today as the reference anchor (use the environment's "today", not file mtimes). From that anchor compute, **inclusive on both ends**, these periods:
   - `today` — the single day equal to the reference date.
   - `last_7_days` — the reference date and the six preceding days.
   - `last_30_days` — the reference date and the twenty-nine preceding days.
   - `month_to_date` — the first day of the reference date's calendar month through the reference date.
   - `total` — every matched file regardless of date.

4. **Scan for severities.** For every line of every file, run a case-insensitive regex that matches the full set of severity tokens you care about in one pass (e.g. `(?i)\b(ERROR|WARNING|INFO)\b`). Use the union so overlapping aliases are collapsed to one canonical label — decide the canonical set explicitly (typically `ERROR`, `WARNING`, `INFO`) and map any synonyms (`WARN` → `WARNING`, `ERR` → `ERROR`) before incrementing.

5. **Accumulate counts.** Maintain a nested map `{period: {severity: count}}`. For each file, determine which periods its date falls into and add that file's severity counts into each of those periods. Files without a parseable date only contribute to `total`. Always pre-seed every `(period, severity)` pair with zero so the CSV is complete.

6. **Emit CSV.** Write header `period,severity,count` then one row per `(period, severity)` combination in a stable order — usually: periods in chronological/range order (`today`, `last_7_days`, `last_30_days`, `month_to_date`, `total`), severities in fixed order (`ERROR`, `WARNING`, `INFO`).

## Key gotchas
- **Inclusive ranges.** "Last 7 days" means today plus the 6 prior days, not "the 7 days before today".
- **Filename date, not mtime.** Use the date embedded in the filename — that is the contract for this layout — so files copied/rotated later still attribute correctly.
- **Single-pass regex.** Matching each severity with its own `re.search` double-counts lines that contain multiple tokens; one alternation regex per line is correct.
- **Zero-fill the grid.** Always emit a row even when the count is `0`; downstream tooling (spreadsheets, charts) expects a complete matrix.
- **Stable row order.** Sort periods and severities explicitly; dict-iteration order alone is not a contract.

## Minimal Python skeleton
```python
import re, csv
from datetime import date, timedelta
from pathlib import Path

SEVERITIES = ["ERROR", "WARNING", "INFO"]
SYNONYMS = {"ERR": "ERROR", "WARN": "WARNING"}
LINE_RE = re.compile(r"\b(ERROR|WARNING|INFO|ERR|WARN)\b", re.IGNORECASE)

def canonical(token: str) -> str:
    return SYNONYMS.get(token.upper(), token.upper())

def period_for(d: date, today: date) -> list[str]:
    periods = ["total"]
    if d == today:
        periods.append("today")
    if today - timedelta(days=6) <= d <= today:
        periods.append("last_7_days")
    if today - timedelta(days=29) <= d <= today:
        periods.append("last_30_days")
    if d.year == today.year and d.month == today.month:
        periods.append("month_to_date")
    return periods

def summarize(log_dir: Path, today: date, out_csv: Path) -> None:
    counts: dict[str, dict[str, int]] = {
        p: {s: 0 for s in SEVERITIES}
        for p in ["today", "last_7_days", "last_30_days", "month_to_date", "total"]
    }
    for path in sorted(log_dir.glob("*.log")):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", path.name)
        d = date.fromisoformat(m.group(1)) if m else None
        for line in path.read_text(errors="ignore").splitlines():
            for tok in LINE_RE.findall(line):
                sev = canonical(tok)
                if sev not in SEVERITIES:
                    continue
                for p in (period_for(d, today) if d else ["total"]):
                    counts[p][sev] += 1

    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["period", "severity", "count"])
        for p in ["today", "last_7_days", "last_30_days", "month_to_date", "total"]:
            for s in SEVERITIES:
                w.writerow([p, s, counts[p][s]])
```