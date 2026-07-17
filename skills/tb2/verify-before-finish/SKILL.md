---
name: verify-before-finish
description: Run the script end-to-end on demo data before declaring a task done. Prevents shipping unverified code that fails on inputs the user actually cares about.
---

When producing a script (or any executable artifact) that processes user-provided data, you MUST execute it against the provided demo inputs and confirm the output is correct BEFORE marking the task complete. Writing the script is not the task — producing verified output is.

This guard-rail exists because it is easy to write a script that "looks right," commit it, and stop — only for the user to discover on first run that a column is missing, a path is wrong, or the inference call silently returns nothing.

## Diagnostic checklist (run BEFORE declaring done)

Run these checks on the script and its output:

1. **Dependency check** — Every import/package the script uses is installed in the runtime. Verify with `python -c "import <pkg>"` or equivalent for each non-stdlib dependency. List missing ones explicitly.
2. **Input shape check** — Read the actual demo input file(s) and confirm the script's parser handles every column/type/edge-case present (e.g., mixed `rectangle` and `polyline` rows, empty cells, encoding quirks). Don't assume from the spec — inspect the bytes.
3. **End-to-end run** — Actually execute the script against the demo inputs and produce the output file. A script that has never been run is a draft, not a deliverable.
4. **Output validation** — Confirm the produced output has the expected schema (same columns, same row count, valid coordinate ranges, no NaN/empty where data was expected). Open and inspect it.

## Stop signal

STOP and reset if any of these is true:

- The script has not been executed against the demo data at least once.
- The output file is missing, empty, or has different columns / fewer rows than the input.
- Any required dependency fails to import.
- The main guard (`if __name__ == "__main__":`) is missing or only contains a `pass` / comment placeholder.

**Reset action:** go back to the failing checklist item, fix it, and re-run the full end-to-end pass. Do not declare success on partial checks.

## Anti-patterns to avoid

- Writing the script, then claiming "done" without invoking it.
- Only running a syntax check (`python -m py_compile`) — that proves nothing about runtime correctness.
- Reading a few rows of input and assuming the rest follows the same pattern.
- Hardcoding paths/values from the task description instead of using the actual demo files.
- Silently swallowing empty predictions / exceptions without a fallback (e.g., empty model output → fall back to bounding box, not silent skip).
- Skipping mask/pixel collision logic — adjacent instances will overlap unless you track occupied pixels.