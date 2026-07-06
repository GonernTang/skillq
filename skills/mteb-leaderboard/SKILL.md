---
name: mteb-leaderboard
description: Programmatic retrieval of top embedding models from the MTEB leaderboard for a specified language subset (e.g. Scandinavian, Nordic, MTEB(DK), MTEB(NO), MTEB(SV)). Use when the task is to find the best embedding model for a non-English or low-resource language, or to cite current MTEB rankings. Do NOT rely on plain web search or scraping the rendered MTEB page — rankings are loaded dynamically and default to English.
---

# Querying the MTEB leaderboard for a language subset

The public MTEB leaderboard is a Gradio app on a Hugging Face Space that
loads its table via JavaScript. Plain `WebSearch` / `WebFetch` of the page
URL returns the static shell, with no rows, and the default filter is
English — so a query like "best embedding model for Swedish" returns
unrelated blog posts. For language-specific subsets you must bypass the
HTML and hit the data layer.

## Procedure

1. **Identify the exact MTEB benchmark slug for the language group.**
   Per-language subsets follow the pattern `MTEB(<ISO-or-name>)`, e.g.
   `MTEB(SV)`, `MTEB(NO)`, `MTEB(DK)`, `MTEB(FI)`. Confirm the slug exists
   in the `mteb` Python package's task registry before treating it as real.
2. **Prefer the `mteb` Python library over scraping.**
   Install with `pip install mteb` and use the leaderboard API
   (`mteb.load_results`, `mteb.get_leaderboard`, or the per-task
   `Benchmark` helper) to pull structured results for the slug in step 1.
   This returns a tidy DataFrame and avoids HTML parsing entirely.
3. **Fallback: query the Hugging Face dataset that backs the Space.**
   The leaderboard Space is backed by a dataset (look for a `mteb/*`
   dataset that exposes per-language scores). Load it via
   `huggingface_hub` / `datasets` and filter rows to the language subset
   and the metric of interest (task average, or a specific task class
   like retrieval / classification).
4. **Last resort: authoritative secondary sources.** GitHub repositories
   or recent technical reports that publish pre-compiled tables for the
   subset (e.g. regional embedding benchmarks). Treat these as
   point-in-time snapshots and note the date — MTEB rankings move
   frequently.
5. **Validate the output before returning it.** See checklist below.

## Diagnostic checklist

Run these checks BEFORE committing to a model name in your answer:

1. **Format check**: the model identifier must be in `org/model_name` form
   (e.g. `intfloat/multilingual-e5-large`). A bare display name, a URL,
   or a "model card" link is not a valid identifier for downstream use
   (download, `SentenceTransformer`, `transformers.AutoModel`).
2. **Language coverage check**: confirm the cited model has actually been
   evaluated on the target language subset. A model that tops the global
   English benchmark but has no row in `MTEB(<lang>)` is the wrong answer
   — do not promote it.
3. **Score-source check**: cite the metric and the date. "Best on MTEB"
   without a benchmark slug, metric, and snapshot date is unactionable.
4. **Cross-source check**: if a model appears at the top in the `mteb`
   library AND in a secondary table, treat the answer as confirmed. If
   only one source surfaces it, flag the answer as single-sourced.

## Stop signal

- If after 2 attempts you still cannot retrieve structured rankings for
  the target language subset (e.g. the slug does not exist, the dataset
  is private, the library errors), **stop** and report the gap explicitly
  to the user — do not silently fall back to a global English-only
  ranking and call it the answer for the requested language.
- If the top model from the programmatic source has no row in the
  per-language subset, **stop** and re-filter on the correct slug
  rather than reporting the global winner.
- Do not iterate on web-search queries of the public leaderboard URL
  past the first failure — the page is client-side rendered and will
  not start returning rows. Switch data source instead.

## Common pitfalls

- Searching the public leaderboard URL with a general web search and
  treating the absence of results as "no model exists" — the page is
  JS-rendered, not missing.
- Returning the global English leader winner as the answer to a
  non-English subset question. MTEB has explicit per-language subsets;
  use them.
- Returning a model name that exists on the leaderboard but in a format
  that downstream code (Hugging Face `from_pretrained`, sentence-transformers)
  cannot resolve. Always normalise to `org/model_name`.
- Citing an undated ranking. MTEB moves monthly; an answer without a
  snapshot date is stale on arrival.