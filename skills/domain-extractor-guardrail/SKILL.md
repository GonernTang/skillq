---
name: domain-extractor-guardrail
description: Guard rail for building complex domain-specific extractors, parsers, recognizers, or generators (e.g. binary files, board images, netlist descriptions) from low-level primitives. Use when the task is "extract X from Y", "recognize Z", or "build a generator for W" and you are tempted to parse byte-by-byte, recognize pixel-by-pixel, or assemble gates by hand. Enforces a library/skill check, tiny-case diagnostics, and a hard stop signal to break debug spirals.
---

# Domain Extractor Guard Rail

The three recurring failures — manual ELF parsing, hand-rolled chess-board recognition, and gate-by-gate circuit synthesis — share one anti-pattern: building a complex domain-specific system from primitives instead of standing on a high-level library, and validating only at the end. This skill encodes the avoidance procedure.

## When to invoke

You should consult this skill whenever the task asks you to:

- Parse or extract structured data from a binary or proprietary file format (ELF, PE, archives, image containers).
- Recognize or interpret a structured visual input (chess board, schematic, OCR, layout).
- Synthesize or generate structured output from a description (logic circuits, netlists, mark-up, code models).
- Bridge any "obvious-looking" domain with a known library that already solves it.

If your plan involves manually walking bytes, scanning pixels, or assembling AND/OR gates from scratch, you are in the danger zone — run the diagnostic checklist below before writing the main implementation.

## Diagnostic checklist (run BEFORE writing the generator)

1. **Library / skill search.** Search for an existing high-level library, framework, or skill that already does the heavy lifting for this exact domain.
   - Binary formats: check for `pyelftools`, `lief`, `binaryparser`, `elf` (Node), `readelf`-style tools.
   - Chess / board games: check for `python-chess`, `chess.js`, or a board-recognition skill.
   - Circuit / hardware: check for a logic-synthesis library, netlist generator, or a verified gate-level template.
   - Always also re-scan the current skill library for a domain-specific skill before rolling your own.

2. **Dependency sanity.** Confirm every import you plan to use is installed in the target environment. If a dependency is missing, either install it or pick an approach that uses only standard-library modules. Never write code that calls a module you have not verified is present.

3. **Tiny-case validation.** Run your chosen approach on the smallest possible inputs (empty input, single record, single cell, single gate). Hand-compute the expected output and confirm a match before scaling up. If N=1 fails, your architecture is wrong — STOP.

4. **Reference cross-check.** Write a short, obvious, possibly inefficient reference implementation (≤30 lines) that produces the answer by brute force. Confirm your structured approach agrees with it on the tiny cases. This is your ground truth.

## Procedure

1. Run the diagnostic checklist. Address every failed item before proceeding — do not skip ahead.
2. If a high-level library exists, write the extractor as thin glue: read input → call library function → format output. Do not re-implement what the library already does.
3. If no library exists, decompose into three layers and validate each in isolation:
   - **Input layer** — read and tokenize / deserialize the raw bytes or pixels.
   - **Domain layer** — apply the domain logic on the parsed input.
   - **Output layer** — serialize the result into the requested format.
4. Combine layers only after each has passed the tiny-case tests.
5. Only then scale to the full problem size.

## Stop signal (mandatory reset)

You MUST stop and reset if any of the following is true:

- You have written **3 versions of the same generator/parser** and they all fail the same diagnostic. The architecture is wrong. Switch to (a) the high-level library you skipped, or (b) the reference cross-check to find the divergence.
- You have spent **>20 minutes** without a single passing diagnostic on a simple case. Re-read the task — you are likely solving the wrong problem.
- A dependency check fails and your immediate instinct is "I'll just install it" or "I'll fake the import". STOP and pick an approach compatible with the actual environment.
- The next thing you are about to write is a 4th iteration of the same `gen.py` / `parse.py` / `recognize.py`. STOP. The pattern from the 2026-06-24 circuit-fibsqrt case is exactly this: 7 versions, 115 minutes wasted, same broken architecture.

## Anti-patterns to avoid

- Manually walking ELF headers byte-by-byte when `pyelftools` already exists.
- Re-implementing chess move generation or evaluation when `python-chess` already exists.
- Hand-assembling 32-bit multipliers from NAND gates when a generator template exists.
- Hand-rolling board recognition from raw pixel analysis when a board-recognition skill exists.
- Producing N versions of the same script hoping the bits will "fall into place" — they will not.
- Skipping the dependency check because "I'll deal with imports later" — you will not, and the failure will surface at the worst moment.