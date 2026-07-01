---
name: ocr-pseudocode
description: Extract pseudocode from a screenshot/image and implement it as working code. Use when given an image of pseudocode (algorithm steps, hash routines, etc.) to translate into a programming language. Workflow: install OCR tooling, preprocess the image, run OCR with multiple page-segmentation modes, manually correct common optical misreads of technical symbols and identifiers, implement the algorithm faithfully, and verify against any known output prefix.
---

# OCR Pseudocode Implementation

When the input is an image of pseudocode that must be implemented, treat the OCR step as the most failure-prone part. The procedure below is the order that minimizes rework.

## 1. Set up OCR tooling

Install the Python OCR stack and confirm the system binary is reachable:
- Python packages: `Pillow`, `pytesseract`
- System binary: `tesseract-ocr`

If the system binary is missing, install it before running OCR — `pytesseract` will fail silently or raise on missing binary.

## 2. Load and preprocess the image

- Open the image with Pillow.
- Apply preprocessing to maximize OCR accuracy:
  - Convert to grayscale
  - Enhance contrast
  - Apply binarization (thresholding)
- If the image is small or noisy, upscale before OCR.
- Iterate preprocessing — different images need different parameter values.

## 3. OCR with multiple segmentation modes

Tesseract's page-segmentation mode (`--psm`) strongly affects output for non-flowing content like pseudocode blocks. Run several passes (e.g. `--psm 3`, `--psm 4`, `--psm 6`, `--psm 7`) and compare. Pick the cleanest reading, or combine the strongest reading from each.

## 4. Manually correct common optical misreads

OCR systematically garbles technical content. After OCR, scan the text and build a correction map of (suspect token → intended token). Common failure patterns:

- **Hash / algorithm names**: `cha256` → `SHA256`, `SHAl` → `SHA-1`, `md5` ↔ `MD5`
- **Output encodings**: `bex` → `hex`, `baseb4` → `base64`
- **Identifiers with subscripts or concatenation**: `H_0`, `T1||T2`, `K[i]`
- **Operator / math glyphs**: `×`, `·`, `←`, `≡`, `≠`, `≤`, `≥`
- **Punctuation confusion**: `;` ↔ `:`, `()` ↔ `{}`, `''` ↔ `""`

Re-read the corrected text top-to-bottom before implementing — every misread you miss here cascades into a code bug.

## 5. Implement the pseudocode

- Pick the target language from surrounding context (Python is the common default).
- Translate line-by-line, preserving the pseudocode structure exactly. Do NOT rename identifiers "for clarity" — verification steps may rely on them.
- Pay special attention to slice / prefix / suffix / salt operations: off-by-one errors and wrong concat direction are the single biggest class of bugs here.
- Match bit widths, endianness, and padding rules exactly as shown.

## 6. Verify against any known output

If the task gives a known output prefix or sample value:
- Compute your implementation's output.
- Compare the prefix exactly (string compare, not numeric compare).
- Mismatch ⇒ revisit OCR corrections first (most likely cause), then slice indices, then endianness.

If no known output is given, run a round-trip self-check (e.g. feed a known input through any reversible step) where possible.

## 7. Write the result

Save the final implementation to the required output path. Keep the file self-contained — no leftover OCR scratch or debug prints.

## Common pitfalls

- Skipping preprocessing → noisy OCR → wrong identifier → wrong implementation.
- Trusting a single PSM mode → the best reading is often a different mode.
- Renaming variables during implementation → breaks any downstream verification.
- Off-by-one in slice/prefix/salt operations.
- Confusing similar-looking identifiers that differ by one character (e.g. `T1` vs `Tl`).