---
name: dataset-token-counting
description: Count tokens in a Hugging Face (or similar tabular) dataset filtered by a user-specified domain/topic, with semantic mapping from the user's coarse domain term to the dataset's actual column subcategories. Use when asked to tally, count, or aggregate tokens across dataset rows that match a category name.
---

# Counting tokens in a dataset by user-specified domain

When a user asks "how many tokens are in dataset X for topic Y", the obvious approach — filter rows where the topic column literally equals Y — silently misses most of the data because dataset taxonomies are usually **finer-grained** than the user's vocabulary. "Science" in the user's head is "biology + chemistry + physics + …" in the column.

## Procedure

1. **Inspect the dataset schema and the relevant column first.**
   - Load the dataset (e.g. `datasets.load_dataset(...)`).
   - Print the column names and the **unique values** (or at least the value counts) of the category/label column the user mentioned.
   - Confirm which column holds the text and which holds the category.

2. **Build a semantic mapping from the user's term to column values.**
   - Treat the user's domain name as a *concept*, not a literal. Enumerate every column value that reasonably belongs under it (e.g. "science" → {biology, chemistry, physics, …}).
   - When in doubt about scope, ask the user. Do not silently pick one subcategory.
   - The matched set should be explicit (a Python set/list) so it is reviewable.

3. **Load the tokenizer defensively.**
   - For community / non-default transformer tokenizers, pass `trust_remote_code=True` to `AutoTokenizer.from_pretrained(...)`. A silent failure to load the tokenizer is the most common reason the final number is zero or wrong.
   - Verify the tokenizer loaded by tokenizing a short sample string and printing the resulting IDs.

4. **Filter and aggregate.**
   - Filter rows whose category column value is in the matched subcategory set. Print the filtered row count and a sample of matching category values before counting.
   - Tokenize each row's text (no special tokens, or with — be consistent and document which).
   - Sum token counts across the filtered subset. Report both the row count and the token total.

5. **Write the result to disk in a documented format.**
   - Save at minimum: the dataset identifier, the column used for filtering, the matched subcategory list, the tokenizer name, the row count, and the total token count. JSON or a small text report both work.
   - Print the absolute path of the output file when finished.

## Diagnostic checklist

Before committing to the full count, run these checks:

1. **Subcategory enumeration check.** Print all unique values of the category column. Does the user's term match any value literally? If not, list every value that semantically falls under the user's term and confirm the set is non-empty. If the set is empty, STOP and ask the user — do not proceed with an empty filter.
2. **Filter sanity check.** After filtering, print `len(filtered)` and a sample of the `category` values that survived. The set of surviving categories must equal (a superset of) the intended mapping. If it does not, the mapping is wrong; fix it before counting.
3. **Tokenizer round-trip check.** Tokenize the string `"hello world"` and assert the result has length > 0 and is a `List[int]`. If this fails, the tokenizer did not load correctly (likely missing `trust_remote_code=True`) and every downstream token count is unreliable.
4. **Small-scale count check.** Run the full pipeline on a 10-row slice first and confirm the per-row token counts look plausible (single-digit to low-thousands for typical English text). Anomalies here predict anomalies at full scale.

## Stop signal

If after two attempts the diagnostic checks still fail — e.g. the filtered set is empty, the tokenizer won't load even with `trust_remote_code=True`, or the per-row counts are obviously wrong (0 or in the millions) — **stop iterating on the same code path**. Instead:

- Re-read the dataset's README / card to learn the taxonomy directly.
- Ask the user to confirm the intended scope (which subcategories, which text column, which tokenizer).
- Consider whether the requested dataset is the right one at all (a different split or config may have the category column).

Three or more "tweak the filter and re-run" attempts without progress is a debug spiral on this architecture. Change the information source (README, user) before changing the code again.

## Common pitfalls

- Treating the user's domain label as an exact-match filter when the dataset uses subcategories.
- Forgetting `trust_remote_code=True` for tokenizers with custom code (e.g. many Llama, StarCoder, and community models).
- Counting tokens on the *whole* dataset because the filter silently matched nothing.
- Reporting a number without recording the matched subcategory list, making the result unverifiable.
- Tokenizing with `add_special_tokens=True` in one run and `False` in another — pick one and document it.