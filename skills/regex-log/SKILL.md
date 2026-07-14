---
name: regex-log
description: >-
  Build and apply regular expressions to search, filter, and extract structured
  fields from log files. Use when parsing application/server logs, pulling out
  timestamps, levels, IPs, IDs, or error messages, tailing/grepping logs, or
  turning noisy text logs into structured records. Triggers include "parse this
  log", "extract X from the log", "grep the logs for", "find errors in", or
  "why is regex not matching my log line".
---

# Regex for Logs

Turn unstructured log text into matches and extracted fields. This skill covers
building the pattern, choosing the right tool, and the pitfalls that make log
regexes silently fail.

## Workflow

1. **Get a real sample.** Never write the pattern from memory of the format.
   Read 5-20 actual lines first (`head`, `tail`, or Read). Logs mix formats,
   wrap lines, and interleave stack traces — the sample reveals this.
2. **Anchor on stable landmarks.** Identify the fixed parts of a line (brackets,
   log level words, ` - `, ISO timestamps) and match those literally. Let the
   variable parts be capture groups.
3. **Start broad, then tighten.** First confirm you match *any* target line,
   then add groups/constraints. Tightening a matching pattern is easier than
   debugging a zero-match one.
4. **Extract with named groups** when the tool supports them — self-documenting
   and order-independent.
5. **Verify on the full file**, then spot-check the misses (lines you expected
   to match but didn't) and false hits.

## Tool selection

| Need | Use | Why |
|------|-----|-----|
| Fast search across many files | `rg` (ripgrep) | PCRE2 with `-P`, fast, recursive |
| Search with basic patterns | `grep -E` | Everywhere; ERE avoids backslash noise |
| Extract one field per line | `rg -o -r '$1'` or `sed -E` | Print only the capture |
| Multi-field structured parse | Python `re` | Named groups, typing, aggregation |
| Column/field math on space-delimited logs | `awk` | Fields are free; regex per-field |

Prefer `rg -P` or `grep -P` when you need `\d`, `\b`, lookarounds, or non-greedy
`*?`. Plain `grep`/`grep -E` (BRE/ERE) does **not** support `\d` or lookarounds.

## Building-block patterns

Reusable fragments — compose, don't reinvent:

```
ISO 8601 ts   \d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?
syslog ts     [A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}
log level     \b(?:TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|CRITICAL)\b
IPv4          \b(?:\d{1,3}\.){3}\d{1,3}\b
IPv4:port     \b(?:\d{1,3}\.){3}\d{1,3}:\d{1,5}\b
UUID          [0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}
HTTP status   \b[1-5]\d{2}\b
bracketed     \[([^\]]*)\]        # anything inside [ ]
quoted        "([^"]*)"           # anything inside quotes
key=value     (\w+)=("[^"]*"|\S+)
```

## Worked examples

**Filter to errors/warnings (ripgrep):**
```
rg -N '\b(ERROR|FATAL|WARN)\b' app.log
```

**Extract just the message after an Nginx/Apache-style prefix:**
```
grep -P '"\K[^"]+' access.log            # request line inside quotes
rg -oP '\] \K.*' app.log                 # everything after the first "] "
```

**Full structured parse (Python, named groups):**
```python
import re
LINE = re.compile(
    r'^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\s+'
    r'(?P<level>TRACE|DEBUG|INFO|WARN|ERROR|FATAL)\s+'
    r'(?:\[(?P<logger>[^\]]+)\]\s+)?'
    r'(?P<msg>.*)$'
)
for line in open("app.log", encoding="utf-8", errors="replace"):
    m = LINE.match(line)
    if m:
        rec = m.groupdict()   # ts, level, logger, msg
```

**Common Log Format (Apache/Nginx access):**
```python
CLF = re.compile(
    r'(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<path>\S+) (?P<proto>[^"]+)" '
    r'(?P<status>\d{3}) (?P<size>\d+|-)'
)
```

## Pitfalls (these cause most "it won't match" bugs)

- **Greedy `.*` overshoots.** `\[(.*)\]` on `[a] [b]` captures `a] [b`. Use a
  negated class `\[([^\]]*)\]` or lazy `\[(.*?)\]`.
- **`.` doesn't cross newlines**, but a single log *event* (stack trace) spans
  many lines. Read the file as one string with the `re.DOTALL`/`(?s)` flag, or
  split on the timestamp anchor, not on `\n`.
- **`\d` and lookarounds need PCRE.** In `grep`/`grep -E` use `[0-9]` and
  `[[:space:]]`, or switch to `grep -P` / `rg`.
- **Shell quoting.** Always single-quote patterns in the shell so `$`, `\`,
  `()`, and `|` reach the regex engine intact.
- **Anchoring.** `^`/`$` match per line by default (good), but multiline mode
  changes this. Be explicit about which you want.
- **Catastrophic backtracking.** Nested quantifiers over optional groups
  (`(\S+ )+`) on long non-matching lines can hang. Prefer specific classes and
  possessive/atomic groups, or a non-regex split first.
- **Encoding.** Logs contain invalid UTF-8 (truncated writes, binary payloads).
  Open with `errors="replace"` in Python; use `LC_ALL=C` for byte-wise grep speed.
- **Timezones/format drift.** The same service may emit two timestamp formats
  across a version bump. Match with an alternation, not one rigid pattern.

## Quick checklist before you trust the result

- [ ] Tested against real sample lines, including edge cases (empty msg, stack traces).
- [ ] Counted matches vs. total lines — does the ratio make sense?
- [ ] Inspected a few non-matching lines to confirm they *should* be skipped.
- [ ] Used the least-powerful tool that works (grep before Python).
- [ ] Pattern anchored on stable landmarks, variable parts in groups.