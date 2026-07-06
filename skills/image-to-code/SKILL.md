---
name: image-to-code
description: Extract pseudocode or source code from an image, implement it in a suitable language, run it, and verify the output. Use when the task input is an image containing pseudocode/algorithm/flowchart that must be transcribed and executed to produce a numeric or string result.
---

# Image-to-Code Pipeline

When given an image of pseudocode (algorithm, flowchart, hand-written logic, etc.) and asked to execute it, follow this end-to-end procedure.

## 1. Verify the image

- Confirm the file exists and inspect its size/format (`.png`, `.jpg`, `.gif`, `.bmp`, etc.).
- If a path or URL is given but the file is missing, search common locations before declaring failure.

## 2. Extract text from the image

Try OCR tools in this order; stop at the first that works:

1. **tesseract** CLI — `tesseract <image> stdout -l eng`
2. **pytesseract** + **Pillow** (`from PIL import Image; import pytesseract`)
3. **EasyOCR** (`import easyocr`)
4. **Raw byte fallback** — if all OCR libraries are unavailable, read the file as bytes and grep for ASCII-range readable runs; useful only when the image embeds plain text (e.g. screenshots of code editors).

Install missing Python deps with `pip install --quiet <pkg>`. If `pip` is unavailable or sandboxed, fall back to the next tier rather than failing.

## 3. Parse the extracted pseudocode

- Read the OCR output and mentally compile it into a control-flow graph: assignments, loops (`for`/`while`/`repeat`), conditionals (`if`/`else`), arithmetic, string ops, function calls.
- Resolve ambiguous tokens by context: `0/O`, `1/l/I`, `5/S`, `rn/m` are the common OCR confusions.
- If the OCR output is garbled or empty, re-run with different PSM modes (`--psm 6`, `--psm 11`) or preprocess with Pillow (`Image.convert('L')`, contrast bump, threshold) before retrying.

## 4. Implement in a suitable language

- Default to Python — it's universally available and concise.
- Translate the pseudocode line-by-line into idiomatic code; preserve loop bounds, indexing (1-based vs 0-based), and data types exactly as written.
- Wrap the algorithm in a `main()` that prints the result to stdout, and a separate writer that saves it to the file path specified by the task.

## 5. Run and verify

- Execute the program: `python3 solution.py`.
- Cross-check the produced value against any hint in the prompt (expected prefix, length, range, checksum).
- If a hint exists and the value disagrees, re-read the pseudocode and the OCR output for a transcription error before assuming the algorithm is wrong.
- If no hint exists, sanity-check by hand-computing a small case or comparing against a known reference for the algorithm.

## 6. Write the result

- Save the final answer to the output path the task specified (commonly `/tmp/.../answer.txt` or similar).
- Print the same value to stdout so the harness can read it.
- Quote the final answer plainly when reporting back; do not paraphrase numeric results.

## Failure modes to watch for

- **Empty OCR output** → preprocessing step (grayscale + threshold) usually fixes it.
- **Library not installed** → fall back one tier; do not abandon the task.
- **Wrong indexing** → re-read whether the pseudocode uses 1-based or 0-based loops.
- **Hint mismatch** → 90% of the time it's a transcription error, not a logic error.
- **Image too large** → downscale with Pillow before OCR: `Image.thumbnail((2000, 2000))`.