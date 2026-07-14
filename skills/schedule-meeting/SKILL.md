---
name: schedule-meeting
description: Find a valid meeting slot across multiple attendees with hard availability constraints and existing calendar conflicts, then emit an ICS invitation. Use when given several attendee ICS calendars, a duration, a date range, and need to produce a single bookable time that respects per-person working hours, recurring blocked periods (lunch, early-leave days), existing bookings, and any soft preferences.
---

# Schedule a constrained multi-attendee meeting

Given N attendee ICS calendars, a target date range, a meeting duration (typically 1 hour), and per-person constraints, find the earliest valid start time and produce a single ICS VEVENT that every attendee can accept.

## Inputs you need to collect or be given

- **Attendee list** — name, email (for mailto URI), attached ICS calendar file.
- **Meeting summary / purpose** — used as `SUMMARY` in the output VEVENT.
- **Target date range** — earliest and latest dates to consider.
- **Meeting duration** — usually 1 hour, sometimes 30 min or 2 hours.
- **Per-attendee availability window** — earliest start, latest end on a working day (e.g., 10:00–16:30 local). Attendees are considered unavailable outside this window.
- **Recurring blocked periods per attendee** — e.g., "lunch 12:30–13:30 every weekday", "early leave on Fridays" (any Friday after a time is blocked), full-day or multi-day blocks.
- **Day-of-week availability** — which weekdays each attendee works (default Mon–Fri).
- **Soft preferences** — non-hard tiebreakers (e.g., avoid Mondays for some attendees when multiple valid slots exist).

## Procedure

### 1. Parse each attendee's ICS into a busy-time list

Read every `VEVENT` block. Extract `DTSTART` / `DTEND` (handle both UTC `Z`-suffixed values and floating `TZID=` values by converting to a consistent timezone — usually the organizer's local zone). Store as `[start, end]` intervals. Include recurring events if `RRULE` is present by expanding over the date range.

Ignore non-VEVENT blocks (`VTIMEZONE`, `VCALENDAR` wrapper, etc.).

### 2. Build the per-attendee constraint model

For each attendee, combine:

- A daily window (start-of-day, end-of-day) on each working weekday.
- All recurring blocked periods that apply unconditionally.
- A set of explicit busy intervals from step 1.

The slot is **valid** iff it is fully inside the daily window AND does not overlap any blocked period AND does not overlap any busy interval, for every attendee.

### 3. Enumerate candidate slots

Iterate day by day from the range start to end. For each candidate day that is a working day for **all** attendees:

- Walk the day in fine-grained steps (e.g., 5- or 15-minute increments).
- For each step, check whether a slot of the required duration beginning at that step is valid for every attendee.
- Collect all valid (date, start_time) tuples.

If two attendees are in different timezones, express all candidate slots in a single consistent reference timezone (usually the organizer's) before comparing.

### 4. Apply soft preferences as tiebreakers

Among all valid slots:

- Prefer the **earliest** start by default.
- Apply any soft preferences (e.g., "avoid Monday", "prefer afternoon") as lexicographic tiebreakers — earliest day-of-week preference wins, then earliest time.
- Only relax a hard constraint if the user explicitly allows it; soft preferences never override a hard "available" check.

### 5. Emit the ICS VEVENT

Once the slot is chosen, produce a single `VEVENT` with:

```
BEGIN:VEVENT
UID:<uniqueid@example.com>
DTSTAMP:<now in UTC, YYYYMMDDTHHMMSSZ>
DTSTART:<chosen slot start in UTC, YYYYMMDDTHHMMSSZ>
DTEND:<chosen slot + duration in UTC>
SUMMARY:<meeting summary>
ATTENDEE;CN="Name";RSVP=TRUE:mailto:email@example.com
  (one ATTENDEE line per attendee, with CN and mailto)
END:VEVENT
```

Wrap it with the standard `VCALENDAR` / `PRODID` / `VERSION:2.0` envelope so the file is directly importable. Convert chosen local times to UTC with the appropriate offset (account for DST on the chosen date).

## Verification checklist before output

- [ ] Every attendee's busy intervals were parsed from their ICS.
- [ ] The chosen slot falls inside every attendee's daily window on a working weekday for each.
- [ ] The slot does not overlap any attendee's busy interval or blocked period.
- [ ] If preferences were specified, the slot is the earliest candidate satisfying them.
- [ ] `DTSTART` and `DTEND` are emitted in UTC with trailing `Z`.
- [ ] Every attendee appears as an `ATTENDEE` line with `CN=` and `mailto:`.
- [ ] `UID` is globally unique; `DTSTAMP` reflects the generation moment.