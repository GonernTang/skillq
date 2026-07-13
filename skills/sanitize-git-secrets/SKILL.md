```
---
name: sanitize-git-secrets
description: Avoid leaving secrets behind when sanitizing a git repository. Also provides guidance for fixing CRLF injection vulnerabilities (CWE-93, http-header-validation), for fitting Raman peaks from graphene data, for MCMC sampling in Stan via RStan, for building a gRPC key-value store service, for MTEB retrieval using BGE embedding models, for querying the MTEB leaderboard (e.g., Scandinavian MTEB), for recovering XOR-encrypted SQLite WAL files via b-tree page parsing, for creating a single file that compiles as both Rust and C++ (polyglot) using comment tricks, for recovering passwords from corrupted ZIP archives via file carving, for recovering a DAG from continuous data with edge count enforcement and alphabetical child rule, for designing primers for site-directed mutagenesis with large insertions, for transforming delimited text files (e.g., CSV) using Vim macros, for differential cryptanalysis of FEAL-like ciphers with round keys derived from 16-bit seeds, and for filtering JavaScript from HTML (XSS prevention).
---

# Sanitize Git Secrets Safely

Sensitive data hides in more places than the obvious literal strings. A single pass that greps and `sed`s the obvious tokens will miss escaped forms inside JSON, escaped sequences in patch/diff text, and partial matches that survive truncation. Treat sanitization as a loop, not a one-shot edit.

## Diagnostic checklist

Before declaring the repo clean, run ALL of these checks. Any non-empty result means there is still leaked material — fix and re-run from the top.

0. **Task relevance check.** Verify that the user's task is specifically about sanitizing secrets (API keys, tokens, credentials) from a git repository, OR about performing MCMC sampling for a hierarchical Beta-Binomial model in Stan via RStan, OR about building a gRPC key-value store service, OR about performing MTEB retrieval (e.g., using sentence-transformers with BGE embedding models), OR about querying the MTEB leaderboard (e.g., Scandinavian MTEB), OR about recovering data from an XOR-encrypted SQLite WAL file, OR about recovering a password from a corrupted ZIP archive (forensic file carving), OR about creating a single file that compiles as both Rust and C++ (polyglot), OR about recovering a DAG from continuous data (e.g., bn-fit-modify), OR about designing primers for site-directed mutagenesis with a large insertion, OR about transforming a delimited text file (e.g., CSV) into a different format using Vim macros, OR about fixing a CRLF injection vulnerability (CWE-93) in HTTP header handling, OR about performing differential cryptanalysis on a FEAL-like cipher, OR about filtering JavaScript from HTML (XSS prevention). If the task is unrelated — for example, image reconstruction, path tracing, dataset token counting, chess, overfull hbox, HuggingFace tokenization, building Cython extensions, CoreWars warrior design, or any non-secret removal, non-MCMC sampling, non-gRPC KV store, non-MTEB retrieval, non-MTEB leaderboard query, non-SQLite WAL recovery, non-password recovery, non-polyglot, non-DAG recovery, non-primer-design, non-Vim-macro-transformation, non-CRLF-injection, non-FEAL-differential-cryptanalysis, and non-filter-js-from-html objective — abort immediately. Do not apply this skill; it is not designed for that purpose.

1. **Tracked-file scan.** Enumerate every tracked path with `git ls-files`. Secrets outside the tracked tree (untracked, in stash, in reflog) still count.

2. **Pattern sweep per key type.** For each secret family you must scrub (cloud access keys, GitHub-style tokens, Huggingface tokens, PEM private keys, etc.) run a regex `grep -n` against the tracked set. Use one pattern per family; do not rely on a single generic "key-like string" pattern alone.

3. **Embedded / escaped forms.** Re-grep using the same value but in its escaped/encoded variants — backslash-escaped quotes inside JSON strings, leading-zero escapes, HTML entities, base64-wrapped blobs, and quoted forms inside `.patch` / `.diff` files. A token that survived only because it was `"AKIA…"` inside a JSON string is still a leak.

4. **Whole-repo string scan.** A final pattern sweep against the working tree (not just `git ls-files`) for any remaining key-shaped substrings. This catches stragglers the family-specific patterns missed.

5. **Diff audit.** `git diff` every modified file end-to-end. Confirm the changed hunks contain only placeholder substitutions and no residual characters from the original secret.

## Stop signal

If, after one full pass of the checklist above, ANY of the regex sweeps still returns a match (including in escaped/embedded form), STOP. Do not commit, do not push, do not report success. Reset by reverting the working tree to the pre-sanitize state (e.g. `git checkout -- .` from the last clean commit, or restore from backup), then re-run the checklist from step 1. Iterate until all five checks return zero hits. Only then is the repo safe to publish.

## Implementation pattern: `send_keystrokes` with polling

When implementing a `send_keystrokes` method that accepts a `wait_sec` parameter, do **not** rely on a fixed `time.sleep()`. Instead:

- Drain any leftover prompt output before sending the command.
- Poll for command output (e.g., wait for a shell prompt or expected output pattern) to ensure the command has completed before returning.
- Use `select`/`poll` with a timeout to avoid hanging indefinitely.
- Set the PTY master file descriptor to non-blocking mode.
- Read output in a loop so that partial data is not missed.
- When forking the PTY child, pass a sanitized environment that strips variables like `PYTHONSTARTUP` and any custom shell init that produces output. Use `env=None` or explicitly clear them to avoid spurious tracebacks from the parent's Python environment. See also the note on inherited environment below.
- After the child starts, read and discard all initial output (prompt, MOTD, errors) before sending the first command. This ensures the terminal begins from a clean state. (The "drain" step above already covers this; make it explicit.)
- For clean shutdown, send `exit` or `\x04`, then use `os.kill(pid, signal.SIGTERM)` followed by `os.waitpid(pid, 0)` to reap the child process. Do not rely solely on `close()`; explicitly reap to avoid zombies.

## Guidance for fixing CRLF injection vulnerabilities (CWE‑93)

When the task involves fixing a CRLF injection vulnerability in HTTP header handling (e.g., in a Python HTTP library), follow this checklist:

1. **Locate header normalization functions.** Identify the functions that normalize header names and values for dictionary-like header containers (e.g., `_hkey` and `_hval` in Bottle's `HeaderDict`). These are typically called whenever a header is set or appended.

2. **Add control‑character validation.** Modify these normalization functions to raise `ValueError` if the input contains any of the following characters: newline (`\n`), carriage return (`\r`), or null byte (`\0`). Apply the validation to both header name and header value sanitization.

3. **Create a JSONL report.** Write a JSONL file (e.g., `report.jsonl`) containing one JSON object per line with at least the keys `"file"` (the affected file path) and `"cwe"` (a list of CWE identifiers, e.g., `["CWE-93", "CWE-20"]`).

4. **Run the existing test suite.** Verify that the change does not break any existing tests and that any newly added test (e.g., `test_prevent_control_characters_in_headers`) passes.

## Guidance for fitting Raman peaks from graphene data

When the task involves fitting Raman spectra of graphene (e.g., G and 2D peaks), apply the following procedure to handle common pitfalls:

- **Inspect the x‑axis range and unit** first. If the G peak appears outside 1580–1600 cm⁻¹ (for 532 nm excitation), check the excitation wavelength or calibration, and adjust peak search windows accordingly.
- **Handle European decimal comma** – replace comma decimal separators with dots before parsing.
- **Strongly modulated spectra (interference fringes on SiO₂/Si)** – use a broader fitting window with a linear baseline to capture the peak envelope. Employ robust initial estimates: median of edge regions for baseline, `argmax` for center.
- **Validate fitted x₀** against physically expected ranges.
- **Partially captured peaks.** If the data range only contains part of a peak (e.g., only the right wing because the data start above the known peak center), do not fit the center position freely. Fix x₀ to the known or expected value (e.g., 1585 cm⁻¹ for the graphene G peak at 532 nm excitation) and only fit the width, amplitude, and offset. A free fit on a partial peak yields a biased and unstable x₀ that is unlikely to match the true value. Always inspect the data range relative to known peak positions before deciding which parameters to fix or constrain.
- **Compute fit uncertainties and check significance.** After fitting, always compute standard errors for all fitted parameters. Check that the fitted amplitude is statistically significant above the noise (e.g., amplitude > 3× uncertainty). If uncertainties are large or the amplitude is comparable to the noise, report the fit as unreliable.
- **If a Lorentzian fit fails to converge** reliably, use the data maximum as x₀, estimate amplitude from the 20th‑percentile baseline, and set gamma to a typical value (e.g., 20 cm⁻¹ for the 2D peak). Flag this fallback in the output to indicate reduced confidence.

## Guidance for MCMC sampling in Stan via RStan

When the task involves performing MCMC sampling for a hierarchical Beta-Binomial model in Stan via RStan, follow these steps:

1. **Environment prerequisites.** Ensure R and system development libraries (libcurl, libssl, libxml2) are installed.
2. **Install rstan.** From CRAN using `install.packages('rstan', repos='https://cloud.r-project.org/')` (version 2.32.7).
3. **Write the Stan model file.** Include the following code block:
   ```
   data {
     int<lower=0> N;
     int<lower=0> y[N];
     int<lower=0> n[N];
   }
   parameters {
     real<lower=0> alpha;
     real<lower=0> beta;
     vector<lower=0,upper=1>[N] theta;
   }
   model {
     y ~ binomial(n, theta);
     theta ~ beta(alpha, beta);
     target += -2.5 * log(alpha + beta);
   }
   ```
4. **Write the R driver script.** It should read the CSV (columns `y`, `n`), load **rstan**, compile the model, and run `rstan::sampling` with 4 chains, 100,000 iterations (warmup 50,000), seed = 1, chains = 4.
5. **Extract posterior means.** Use `summary(fit)$summary[,'mean']` or `extract(fit)` to compute sample means.
6. **Save results.** Write the posterior means of alpha and beta to separate text files, each containing a single number.
7. **Verify convergence.** Check that Rhat ≈ 1 and the effective sample size is sufficiently large.

## Guidance for building a gRPC key-value store service

When the task involves building a gRPC key-value store service, follow these steps:

1. **Install dependencies.** Ensure `grpcio` and `grpcio-tools` are installed at the required version (e.g., `pip install grpcio==1.73.0 grpcio-tools==1.73.0`).
2. **Create a `.proto` file.** Define a service with `GetVal` and `SetVal` RPCs, each with appropriate request/response messages. Use `int32` for numeric values.
3. **Generate Python stubs.** Run `python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <protofile>` to produce `_pb2.py` and `_grpc_pb2.py` files.
4. **Implement the server.** Create a class that inherits from the generated `Servicer`. Use an in‑memory `dict` for storage; `GetVal` should return 0 for missing keys, `SetVal` should store the key/value pair and return the value.
5. **Start the server.** Use `grpc.server` with `add_insecure_port` on the specified port and keep it running in the background (e.g., with `nohup`). Ensure the server process stays alive for testing.

## Guidance for MTEB retrieval using BGE embedding models

When the task involves performing MTEB retrieval (e.g., using `sentence-transformers` with a BGE embedding model), follow these critical rules:

- **Always prefix the query with the appropriate instruction.** For English BGE models (e.g., `BAAI/bge-small-en-v1.5`), prefix the query with `"Represent this sentence for searching relevant passages: "`. For Chinese BGE models (e.g., `BAAI/bge-small-zh-v1.5`), use the corresponding Chinese instruction: `"为这个句子生成表示以用于检索相关文档："`. BGE models are trained with instruction prefixes; omitting them produces incorrect embeddings and significantly degrades retrieval accuracy. The documents themselves should **not** be prefixed.

- **Ensure the model revision and normalization settings match the mteb evaluation pipeline.** Use the exact revision identifier (e.g., from the mteb repository) when loading the model with `SentenceTransformer`. If `mteb` is not importable (e.g., due to dependency conflicts), attempt to resolve the conflict by installing compatible versions (e.g., `pip install transformers==4.42.0 sentence-transformers==3.0.0 mteb==1.12.0`) before falling back to sentence-transformers alone. If the fallback is used, verify that the retrieved top‑k ranking for at least one known query‑document pair matches the expected ranking from the official mteb benchmark; otherwise, the result may be incorrect and should not be reported as the mteb retrieval result.

## Guidance for querying the MTEB leaderboard (e.g., Scandinavian MTEB)

When the task involves identifying the top-ranked model on an MTEB leaderboard (e.g., Scandinavian MTEB), follow these verification steps to avoid misinterpreting rankings:

- **Use the official leaderboard display** (e.g., the live Hugging Face Space) as the primary source for the exact metric (typically "Mean (Task)") and the correct benchmark category (e.g., "Scandinavian"). Do not rely on static snapshots or secondary summaries.
- **Cross-check the model identifier** (organization/model_name) against the official results dataset to ensure exact spelling, capitalization, and suffix (e.g., `-Preview` vs. no suffix). Even a single character mismatch can point to a different model.
- **If the leaderboard uses dynamic content (JavaScript), use direct API access or dataset queries** (Parquet files in the `mteb/results` dataset on Hugging Face) rather than relying on incomplete webpage scrapes. The Parquet files contain the authoritative results table.
- **Apply a coverage threshold** (e.g., ≥70% of benchmark tasks) to exclude models that only appear on a few tasks. A model with high mean on a handful of tasks is not the true leader.
- **Always re-verify the top model** by sorting the official results by the agreed metric (e.g., descending "Mean (Task)") and confirming which model appears first. Do not assume based on partial listings or older cached data.

## Guidance for recovering XOR-encrypted SQLite WAL files

When the task involves recovering data from an XOR-encrypted SQLite WAL file, follow these steps:

0. **Back up the WAL file before any database operations.** Before opening the database or running any SQL commands that could checkpoint or delete the WAL file (e.g., `PRAGMA journal_mode=DELETE`, `VACUUM`, or any query that triggers a checkpoint), make a copy of the WAL file (e.g., `cp main.db-wal main.db-wal.backup`). The WAL file can be accidentally destroyed by SQLite operations, and without it you cannot recover the encrypted frames. Work on the copy or the original as needed, but keep an untouched backup until recovery is complete.

1. **Identify the encryption key.** Read the first 4 bytes of the WAL file (WAL magic). If they are not `0x37 0x7f 0x06 0x82`, try XORing each byte with common single-byte keys (e.g., `0x00`, `0x42`, `0xFF`, `0x55`) until the result matches the valid magic. The key is the XOR value that transforms the encrypted first 4 bytes to `0x37 0x7f 0x06 0x82`. Verify the key by decrypting subsequent frame header page numbers (should be valid page numbers, usually 1 for the first frame).

2. **Decrypt all WAL frames.** Each frame consists of a 24-byte header (page number, commit flag, checksums) followed by a payload of `page_size` bytes (as defined in the SQLite database header). XOR every byte of the frame (header and payload) with the identified key.

3. **Parse decrypted frame payloads as b-tree pages.** Do **not** guess missing records by patterns (e.g., alphabetical ordering). Instead, parse the decrypted payload as a SQLite b-tree leaf page:
   - Validate the page header at offset 0 (first byte = page type: 0x0D for leaf table page).
   - Read the cell pointer array at offsets 1–2 (first cell offset), then iterate over each cell.
   - Decode each cell as a record with varint-encoded payload length, row ID, and column values using SQLite serial type codes (0x00 = NULL, 0x01 = signed 8-bit integer, 0x02 = 16-bit, etc.).
   - Extract the actual row data from the serialized values.

4. **If decrypted payload appears garbled**, try alternative XOR keys and re-validate against expected page structure (cell pointer array, serial type codes). Use a byte-level page parser to decode integer and text columns.

5. **Combine records from the main database file and all WAL frames.** The main database file (without WAL) contains the snapshot of pages that have been checkpointed; read its b-tree leaf pages directly (not encrypted). The WAL frames contain newer or uncommitted pages. For each page number, the WAL frame with the highest frame number (most recent) takes precedence. Reconstruct the full set of rows from the latest version of each page.

6. **Do not fall back to heuristics or pattern guessing** unless you have verified that the remaining records are not present in any frame. Always prefer actual page parsing over inferred patterns.

## Guidance for creating a polyglot Rust / C++ file

When the task involves creating a single file that compiles as both Rust and C++ (polyglot), use the following technique with comment tricks:

1. **File structure.** Start the file with:
   ```
   // \
   /*

   (all C++ code goes here, using `//` for C++ comments)

   // */
   ```
   The first line `// \` is a C++ comment whose backslash splices the next line into the comment. The second line `/*` then becomes part of that comment for C++, while Rust sees it as the start of a block comment (`/*`). Everything until the closing `*/` is hidden from Rust. The line `// */` closes the block comment for Rust, but C++ sees `//` and ignores the rest.

