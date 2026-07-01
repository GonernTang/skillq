---
name: schedule-meeting
description: Schedule a group meeting from multiple participants' ICS calendars and availability constraints. Use when given several ICS calendar files together with per-participant availability windows, excluded days, breaks, post-meeting buffers, and soft preferences, and asked to find a slot that satisfies everyone and emit a meeting ICS file.
---

# Schedule a Meeting from ICS Calendars + Constraints

Given N participants, each with an ICS calendar file plus a set of availability constraints (preferred/allowed windows, excluded weekdays, breaks, buffers, soft preferences), find a meeting slot of a given duration that satisfies every hard constraint, then emit a valid ICS `VEVENT`.

## Procedure

### 1. Parse each ICS file
- Walk the calendar; for every `VEVENT` extract `DTSTART`, `DTEND` (or `DURATION`), `SUMMARY`, and any `ATTENDEE`.
- Convert all times to a single canonical timezone. If `TZID` is present with a `VTIMEZONE`, apply it; otherwise treat values as floating local times.
- Normalize to a comparable datetime representation while preserving the wall-clock time, since the slot grid is generated in local time.

### 2. Encode each participant's constraints
For every participant, build two predicates over candidate slots:
- **Hard predicate** (must all hold for the slot to be valid):
  - Allowed time windows (e.g. `09:00–12:00` ∪ `12:00–14:00`).
  - Excluded weekdays (e.g. "no Mondays").
  - Hard-busy intervals: lunch breaks, declared unavailable ranges.
  - Existing events extracted from the participant's ICS (no overlap with any VEVENT).
  - Buffer rules (e.g. require N free minutes *after* any meeting that ends at or after a threshold, or before the slot start).
- **Soft predicate** (preferences that only break ties):
  - Preferred time-of-day or weekday for this participant.
  - Keep hard and soft strictly separate — only the hard predicate may reject a slot.

### 3. Enumerate candidate slots
- Pick a date range (typically the next 7–14 weekdays from today).
- On each candidate date, walk the business day (commonly 09:00–18:00, Mon–Fri) in steps equal to the desired meeting duration (commonly 60 minutes), starting at the requested offset.
- Each candidate is a `(start_dt, end_dt)` pair. Iterate in deterministic sorted order by start time to keep results reproducible and easy to debug.

### 4. Filter by hard constraints
For every candidate slot, evaluate every participant's hard predicate:
- Slot start and end must lie inside one of the participant's allowed windows.
- Day of week must not be in the excluded set.
- The slot must not overlap any existing VEVENT from that participant's ICS.
- The slot must respect break intervals and post-meeting buffer rules.
- A slot is **valid** only when *all* participants accept it. Track which constraint blocked which slot so failures are diagnosable.

### 5. Rank by soft preferences
Among the valid slots:
- Score each slot by aggregating the participants' soft preferences (e.g. "avoid Mondays for participant X", "prefer mornings for participant Y").
- Pick the earliest valid slot; break ties by (a) the highest soft score, (b) deterministic ordering by start time.
- If no slot passes the hard filter, report the offending participant/constraint per the nearest candidates instead of silently failing.

### 6. Emit the ICS VEVENT
Build an ICS file with the required envelope:
- `BEGIN:VCALENDAR` / `VERSION:2.0` / `PRODID:-//...` / `END:VCALENDAR`.
- One `VEVENT` containing `UID` (stable), `DTSTAMP` (UTC generation time), `DTSTART`, `DTEND`, `SUMMARY` (the agreed meeting title), and an `ATTENDEE` line per participant formatted as `mailto:<address>`.
- Format datetimes as local floating times (`YYYYMMDDTHHMMSS`) unless a specific `TZID` is requested; otherwise include `TZID=...` and a matching `VTIMEZONE` block.

## Pitfalls
- Mixing local and zoned datetimes across participants will silently drop valid slots; pick one canonical frame before enumeration.
- Buffer rules are easy to double-count when applied both before a slot and after the preceding event. Apply them once, on the right side of the boundary.
- ICS line folding (lines longer than 75 octets wrapped with a leading space on the continuation) must be preserved by the parser, otherwise `ATTENDEE` and `DESCRIPTION` values get truncated.
- Candidate enumeration should always be sorted by `(date, start_time)`; unsorted grids surface plausible-but-non-optimal slots and make tie-breaks unstable.