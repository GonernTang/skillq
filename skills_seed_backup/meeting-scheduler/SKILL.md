---
name: meeting-scheduler
description: Schedule a meeting across multiple participants given availability constraints and existing calendar conflicts. Use when the task requires parsing ICS calendars, applying per-participant hard constraints (time windows, lunch breaks, day-of-week restrictions, special rules), computing common free slots, and emitting an ICS output file.
---

# Meeting Scheduler Under Constraints

Use this procedure when you must find a meeting slot that satisfies every participant's hard constraints while avoiding their existing calendar events.

## Steps

1. **Parse inputs.** Identify each participant's ICS calendar file. Extract every existing event's start and end time. Note each participant's hard constraints:
   - Allowed time windows (e.g. 09:00–17:00)
   - Mandatory breaks (e.g. lunch 12:00–13:00)
   - Day-of-week restrictions (e.g. no Fridays)
   - Special rules (e.g. "leave early on Wednesdays", "no back-to-back after external travel")

2. **Build per-day free intervals.** For each participant and each day in the candidate range:
   - Start with the participant's allowed working window for that day.
   - Subtract lunch/break blocks.
   - Subtract every existing event block (clamp events to the working window).
   - Apply special rules (e.g. trim end-of-day for "leave early" days).

3. **Intersect across participants.** For each day, intersect every participant's free intervals to produce the common-available intervals. If the intersection is empty for a day, that day is infeasible.

4. **Score and order candidates.** Generate candidate slots of the required duration (default 1 hour) within each common-available interval. Apply any preference ordering the user stated (e.g. "avoid Mondays if possible", "prefer mornings", "earliest acceptable"). Keep preference rules soft — they break ties, never hard constraints.

5. **Select the slot.** Pick the earliest feasible slot that satisfies all hard constraints. If preferences were given, prefer a slot that matches them; otherwise just take the earliest.

6. **Emit the ICS output.** Write an ICS file containing the chosen meeting with:
   - `BEGIN:VEVENT` / `END:VEVENT`
   - `DTSTART` / `DTEND` in UTC or with `DTSTART;TZID=...`
   - `SUMMARY:<meeting title>`
   - `ATTENDEE;CN=...;RSVP=TRUE:mailto:<email>` for each participant
   - `UID`, `DTSTAMP`, `PRODID` headers required by RFC 5545

## Decision rules

- Treat hard constraints as non-negotiable. If no slot exists within the date range, report the gap rather than relaxing constraints silently.
- Treat preferences as tie-breakers only.
- When two days are equally preferred, choose the earlier calendar date.
- When two slots on the same day are equally preferred, choose the earlier start time.

## Verification

Before emitting:
- Confirm the chosen slot is inside every participant's working window.
- Confirm the chosen slot does not overlap any existing event for any participant.
- Confirm the slot length matches the requested meeting duration.
- Confirm the ICS file is well-formed (header `BEGIN:VCALENDAR` / `VERSION:2.0` / `PRODID:...` / `END:VCALENDAR`).