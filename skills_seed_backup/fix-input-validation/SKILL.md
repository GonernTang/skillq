---
name: fix-input-validation
description: Fix input validation vulnerabilities (CWE-20) in Python web frameworks by adding type and value checks at function boundaries, replacing silent returns or generic exceptions with specific TypeError/ValueError/custom exceptions, and producing a CWE-tagged fix report. Use when handlers or helpers accept user input and either ignore invalid values or raise bare `Exception`.
---

# Fix Input Validation Vulnerabilities

## When to use
- A function or request handler in a Python web framework (Flask, Django, FastAPI, etc.) takes user-controlled input.
- The function either silently swallows invalid input (e.g. returns `None`, `False`, or a default) or raises a generic `Exception(...)` without a clear type.
- The defect maps to CWE-20 (Improper Input Validation) or a closely related weakness (CWE-1284, CWE-1286, etc.).

## Procedure

1. **Locate vulnerable entry points**
   - Find functions that consume request data: query params, form fields, JSON body, path params, headers, cookies.
   - Flag any function that lacks an upfront validation step, or that catches and silently discards validation errors.

2. **Add explicit checks at the boundary**
   - Validate **before** any side effect, branching, or persistence.
   - Use `isinstance` for type checks against the expected concrete type (not a bare `object`).
   - Add range / format / allowlist checks appropriate to the field (e.g. `0 < n <= MAX`, `re.fullmatch(pattern, s)`, membership in an allowlist).
   - Reject empty strings, `None`, and unexpected types explicitly.

3. **Replace silent failures and generic exceptions**
   - Silent return / default → `raise` an exception instead; never coerce bad input to a "safe" value silently.
   - Generic `raise Exception("...")` → map to the narrowest applicable type:
     - Wrong type → `TypeError("<param> must be <ExpectedType>, got <ActualType>")`
     - Out of range or malformed → `ValueError("<param> must be ..., got <repr-of-value>")`
     - Domain-specific rule violated → a project-defined exception class (e.g. `InvalidUserInput`).
   - Message must identify the offending parameter and the constraint, but must **not** leak internals (stack frames, file paths, secrets, DB schema).
   - Never use `except Exception: pass` or a bare `except:` to mute validation errors.

4. **Verify with the project test suite**
   - Run the project's standard runner (e.g. `pytest -rA`, `python -m unittest discover`).
   - Existing tests must still pass — validation must not break legitimate inputs.
   - If the suite lacks coverage for the new validation paths, add focused tests asserting that bad inputs raise the expected exception type with a non-empty message.

5. **Produce a fix report**
   - File path and line range of the change.
   - CWE identifier (CWE-20 by default; cite a more specific CWE if it fits better).
   - One-sentence description of the original flaw and the specific change applied.
   - Test command run and its result (pass / fail summary).
   - Any new tests added.

## Principles
- Validate at the boundary; do not push validation deep into helpers.
- Narrow exception types are documentation — pick the most specific one that fits.
- Messages help legitimate callers diagnose the problem; they should not help an attacker probe internals.
- A passing test suite is the bar, not the goal — the new tests are what prove the vulnerability is closed.