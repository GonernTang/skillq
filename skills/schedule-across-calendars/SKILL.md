---
name: schedule-across-calendars
description: Find a meeting time that satisfies every participant's availability constraints and existing calendar events, then emit a valid ICS invite. Use for multi-attendee scheduling given ICS files plus rules like business hours, lunch breaks, "no meetings before 9am", or hard stop times.
---

# Schedule Across Calendars

Find the earliest meeting slot that fits all participants' free time and constraints, then produce a valid ICS invite. **Never modify the input ICS files** — read only.

## Procedure

1. **Parse each ICS.** Extract every `VEVENT`'s `DTSTART`/`DTEND` (busy blocks). Watch for timezones (`DTSTART;TZID=...` vs `...Z` UTC) and normalize everything to one timezone before comparing.

2. **Build each participant's daily availability.** Start from allowed working hours, then subtract:
   - Existing events from step 1.
   - Recurring blocks (lunch, standing breaks).
   - Hard rules ("no meetings before 9:00", "must leave by 16:30 Tue/Thu"). Apply day-of-week-specific rules per date.
   Represent availability as a set of free `[start, end)` intervals per day.

3. **Intersect across participants.** For each candidate day in the target range, compute the intersection of all participants' free intervals at **minute granularity**. The result is the time all attendees are simultaneously free.

4. **Find the slot.** Scan the intersected free intervals for the earliest contiguous block ≥ the requested duration (default 60 min). A slot is valid only if it fits fully inside every attendee's availability with no event conflict.

5. **Apply tiebreakers.** If a preference is stated (avoid Mondays, prefer afternoons, latest-possible, etc.), rank valid slots accordingly; otherwise pick the earliest.

6. **Emit the ICS.** Write a new `.ics` file — do not touch inputs.

## ICS output template

```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//YourOrg//Scheduler//EN
BEGIN:VEVENT
UID:<unique-id>@yourdomain
DTSTAMP:20260101T120000Z
DTSTART:20260101T150000Z
DTEND:20260101T160000Z
SUMMARY:<meeting title>
ATTENDEE:mailto:alice@example.com
ATTENDEE:mailto:bob@example.com
END:VEVENT
END:VCALENDAR
```

- Use UTC (`Z` suffix) for `DTSTART`/`DTEND`/`DTSTAMP` to avoid ambiguity.
- `UID` must be unique; one `ATTENDEE:mailto:` line per participant.
- `DTEND` = `DTSTART` + duration.

## Pitfalls

- **Timezone mismatches** are the top source of wrong answers — normalize before any interval math.
- **Boundary handling:** treat intervals as half-open `[start, end)` so a slot ending at 12:00 and lunch starting 12:00 don't falsely conflict.
- **Off-by-one on hard stops:** a 4:30pm departure means the meeting must *end* by 16:30, not start.
- **No valid slot:** report clearly which constraint(s) eliminated all candidates rather than emitting an invalid invite.
- Verify the chosen slot against each raw ICS one final time before writing output.