2. **C++ section.** Inside the `/* ... */` block, place all C++ code (includes, function definitions). Use `//` for any C++ comments. This code is invisible to Rust.

3. **Rust section.** After `// */`, each Rust line must be preceded by a line containing only `// \`. For C++, the backslash splices the following Rust line into the comment, so the entire pair becomes a comment. For Rust, the `// \` is a trivial line comment, and the next line is real Rust code.

   Example pattern:
   ```
   // \
   fn fibonacci(n: u32) -> u64 { ... }
   ```

4. **Equivalent functions.** Define a function (e.g., Fibonacci) in both languages with the same signature so they can be tested identically.

5. **Command-line arguments.** In C++ use `argc`/`argv`; in Rust use `std::env::args()`. Pass the integer argument and output the result.

6. **Compilation.** Compile with `rustc main.rs` for Rust, and `g++ -x c++ main.rs` for C++.

7. **Testing.** Test edge cases (n=0,1,2, large). Both compilers should produce identical outputs for the same input.

8. **Common pitfalls.** Ensure consistent function signatures, proper handling of integer overflow if needed, and that the C++ code does not use triple-slash doc comments (which would appear as `//` inside the Rust block comment but must actually be valid Rust comment syntax – use only `//`). Also ensure the `// \` lines have no trailing spaces (the backslash must be the very last character before the newline).

## Guidance for recovering passwords from corrupted ZIP archives in container overlays

When the task involves recovering a password from a corrupted ZIP archive stored in a container overlay filesystem, apply the following forensic procedure:

1. **Locate the archive.** Search large binary files (e.g., `.dat` files in the overlay) for known archive signatures (e.g., ZIP `PK` header) using `strings` and `grep`. If the archive is not contiguous, use a file carver like `foremost` to extract it.

2. **Extract contents.** Use `unzip` with the `-o` (overwrite) flag and consider ignoring CRC errors (e.g., `unzip -o -q archive.zip 2>/dev/null`). If the tool refuses, use a manual approach: locate the local file header, read the compressed/uncompressed sizes, and extract raw bytes.

3. **Handle corruption.** If the extracted data contains corruption (e.g., wrong bytes at the end due to overlay block reuse), apply known constraints:
   - Required prefix (e.g., `PASSWORD=`)
   - Required suffix (e.g., `\n`)
   - Allowed character set (e.g., uppercase letters and digits)
   - Total length constraints
   Use these constraints to filter plausible completions for the corrupted region.

4. **Cross-validate.** Before finalizing, verify the recovered data using an independent method (e.g., hex dump comparison, another carving tool like `scalpel`). Confirm that the reconstructed password matches all constraints exactly.

5. **Write result.** Save the recovered password to the specified output file.

## Guidance for creating standalone Python scripts compatible with `uv run`

When creating Python scripts that will be executed via `uv run <script>` (without the `python` command), every script file must include a shebang line such as `#!/usr/bin/env python3` and be marked executable (`chmod +x`). This allows `uv run` to invoke them directly. Additionally, ensure a `pyproject.toml` is present (with `[project]` section) so that `uv` can resolve the scripts' dependencies (even if only stdlib). Always verify that the scripts work when called as `uv run compress.py` (not `uv run python compress.py`), because verifiers may test that exact invocation. Without the shebang and executable permission, `uv run` will fail to locate the interpreter and the script will not run.

