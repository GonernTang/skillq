---
name: verify-output-format
description: Before writing extracted or recovered values to an output file, verify the exact format the task spec demands — distinguish "value only" from "key=value" lines, and respect phrasing like "matching X" or "one per line".
---

# Verify Output Format Before Writing

A recovered value written in the wrong shape fails the task even when the
underlying work is correct. The most common failure mode: emitting
`KEY=value` when the spec asked for `value` on each line, because the
recovered data happened to come from a `KEY=...` source.

## Diagnostic checklist

Before committing the first write to the output file, run **all** of these:

1. **Quote the spec's format clause verbatim.** Find the exact sentence
   that describes what each output line should look like
   (e.g., "one password per line", "matching password", "the value").
   Re-read it after you have produced a candidate line.
2. **Strip source-side prefixes.** If the value was extracted from a
   `KEY=...` configuration line, an environment dump, or an INI/JSON
   field, the prefix belongs to the *source*, not to the *output*.
   Output only the value unless the spec explicitly asks for the pair.
3. **Sanity-check against a single example.** If the spec gives an
   example output line, your first generated line must match that shape
   exactly — same prefix, same separator, same trailing newline, no
   extra quoting.
4. **Confirm line semantics.** "one per line", "each line", and
   "matching X" all mean: one logical record per line, with just the
   requested datum. They do **not** authorize echoing the source label.

## Stop signal

**Stop and reset** if any of the following is true before writing the
output file:

- You are about to emit a `LABEL=value` or `key: value` line and the
  spec's format clause does not contain the words "key", "label",
  "prefix", or an explicit "= " / ": " separator example.
- Your candidate output line, when stripped of any prefix you added,
  becomes identical to a line in the source artifact — that is a strong
  signal the prefix is leakage from the source, not a requirement.
- You cannot quote the exact format sentence from the spec. Go back and
  re-read it; do not infer the format from the recovered data.

**Reset action:** re-read the task spec, copy the format-defining
sentence into a comment or scratch note, then regenerate the output
matching that sentence's exact shape before writing the file.