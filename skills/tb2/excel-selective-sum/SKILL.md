---
name: excel-selective-sum
description: Compute a sum from an Excel file by including only specified columns and excluding others. Use when the user wants totals for a subset of categories (e.g., sum food sales but exclude drinks).
---

# Excel Selective Column Sum

## When to use
- User wants a numeric total from an `.xlsx`/`.xlsm` file
- The total must include some columns/categories and exclude others
- Data is tabular with a header row identifying column meaning

## Procedure

1. **Ensure the openpyxl library is available.**
   ```bash
   python -c "import openpyxl" 2>/dev/null || pip install openpyxl
   ```

2. **Load the workbook and select the active sheet.**
   ```python
   from openpyxl import load_workbook
   wb = load_workbook(path, data_only=True)
   ws = wb.active
   ```

3. **Read the header row and build an include-set.**
   - Pull `header = [cell.value for cell in ws[1]]`.
   - Decide which header tokens designate *included* categories and which designate *excluded* categories. Use substring or exact matching against the lowercased header values.
   - Collect the set of **column indices (1-based)** whose header matches an *included* token. Excluded columns are skipped entirely.

4. **Iterate data rows and sum only included columns.**
   - Skip the header row. For each subsequent row, walk only the included column indices and accumulate `value or 0` (treat `None`/blank as 0; cast numerics directly).
   - Guard against non-numeric cells with `try/except` (e.g., `ValueError`, `TypeError`) and skip them.

5. **Format and print the result.**
   ```python
   print(f"{total:.2f}")
   ```
   Always emit a float with exactly two decimal places.

## Reusable template

```python
from openpyxl import load_workbook

path = "<PATH_TO_XLSX>"            # the Excel file
include_keywords = ["food", "meal"]  # headers containing any of these are summed
exclude_keywords = ["drink", "beverage"]  # headers matching these are skipped

wb = load_workbook(path, data_only=True)
ws = wb.active

header = [c.value for c in ws[1]]
include_idx = [
    i for i, h in enumerate(header, start=1)
    if h and any(k in str(h).lower() for k in include_keywords)
    and not any(k in str(h).lower() for k in exclude_keywords)
]

total = 0.0
for row in ws.iter_rows(min_row=2, values_only=True):
    for i in include_idx:
        v = row[i - 1]
        if v is None:
            continue
        try:
            total += float(v)
        except (TypeError, ValueError):
            pass

print(f"{total:.2f}")
```

## Customization points
- `include_keywords` / `exclude_keywords`: tune to the user's actual category names.
- Use `wb[sheetname]` instead of `wb.active` when the target sheet is not the first/active one.
- If the workbook uses formulas and you need cached values, keep `data_only=True`.

## Pitfalls
- Header text casing varies — always lowercase before substring matching.
- Some "drink" columns may live at the start or end of the sheet; do not assume position.
- Empty cells are `None`; treat as 0, do not raise.
- Keep excluded columns out of the include-set to begin with rather than subtracting post-hoc — cleaner and avoids double-counting errors.