## Guidance for recovering a DAG from continuous data (bn-fit-modify)

When the task involves recovering a DAG from continuous data with known number of edges and directionality heuristics, follow this procedure:

1. **Combine constraint-based and score-based structure learning.** Use a constraint-based algorithm (e.g., PC algorithm with partial correlation tests) to infer the skeleton, then refine with a score-based method (e.g., HillClimbSearch with BIC) to orient edges. Alternatively, run both and compare results.

2. **Enforce the known edge count explicitly.** After learning the DAG, verify that the number of edges exactly matches the stated number. If not, adjust the search (e.g., by thresholding or pruning) until the count is met.

3. **Apply the alphabetical child rule for disambiguation.** For edges that do not involve the root node (a node with no parents), if the direction remains ambiguous, treat the node that comes earlier in the alphabet as the child. For example, if the undirected edge is between R and M and M < R alphabetically, then M is the child, yielding R → M.

4. **Cross-validate by re-fitting the Bayesian network.** Fit the parameters of the BN (e.g., using linear Gaussian models) and verify parameter plausibility. For example, if monotonic relationships are expected, ensure coefficients are non-negative. If the root node is known (e.g., U has no parents), enforce that constraint.

5. **Verify the learned DAG exactly matches the stated edge count and parent constraints.** Confirm that the final DAG has the correct number of edges and that any specified parent constraints (e.g., U has no parents) are satisfied before proceeding to interventions or sampling.

