---
name: validate-at-lowest-layer
description: When fixing input-validation or injection vulnerabilities (CWE-20, CWE-93, CWE-113, CWE-79, etc.), place the validation in the lowest-level sink helper so every caller inherits protection, then verify no parallel write paths bypass it. Use before adding guards to high-level methods.
---

# Validate at the lowest layer

When patching an injection-class vulnerability, it is tempting to add a
guard at the most obvious high-level entry point (a public method, a
specific public API). That leaves every other caller — alternate
methods, internal helpers, status setters, format-string builders,
sibling classes — still vulnerable. The fix is to push the check down
to the **lowest shared helper** that every path funnels through, so
protection is structural rather than per-caller.

## Diagnostic checklist

Run these BEFORE adding the validation at any single call site:

1. **Map every sink.** Enumerate every public and internal function
   that ultimately writes the unsafe value to the wire / buffer /
   interpreter. Include setters, `__setitem__`, `add_*`, `set_*`,
   constructors, builders, and status/format helpers.
2. **Find the shared helper.** Identify the lowest function that all
   sinks above pass through (e.g., `_hkey`, `_hval`, `_encode`,
   `_format`, the leaf string-builder). If there is no shared helper,
   that itself is the bug — introduce one.
3. **Confirm no parallel write path exists.** Grep for direct writes
   that bypass the helper: raw concatenation, `+=`, template
   literals, `f"..."`, `format(...)`, or sibling classes that re-encode
   independently. Each bypass is a hole the fix must also close.
4. **Pick the right character set once.** Decide the exact deny-list
   (e.g., `\r \n \0` for HTTP headers, `< > & " '` for HTML, `;`
   for shell) and apply it identically in the helper. Do not let each
   caller invent its own subset.

## Stop signal

If after adding the guard you find **more than one caller still
exposes an unvalidated write path** (e.g., a status-line setter that
bypasses the header helper, or a sibling class with its own encoder),
STOP. Reset by:

1. Reverting the high-level guard.
2. Moving the check into the lowest shared helper.
3. Re-running the diagnostic checklist above.
4. Writing a single failing test per bypass path that exercises the
   exact input (e.g., `"bad\r\nInjected: yes"`) and asserting
   `ValueError`.

A fix is complete only when **every** identified write path raises the
same exception for the same malicious input, with no special cases per
caller.