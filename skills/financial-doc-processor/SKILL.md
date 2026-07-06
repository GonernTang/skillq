---
name: financial-doc-processor
description: Process a mixed directory of PDF and image files, classify each as invoice vs. other, extract total/VAT amounts from invoices, and emit an aggregated summary CSV.
---

# Financial Document Processor

## When to use
- Source directory contains a heterogeneous mix of PDFs and image files (scans, photos).
- Need to: (1) classify each file as invoice or other, (2) extract total and VAT amounts from invoices, (3) produce a single CSV summary with per-file rows and a final aggregated row.

## Procedure

### 1. Survey the source directory
- List all files. Partition by extension:
  - `.pdf` → text-extractable documents
  - image extensions (`.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp`) → OCR required
- Note the count of each class; all will be classified in step 3.

### 2. Install required tools
- `poppler-utils` — provides `pdftotext` for PDF text extraction.
- `tesseract-ocr` — provides `tesseract` for image OCR.
- Install via the system package manager (apt/yum/brew) as needed.

### 3. Extract text from each file
- **PDF**: `pdftotext <file> -` (stdout).
- **Image**: `tesseract <file> -` (stdout).
- Capture each file's text into memory keyed by filename.

### 4. Classify each document
- Classification rule (case-insensitive): if the extracted text contains the word `Invoice` (or close variants like `Tax Invoice`, `Invoice #`), classify as `invoice`. Otherwise classify as `other`.
- This rule is intentionally simple and content-based — do not rely on filename hints.

### 5. Sort files into target directories
- Create two destination directories (e.g., `invoices/` and `other/`).
- Move each source file to its classified directory.
- The source directory must be empty after the move.

### 6. Extract monetary fields from invoice text
For each invoice, parse the text with these rules:

**total_amount** — search, in priority order, for:
- `Total` / `Grand Total`
- `Amount Due` / `Balance Due`
- Tie-breaker: if both `Total` and `Amount Due` appear with different values, **use only `Total`** (Amount Due is often a partial balance).
- Strip currency symbols and thousands separators; parse as a float.

**vat_amount** — search for any of:
- `VAT` / `Value Added Tax`
- `Tax` / `Sales Tax`
- `GST` (regional synonym)
- If no VAT/tax field is present, set `vat_amount` to `0` (or empty string if a sentinel is preferred).

### 7. Emit the summary CSV
- File location: `<invoices_dir>/summary.csv`
- Columns: `filename,total_amount,vat_amount`
- One row per invoice, in the same order files were processed.
- **Final row**: `filename = "total"`, with `total_amount` and `vat_amount` set to the column sums across all invoice rows.
- Write header row first, then data rows, then the total row.

### 8. Validate
- Confirm the source directory is empty.
- Confirm the CSV has one row per invoice + one total row.
- Confirm the total row's sums match a manual recomputation of the data rows.
- Spot-check at least one extracted amount against the original document text.

## Heuristics & gotchas
- **OCR noise**: tesseract may misread characters in totals (e.g., `1,234.56` → `l,234.56`). Prefer regex like `r"[0-9]+[0-9.,]*"` and validate plausibility (two decimal places, non-negative).
- **Multi-currency**: assume a single currency per batch unless the task specifies otherwise; do not attempt FX conversion.
- **Negative values**: refunds/credits may show as `-amount`. Preserve the sign in the CSV; the total row is the algebraic sum.
- **Duplicate labels**: an invoice may list subtotal, tax, and total in sequence. Always take the *last* match for `Total` if multiple exist (often the grand total appears last), and the *first* match for VAT.
- **Non-invoice PDFs**: contracts, receipts, and statements often lack the word "Invoice" — these belong in `other/` and contribute no rows to the CSV.