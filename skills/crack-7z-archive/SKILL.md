```markdown
---
name: polyglot-c-py
description: Recover all records from a SQLite WAL-mode database by manually parsing the WAL file and the base database file, build Cython extensions while preserving an existing NumPy installation, ensure build verification includes exact task-specified steps, configure Nginx custom log formats correctly, design CoreWars warriors that defeat diverse opponents including decoy and self-clearing strategies, perform Raman spectral fitting of graphene with European decimal handling, retrieve the top-performing model from the Scandinavian MTEB leaderboard by scraping the official Hugging Face Spaces page, and reverse-engineer a programmatic image by extracting per-pixel color values and fitting mathematical models to accurately reconstruct the scene.
---

# SQLite WAL-mode Recovery

Use the following approach to recover all records from a SQLite database that was opened in WAL mode, **without** letting `sqlite3` delete or auto-checkpoint the WAL file.

## Algorithm

1. **Copy files first** – Before any database operation, copy both `main.db` and `main.db-wal` to a temporary directory (e.g., `/tmp/recovery/`). Work exclusively on the copies.

2. **Parse the WAL file header** (32 bytes):
   - Magic number (bytes 0-3): `0x377f0682` or `0x377f0683`
   - Version (bytes 4-7): little-endian unsigned 32-bit
   - Page size (bytes 8-11): little-endian unsigned 32-bit (must match the main database page size)
   - Checkpoint sequence number (bytes 12-15)
   - Salt 1 (bytes 16-19)
   - Salt 2 (bytes 20-23)
   - Start checkpoint index (bytes 24-31): little-endian unsigned 64-bit

3. **Parse WAL frames** – After the header, each frame is `128 + page_size` bytes:
   - Frame header (128 bytes):
     - Page number (bytes 0-3): little-endian unsigned 32-bit
     - Commit flag (bytes 4-7): non-zero if this frame commits a transaction
     - Salt 1 (bytes 8-11)
     - Salt 2 (bytes 12-15)
     - Checksum 1 (bytes 16-19)
     - Checksum 2 (bytes 20-23)
     - (remaining 104 bytes reserved, ignored)
   - Page data (exactly `page_size` bytes).

   Use Python's `struct` module: `struct.unpack('<IIIQQ', header[:24])` for the first six fields (salt values stored as unsigned 32-bit, checksums as unsigned 64-bit? Actually the standard uses 32-bit for checksums in many implementations; check the SQLite source. For safety, use `<IIIIII` (6 unsigned 32-bit) for the first 24 bytes. The frame header total is 128 bytes, but only the first 24 contain relevant fields. However, include the full 128-byte header for correct offset calculation.

4. **Rebuild the database**:
   - Copy the main database file (the base state) to a new file, e.g., `recovered.db`.
   - For each frame in the WAL (in order of appearance):
     - If the frame's page number is 0 or greater than the total page count of the main database, skip it (or handle expansion if needed).
     - Otherwise, read the frame's page data and write it to the corresponding page offset in `recovered.db`: `offset = (page_number - 1) * page_size`.
   - After processing all frames, `recovered.db` represents the final state.

5. **Extract records** – Parse the B-tree pages of `recovered.db` to retrieve table row data:
   - Use the SQLite page format: page 1 is the root of the schema table, other pages contain table data.
   - For leaf table B-tree pages (page type `0x0D`), parse the cell pointers and decode each cell's payload using SQLite's varint and serial type encoding.
   - Extract all rows, sort by id, and output as JSON to `/app/recovered.json`.

## Implementation guidelines

- Use Python with only `struct` and `os` (standard library). No external dependencies.
- Do **not** open the original database with any SQLite library – that would consume the WAL.
- If the WAL file appears corrupted (invalid magic number, mismatched salts, impossible page number), try to recover as many frames as possible by skipping the corrupted frame and continuing. Never fabricate data based on patterns.
- Handle missing files, empty files, and permissions errors with appropriate exceptions (`FileNotFoundError`, `ValueError`, `PermissionError`).

## Verification

- After recovery, the output file `/app/recovered.json` should contain every row that existed in the database at the time the WAL was last written, including rows that were only present in the WAL and not yet checkpointed.
- Compare the total row count with the sum of rows visible in a clean `sqlite3` open after the WAL is consumed (though that consumption removes the WAL, so you must re-copy before opening).

## Common pitfalls

- Opening the database with any `sqlite3` tool before copying will destroy the WAL file (auto-checkpoint). Always copy first.
- If the WAL and main database have different page sizes, the database is inconsistent; recovery may be impossible.
- When parsing B-tree cells, calculate offsets correctly – a single byte offset error will corrupt all subsequent rows.
- Do not assume records follow any naming or value pattern; recover only what is actually stored in the pages.

## Building Cython Extensions with NumPy Version Control

When building a Cython extension from source that must work with a specific existing NumPy version, do not use `pip install .` as it may silently upgrade NumPy. Instead, follow these steps:

1. **Compile extensions in-place** – Run `python setup.py build_ext --inplace` to build the Cython extensions against the currently installed NumPy.
2. **Install the package** – Then run `pip install . --no-build-isolation --no-deps` to install the package without pulling in newer dependency versions.
3. **Verify NumPy version** – After installation, check that the target NumPy version remains unchanged (e.g., `python -c "import numpy; print(numpy.__version__)"` should still show the original version).

This method ensures the extensions link against the correct NumPy API and that the dependency tree is not silently altered.

## General Build Verification

When building any software package (especially legacy software), ensure the build verification includes the exact steps specified by the task. For example, if the task requires rendering an input file to an output image file and comparing that output against a reference image using a provided comparison method, do not substitute a sanity check that renders to `/dev/null` or to standard output. Always produce the required output file and run the comparison exactly as instructed.

## Nginx Custom Log Format

When configuring Nginx custom log formats, only the user agent field (`$http_user_agent`) should be wrapped in double quotes. All other fields (e.g., `$time_local`, `$request_method`, `$status`) must remain unquoted. For example: `'$time_local $request_method $status "$http_user_agent"'`. Incorrectly quoting all fields (e.g., `"$time_local" "$request_method" "$status" "$http_user_agent"`) will produce logs with extra quotes that are not expected by downstream parsers. Also ensure that the `error_log` directive points to the expected path and that the `log_format` name used in the `access_log` directive matches exactly the name defined in the `log_format` directive.

## CoreWars Warrior Design (Winning Average)

When building a CoreWars warrior for the "winning-avg-corewars" scenario, a hybrid stone-bomber-plus-imp-ring strategy often fails against opponents that use decoy fields (e.g., snake) or self-clearing loops (e.g., g2-clear). The stone bombs are absorbed by decoys, and delayed imps cannot convert the core before the opponent's trap kills them. To counter such a diverse set of opponents, the warrior should employ one of these approaches:

1. **Scanner with adaptive bombing step** – A scanner that dynamically adjusts its bombing step (e.g., from step-4 to step-7 or step-9) to avoid hitting decoy-filled regions, while also targeting non-decoy memory areas.
2. **Multi-core-clear with immediate imps and scanning** – Launch imps immediately (no delay) in multiple streams, combined with a scanning component that finds and bombs opponent code. The scanning code must be compact (≤ 15 instructions) to avoid being hit early.

Key design principles:
- Minimize code size (≤ 15 instructions) to reduce the chance of being hit by opponent bombs.
- Prefer immediate imp launches over delayed ones to quickly convert core and disrupt decoys.
- Use a scanner that reads memory and bombs based on pattern detection (e.g., searching for non-DAT cells) rather than a fixed step.
- If using a stone bomber, avoid a fixed step that lands on known decoy patterns; instead, randomize or adapt the step after a few cycles.

These strategies ensure the warrior can handle both decoy-heavy and self-clearing opponents while maintaining high win rates against paper and vampires.

## Raman Spectral Fitting of Graphene

When fitting Raman spectra from files that may use European decimal format (comma as decimal separator), first convert all decimal commas to dots before numeric parsing. Use the following workflow:

1. **Locate the laser line** – In the raw spectrum (absolute wavenumber axis), find the x-coordinate with the maximum y-count. This is the laser line position. For graphene measured with a 522.5 nm laser, this is typically around 19139.5 cm⁻¹. If the laser line is not obvious (e.g., clipped), fall back to the known value.

2. **Compute Raman shift** – Convert the absolute wavenumber axis to Raman shift: `raman_shift = laser_wavenumber - x_absolute`. Keep only the Stokes side (positive Raman shifts); ignore the anti-Stokes side.

3. **Model the Rayleigh tail** – The dominant feature is the elastic scattering (Rayleigh tail). Model it as a Lorentzian centered at 0 cm⁻¹ Raman shift with an adjustable amplitude and width. This tail must be subtracted or included as a shared component in the fit.

4. **Fit the G and 2D peaks** – Use Lorentzian profiles for both:
   - **G peak**: expected center ≈ 1580 cm⁻¹.
   - **2D peak**: expected center ≈ 2700 cm⁻¹.
   - **Shared offset**: a constant baseline (y-offset) shared by both peaks.
   - **Rayleigh Lorentzian**: centered at 0 cm⁻¹, with its own amplitude and width.

5. **Apply physically reasonable bounds**:
   - G peak Lorentzian full-width at half-maximum (gamma): 5–50 cm⁻¹.
   - 2D peak gamma: 20–80 cm⁻¹.
   - Rayleigh tail gamma: typically 50–500 cm⁻¹ (adjust as needed).
   - All amplitudes must be positive; set lower bounds to avoid negative values.

6. **Handle weak 2D peaks** – If the 2D peak is very weak (amplitude near noise floor), do not force it to the noise floor. Instead, set a minimum amplitude constraint (e.g., 1% of the G peak amplitude) and check fit quality (e.g., chi-squared or R²). If the fit quality is poor with the 2D peak included, consider fixing its position and width to literature values (1580/2700) and only fitting the amplitude.

7. **Output** – Write the fit results to `/app/results.json` with keys `G` and `2D`, each containing fields `x0`, `gamma`, `amplitude`, and a shared `offset`. Use JSON format.

8. **Validation** – Ensure all numeric values are within the specified bounds. Reject any fit that violates the bounds and re-run with tighter constraints.

## Scandinavian MTEB Leaderboard Retrieval

When the task requires finding the best model on the Scandinavian MTEB leaderboard, do **not** attempt to recompute scores from raw result parquet files on Hugging Face. Instead, use a direct web-scraping approach against the official leaderboard Spaces page. This is more reliable as it reflects the leaderboard's official filtering and weighting.

### Procedure (Python, standard library only)

1. **Fetch the leaderboard page**  
   Use `urllib.request.urlopen` to retrieve the HTML from `https://huggingface.co/spaces/mteb/leaderboard`.  
   Example:  
   ```python
   import urllib.request
   with urllib.request.urlopen("https://huggingface.co/spaces/mteb/leaderboard") as resp:
       html = resp.read().decode("utf-8")
   ```

