---
name: meeting-scheduler
description: |
  Schedule a meeting from multiple ICS calendars under hard availability
  constraints (per-participant working hours, lunch breaks, day-of-week
  restrictions). Use when the task combines VEVENT parsing (RFC 5545),
  intersection of free-busy intervals, preference-aware 1-hour slot
  selection, and ICS output with ATTENDEE + UID. Encodes the most common
  failure pattern as a guard rail: silently mixing ICS event times
  (often TZID-tagged or UTC) with business-hours constraints (often
  floating local) so the intersection is off by hours and looks plausible.
---

# Meeting from ICS + Constraints

## When to use
Multiple ICS calendar inputs (one per participant) plus a stated set of
hard constraints (earliest/latest, lunch, day limits) plus optional
preferences (e.g. "earliest slot"). Output must be a valid ICS event the
attendees can import.

## Procedure
1. **Parse each ICS.** For every VEVENT capture `DTSTART` and `DTEND`
   with their original timezone tag (`TZID=` parameter, `Z` suffix, or
   floating). Do not flatten to naive datetimes.
2. **Read the constraints as written.** Record earliest start, latest
   end, lunch breaks, day-of-week limits. Note the timezone each
   constraint is given in. If a constraint is `12:00-13:00` with no zone
   and the task names no zone, ASK once before guessing; if you must
   guess, assume the same zone as the ICS files and document it in the
  output.
3. **Normalize before any arithmetic.** Convert every VEVENT boundary
   AND every constraint boundary to one canonical timezone (UTC is
   safest) BEFORE subtracting or intersecting. This step is where
  scheduling tasks silently fail — see guard rail below.
4. **Per-participant availability windows.** For each participant,
   materialize their working hours per day as intervals in the canonical
   timezone, then subtract their existing events. Result: a set of free
   intervals per participant, per day.
5. **Intersect across participants, day by day.** The intersection of
   N sets of intervals is itself a set of non-overlapping intervals.
6. **Pick the slot.** Default to the earliest 1-hour interval in the
   intersection. Apply any explicit preference overrides (e.g.
   "afternoon preferred") only among ties, never before the
   intersection is non-empty.
7. **Emit ICS.** Round-trip the chosen slot back to the original ICS
   timezone (or the constraint's zone if that matches stated intent).
   Include `ATTENDEE;CN=...:mailto:` for each participant and a fresh
   `UID` (use a UUID, not a counter).

## Guard rail: timezone consistency
The recurring failure mode is *plausible-looking wrong output*: the
algorithm produces a free-busy intersection, returns a slot, and the slot
is at the wrong wall-clock time because steps 1+2 mixed zones silently.
Treat timezone normalization as a hard prerequisite, not an
optimization. Never subtract an `Asia/Tokyo` `DTSTART` from a "09:00
local" working-hour boundary without first projecting both to UTC (or
both to one named zone).

## Diagnostic checklist (run BEFORE committing to the slot)
1. **Round-trip one event.** Parse a single VEVENT with a non-UTC
   `TZID`, convert to canonical zone, convert back, and assert the
   wall-clock time matches. If the round-trip drifts, the parser or
   timezone library is misconfigured — fix before any intersection.
2. **Empty-day sanity.** For a participant with no events on a day,
   the free-interval set must equal the stated working-hour window
   exactly. If it is empty or shifted, your subtraction or your
   normalization is wrong.
3. **Negative intersection.** Pick a day where two participants have
   non-overlapping lunches (or one is unavailable the whole day). The
   intersection MUST be empty. If it is non-empty, your intersect or
   your window materialization is wrong.
4. **Constraint zone probe.** Take one constraint (e.g. "lunch
   12:00-13:00") and verify what timezone it is interpreted in by
   printing the canonical-zone boundaries it produces. If it produces
   something you did not expect, surface that to the user rather than
   quietly proceeding.

## Stop signal
- After **2 rewrites of the timezone-conversion code** with the same
  round-trip drift in diagnostic 1, stop patching. Print every
  datetime the parser produces with its original zone next to the
  canonical zone, then rewrite step 3 from scratch against that
  printed list rather than adding one more `astimezone()` layer.
- If **every day's intersection is empty** on inputs that should have
  at least one valid slot, the bug is almost certainly a shifted
  timezone in step 3, not a true "no solution". Do NOT emit a
  "no slot found" output and exit. Backtrack to step 3 first and
  re-verify before declaring no-solution.
- If you have produced **3 candidate slots** in different attempts and
  they all disagree by an integer-hour offset, the answer is a
  timezone shift — fix that once, do not retry the algorithm.