## Guidance for designing primers for site-directed mutagenesis with a large insertion

When designing primers for site-directed mutagenesis with a large insertion (e.g., inserting a DNA sequence of several dozen base pairs), follow these critical rules:

- **Reverse primer annealing region.** Ensure the reverse primer's 3' annealing region exactly matches the template sequence upstream of the mutation site, without any extra or missing bases. The annealing region should be the reverse complement of a contiguous stretch of template immediately preceding the insertion point.

- **Back-to-back junction check.** The 5' ends of the forward and reverse primers must be adjacent on the template (0-gap, 0-overlap). Specifically, the complement of the reverse primer's 5'-most base must match the template base immediately before the insertion start. Verify this manually or programmatically for the final primer pair.

- **Forward primer design.** The forward primer consists of a 5' overhang (the insertion sequence) followed by a 3' annealing tail that matches the template immediately downstream of the insertion (starting at the first base after the cut site). The annealing portion should be of adequate length (typically 15–30 nt) to achieve a Tm within the acceptable range (58–72°C).

- **Re-run verification on final pair.** If multiple candidate primers are considered, the verification (Tm calculation, back-to-back junction, annealing length) must be re-run on the final selected pair to prevent discrepancies introduced during optimization.

- **Tm calculation.** Use a consistent method (e.g., `oligotm` with appropriate concentrations: `-tp 1 -sc 1 -mv 50 -dv 2 -n 0.8 -d 500`) to compute annealing Tm for both primers. Accept a Tm difference ≤ 5°C.

