---
name: invoice-ocr-processor
description: Batch-process financial documents (PDFs and images) — extract text via OCR, classify each as invoice vs. other, extract total and VAT amounts from invoices, sort files into output folders, and emit a summary CSV with column totals. Also provides guidance for designing CoreWars warriors that meet win-rate thresholds against diverse opponent types. This skill is intended for financial document processing and CoreWars warrior design.
---

# Invoice OCR Processor

Reusable procedure for batch-processing a mixed folder of financial documents and producing a structured summary.  
Also provides a separate procedure for designing CoreWars warriors that meet specific win-rate thresholds.

## When to use
When given a directory of `.pdf`, `.jpg`, `.jpeg`, or `.png` files and asked to: separate invoices from other documents, extract monetary totals from invoices, and produce a CSV report.  
**Or** when asked to design a CoreWars warrior that must achieve win-rate thresholds against diverse opponent types (stone, paper, vampire, snake, clear).  
**Important:** For financial tasks, this skill is strictly for financial document processing. For CoreWars tasks, it provides the necessary strategic checklist.

## Inputs
- **Financial task:** Source directory containing PDFs and/or images; output directory where `invoices/`, `other/`, and the summary CSV are written.
- **CoreWars task:** None required beyond the specification of opponent types and desired win rates; the warrior is written as a `.red` file.

## Procedure

0. **Verify task scope.** Briefly examine the user’s request.
   - If the request contains at least one of the financial keywords (`invoice`, `receipt`, `bill`, `expense`, `financial`, `payment`), follow the **Financial Procedure** (steps 1–9 below).
   - If the request contains at least one of the CoreWars keywords (`CoreWars`, `warrior`, `stone`, `paper`, `vampire`, `snake`, `clear`, `win rate`, `winning-avg`), follow the **CoreWars Procedure** (step 10 below).
   - Otherwise, immediately raise an error and stop: “This skill is for invoice OCR processing or CoreWars warrior design only – it cannot handle the requested task.”

---

### Financial Procedure

1. **Verify input file types and source directory.** Check that the source directory exists and contains at least one file. Then check that every file in the source directory has one of the allowed extensions: `.pdf`, `.jpg`, `.jpeg`, or `.png`. If the directory is empty, does not exist, or any unrecognised extension (e.g., `.txt`, `.csv`, `.dat`, `.pth`) is found, immediately raise an error and stop — this procedure is only designed for financial documents in PDF or image format.

2. **Inventory the source directory.** List files and bucket them by extension: images (`.jpg`, `.jpeg`, `.png`) vs. PDFs.

3. **Extract text from each file.**
   - **PDFs:** Try direct text extraction first (`pdfplumber` or `PyPDF2`). If the extracted text is empty or near-empty, render each page to an image (`pdf2image`) and OCR the rendered image.
   - **Images:** OCR directly with `pytesseract` using English language config.

4. **Classify as invoice vs. other.** Scan the extracted text case-insensitively for any of: `INVOICE`, `TAX INVOICE`, `INVOICE NUMBER`. If any match → invoice; otherwise → other.

5. **Extract `total_amount` from invoice text.**
   - Regex pattern to find a label followed by a monetary value: `\b(Total|Amount Due|Grand Total|Total Due)\b[^\d]*\$?[\d,]+(?:\.\d{2})?`
   - Prefer the value following `Total` / `Grand Total` over `Amount Due` when both are present and differ — `Total` is treated as the authoritative figure.

6. **Extract `vat_amount`.** Search for `VAT`, `Tax`, or `GST` near a monetary value with the same money pattern. If absent, record `0`.

7. **Sort files into the output directory.**
   - Invoices → `output/invoices/`
   - Other documents → `output/other/`

8. **Write the summary CSV** at `output/summary.csv` with columns:
   - `filename`
   - `total_amount`
   - `vat_amount`
   - One row per invoice (skip non-invoice files).
   - Final row with `filename = "total"` containing the sum of each numeric column.

9. **Verify the source directory is empty** after moving. If files remain, surface them as an error before reporting completion.

---

### CoreWars Procedure

10. **Design a CoreWars warrior** to meet the required win-rate thresholds against stone, paper, vampire, snake, and clear opponents.

    - **Identify opponent types.** Determine which opponent types dominate the battlefield (stone, paper, vampire, snake, clear). Each requires a specific counter.
    - **Design with at least two complementary strategies.** A single stone-bomber is insufficient. Combine strategies such as:
      - Stone bomber (for stone)
      - Replicator / paper (for paper)
      - Imp spiral / vampire hybrid (for snake)
      - Core-clearing loop (for clear)
      - Vampiric pit-trapper (for vampire)
    - **Test against each opponent individually.** Run simulations against each opponent type separately, recording win rates.
    - **Iteratively adjust.** Modify the ratio of processes, bomb placement, or strategy mix based on test results. For example, adding more processes or a second bomber at a coprime step can improve coverage.
    - **Checklist:**
      1. Identify which opponent types are present.
      2. Design a warrior with at least two complementary strategies (e.g., bomber + imp spiral + clear).
      3. Test against each opponent individually and adjust the ratio of processes or bomb placement.

    The final warrior should achieve the specified thresholds (e.g., ≥75% vs stone/paper/vampire and ≥33% vs snake/clear).

## Robustness rules
- Always attempt text extraction before OCR — text-based PDFs are fast and lossless; OCR is a fallback.
- Tolerate varied formatting: amounts may have `$`, commas, or be raw decimals (`1234.56`).
- Missing VAT is `0`, not blank — keeps CSV totals straightforward.
- Move files (not copy) so the source is verifiably drained at the end.

## Common libraries
- `pdfplumber` or `PyPDF2` for PDF text
- `pdf2image` for PDF → image rendering (requires `poppler`)
- `pytesseract` for OCR (requires Tesseract installed)
- `Pillow` for image loading
- Built-in `csv` and `re` modules for parsing and writing

## Output schema (CSV)
```
filename,total_amount,vat_amount
file1.pdf,1234.56,200.00
file2.pdf,890.00,0
total,2124.56,200.00
```