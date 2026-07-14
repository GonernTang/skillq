---
name: count-dataset-tokens
description: Count total tokens across a filtered subset of a HuggingFace dataset using a specified tokenizer, combining row text fields and writing the integer total to an output file.
---

# Count Tokens in a HuggingFace Dataset Subset

Use this skill when asked to count tokens across a filtered subset (e.g., by topic/domain) of a HuggingFace dataset using a specific tokenizer, and write the integer total to an output file.

## Inputs to identify

From the task, confirm:
- **Dataset identifier** on HuggingFace (e.g., `Maxwell-Jia/AIME_2024`).
- **Config / subset name** if the dataset uses multiple configs — pick the one that exposes the column you need for filtering (often `metadata`, `default`, or the named subset).
- **Filter column** and **target values** (e.g., `domain` ∈ {`biology`, `chemistry`, `physics`}).
- **Tokenizer** identifier (e.g., `meta-llama/Llama-3.1-8B-Instruct`, `gpt2`).
- **Text fields** to combine per row (e.g., `reasoning` + `solution`).
- **Separator** between fields (typically `\n`).
- **Special tokens policy** — `add_special_tokens=True` or `False` (match what the task implicitly or explicitly requires).
- **Output file path** (e.g., `/app/answer.txt`).

## Procedure

```python
from datasets import load_dataset
from transformers import AutoTokenizer

dataset = load_dataset(DATASET_ID, CONFIG_NAME, split=SPLIT)

# 1) Filter the dataset to the desired subset
def keep(example):
    return example[FILTER_COLUMN] in TARGET_VALUES

filtered = dataset.filter(keep)

# 2) Load the tokenizer
tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_ID)

# 3) Combine fields per row, tokenize, sum lengths
total = 0
for example in filtered:
    parts = [example[field] for field in TEXT_FIELDS]
    text = "\n".join(parts)
    ids = tokenizer.encode(text, add_special_tokens=ADD_SPECIAL_TOKENS)
    total += len(ids)

# 4) Write total to output file
with open(OUTPUT_PATH, "w") as f:
    f.write(str(total))
```

## Key notes

- Use the **config name** in `load_dataset` when present — many datasets put filter columns (domain, subject, source) in a separate config like `metadata`.
- Keep filter logic close to a plain equality/membership check; do not rely on the dataset's own `filter` helpers unless verified.
- Joining fields with `\n` is the safest default; only use a different separator if the task specifies one.
- If the task wording implies "tokens as defined by the tokenizer" without specifying special tokens, `add_special_tokens=False` is usually expected for raw token counts; otherwise default to `True`.
- Output must be the **integer total** only — no labels, no JSON, no trailing whitespace required. Write exactly `str(total)`.
- Run inside the same environment the task lives in (e.g., `/app` for sandboxed jobs); ensure `datasets` and `transformers` are installed.

## Verification

After running:
- Print or log `len(filtered)` and `total` to confirm the count is plausible.
- Re-read the output file and confirm it parses as an integer.
- If `total == 0`, re-check the filter column and config — the most common failure is loading the wrong config.