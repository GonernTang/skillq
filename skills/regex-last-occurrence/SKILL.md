---
name: regex-last-occurrence
description: Build regex patterns that capture the last occurrence of a target token on lines that also satisfy a contextual condition (e.g., extract the last date from each line that contains an IP address). Use for log parsing, structured-text extraction, and similar "last match with context guard" tasks.
---

# Matching the Last Occurrence on Context-Bearing Lines

## When to use

Reach for this pattern whenever a task asks you to extract the **last** occurrence of some token (a date, a path, a field value) from a line, **and** the line must also contain another required token (an IP address, a user id, an error code). Typical cases:

- "Extract the last date on each log line that also has an IPv4 address"
- "Get the last URL on each line containing 'ERROR'"
- "Find the last timestamp from lines tagged with a given severity"

## The regex recipe

Use the multiline flag (`m`) so `^` / `$` match line boundaries, and combine four ingredients in this order:

```
(?=.*\bCONTEXT\b)   positive lookahead: line MUST contain the context token
.*\b                greedy consume up through a word boundary
(TARGET)            capture group for the value you want
(?!.*\bTARGET\b)    negative lookahead: nothing identical may follow
```

Concrete skeleton:

```regex
/(?=.*\bCONTEXT\b).*\b(TARGET)(?!.*\bTARGET\b)/gm
```

Capturing group `1` holds the last occurrence of `TARGET` on every line that contains `CONTEXT`.

### Why the pieces work

- **Positive lookahead `(?=.*\bCONTEXT\b)`** — anchors "this line must contain CONTEXT" without consuming characters, so the engine can still scan to the last `TARGET`.
- **Greedy `.*\b`** — the engine, with backtracking, extends `.` to the right as far as it can while still leaving room for a `TARGET`. Combined with the closing negative lookahead, that resolves to the *last* `TARGET`.
- **Negative lookahead `(?!.*\bTARGET\b)`** — guarantees nothing identical follows on the same line, locking onto the rightmost match.
- **`\b` word boundaries** on both sides — prevents matching fragments of longer tokens (e.g., `12-34` should not match inside `ip12-34` style strings).

## Reusable validation subpatterns

These pair cleanly with the recipe:

- **YYYY-MM-DD** (with range-checked month and day):
  `(?:\d{4})-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b`
- **IPv4 octet** (0–255, no leading zeros):
  `(?:0|[1-9]\d?|1\d\d|2[0-4]\d|25[0-5])`
- **Full IPv4 address** (reuse four times, joined by `\.(?=...))` is not needed; just join with literal `.`):
  `(?:0|[1-9]\d?|1\d\d|2[0-4]\d|25[0-5])(?:\.(?:0|[1-9]\d?|1\d\d|2[0-4]\d|25[0-5])){3}\b`

## Worked example

Goal: on each log line that contains an IPv4 address, capture the **last** YYYY-MM-DD date.

```regex
/(?=.*\b(?:\d{1,3}\.){3}\d{1,3}\b).*\b((?:\d{4})-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))(?!.*\b\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b)/gm
```

(You may swap the loose `(?:\d{1,3}\.){3}\d{1,3}` for the strict octet pattern above when false positives are a concern.)

## Variations

- **First instead of last** — drop the trailing negative lookahead and use a *lazy* `.*?` before `(TARGET)` if no positive lookahead on CONTEXT is needed.
- **Nth from last** — chain N copies of `(?!.*\bTARGET\b)` *before* the capture, each preceded by a backreference-guarded consume. Simpler: split the line manually and pick by index.
- **Different delimiting unit** — replace `.*` with `[\s\S]*?` if you may want lazy (left-most) rather than right-most matching.
- **Multiline blocks instead of single lines** — combine the global flag `s` (dotall) with explicit record boundaries and drop the `m` flag.

## Pitfalls

- **Anchoring to whole lines is rarely needed and often wrong** — the lookaheads already constrain the match to one line.
- **Forgetting word boundaries** lets the target match inside longer tokens.
- **Overly strict octet validation** in CONTEXT can reject real addresses that include leading zeros in some logs; loosen the octet pattern when in doubt.
- **The negative lookahead can be expensive** on very long lines with many `TARGET` occurrences. Mitigate by capping input length or by splitting the line first.