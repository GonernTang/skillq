I'll add a new checklist item to the diagnostic section covering the specific C-based inference pattern. This is a local insertion that doesn't change any existing content, respects all constraints, and directly addresses the gap identified in the failure diagnosis.

--- START OF EDITED SKILL ---
---
name: verifier-spec-match
description: Ensure the implementation matches the verifier's exact expectations — paths, signatures, function names, output formats, and harness criteria — before submitting. Use when a task has a hidden test harness or specific deliverable structure.
---

# Verifier-Spec Match Guard-Rail

A correct algorithm is not a passing submission. Verifiers often fail
submissions for *interface* mismatches — wrong file path, wrong function
signature, wrong output format, missing helper. This skill forces a
spec-first pass before writing code.

## Diagnostic checklist (run BEFORE coding the algorithm)

1. **Path audit.** Locate every file the task mentions by exact path.
   Note the directory, filename, and extension. If the task says
   `samples.txt` at the project root, write to `<cwd>/samples.txt`,
   not `./output/samples.txt`.
2. **Signature audit.** For every required function, record the
   exact name, parameter list, return type, and any defaults. Do
   not rename, do not reorder parameters, do not add "convenience"
   wrappers that obscure the required entry point.
3. **Format audit.** Confirm the on-disk format per file:
   - One record per line? Comma-separated? Header row?
   - Numeric precision / scientific notation?
   - Required trailing newline? UTF-8? BOM?
4. **Test-harness audit.** If a `test()` function is referenced, it
   MUST `return TRUE` on success and print a clear `PASS` / `FAIL`
   line per check. Print to stdout, not stderr. Do not raise on
   expected edge cases — catch and report.
5. **C-based inference audit.** If the task involves deploying a neural network as a standalone CLI tool in an environment without Python ML libraries, examine any existing source files for C-based implementations (e.g., lodepng for PNG decoding, cJSON for JSON parsing). Adapt the build by renaming .cpp to .c if necessary, compile with gcc linking the math library (-lm), implement the forward pass using matrix-vector multiplication, ReLU activation, and argmax. Output only the predicted digit to stdout. Create a `prediction.txt` file containing that digit. Test the binary with a sample image and verify all required artifacts exist (cli_tool, weights.json, prediction.txt).

## Stop signal

Stop and reset if any of the following is true:

- **≥2 unverifiable interface details remain.** (e.g., you don't
  know the exact output path AND the exact function signature.)
  Action: re-read the task description character-by-character and
  list every concrete deliverable in a checklist before writing
  any code.
- **The implementation passes a smoke test but the test harness
  fails silently.** Action: invoke the official harness (or
  replicate its checks line-by-line) and compare its expected
  outputs against yours byte-for-byte.
- **The task involves database recovery (e.g., "db-wal-recovery", "wal-corruption", "SQLite").** This skill is designed for matching verifier specs, not for recovery procedures. Stop and select the appropriate recovery skill.

## Common interface failures to pre-empt

- Writing the right answer to the wrong path → 0 score despite
  correct algorithm.
- Using a CSV when the verifier reads one-sample-per-line, or
  vice versa.
- Returning a Python `list` from a function expected to return a
  `numpy.ndarray` (or the reverse).
- Naming a function `sample` when the harness calls `ars_sample`,
  or accepting `n` as a kwarg when it is positional.
- Omitting the test() helper that prints PASS/FAIL — verifiers
  often grep for those literal strings.
- Submitting without running the harness once — silent interface
  bugs survive that would have been caught in 5 seconds.

## How to apply

1. Open the task text. Underline every path, filename, function
   name, parameter name, and output format string.
2. Build a deliverables table before writing code: rows are
   deliverables, columns are (path, format, signature, harness
   hook).
3. Implement against the table, not against intuition.
4. Run the official harness (or its documented equivalent) before
   the final submission. If you cannot run it, hand-simulate each
   check and diff against expected output.
--- END OF EDITED SKILL ---