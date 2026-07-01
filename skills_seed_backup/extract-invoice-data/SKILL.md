---
name: extract-invoice-data
description: Process a mixed directory of financial documents — classify each file as invoice or other, extract total amount and VAT via keyword matching from PDFs (pdftotext) and images (tesseract OCR), handle conflicting totals and missing VAT, then emit a CSV summary with per-file rows plus a totals row.
---

# Extract Invoice Data from Mixed Financial Documents

## When to use

A directory contains a heterogeneous mix of financial documents (invoices mixed with receipts, statements, contracts, letters, etc.) in PDF and image formats. You need to (a) sort them into invoice vs. non-invoice, and (b) pull total and VAT figures out of every invoice into one CSV.

## Procedure

### 1. Set up output folders

Create two destination directories before processing begins:
- `<output>/invoices/` — files classified as invoices
- `<output>/other/` — files classified as non-invoice financial documents

### 2. Extract text from each file

For every file in the input directory:

- **PDFs** → run `pdftotext` (e.g. `pdftotext -layout <file> -`) to get plain text. Capture to a string.
- **Images** (JPG, PNG, TIFF, etc.) → run `tesseract <file> -` (OCR) to get plain text. Capture to a string.

If extraction yields empty output, treat the file as "other" (not an invoice) and move on.

### 3. Classify as invoice vs. other

Scan the extracted text for invoice identifier keywords. A document is an invoice if its text contains any of (case-insensitive, with word boundaries):

- `Invoice`
- `Total`
- `Amount Due`

Match any one of these → invoice. None found → other. Move the file to the corresponding output folder.

### 4. Extract amount fields from invoices

For each invoice, scan the text for amount patterns. Prefer pattern matching against the same line or the line following the keyword.

**Total amount (`total_amount`)** — search for, in this priority order:
1. `Total:` (or `Total Due:`, `Grand Total:`)
2. `Amount Due:`

Take the **first match**. If both `Total` and `Amount Due` are present with **different** values, use only the `Total` value and discard the `Amount Due` value. If `Total` is absent, fall back to `Amount Due`. If both are absent, set `total_amount = 0`.

**VAT amount (`vat_amount`)** — search for:
- `VAT:`
- `Tax:`
- `GST:`

Take the first match. If none of these keywords are present, set `vat_amount = 0`.

Numeric values: strip currency symbols and thousands separators (commas, spaces) before parsing as a float. Do not assume a particular currency.

### 5. Build the summary CSV

Write a CSV at `<output>/summary.csv` with these columns, in this exact order:

```
filename,total_amount,vat_amount
```

- One row per invoice, using the original filename.
- Non-invoice files get **no** row.
- After the last invoice row, append a final row:

```
total,<sum of total_amount>,<sum of vat_amount>
```

The final `total` row's filename cell is the literal string `total` (no extension).

## Edge cases to handle

- **Conflicting totals**: when `Total:` and `Amount Due:` differ, trust `Total:` only.
- **Missing VAT**: emit `0` rather than skipping the row or leaving the cell blank.
- **Unreadable files** (empty OCR/PDF output): classify as other; do not appear in CSV.
- **Multiple matches on one document**: take the first match per field.
- **Currency symbols / formatting**: normalize to a plain decimal number; do not hard-code a currency symbol.

## Verification checklist

- [ ] Every input file is in exactly one of the two output folders (or skipped if unreadable).
- [ ] Every invoice produces exactly one CSV row with two numeric columns.
- [ ] Every non-invoice file produces zero CSV rows.
- [ ] The CSV's final row is `total,<sum>,<sum>`.
- [ ] Numeric values are plain decimals, no currency symbols.