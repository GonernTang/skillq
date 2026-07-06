---
name: regex-conditional-match
description: Construct a regex that matches a target pattern only on lines that contain a required companion pattern (e.g., dates only on lines with an IPv4 address), including matching the LAST occurrence. Use lookaheads, word boundaries, validated date / IP components, and edge-case tests.
---

# Procedure: regex-conditional-match

When you need a regex that conditionally matches a pattern only when the surrounding text also contains another pattern (a classic log-parsing / data-extraction problem).

## 1. Identify the two patterns

Separate the requirements clearly:

- **Companion pattern** (must be present somewhere on the line): e.g., an IPv4 address.
- **Target pattern** (what you actually want to extract): e.g., a date.

Decide whether you want ALL occurrences of the target or only the LAST one.

## 2. Anchor with a positive lookahead at line start

To require the companion pattern to be on the same line, prepend a lookahead that matches anywhere later in the line:

```python
pattern = r'^(?=.*<companion>).*?<target>'
```

Use `re.MULTILINE` so `^` matches each line start.

## 3. Capture only the LAST occurrence (optional)

To capture the last target pattern rather than the first, capture the target followed by a negative lookahead forbidding another occurrence:

```python
last_target = r'(<target>)(?!.*<target>)'
```

Combine with the companion assertion and use a capture group:

```python
pattern = r'^(?=.*<companion>).*?(<target>)(?!.*<target>)'
```

## 4. Use `\b` word boundaries around every pattern

Without boundaries, `abc192.168.1.1` matches as an "IP", and `1134-12-1234` matches as a "date". Wrap each pattern with `\b...\b`.

## 5. Validate numeric components (octets, day counts)

**IPv4 octet (0–255, no leading zeros):**

```python
octet = r'0|[1-9]\d?|1\d\d|2[0-4]\d|25[0-5]'
ipv4 = r'\b(?:' + octet + r'\.){3}' + octet + r'\b'
```

**Date validation by enumerating months and allowed day ranges:**

- 31-day months: `01, 03, 05, 07, 08, 10, 12`
- 30-day months: `04, 06, 09, 11`
- February: `01-29` (or stricter `01-28` if you do not want to allow leap years)

```python
date = (
    r'\b(?:'
    r'(?:(?:0[13578]|1[02])-(?:0[1-9]|[12]\d|3[01]))'  # 31-day
    r'|(?:(?:0[469]|11)-(?:0[1-9]|[12]\d|30))'           # 30-day
    r'|(?:02-(?:0[1-9]|1\d|2[0-8]))'                     # Feb (non-leap)
    r'|(?:02-29)'                                         # Feb 29 (leap, optional)
    r')-(?:\d{4})\b'
)
```

## 6. Always test against these edge cases

Before declaring the regex correct, run it against:

1. A line containing both the companion and one target — expect a match.
2. A line containing the companion but NO target — expect NO match.
3. A line containing the target but NO companion — expect NO match.
4. A line containing the companion and MULTIPLE targets — verify whether you wanted first or last.
5. Alphanumeric prefixes/suffixes glued to either pattern (e.g., `abc192.168.1.1`, `1134-12-1234`) — expect NO match (boundary check).
6. Invalid dates (Feb 30, Apr 31, month 13, day 00) — expect NO match.
7. Invalid octets (256, 999, leading-zero `010`) — expect NO match.

## 7. Assemble the final pattern

```python
import re

OCTET = r'0|[1-9]\d?|1\d\d|2[0-4]\d|25[0-5]'
IPV4 = rf'\b(?:{OCTET}\.){{3}}{OCTET}\b'

DATE = (
    r'\b(?:'
    r'(?:0[13578]|1[02])-(?:0[1-9]|[12]\d|3[01])'
    r'|(?:0[469]|11)-(?:0[1-9]|[12]\d|30)'
    r'|02-(?:0[1-9]|1\d|2[0-8])'
    r'|02-29'
    r')-\d{4}\b'
)

# Last date on lines containing an IPv4:
pattern = rf'^(?=.*?{IPV4}).*?({DATE})(?!.*?{DATE})'
text = "2024-03-15 server 10.0.0.1 boot 2024-04-20"
m = re.search(pattern, text, re.MULTILINE)
assert m and m.group(1) == "2024-04-20"
```

## Pitfalls to avoid

- Forgetting `\b` — false positives on alphanumeric attachments.
- Forgetting `re.MULTILINE` — `^` only matches the start of the whole string, not each line.
- Using `.*` greedily without the negative lookahead — captures the FIRST occurrence, not the last.
- Writing `25[0-5]` only — misses `200–249` (handled by `2[0-4]\d`) and `100–199` (handled by `1\d\d`).
- Trying to validate dates with a single `(0[1-9]|[12]\d|3[01])` for all months — lets Feb 30 and Apr 31 through.