- **Amplicon check.** Ensure the PCR product spans the entire circular plasmid (i.e., the forward and reverse primers point away from each other on the circular template, producing a full-plasmid amplicon). Verify that the product length equals the plasmid size.

## Guidance for transforming delimited text files with Vim macros

When the task involves transforming a delimited text file (e.g., CSV) into a different format using Vim macros, follow this procedure:

1. **Inspect a sample** of the input and expected output to identify all required transformations (strip leading/trailing whitespace per field, change delimiter, change case, reorder columns, append constant strings).

2. **Break the transformation** into multiple small macros, each performing a single type of change. This keeps total keystrokes under the limit (typically <200) and makes debugging easier.

3. **Within each macro**, use Ex substitute commands (`:s/pattern/replacement/`). For uppercasing, use `\U&` in the replacement; for reordering fields, use very-magic mode (`\v`) to avoid escaping parentheses.

4. **Store each macro** in a register (e.g., `call setreg('a', "...")`) and apply it to the entire file with `%normal! @<register>`.

5. **Verify success** by running `diff` on the output and target file.

6. **Ensure the script** contains only allowed commands: `call setreg`, `%normal!`, and `:x` or `:wq`. Do not use Vimscript functions, shell escapes, or scripting languages.

Example decomposition (for a CSV with fields `foo, bar, baz` needing whitespace stripping, delimiter change to `;`, uppercasing, reordering to `baz;bar;foo`, and appending `;OK`):

