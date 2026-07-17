---
name: image-to-code
description: Convert pseudocode or algorithm descriptions found in an image into working code. Use when given an image file containing pseudocode, an algorithm sketch, or handwritten code that needs to be transcribed and implemented in a target language.
---

# Image to Code

Convert pseudocode or algorithm sketches contained in an image into working, verified source code.

## When to use

- The user supplies an image (PNG, JPG, etc.) containing pseudocode, a hand-drawn algorithm, or a code snippet that must be transcribed.
- The expected output is a runnable implementation (often verified against a hint such as an expected hash prefix).

## Procedure

1. **Locate and inspect the image.** Identify the input path and the required output path. Use `PIL` (or similar) to open the image and record its size and mode — this confirms the file is readable and helps when reasoning about layout.

2. **Attempt OCR first.** Run `tesseract <image> stdout` (or any available OCR tool) to extract text. OCR is usually noisy on pseudocode: symbols like `+`, `|`, `^`, brackets, and arrows are frequently misread. Treat OCR output as a rough draft, not ground truth.

3. **Reconstruct the algorithm from visual patterns.** When OCR is unreliable:
   - Scan the pixel grid programmatically to detect lines, characters, or symbols.
   - Compare regions of the image to known glyphs (digits, operators, letters) by template matching or by clustering connected components.
   - Map ambiguous symbols back to their intended meaning using the surrounding context (e.g. `Sha256(x || y)` vs `Sha256(x + y)` matters).
   - Pay special attention to operators that are easily confused: concatenation (`||` or `+`), XOR (`^`), OR (`|`), assignment vs equality, and braces vs parentheses.

4. **Write out the pseudocode as comments.** Before implementing, sketch the algorithm in a comment block at the top of the source file. Spell out what each operator actually means (concatenation, hashing, indexing). This forces a concrete interpretation of every ambiguous symbol and serves as documentation for the implementation.

5. **Implement in the target language** using standard library facilities (e.g. `hashlib` for SHA-256, `PIL`/`numpy` for pixel work, `struct` for byte packing). Match the pseudocode line by line. Prefer clarity over cleverness — the goal is fidelity to the source.

6. **Verify against any provided hint.** If the task includes a check value (expected hash prefix, expected output text, sample input/output), run the implementation on a small case and confirm the result matches before declaring success. Iterate on operator interpretation until verification passes.

7. **Write the final artifact** to the path specified by the task as a plain text file. Do not include debug output, OCR transcripts, or scratch notes in the final file unless requested.

## Pitfalls

- **Operator ambiguity.** `+`, `|`, and `||` look similar in low-resolution images and OCR often collapses them. Always cross-check with the algorithm's intent (e.g. hashing two strings almost always means concatenation, not addition).
- **Integer vs string.** A loop bound or index read as a string will silently break arithmetic. Coerce types explicitly.
- **Endianness / byte order.** When packing fields into a hash input, byte-order mismatches are the most common cause of a verification hash not matching. Verify with a known sample before tuning anything else.
- **Partial OCR confidence.** Don't trust any single OCR pass — re-derive the truth from the image itself when verification fails.