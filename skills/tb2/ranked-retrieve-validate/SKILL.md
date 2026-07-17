---
name: ranked-retrieve-validate
description: Guard-rail for ranked retrieval tasks (e.g., select the k-th highest-similarity document). Prevents off-by-one indexing, unverified corpus line counts, silent whitespace drift on output, and bypassing a canonical domain library's retrieval API.
---

# ranked-retrieve-validate

Use when a task asks you to score, sort, and pick the k-th ranked item (document, passage, candidate) from a corpus using a similarity or relevance model — especially under a benchmark harness that grades exact-string match.

## Diagnostic checklist

Run ALL of these BEFORE writing your final answer:

1. **Parse + count check** — Read the corpus with a method robust to missing trailing newlines (e.g., `f.read().splitlines()`). Verify the parsed count matches the expected document count. If they disagree, the corpus is off-by-one; do not proceed.
2. **Index-base check** — Confirm whether `k` is 1-based in the task language ("k-th", "top-k", "rank k", "highest #k"). Translate to 0-based at the indexing site: descending-sorted selection is `sorted_indices[k-1]`, never `sorted_indices[k]`.
3. **Canonical-API check** — If a domain library tied to the benchmark/task family is installed (e.g., the one whose name appears in the task ID), prefer its built-in retrieval API over a hand-rolled cosine-similarity loop. Hand-rolled paths diverge from the benchmark's expected metric, model revision, or preprocessing and silently mis-rank.
4. **Round-trip byte check** — After writing the output, read it back and confirm it equals the source line byte-for-byte (no added or dropped whitespace, no trailing-newline noise, no quote/encoding drift). A diff here invalidates the answer even when the index was correct.

## Stop signal

STOP and reset whenever any check fails:

- parsed_count != expected_count → reset to the robust parser and re-validate count.
- retrieved_index != k-1 (0-based) → reset the translation step; do not patch the index in place.
- output line differs from source line on re-read → re-extract from the source corpus, do not patch the output string.
- domain library available but bypassed → restart on the library API path.

Do not patch one issue at a time: a single failed check means the whole retrieval path is suspect; restart from the corpus read.

## Notes

- "k-th highest" / "rank k" / "top-k" are 1-based in user language even when code is 0-based.
- Domain libraries often pin model revisions; do not substitute a "similar" revision even if it loads faster.
- Re-reading the output is the last line of defense against whitespace bugs that string-equality graders punish silently.