---
name: vim-macro-transform
description: Reusable procedure for transforming large text files with Vim macros. Covers delimiter/case/column-ordering changes, keystroke-efficient macro construction, and pre-flight sanity checks. Use when a task requires in-place, deterministic, headless-style edits across many lines via Vim commands.
---

# Vim Macro Transform Procedure

## When to use

A task requires a single, deterministic, in-place edit across every line of a large text file using Vim — e.g. delimiter change, case conversion, column reorder, constant-string append. The constraint set typically allows only a limited set of `ex` commands, a bounded keystroke budget, and headless execution.

## Pre-flight analysis

Before writing any macro, characterize the input/output diff:

1. **Delimiter** — identify the exact separator in the input (`,`, `;`, `|`, whitespace) and the desired output separator. Note any leading/trailing whitespace around it.
2. **Case** — does the spec require upper, lower, or title case? Mixed?
3. **Column count and order** — count fields per line. Are they all uniform? Note the source order and the desired target order.
4. **Constants** — any fixed text to append, prepend, or substitute (e.g. a status flag, a column header).
5. **Edge rows** — header line? Blank lines? Comments? Quoted fields containing the delimiter?

Capture this as a one-line spec: `from → to` (delimiter, case, column-reorder, constant).

## Macro construction

Decompose the transform into the minimal set of `ex` substitutions, each in its own named register (`a`, `b`, `c`, …). Prefer **one concern per macro** so each is auditable:

- **Normalize whitespace / change delimiter**
  `:s/\s*<old>\s*/<new>/g`
  Use `\s*` to absorb stray padding around the separator. Anchor with `^…$` only when the row is uniform.

- **Change case**
  - Uppercase: `:s/.*/\U&/`
  - Lowercase: `:s/.*/\L&/`
  - Title: combine per-word `\u` substitutions, or use `gUaw` over visual ranges.

- **Reorder columns and append a constant**
  Use a single anchored substitution that captures each field and rewrites it:
  `:s/^\([^<sep>]*\)\(<sep>\)\([^<sep>]*\)\(<sep>\)\([^<sep>]*\)$/\5\2\3\2\1\4<CONST>/`
  The trailing `<CONST>` is the constant text the spec requires to be appended (or prepended by placing it before the first capture group).

Keep each macro to one `:s` line. If the spec needs more than three captures, the row schema is probably non-uniform — split the problem rather than chaining captures.

## Execution

Run macros sequentially on the whole buffer, one register at a time, in spec order:

```
:%normal! @a
:%normal! @b
:%normal! @c
```

Use `normal!` (with the bang) to skip user mappings. Replay order must match the spec order — case conversion after delimiter change, reorder after normalization, constant append last.

## Sanity-test checklist (do this BEFORE the full run)

1. Copy **one representative row** (a header plus 2–3 data rows including an edge case) into a scratch buffer.
2. Run the macros on the scratch only.
3. Manually diff the result against the expected output from the pre-flight spec.
4. Verify: delimiter correct, case correct, column order correct, constant present, no stray whitespace, header line still present (or intentionally consumed).
5. Only then run `:%normal! @a` etc. on the full file.

## Constraint compliance

- **Allowed-command whitelist** — confirm each `:s` form and each `:%normal!` call uses only commands on the allowed list. Strip anything else (e.g. `:%!`, `g/`, custom functions).
- **Keystroke budget** — count characters per macro; if a single register exceeds the limit, split the spec across two macros.
- **Headless execution** — use `vim -es` (silent ex) or `vim -n -u NONE` style flags as the task requires; macros themselves do not change, only the invocation.
- **Idempotence** — never re-run a macro that already produced its effect on the buffer; it will corrupt rows that no longer match its pattern.

## Failure modes to watch for

- **Unanchored `:s` matches the constant you just appended** — anchor with `^…$` when the constant is a literal you do not want rewritten.
- **Case flag (`\U`/`\L`) in a macro that also captures** — apply case conversion in its own macro, not inside the reorder.
- **Whitespace delta** — `\s*` in the delimiter macro is greedy; verify it does not collapse a field that legitimately contains the separator inside quotes.
- **Off-by-one in column count** — when capture groups do not match the row schema, the substitution silently leaves the row untouched; sample a row before and after to catch this.