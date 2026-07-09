```markdown
---
name: polyglot-c-py
description: Recover all records from a SQLite WAL-mode database by manually parsing the WAL file and the base database file, build Cython extensions while preserving an existing NumPy installation, ensure build verification includes exact task-specified steps, configure Nginx custom log formats correctly, design CoreWars warriors that defeat diverse opponents including decoy and self-clearing strategies, perform Raman spectral fitting of graphene with European decimal handling, retrieve the top-performing model from the Scandinavian MTEB leaderboard by scraping the official Hugging Face Spaces page, reverse-engineer a programmatic image by extracting per-pixel color values and fitting mathematical models to accurately reconstruct the scene, retrieve the k-th highest cosine similarity document using a SentenceTransformer model with revision and guard rails for index bounds and missing indices, perform model extraction on one-layer ReLU networks from black-box queries by detecting gradient discontinuities along random 1D lines, clustering jump vectors, and sign-aligning to recover hidden weight rows, wait for legacy OS QEMU VM guest boot by polling the VNC framebuffer and optionally confirming guest reaction via QEMU monitor keystrokes, implement Adaptive Rejection Sampler (Gilks & Wild, 1992) in R with exact function names and file paths, build date-range severity summaries from log files, recover passwords from forensic data with strict output formatting and constraint verification, and fix overfull hbox warnings in LaTeX via synonym replacement with strict guard rails against altering non-synonym words.
---

# SQLite WAL-mode Recovery

[existing content unchanged]

## Building Cython Extensions with NumPy Version Control

[existing content unchanged]

## General Build Verification

[existing content unchanged]

## Nginx Custom Log Format

[existing content unchanged]

## CoreWars Warrior Design (Winning Average)

[existing content unchanged]

## Raman Spectral Fitting of Graphene

[existing content unchanged]

## Scandinavian MTEB Leaderboard Retrieval

[existing content unchanged]

## Embedding Retrieval with SentenceTransformer

[existing content unchanged]

## Programmatic Image Reverse-Engineering

[existing content unchanged]

## Model Extraction of One-Layer ReLU Networks

[existing content unchanged]

## Legacy OS QEMU VM Boot Verification

[existing content unchanged]

## Adaptive Rejection Sampler (Gilks & Wild, 1992)

[existing content unchanged]

## Log File Date-Range Severity Summary

[existing content unchanged]

## Site-Directed Mutagenesis Insertion Primer Design (NEB Q5 Kit)

[existing content unchanged]

## Password Recovery from Forensic Data

When recovering a password from forensic data (e.g., corrupted archives, memory dumps, or log remnants), follow the format and verification steps below to avoid verifier rejection.

### Output Format

- **Strictly follow the output format specified in the task description.**  
  If the original file contained a line like `PASSWORD=XXXXXXXXXX`, write the complete line (including `PASSWORD=`) to the output file, unless the task explicitly states to write only the value.
- **Always double-check** the written output against the exact wording of the expected format. If a verifier is available, submit a trial with the formatted output before finalizing.

### Reconstruction and Validation

1. **Extract and reconstruct** the password from the available corrupt data (e.g., by applying known constraints such as prefix, suffix, character set, length).
2. **Verify the resulting password against all known constraints:**
   - Prefix / suffix match
   - Character set (e.g., only uppercase letters and digits)
   - Exact length (including any prefix like `PASSWORD=`)
3. **Cross-reference with stored checksums** if available (e.g., CRC from a ZIP local file header). Remember that constraints alone may produce multiple candidates; use additional heuristics (e.g., matching CRC, file metadata, context from other fragments) to disambiguate.
4. **Write the formatted output** (as per step above) to the specified output file path (often `/app/recovered_passwords.txt`). Ensure the file contains only the required line(s) and no extraneous text.

### Implementation Notes

- Use only standard Python libraries (`os`, `struct`, `zlib`, `binascii` for CRC) – no external dependencies.
- If reconstructing from a corrupted ZIP, parse the local file headers to extract the stored CRC and data, then apply constraint-based correction to the password field.
- Validate the final password by recomputing the CRC of the corrected data (if applicable) and checking against the stored CRC. If they do not match, the candidate is incorrect – fall back to other heuristics.
- Do not output the password before confirming all constraints and checksum matches (when available). If ambiguity remains, report the candidates with associated confidence and let the task’s verifier decide (unless the task requires a single answer).

## Overfull Hbox Warning Fix via Synonym Replacement

When fixing overfull `\hbox` warnings in LaTeX by replacing words with synonyms from a provided synonym file (e.g., `synonyms.txt`), follow these strict rules:

1. **Only replace words/phrases that appear in the synonym file.** The synonym file is assumed to contain lines of the form `original_word_or_phrase → replacement_word_or_phrase`. Only substitute an exact match of the original text (case‑sensitive, per the specification) with the replacement.
2. **Do not alter any surrounding words.** Articles (`a`, `an`, `the`), prepositions (`of`, `in`, `to`, etc.), punctuation, and whitespace must remain exactly as in the original text. For example, if the original has `an intimate revelation` and the synonym file maps `intimate → close`, replace only `intimate` with `close`, yielding `an close revelation`. Do not change the article even if it creates a grammatical disagreement – the constraint is that only synonym‑file entries are modified.
3. **Guard rail:** Before finalizing each replacement, compare the old and new text at the location of the change. Confirm that no other characters were added, removed, or modified. If the change affects any character outside the exact match of the original word/phrase, revert and report the error.
4. **Work only on the specified LaTeX input file** (e.g., `input.tex`). Do not modify the synonym file or auxiliary files.
5. **Verify** that each replacement reduces the overfull box width or eliminates the warning. If a replacement does not help, try the next synonym candidate (if multiple synonyms exist for the same word). Multiple replacements per warning are allowed, but each must individually satisfy rules 1–3.
```