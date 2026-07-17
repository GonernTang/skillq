---
name: crlf-header-fix
description: Guard-rail for fixing CRLF / header-injection (CWE-93) vulnerabilities and emitting a conforming vulnerability report. Apply when patching HTTP-header normalizers or generators, or when producing a JSONL vulnerability-finding report that the verifier will grade.
---

# CRLF / CWE-93 Header-Injection Fix

A header-injection bug is fixed by raising on the bad input at the
narrowest choke point — the function that *normalizes or emits* a
header name or value. Patching call sites leaves the bug alive in
every other caller. After the code change, a verifier also grades the
shape of the vulnerability report; mis-typed keys or wrong casing
cause silent rejection. Follow both halves of this skill.

## Diagnostic checklist — run BEFORE writing the patch

Run these checks against the codebase and the task spec. If any
fails, fix the assumption first; do not start patching.

1. **Locate the single normalizer.** Find the function(s) that
   canonicalize header names and values (e.g. `_hkey`, `_hval`,
   `normalize_header`, `encode_header`). Confirm there is *one*
   choke point per axis (name, value). If multiple paths build
   headers, patch the shared normalizer — not each call site.
2. **Confirm the rejection contract.** Decide what the normalizer
   raises on bad input (typically `ValueError`) and confirm the
   caller already handles that exception, or decide to add a
   handler. A raise that goes uncaught turns an injection bug into
   a DoS — that is still better than shipping the injection, but
   note it in the change.
3. **Enumerate the forbidden byte set.** CRLF injection covers
   `\n`, `\r`, `\0` at minimum. Treat the whole control-character
   range (`\x00`–`\x1f`, plus `\x7f`) as forbidden in both names
   and values, not just `\r` and `\n`. The verifier checks the
   `cwe_id` value, not the byte set, but a narrow check is a real
   security regression.
4. **Re-read the report schema.** Before emitting any JSONL
   finding, re-read the task instructions for: exact key order,
   required fields, value types (string vs int, leading `/` on
   paths), and required casing of identifiers such as `cwe_id`
   (lowercase, e.g. `cwe-93`, not `CWE-93`). A correct fix with a
   malformed report still fails the verifier.

## Applying the fix

- In the name normalizer: reject any control character; allow
  only printable ASCII letters, digits, `-`.
- In the value normalizer: reject `\n`, `\r`, `\0`, and the rest
  of the C0/C1 control range. Optionally allow printable
  whitespace (`\t`, space) only if the surrounding protocol
  permits it.
- Raise a typed exception (`ValueError`) with a message that
  names the offending field; do not silently strip or replace
  control bytes — silent mutation hides the bug from logs.
- Do not encode the value as base64 or HTML-escape it as the
  "fix". That moves the problem to the decoder.

## Verifying the patch

- Add or extend unit tests for: bare `\n`, bare `\r`, `\r\n`,
  embedded `\0`, leading/trailing control chars, and a benign
  value that must still pass.
- Run the **full** test suite, not only the new tests. Header
  normalizers sit on a hot path; existing tests may have
  embedded control bytes that were tolerated only because the
  bug was unfixed.

## Stop signal

Stop and reset if any of the following is true:

- You find yourself patching more than two call sites instead of
  the shared normalizer → you located the wrong choke point;
  re-run diagnostic check 1.
- Your report contains `CWE-93` (uppercase), a `file_path` without
  a leading `/`, an integer where a string is required, or keys in
  the wrong order → re-emit the JSONL from scratch against the
  schema; do not hand-edit one field.
- Tests fail on pre-existing cases that pass control characters
  → those tests are documenting the bug. Update them; do not
  weaken the new check.

## Reporting checklist — run BEFORE writing the JSONL

1. Keys appear in the exact order the task spec lists them.
2. `cwe_id` is lowercase: `cwe-93`.
3. `file_path` is a string beginning with `/`.
4. Every field is the type the schema requires (string vs int vs
   array); no Python `True`/`False` where JSON `true`/`false` is
   expected, no tuple where a list is expected.
5. One JSON object per line, terminated by `\n`, no trailing
   comma.