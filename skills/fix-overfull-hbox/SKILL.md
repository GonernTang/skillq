---
name: fix-overfull-hbox
description: Eliminate LaTeX "Overfull \hbox" warnings without changing document structure (preamble, geometry, layout). Use when pdflatex reports overfull hbox warnings and the constraint is to fix the text only via synonym substitution.
---

# Fix Overfull \hbox Warnings via Synonym Substitution

## When to use
Use this skill when:
- A LaTeX document compiles with `Overfull \hbox` warnings.
- The constraint forbids changing the document structure: no preamble edits, no `\usepackage`/`\geometry` changes, no margin adjustments, no `\sloppy` / `\emergencystretch` tricks.
- A synonym/dictionary file mapping each long word to a shorter, meaning-preserving alternative is available (or can be constructed).
- The goal is to make the document compile with zero overfull hbox warnings.

## Procedure

### 1. Baseline: compile and capture warnings
- Compile with nonstopmode so it does not stop on errors:
  ```
  pdflatex -interaction=nonstopmode <main>.tex
  ```
- Capture the log and grep for the warnings:
  ```
  grep -n "Overfull \\hbox" <main>.log
  ```
- Each warning reports: source file, line number, offending text, and the excess width in points. Record all of these.

### 2. Locate the offending text
- For each warning, open the input file (`.tex` / `.sty` / source) at the reported line.
- Read the full paragraph (warnings reference a single line but the overfull word came from the surrounding typeset paragraph).
- Identify every long word in that paragraph — a "long word" is anything likely to cause TeX to refuse a break: a long compound, a long technical term, an unhyphenatable token, etc.

### 3. Consult the synonym dictionary
- A synonym file maps each long word → one or more shorter equivalents that preserve meaning in context.
- Treat the dictionary as read-only data. Do not edit it.
- For every long word in the offending paragraph, pick the shortest synonym listed. Prefer single-token replacements that are 2+ characters shorter than the original.

### 4. Substitute and recompile
- In the source file, replace the long word with the chosen shorter synonym. Keep the rest of the paragraph (and all surrounding markup) untouched.
- Recompile with `pdflatex -interaction=nonstopmode <main>.tex`.
- Re-grep for `Overfull \hbox`. If any remain in the same paragraph, repeat step 3 with the next-shortest synonym for the remaining long words. If a new warning appeared elsewhere, jump to step 2 for that location.

### 5. Iterate per warning
- Process warnings one paragraph at a time, but it is fine (and usually faster) to substitute all long words in a single offending paragraph in one pass and then recompile once.
- Stop iterating on a paragraph only when its warning is gone from the log.
- Continue until `grep "Overfull \\hbox" <main>.log` returns no output.

### 6. Verify a clean compile
- After the log is clean, run the full build chain (e.g. `pdflatex` twice, or `pdflatex` + `bibtex` + `pdflatex` + `pdflatex` as the project requires).
- Confirm:
  - No `Overfull \hbox` lines in the log.
  - No new errors introduced (e.g. undefined control sequences, missing braces).
  - Page count and visible layout are unchanged from intent.
- The synonym swap must not introduce a grammatical or semantic regression — re-read the modified paragraph in the typeset PDF to confirm.

## Hard constraints
- **Do not** modify the LaTeX preamble, `\documentclass`, `\usepackage`, `\geometry`, `\setlength`, or any layout/macro definitions.
- **Do not** add `\sloppy`, `\emergencystretch`, `\hbadness=...`, `\hfuzz=...`, or any global reformatting switch.
- **Do not** edit the synonym dictionary — it is the source of truth for valid replacements.
- **Do not** rewrap, rephrase, or delete words. Only do 1-to-1 (or 1-to-few) word-for-synonym substitution.
- All replacements must be meaning-preserving synonyms; never invent a replacement that changes the claim.

## Failure modes and recovery
- **Warning persists after one substitution** → pick a different (shorter) synonym from the dictionary for the same word, or move to the next-longest word in the paragraph.
- **New warning appears elsewhere** → it is unrelated; process it on its own merits from step 2.
- **No synonym is short enough** → surface the warning to the user; do not fabricate a replacement or weaken the constraint to change layout.
- **Compile error after substitution** → revert the last change, re-check the dictionary entry, retry.

## Done criteria
- `grep -c "Overfull \\hbox" <main>.log` returns `0`.
- Document still compiles to PDF with no errors.
- No preamble, geometry, or synonym-file edits were made.