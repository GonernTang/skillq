---
name: header-crlf-defense
description: Prevent and fix CRLF injection (CWE-93) vulnerabilities in HTTP header setters. Use when adding, reviewing, or hardening code that constructs or assigns HTTP header names/values in any web framework or library.
---

# Header CRLF Injection Defense

When fixing or hardening HTTP header handling against CRLF injection (`\n`, `\r`, `\0`), the fix fails if validation is applied only at one entry point while sibling setters remain unchecked. An attacker only needs the unguarded path.

## Diagnostic checklist

Run these BEFORE committing to a single-line validation fix:

1. **Enumerate every header-write path.** Grep for assignments to header dicts/sets, low-level key/value normalization helpers (e.g. `_hkey`, `_hval`, `_set_header`, `HeaderDict.__setitem__`, `Response.headers[...] =`), and any public method that mutates headers (`add_header`, `set_header`, `append`, `replace`, `update`, `pop`-then-set). The fix MUST cover every path, not just the one shown in the bug report.
2. **Centralize validation at the lowest setter.** Put the control-character check (`\n`, `\r`, `\0`, plus any other bytes prohibited by RFC 7230) in the primitive that normalizes/stores the key or value, then route all higher-level methods THROUGH it. Calling the validator from `add_header` but skipping `__setitem__` (or vice versa) leaves a hole.
3. **Match the existing test idiom.** Search the test suite for patterns like `test_prevent_control_characters_in_headers`, `test_invalid_header`, or `assertRaises(ValueError, ...)` near header tests. The fix should add or extend a test that exercises EACH public setter, not only the one flagged in the report.
4. **Pick the right CWE.** CRLF injection in HTTP response splitting is `CWE-93` (Improper Neutralization of CRLF Sequences / "CRLF Injection"). Do not file it as CWE-79, CWE-113, or CWE-117 unless the codebase's taxonomy explicitly maps it that way.

## Stop signal

If after step 1 you find MORE THAN TWO distinct code paths that write header names or values, STOP patching one path at a time. Reset and refactor: introduce (or reuse) a single validated setter and migrate every writer to call it. A patch that adds validation to one method while leaving siblings unchanged does not close the vulnerability — it just narrows it.

## Implementation notes

- Raise `ValueError` (not `TypeError`, not a silent `return`) so misbehavior is loud and testable.
- Validate BOTH the key and the value; CRLF in a header name is equally exploitable for response splitting in many frameworks.
- After patching, run the FULL test suite, not only the new/header tests — header normalization is on the hot path for many other features.
- File the vulnerability report with the exact file path of the LOWEST setter you hardened (not the higher-level wrapper), so future audits land on the chokepoint.
- Briefly audit sibling input-sanitization surfaces (cookie values, redirect Location, Set-Cookie, query-string reflection in headers) for the same class of bug; CRLF fixes often cluster.

## Out of scope

This skill is about CRLF/header injection specifically. For SQL injection, XSS, path traversal, or template injection, use the respective vulnerability-class skills — the validation patterns and CWEs differ.