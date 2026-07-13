---
name: regex-log-pattern
description: Build a regex that captures the last occurrence of a target pattern from log lines, asserting co-occurrence with another pattern, using lookaheads, greedy quantifiers, word boundaries, and strict numeric ranges.
---

# Regex Pattern for Log Extraction with Co-occurrence Constraints

Use this procedure when you need to extract a value (e.g., an IP address or timestamp) from log lines where the target pattern may appear multiple times, must co-occur with another required pattern, and you want the **last** occurrence.

## Step 1 — Identify the constraint structure

A log-extraction regex of this shape has three roles:

1. **Guard pattern** — a marker that must be present on the line (e.g., a specific keyword or another structured value).
2. **Target pattern** — what you actually want to capture (e.g., an IPv4 address, a date).
3. **Co-occurrence requirement** — both the guard and target must appear somewhere on the same line.

## Step 2 — Anchor with positive lookaheads at line start

Use two positive lookaheads at `^` to assert both patterns exist without consuming characters:

```
^(?=.*<guard-pattern>)(?=.*<target-pattern>)
```

Order of the two lookaheads does not matter — both are zero-width assertions. Anchoring at `^` keeps the engine from re-scanning mid-line redundantly.

## Step 3 — Greedy prefix to reach the last occurrence

After the lookaheads, write `.*` (greedy by default) so it consumes as much of the line as possible. Then append the capturing group for the target. Because `.*` is greedy, the engine backtracks only enough to let the target pattern match — yielding the **last** occurrence on the line.

```
^(?=.*<guard>)(?=.*<target>).*<capture-group>
```

Wrap the capture group in `\b…\b` so adjacent alphanumeric characters do not produce a partial match (e.g., `192.168` inside `192.1681`).

## Step 4 — Strict numeric ranges via non-capturing alternation

When a numeric field must enforce exact valid values (reject leading zeros, enforce bounds), express each range as alternation inside a non-capturing group:

- **IPv4 octet (0–255, no leading zero):**
  `(?:0|[1-9]\d?|1\d{2}|2[0-4]\d|25[0-5])`
- **Month (01–12):**
  `(?:0[1-9]|1[0-2])`
- **Day (01–31):**
  `(?:0[1-9]|[12]\d|3[01])`

Combine with separators (e.g., `-` or `/`) to form dates or with `.` to form dotted-quad IPs.

## Step 5 — Assemble and verify

Concrete example — extract the last IPv4 address from lines that also contain a date, capturing only the IP:

```
^(?=.*\b(?:0[1-9]|[12]\d|3[01])[-/](?:0[1-9]|1[0-2])[-/]\d{2,4}\b)(?=.*\b(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\b).*\b((?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d))\b
```

Test against:
- A line with one IP and one date → match, group 1 = that IP.
- A line with multiple IPs and a date → match, group 1 = the **last** IP.
- A line with only IPs and no date → no match (lookahead fails).
- A line with leading-zero octets like `010` → no match (strict octet regex rejects).

## Checklist

- [ ] Both patterns asserted via `(?=.*…)` at `^`.
- [ ] `.*` is greedy and precedes the capture group so the last occurrence is selected.
- [ ] Numeric subfields use non-capturing alternation with explicit ranges; no `\d+` for bounded values.
- [ ] Word boundaries `\b` wrap the target so adjacent digits/word chars don't bleed in.
- [ ] The capture group only encloses the target value, not the guard.