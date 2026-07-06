---
name: gcode-text-extraction
description: Extract user-visible text from G-code files (e.g., "Embossed text" labels for 3D print objects). Use when a task requires pulling printable / human-readable strings out of a `.gcode` file and writing them to an output file. Trigger keywords: "gcode-to-text", "gcode analysis", "extract text from gcode", "M486 object name", "G-code label".
---

# G-code Text Extraction

When a task asks for the **text content embedded in a G-code file**, do not guess or invent strings. G-code produced by modern slicers (PrusaSlicer, SuperSlicer, OrcaSlicer, Cura-with-plugin) routinely carries object-name metadata that IS the text the user wants. Missing this layer is the dominant failure mode — agents instead parse movement commands and end up with garbage or empty output.

## Where the text actually lives

1. **Object-cancel / object-name markers** — the canonical source.
   - `M486 A <name>` — assigns a printable name to the active object (PrusaSlicer / SuperSlicer / OrcaSlicer convention).
   - `M486 S <name>` — older / firmware-side variant of the same idea.
   - `M486 A1 "Quoted Name"` — quoted form is legal; strip quotes.
2. **`; comment` lines** that wrap an object block, e.g.
   `; object:Embossed text` or `; printing object "Embossed text"`.
3. **Slicer preamble banners** — sometimes the project name or filename appears once in a header comment.

## Procedure

1. Open the file as text (UTF-8, errors=`replace`).
2. Scan every line and collect text from these sources IN ORDER:
   a. All `M486 A <name>` / `M486 S <name>` values (strip surrounding quotes).
   b. All comment lines matching `; object[: ]<name>` or `; printing object "<name>"`.
   c. Header banner comment (first non-empty `; ...` block at top of file).
3. **Deduplicate** while preserving first-seen order.
4. If multiple objects are listed (typical: M486 markers come in pairs — one per object), emit them in the order they first appear. Do NOT alphabetize.
5. Write the joined result to the required output file. Default separator: newline. If the task asks for a single string, join with single spaces.

## Diagnostic checklist (run BEFORE writing the output file)

1. **Marker scan** — `grep -c 'M486 A' file.gcode` should return ≥ 1 if the file has named objects. If it returns 0, fall back to comment-line scanning and flag the fallback explicitly.
2. **Round-trip sanity** — print every extracted candidate string to stderr; visually confirm at least one matches a word or phrase (not a coordinate or hex value).
3. **Count vs. object count** — if the slicer reports N objects, you should see ~N M486 A entries (or N+1 with the "current object" sentinel). A mismatch means you missed a section.
4. **Quote and whitespace strip** — confirm no extracted string starts/ends with `"`, `'`, or whitespace before writing.

## Stop signal

- If you have run the marker scan + comment scan + header banner and produced **zero candidate strings**, do NOT fabricate text from G1 coordinates. Instead:
  - Re-scan with a relaxed regex (`;.*[A-Za-z]{4,}`) and report what you found.
  - If still empty, write an empty output file and surface the failure — guessing coordinates as "text" is the documented failure mode this skill exists to prevent.
- Threshold: **3 parse attempts with the same input yielding no M486 or named-object comments** → stop, report the file appears to lack object-name metadata, and ask whether the user wants header-comment extraction only.

## Common pitfalls

- **Treating G1 X/Y moves as text** — coordinate sequences are not user-visible text; this is the wrong layer.
- **Skipping M486 because it looks like a motion command** — `M486` is a meta-command (object cancellation / labeling), not a movement; always read its argument.
- **Losing order** — when the file defines multiple objects, the order of M486 A lines defines reading order. Sorting destroys intent.
- **Ignoring quoted forms** — slicers quote names containing spaces; trim both quote styles.
- **Reading only the first 100 lines** — object-name markers can appear anywhere; if a slicer wraps objects across sections, early-stop misses later objects.