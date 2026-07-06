---
name: count-dataset-tokens
description: Count tokens in a subset of a Hugging Face dataset using a custom tokenizer and write the integer total to an answer file. Use when the task is to filter a HF dataset by some criterion (domain, split, label, etc.), concatenate selected text fields per row, tokenize with a specified tokenizer, sum the token counts, and persist the bare integer result.
---

# Count Tokens in a Filtered Hugging Face Dataset Slice

When asked to compute a total token count over a subset of a Hugging Face dataset (filtered by any criterion — domain, language, split, label, tag), tokenized with a specific pretrained tokenizer, and to write the result as a bare integer, follow this procedure.

## When to use this skill

- The data source is a Hugging Face dataset (or any `datasets`-compatible source).
- A subset is required (filter on a column such as `domain`, `lang`, `label`, `task`).
- The token count must use a specific tokenizer (e.g., `AutoTokenizer.from_pretrained(...)`).
- The deliverable is one integer written to a file (no formatting, no commas, no units).

## Procedure

1. **Install dependencies** if not already present:
   - `pip install transformers datasets`
   - For tokenizer-only operation, PyTorch is *not* required; the tokenizer call `tokenizer.encode(text)` works without the model weights or the `torch` backend.

2. **Inspect the dataset schema first.** Load a small slice to discover which columns hold text and which column holds the filter criterion. When the dataset exposes multiple configurations/subsets, load the lightweight `metadata` (or equivalent) subset if available — its rows usually carry the filter attribute without heavy payload columns.

   ```python
   ds = load_dataset(DATASET_NAME, "metadata", split="train")
   print(ds.column_names)
   ```

3. **Identify the filter column and the text column(s).** Read the dataset README / dataset card if the column meaning is unclear. Guard rails:
   - Domain labels are sometimes strings, sometimes integer IDs — match the actual dtype.
   - Some datasets ship multiple reasoning/answer fields; pick the ones meant to be counted.

4. **Filter rows by the criterion:**

   ```python
   subset = ds.filter(lambda row: row["<filter_col>"] in TARGET_VALUES)
   ```

5. **Load the tokenizer** specified by the task. If a model id is given, use `AutoTokenizer.from_pretrained(model_id)`. Confirm encoding is fast and consistent across calls (no chat-template wrapping unless the task demands it — raw `encode` of the field text is usually what's wanted).

6. **Build per-row text and accumulate token counts:**

   ```python
   total = 0
   for row in subset:
       parts = [str(row[col]) for col in TEXT_COLUMNS if row.get(col)]
       text = "\n".join(parts)
       total += len(tokenizer.encode(text))
   ```

   Notes:
   - Concatenate the relevant text fields with a separator (`"\n"` is a safe default) so a multi-field reasoning+answer gets counted as a single document.
   - Skip rows where the field is missing/empty rather than failing.

7. **Write the result** as a bare integer (no spaces, no commas, no newline decorations beyond a trailing `\n` if desired):

   ```python
   Path(ANSWER_PATH).write_text(str(total))
   ```

   If the task specifies a shell variable like `$ANSWER_FILE` for the output path, expand it before writing.

## Common pitfalls

- **Wrong subset config.** A dataset may have several `config_name`s; loading the heavy one when only metadata is needed wastes time and bandwidth.
- **Counting metadata columns.** Filter on the metadata subset so rows without the criterion never load the heavy payloads.
- **Tokenizer-PyTorch coupling.** Some setups assume `torch` is installed even for encode-only calls; if `from_pretrained` fails, install the latest `transformers` first and retry.
- **Multiple text fields.** If both reasoning and solution exist, the task usually wants both — concatenate, don't pick one arbitrarily.
- **Formatting the answer.** A bare integer is required; writing `"1,234,567"` or `"1234567 tokens"` will fail the checker.

## Verification

Before declaring done:
- `print(total)` once during development to sanity-check the magnitude.
- Re-read the ANSWER file and confirm it parses as an integer (`int(open(p).read())`).