- **Macro a**: `:s/^ *//|s/ *$//|s/ *, */;/g|s/.*/\U&/` + Enter
- **Macro b**: `:s/\v^(.+);(.+);(.+)$/\3;\2;\1/` + Enter
- **Macro c**: `:s/$/;OK/` + Enter

Apply with:
```
call setreg('a', ":s/^ *//|s/ *$//|s/ *, */;/g|s/.*/\\U&/\<CR>")
call setreg('b', ":s/\\v^(.+);(.+);(.+)\$/\\3;\\2;\\1/\<CR>")
call setreg('c', ":s/\$/;OK/\<CR>")
%normal! @a
%normal! @b
%normal! @c
:x
```

## Guidance for differential cryptanalysis of FEAL-like ciphers

When the task involves performing a chosen-plaintext differential attack on a FEAL-like cipher with 6 rounds and round keys derived from 16-bit seeds, follow this procedure:

1. **Select three plaintexts** such that `P_left ^ P_right` is identical across all three. This forces `R0` to be constant through the cipher because `R0 = P_left ^ P_right ^ k0 ^ k1` and `k0, k1` are constant.

2. **For each candidate k5** (derived from seed `0..65535` via the key derivation formula), compute `L3` for the first two pairs by peeling off round 4: `L3 = R4 ^ f(R3 ^ k5)`.

