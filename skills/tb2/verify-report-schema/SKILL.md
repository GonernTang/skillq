---
name: verify-report-schema
description: Guard-rail for security-fix tasks that require a structured report. Use before emitting any CWE/CVE JSONL output to ensure keys, case, and format match the verifier's exact expectations — preventing "almost right" submissions that fail grading.
---

When a vulnerability-fix task asks you to report findings (CWE IDs, file paths,
JSONL lines, etc.), the report format is as graded as the fix itself. A correct
patch with a malformed report fails the task. This skill forces a pre-emit
verification pass.

## Diagnostic checklist

Before writing the report file, confirm ALL of the following:

1. **Specification re-read.** Open the task description / spec file and
   re-read the report-format section literally. Do not rely on memory of what
   was requested earlier in the session — the spec is the only source of truth.
2. **Key set match.** Compare the required keys against the keys you are about
   to emit. If the spec lists three keys and you only set two, the verifier
   rejects the row — add the missing key, even if it feels redundant.
3. **CWE/CVE identifier format.** Re-check case, hyphenation, and prefix.
   Typical expected form is lowercase `cwe-93` (not `CWE-93`, not `CWE93`,
   not `cwe:93`). Match the spec verbatim.
4. **One record per line for JSONL.** Verify each line is independently
   parseable JSON, with no trailing commas, no array brackets, no commas
   joining lines.

## Stop signal

If ANY of the following is true, STOP and reset before emitting:

- You have not re-read the task spec within the last 2 minutes.
- You are uncertain whether a key is required vs. optional — treat it as
  required and include it.
- The CWE ID you are about to write has not been copy-pasted (or otherwise
  freshly verified) from the spec this turn.

Reset action: re-open the task spec, list the required keys and identifier
format in a scratch note, then build the report against that list. Do not
guess, do not paraphrase, do not normalize.