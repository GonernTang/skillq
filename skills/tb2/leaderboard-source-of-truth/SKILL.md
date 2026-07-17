---
name: leaderboard-source-of-truth
description: When answering "top/ranked/best X" questions that involve a temporal cutoff, always go to the canonical leaderboard source, filter there, and verify dates — never trust web search snippets or secondary summaries.
---

# Source-of-truth leaderboard lookup

When a user asks "what was the top X on leaderboard Y as of date Z", do not rely
on web search snippets, blog posts, or LLM recall. Those sources frequently
include models/items that did not exist before the cutoff (training-data
contamination) or misrank items that have since been surpassed.

## Diagnostic checklist (run BEFORE answering)

Run these checks in order. If any fails, reset and use the next step's recovery action.

1. **Identify the canonical primary source.** Is there an official leaderboard
   (e.g., a Hugging Face Space, official ranking page, or competition site)?
   If yes, you MUST fetch directly from it. If you cannot name the canonical
   URL, you have not yet established a source of truth — stop and find it.
2. **Apply the filter at the source.** Use the source's own filter UI/params
   (language, task subset, category, time window). Do NOT transpose filters
   from secondary write-ups — the filter vocabulary must match what the
   source exposes.
3. **Sort by the exact target metric the user asked about.** Read the column
   header verbatim from the source table (e.g., "Mean (Task)", "Score",
   "ELO", "Rank"). Do NOT assume a default metric or substitute a proxy.
4. **Date-verify each candidate against the cutoff.** For every model/item in
   the top-N, confirm its release/publication date is strictly before the
   required cutoff. Cross-check via the model's own page, paper, or commit
   history — not via the leaderboard's own timestamp (which can reflect
   later re-submissions).

## Stop signal

If, after retrieval, ANY of the following is true, STOP and restart from
the top of the checklist:

- The answer came from a web search snippet, a cached page older than the
  cutoff, or an LLM-generated summary rather than a direct fetch of the
  canonical leaderboard.
- You cannot name the exact URL you fetched the table from.
- The top-ranked item's release date is on or after the user's cutoff date.
- You sorted by a metric whose name differs from what the user asked about,
  even if "it seems close".

**Reset action:** re-fetch the canonical leaderboard URL from scratch,
re-apply the filter explicitly, re-sort by the user's stated metric, and
re-verify dates. Do not patch a flawed prior answer — discard it.

## Notes

- Prefer the source's structured export (CSV/JSON/API) over scraping the
  rendered table when available — it removes a class of parse errors.
- Cutoff-aware ranking is the default mode for "as of date T" questions;
  if the user did not name a date, ask before defaulting to "today".
- Secondary sources (blog posts, recap articles) are useful only to discover
  the canonical URL — never as the answer itself.