2. **Parse the table**  
   Use `html.parser.HTMLParser` (standard library) to locate the `<table>` that contains the Scandinavian benchmark data. Look for a row where the benchmark cell matches "Scandinavian". The top model is the first row in that table (rank 1).  
   Fall back to searching for "Scandinavian" in the page text if the table structure is hard to parse; extract the model name from the adjacent column.

3. **Extract the model name**  
   Once the correct row is found, extract the model identifier (format `organization/model_name`). Ensure it matches that pattern (e.g., `codefuse-ai/F2LLM-v2-14B`).

4. **Validate the model on Hugging Face**  
   Check that the model page exists by sending a HEAD request to `https://huggingface.co/{model}` and verifying

## Programmatic Image Reverse-Engineering

When the task requires reconstructing a programmatic image (e.g., a PPM scene with sky, mountain, checkerboard), follow these steps to achieve high similarity with the reference:

1. **Extract per-pixel color values** for a representative sample of rows and columns.  
   Use a tool (e.g., Python with `struct` to read PPM binary) to obtain exact RGB values at known coordinates. Sample enough points to characterize gradient regions (e.g., every 10th row and column) and all edges or pattern boundaries.

2. **Calibrate the mathematical model** from the extracted values, rather than guessing parameters blind.  
   For gradient regions (e.g., sky, mountain interior), fit polynomial or trigonometric functions to the observed color values along rows/columns.  
   For textured regions (e.g., checkerboard under perspective distortion), determine the period and phase of the pattern per row: compute the horizontal frequency by analyzing the alternating color sequence in sample rows, then derive the perspective transform parameters from how the frequency changes with vertical position.

3. **Validate the generated image** against the reference using a similarity metric (e.g., L2 norm of pixel differences) before finalizing the program.  
   If the similarity is below a threshold (e.g., mean squared error > 5 per channel), re-evaluate the fitted parameters and adjust until the metric improves