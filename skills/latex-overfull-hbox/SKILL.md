---
name: latex-overfull-hbox
description: Iteratively fix LaTeX "Overfull \hbox" warnings by substituting long words with shorter synonyms from a provided list. Trigger when a LaTeX document compiles with overfull hbox warnings and a synonym list is available to shorten offending words.
---

# Fixing LaTeX Overfull Hbox Warnings via Synonym Substitution

When a LaTeX document produces `Overfull \hbox` warnings, the warnings will
NOT resolve on their own — they persist across recompiles until the source
text actually fits within the line's horizontal tolerance. The only way to
clear them is to shrink the offending content. If a synonym list is
available, replace long words with shorter equivalents from that list.

## Procedure

1. **Compile** the document and capture the full log. Search for every line
   matching `Overfull \hbox` — each warning names a source line number
   (e.g., `Overfull \hbox (12.345pt too wide) in paragraph at lines 124--127`).
2. **Locate the paragraph** for each warning using the reported source
   line range. Read the paragraph, not just the single line — TeX reports
   where the overfull *paragraph* starts, and the bad break often sits at
   its last line.
3. **Identify long words** in that paragraph (heuristic: words ≥ 8 chars,
   or words containing long token sequences without easy breakpoints).
4. **Cross-reference the synonym list.** For each long word, find a
   shorter synonym. Prefer the shortest synonym that preserves meaning.
5. **Replace the word in-source** with the shorter synonym. Replace ONE
   word per pass; do not batch — that way, if a warning persists, you
   know which substitution was insufficient.
6. **Recompile.** Re-scan the log for `Overfull \hbox`. Expect the warning
   to either vanish or shift to a different line.
7. **Iterate** steps 2–6 for every remaining warning until the log
   contains zero `Overfull \hbox` lines.

## Diagnostic checklist

Run these BEFORE claiming success:

1. `grep -c "Overfull \\\\hbox" <log>` returns **0**. A non-zero count
   means warnings remain; do not stop.
2. The synonym substitution actually shortened the word — verify the
   replacement string has strictly fewer characters than the original
   (or fewer TeX-stretched tokens). Substituting a same-length or
   longer word will not help and indicates a wrong pick from the list.
3. Every warning's reported source line range was visited. Walk the
   grep output and confirm each `(N--M too wide)` line maps to a
   paragraph that was read and edited.
4. The synonym came from the provided list, not invented. Invented
   synonyms risk changing meaning or being unavailable in the
   document's language.

## Stop signal

If you have replaced words in 3 different warnings using available
synonyms and the log STILL shows the same warning count (or the same
warning persists after every substitution):
- **STOP** — you are in a debug spiral on the same architecture.
- Re-read the synonym list and confirm the words you picked really
  are shorter. If they are, the overfull may be structural (long
  unbreakable URL/math/cite token) and synonym substitution alone
  cannot fix it — escalate to the user with the exact source line
  and word, rather than thrashing the document further.

## Common pitfalls

- Stopping after the first compile: one fix rarely clears all warnings.
- Editing only the line number TeX prints — TeX reports the *paragraph*
  start; the offending break is usually one line above that.
- Replacing a long word with a synonym that is itself long (or longer).
- Using `\\` or `\linebreak` to mask the warning instead of fitting
  content — this hides the issue and breaks justification downstream.
- Skipping warnings near the end of the document because they "look
  small" — a 1pt overfull still counts and still ships.

## Script

A reference driver for the parse → locate → substitute → recompile loop
is provided in `scripts/fix_overfull.sh`. It greps the log for warnings,
prints the offending source paragraphs, and exits non-zero while any
warning remains — wire it into your build as a gate.