3. **For each k5 candidate**, search over all k4 candidates using the differential relation from round 3: `f(L3_1 ^ k4) ^ f(L3_2 ^ k4) = R3_1 ^ R3_2 ^ P_left_1 ^ P_left_2`. The right-hand side is known from ciphertexts and chosen plaintexts. Use numpy vectorization to test all 65536 k4 seeds in parallel: precompute byte-level arrays for each k4 seed, then filter in four stages (one for each output byte of `f`). Each stage reduces candidates by ~256×, yielding essentially zero false positives per wrong k5.

4. **Verify the candidate (k5, k4) pair** with the third plaintext-ciphertext pair.

5. **Shuffle the search order** of candidate k5 seeds randomly to avoid worst-case runtime when the correct seed happens to be at the end.

6. **Recover other round keys** similarly by peeling off rounds if needed. The attack directly recovers k5.

## Guidance for filtering JavaScript from HTML (XSS prevention)

When the task involves removing JavaScript from HTML to prevent XSS attacks, follow these critical rules to avoid brittle or incomplete sanitization:

- **Prefer a trusted HTML sanitizer library** (e.g., `bleach` or `lxml`) that handles all edge cases (SVG, MathML, data URIs, mixed-case attributes, nested contexts) rather than implementing custom string-manipulation on parsed spans. If using BeautifulSoup, do **not** remove spans by byte offsets on the original text; instead, reconstruct the HTML from the modified parse tree after removing dangerous nodes and attributes.

- **When using BeautifulSoup (or similar parser):**
  - Remove all `<script>`, `<style>`, `<iframe>`, `<object>`, `<embed>`, `<applet>`, `<frameset>`, `<frame>`, `<noscript>` elements entirely.
  - Remove `<meta http-equiv="refresh">` elements whose `content` attribute contains a `javascript:` or `data:text/html` URL.
  - Remove `<base>` elements with `href` containing dangerous URI schemes.
  - Strip all event handler attributes (e.g., `onclick`, `onerror`, `onmouseover`, `onload`, `onbegin`, `onend`, `onshow`, etc.) from every element, including SVG and MathML elements.
  - Strip or