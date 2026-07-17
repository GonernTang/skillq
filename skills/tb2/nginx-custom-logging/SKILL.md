---
name: nginx-custom-logging
description: Count tokens in a Hugging Face dataset, respecting domain definitions from the dataset card and using proper tokenization settings (add_special_tokens=False). Verify counts via per-domain breakdown.
---

# Count Tokens in a Hugging Face Dataset

Reusable procedure for accurately counting tokens in a Hugging Face dataset, especially when domains are defined in the dataset card and multiple configs (default + metadata) exist.

## Steps

1. **Read the dataset card (README)** – Discover how domains are defined, which config to use, and any special instructions for combining text fields.

2. **Load both the default and metadata configs** (if available) to align row indices.  
   Example:  
   `dataset = load_dataset("org/name", split="train")`  
   `metadata = load_dataset("org/name", "metadata", split="train")`

3. **Determine the domain of interest** from the dataset card. Apply filtering using the metadata config (e.g., domain labels). Ensure the filtering logic exactly matches the README's domain list.

4. **Combine text fields per row** – For conversation-style data, join system prompt and all turn values with `\n`.

5. **Tokenize using `add_special_tokens=False`** – Some tokenizers treat `add_special_tokens=False` identically to `True`; verify on a sample to avoid double-counting.

6. **Count tokens** – Sum the token counts over all filtered rows.

7. **Cross-check** by re-running with an explicit per-domain breakdown. Manually verify that the domain-filtering logic exactly matches the README's domain list.

## Notes

- Use `AutoTokenizer.from_pretrained("model-name")` to load the tokenizer.
- For large datasets, iterate in batches and accumulate counts.
- If the dataset card specifies special concatenation rules (e.g., separate domains), follow those exactly.
- The final answer should be written to `/app/answer.txt` with a clear summary.