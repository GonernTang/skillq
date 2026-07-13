---
name: verify-output-spec
description: Always reconfirm what an output argument actually represents (file path vs. folder, single artifact vs. many) and what shape the verifier expects, before writing code. Use whenever a task spec mentions an output path, output folder, save location, or asks you to write/converta artifacts (masks, CSVs, images, JSON).
---

A recurring failure mode is to treat an argument named `output_path`, `save_dir`, or `out_dir` as a file path when the spec calls it a folder, or to ship artifacts in a shape (one CSV, one big file, one image) the verifier does not match (many per-image files, one-per-row, etc.). Cost: silent wrong shape, no error, full re-run.

## Diagnostic checklist

Run these BEFORE writing the first line of output code:

1. **Reread the exact wording of every output argument.** Quote it. Decide: is it a *file path* (one file) or a *directory/folder* (many files inside)? Words like "folder", "directory", "out_dir", "save_to", "output folder" mean a directory; words like "output path for the CSV" mean a file. If a noun is absent, assume the safer default (a folder) and confirm against examples.
2. **Check for example outputs or prior runs.** Look in the workspace for sample outputs, a `README`, a verifier script, an `expected/` directory, or any prior run's artifacts. The verifier's expectation is encoded in *what it actually reads*, not in the prose. Match that shape.
3. **For conversion/serialization tasks (masks → files, frames → video, records → CSV), explicitly decide the output granularity.** One monolithic file vs. one file per input item vs. a single multi-row CSV vs. a directory of small files are all valid answers — only one matches the verifier. Write the chosen shape on a sticky note before coding.
4. **Verify write semantics for the chosen shape.** If the arg is a folder, the first I/O must be `os.makedirs(path, exist_ok=True)` (or equivalent) and every output must be `<path>/<name>`. If the arg is a file, parent dirs still need `exist_ok=True` and the filename must match what the verifier looks for.

## Stop signal

If, while coding, you find yourself about to call `open(path, "w")` or `save(path)` or `to_csv(path)` / `imsave(path)` against an argument whose spec wording you have not re-quoted in this session — STOP. Also STOP if you cannot point to a concrete example or verifier artifact that confirms the chosen output granularity. The reset action: close the editor, reread the argument description verbatim, list candidate output shapes (single file / per-item files / single CSV / directory), and pick the one whose shape matches an example or the most literal reading of "folder" vs "file". Only then resume coding.