---
name: embedding-retrieval
description: Avoid the dense-retrieval off-by-one trap when finding the k-th highest similarity document from a line-delimited file. Use when a task asks "find the k-th most similar line/document via embeddings" and the output must be the exact original line (including any leading index prefix). Covers loading a sentence-transformers model with revision, computing normalized embeddings, cosine similarity, sorting, and selecting sorted_indices[k-1]. Skips subtle index-versus-rank bugs.
---

# embedding-retrieval

## When to use

- Task: identify the *k*-th highest-similarity document from a file where each line is a separate document (one-doc-per-line).
- Output must be the **exact original line bytes** written to an output file (not a recomputed variant).
- Model is a HuggingFace sentence-transformers checkpoint that must be loaded with an explicit `revision`.

If you are NOT selecting a *k*-th ranked item, or the output is not expected to be the verbatim original line, this skill does not apply.

## Procedure

1. **Read the file preserving bytes.** Open the file in text mode with `splitlines(keepends=False)` only AFTER confirming there is no leading numeric prefix you need to keep. If the file uses `"1\ttext"`, `"2\ttext"` style indices, **strip the index off but remember the original line content**. Store both `documents[i]` (text only) and `raw_lines[i]` (verbatim) in two parallel lists.
2. **Load the model with revision.** `SentenceTransformer(model_name, revision=revision)` — never omit the revision when one is provided; failing it changes the embedding space silently.
3. **Compute NORMALIZED embeddings.** `encode(documents, normalize_embeddings=True)`. Without normalization the cosine function and the dot product diverge; pick one and stay consistent.
4. **Score with a single similarity function.** Use `util.cos_sim(query_emb, doc_embs)` (or torch/numpy dot product after normalization). Do NOT mix `cdist`, `pearson`, or hand-rolled loops.
5. **Sort ONCE, descend.** `sorted_indices = scores[0].argsort(descending=True).tolist()`. For the k-th highest, the answer index is `sorted_indices[k-1]` (0-based; off-by-one here is the most common bug).
6. **Validate by printing BEFORE writing.** Print (a) the chosen index, (b) the score, (c) the first ~80 chars of `raw_lines[idx]`, (d) the top-5 `(rank, score, snippet)` table. Only proceed if snippet matches what you'd expect.
7. **Write the verbatim original line.** `output.write(raw_lines[idx])` — write the full `raw_lines[idx]`, NOT a recomputed string. If the file ended with a newline, preserve it; if not, don't add one.

## Diagnostic checklist

Run these BEFORE writing the output file:

1. **Empty / single-doc sanity**: run the pipeline with `k=1` against a 2-line file where line 2 is clearly the answer. Output should equal line 2 exactly.
2. **k=1 vs k=N cross-check**: for *N* <= 4, verify that `sorted_indices[0]`, `sorted_indices[N-1]` correspond to your intuitive top/bottom picks by eyeballing the file.
3. **Index offset probe**: print `sorted_indices[k-1]` AND `sorted_indices[k]` AND `sorted_indices[k]`-then-minus-one. Confirm the printout says the expected line number (1-based if file is 1-based; 0-based otherwise).
4. **Verbatim write**: after writing, re-read the output file and `assert output.read() == raw_lines[idx]`. If the assertion fails, you regenerated the string instead of writing the preserved line.

## Stop signal

If you have rebuilt the similarity / sort / selection block **twice** and the printed snippet still does not match the expected line, STOP — do not write a third version. Instead:

1. Dump the full `scores` vector to disk and inspect the top-10 ranks manually.
2. Verify the model's `revision` was applied (`model.modules()[0].auto_model.config._name_or_path` should contain the revision).
3. Re-check the file: are lines blank? Is there a header row you forgot to skip? Does the file use `\r\n` and your `splitlines()` collapsed it?

Past two failed attempts on the same architecture, the bug is almost certainly in (a) the file-read step, (b) the revision, or (c) a silent re-encoding. Switching to TF-IDF or BM25 will not save you — fix the embedding pipeline.

## Common pitfalls

- **0-based vs 1-based confusion**: `sorted_indices[k-1]` is the *k*-th highest, never `sorted_indices[k]`.
- **Stripping the index, then forgetting you did**: you wrote `documents[i]` (text-only) when the prompt asked for the raw line — output is correct content but missing the leading "123\t" prefix.
- **Mutating the line**: calling `.strip()` or `.lower()` on `raw_lines` after persisting it. Persist early; transform a copy.
- **Off-by-one in `k`**: prompt says "k-th" where k is 1-indexed but your code is 0-indexed. Subtract 1 exactly once, at the point of indexing.
- **Noisy top-rank ties**: when top scores are within 1e-4, sort stability matters; use `kind='stable'` if results jitter.