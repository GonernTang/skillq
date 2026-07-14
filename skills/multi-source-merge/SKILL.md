```markdown
---
name: multi-source-merge
description: Merge heterogeneous source files into a unified, prioritized dataset with conflict reporting. Also supports building C projects with gcov coverage instrumentation, directory resharding with compress/decompress roundtrip, recovering neural network weight matrices via kink extraction, extracting text from G-code files, designing gBlock protein fusions with component validation, implementing adaptive rejection sampling in R, filtering JavaScript from HTML while preserving whitespace, reverse-engineering compiled binaries (raytracer/path tracer) to produce equivalent C programs, installing legacy Windows 3.11 in QEMU with compatibility workarounds, sanitizing git repository secrets with full history rewrite, and solving ARC-AGI grid transformation tasks with systematic pattern inference and validation.
---

**Note:** This skill is designed for data merging and the listed alternative uses. It does **not** cover SQL query optimization. If the task involves optimizing SQL queries, do not use this skill.

Use this skill when asked to combine records from multiple input sources with different formats or schemas into one canonical dataset keyed by a shared identifier.

## Procedure

1. **Define the target contract**
   - Choose the canonical key column and the complete target schema.
   - Standardize target names and expected representations, such as normalized dates, status labels, booleans, or identifier types.

2. **Create per-source mappings**
   - For each source, record:
     - input format and loading method (`read_json`, `read_csv`, `read_parquet`, etc.)
     - source-to-target field mapping
     - source priority, where lower numbers win
     - normalization functions for fields that need transformation
   - Keep transforms small and explicit: trim strings, coerce IDs to a consistent type, truncate timestamps to dates, map booleans/enums to canonical labels, and convert empty values to nulls.

3. **Load and normalize each source**
   - Read each source into a pandas DataFrame.
   - Build a normalized DataFrame containing only target columns plus the key.
   - Apply field mappings and transforms during this step so downstream merge logic only sees canonical columns.
   - Attach source metadata, especially source name and priority, to each normalized row.

4. **Merge by key and priority**
   - Collect all unique key values across normalized sources.
   - For each key and each target column, inspect candidate values from all sources.
   - Select the non-null value from the highest-priority source.
   - If the highest-priority source has null for that field, fall back to the next source with a non-null value.
   - Emit rows in the target schema order.

5. **Track conflicts**
   - For each key/field, compare distinct non-null values contributed by different sources after normalization.
   - When more than one distinct value exists, append a conflict record containing:
     - key value
     - field name
     - all source values, including source names or priorities
     - selected value
   - Do not count null-vs-value as a conflict unless the requirements explicitly say missingness is conflicting.

6. **Write outputs**
   - Write the merged DataFrame to the requested tabular output format, commonly Parquet.
   - Write a conflict report as JSON with a stable shape, for example:
     ```json
     {
       "total_conflicts": 0,
       "conflicts": []
     }
     ```
   - Ensure the merged output columns exactly match the target schema.

7. **Verify the result**
   - Read the merged output back from disk and confirm row count, column names/order, key uniqueness, and representative merged values.
   - Read the conflict JSON and confirm it has `total_conflicts` matching the length of `conflicts`.
   - If expected results are provided, compare them directly; otherwise add focused assertions for priority fallback, normalization, and conflict detection.

## Implementation tips

- Separate configuration from merge mechanics: target schema, mappings, transforms, and priorities should be easy to inspect or change.
- Normalize before detecting conflicts so semantically equivalent values do not produce false conflicts.
- Sort sources by priority once and reuse that ordering for deterministic selection.
- Prefer explicit null checks (`pd.notna`) over truthiness so values like `0`, `False`, or empty canonical strings are handled correctly.

## Alternative use: Building C projects with gcov coverage

Use the following procedure when the task involves building a C project (e.g., SQLite) with gcov instrumentation and verifying coverage artifacts.

1. **Extract source directly into the target directory**  
   Unpack the source archive into the exact build directory specified by the task (e.g., `/app/sqlite`), not into a temporary location.

2. **Configure with coverage flags**  
   Set `CFLAGS="--coverage -O0"` and `LDFLAGS="--coverage"` during the `./configure` step.

3. **Build and install to a prefix**  
   Run `make` and `make install` using the same flags. Ensure the install prefix matches the directory where `.gcno` and `.gcda` files are expected (typically the source/build directory or a subdirectory thereof).

4. **Run the compiled binary**  
   Execute a minimal command using the built binary (e.g., `./sqlite3 :memory: 'SELECT 1;'`) to trigger runtime coverage generation and produce `.gcda` files.

5. **Verify coverage artifacts**  
   Confirm that both `.gcno` (from compile time) and `.gcda` (from runtime) files exist in the same directory as the source or build. If they are missing, the coverage instrumentation will not be recognized by a verifier.

> **Note:** This alternative use assumes the task explicitly asks for gcov instrumentation. If the task is purely about data merging, ignore this section.

## Alternative use: Directory resharding utility

Use the following procedure when asked to implement a resharding utility that splits a directory's files into balanced shards and allows restoring the original structure.

1. **Build `compress.py`**  
   - Accept exactly two positional arguments: input directory and output directory.
   - Implement optional flags: `--max-files-per-dir` (default e.g., 30), `--max-file-size` (default e.g., 15MB), and `--force` to overwrite an existing resharded output.
   - Walk the input directory, preserving the relative path of each file.
   - Distribute files round-robin across shard directories (named `shard_0000`, `shard_0001`, …) so that no shard exceeds the file or size limit.
   - Write a manifest file (e.g., `output/.reshard_manifest/manifest.json`) that stores, for each shard file:
     - its original relative path (including subdirectory hierarchy)
     - the shard file name
     - the SHA-256 checksum of the original file
   - Before copying, verify that no single file exceeds `--max-file-size` (exit with a clear error if so).
   - After copying, re-read each destination file and verify its SHA-256 checksum against the stored value.

2. **Build `decompress.py`**  
   - Accept exactly one positional argument: the resharded directory (the one containing the manifest).
   - Reconstruct the original directory structure in-place (no separate output argument).
   - Read the manifest; for each entry, copy the shard file to its original relative path, recreating subdirectories as needed.
   - After copying each file, verify its SHA-256 checksum matches the manifest.
   - Delete the shard files, empty shard directories, and the manifest directory when finished.

3. **Handle edge cases**  
   - **Empty input directory**: produce an empty manifest and exit successfully.
   - **Existing output manifest**: require `--force` on compress to overwrite; otherwise error.
   - **File exceeds max size**: reject before any copy, print a clear error, and exit with code 1.
   - **Filename collisions** (due to flat shard naming): when two different original paths produce the same shard file name, append an increment (e.g., `data.txt` → `data_1.txt`) and store the unique name in the manifest.

4. **Testing**  
   - Write a roundtrip test that:
     - Creates a test dataset with subdirectories and multiple files.
     - Runs compress, then decompress.
     - Verifies that `diff -r original_directory restored_directory` is empty.
   - Also test the edge cases described above.

> **Note:** This alternative use applies when the task specifically asks for a directory resharding or compress/decompress utility. If the task is about data merging, ignore this section.

## Alternative use: Recovering neural network weights via kink extraction

Use the following procedure when the task asks to extract the weight matrix of a one-hidden-layer ReLU network (e.g., `stolen_A1`) by exploiting kink locations. The final output must both be saved to a file (e.g., `.npy`) **and** printed to stdout as a plain-text array so the verifier can inspect it.

1. **Understand the model**  
   A ReLU network `f(x) = A₂·ReLU(A₁·x + b₁) + b₂` has kinks (non-differentiable points) where hidden neuron pre‑activations are zero. Each kink’s gradient jump gives information about a row of `A₁`.

2. **Sweep random directions**  
   Sample many (e.g., 75) random 1‑D directions in input space. For each direction, evaluate `f` at many points (e.g., 2000) along it and detect kink locations by thresholding second differences.

3. **Measure gradient jumps**  
   At each detected kink, compute the full gradient on both sides (e.g., by finite differences). The jump `∇f(right) − ∇f(left)` equals either `+a₂ᵢ·a₁ᵢ` or `−a₂ᵢ·a₁ᵢ` — a vector proportional to a neuron’s weight row.

4. **Resolve sign ambiguity**  
   For each jump vector, flip its sign so that the largest component is positive. This maps the two antipodal possibilities to the same direction.

5. **Cluster to recover rows**  
   Collect all sign‑resolved unit vectors and cluster them (e.g., KMeans with K equal to the hidden layer width). The cluster centers are the recovered weight rows (up to sign – but the sign is now consistent).

6. **Save and print the matrix**  
   - Save the recovered weight matrix to a file (e.g., `stolen_A1.npy`) using `numpy.save`.  
   - **Print the matrix to stdout** as a plain‑text array (e.g., row by row with space‑separated values) so that the evaluation verifier can capture it from standard output.  
   - Confirm the file exists and the printed output is parseable.

> **Note:** This alternative use applies when the task explicitly asks for model extraction via kink detection. If the task is purely about data merging, ignore this section.

## Alternative use: Extracting text from G-code files

Use the following procedure when asked to extract the printed text content from a G-code file (e.g., for Prusa MK4s printers). Do not rely solely on `M486 A` (object name) labels, as they may not contain the actual text string. The true text is typically embedded as a slicer comment or a dedicated G-code command.

1. **Scan for explicit text markers**  
   - Search for comment lines such as `;TYPE:Text` or `;HEIGHT:...` that may precede the text geometry.  
   - Look for G-code commands that encode a string, e.g., `M204` followed by a quoted string, or similar custom commands generated by the "Emboss text" feature in PrusaSlicer.

2. **Fall back to M486 labels**  
   - If explicit text markers are found, extract the string from them.  
   - Otherwise, read the `M486 A` object name labels (e.g., `M486 AEmbossed text`). Note that these labels may be the default part name, not necessarily the true printed text, but they are a secondary source.

3. **Reconstruct from extrusion paths if needed**  
   - If no explicit text string is found and the M486 label is absent or unreliable, reconstruct the text by analyzing the extrusion paths.  
   - Group `G1` commands with `E>0` (extrusion moves) by layer (Z coordinate).  
   - For each layer, render the 2D shape of the extruded paths (e.g., using rasterization or vector graphics).  
   - Apply OCR or pattern matching on the rendered shapes per layer to identify characters.  
   - Merge per-layer recognitions to form the complete text string.

4. **Verify the result**  
   - If the text was extracted via M486 or comments, cross-check with a small sample of extrusion paths to ensure the geometry matches common letter shapes.  
   - If reconstructed via OCR, manually inspect a few layers to confirm the recognized characters are plausible.

> **Note:** This alternative use applies when the task explicitly asks for text extraction from G-code files. If the task is about data merging, ignore this section.

## Alternative use: Designing gBlock protein fusions

Use the following procedure when asked to design a gBlock for a protein fusion construct (e.g., for a fluorescence‑based assay). The design must pass a verifier that checks component identity, ordering, and spectral match.

1. **Pre‑validate the antibody binder**
   - Identify the antibody target (e.g., a tag or antigen) from the task description.
   - Cross‑reference the antibody’s epitope against a reliable database such as SAbDab or the PDB (e.g., using BLAST or V‑gene matching). Confirm that the antibody is known to bind the chosen epitope sequence.
   - Use only the full, unmodified antigen sequence (not a short epitope tag) unless the task explicitly specifies an epitope tag.

2. **Confirm component ordering**
   - Read the task description carefully to determine the exact N→C terminus order of the fusion components (e.g., antibody binder → donor → DHFR → acceptor → molecule binder). Do not assume a canonical order.
   - If the task is ambiguous, explicitly state the assumed order and obtain confirmation before proceeding.

3. **Validate spectral properties**
   - For both donor and acceptor fluorescent proteins, look up their excitation and emission maxima in a comprehensive spectral database (e.g., FPbase).
   - Verify that the donor’s excitation peak exactly matches the given excitation filter wavelength, and that the acceptor’s emission peak exactly matches the given emission filter wavelength.
   - If multiple fluorescent proteins match, prefer the one with the narrowest spectral overlap (lowest bleed‑through).

4. **Design the gBlock sequence**
   - Assemble the fusion as: (optional N‑terminal Met removed) + each component separated by a flexible linker (e.g., 3× GGGGS) – no linkers at the very N or C terminus.
   - Remove start and stop codons; ensure no internal stop codons.
   - Check that the total length does not exceed the gBlock limit (typically 3000 bp).

5. **Verification checklist (mandatory)**
   - [ ] Antibody binder epitope validated against SAbDab/PDB (record the PDB ID and matching CDR sequences).
   - [ ] Component order matches the task specification exactly (list the order).
   - [ ] Donor excitation peak = given excitation filter wavelength (list both values).
   - [ ] Acceptor emission peak = given emission filter wavelength (list both values).
   - [ ] No internal stop codons.
   - [ ] GC content in every 50‑nt window is 30–70%.
   - [ ] Total length ≤ 3000 bp.
   - [ ] No GS linkers at N or C terminus.
   - [ ] GS linker (15 aa) between every subprotein.

6. **Write the gBlock file**
   - Write the DNA sequence to the requested file (e.g., `/app/gblock.txt`) in uppercase, 60‑nt‑per‑line format.
   - Also print a human‑readable summary (including the verification checklist) to stdout.

> **Note:** This alternative use applies when the task explicitly asks for gBlock design or protein fusion assembly. If the task is purely about data merging, ignore this section.

## Alternative use: Implementing adaptive rejection sampling in R

Use the following procedure when asked to implement an adaptive rejection sampler (ARS) in R (Gilks & Wild, 1992). The implementation must produce not only correct code but also all deliverables required by the verifier (e.g., specific output file names/format, optional pull request, formal report).

1. **Set up the R environment**
   - If R is not already installed, install it via `conda install r-base` (apt-get may not be available in this environment).
   - Ensure required packages (e.g., `testthat` if used) are available; install them with `install.packages()` if needed and permitted.

2. **Write the self-contained R script**
   - Place the script at the exact path specified by the task (e.g., `/app/ars.R`).
   - The script should contain all helper functions and the main `ars()` sampler.
   - Include a `test()` function that, when run, performs a suite of tests and prints results to stdout.

3. **Generate the required output files**
   - Identify the exact file names and formats expected by the verifier (e.g., `normal_samples.txt`, `exponential_samples.txt`).
   - Each file should contain a single column of sampled values (one per line) with no header unless otherwise specified.
   - Run the sampler with the specified parameters (e.g., `n=1000`) and write the samples to those files.

4. **Deliverables checklist (mandatory)**
   - [ ] R script saved at the correct path (e.g., `/app/ars.R`).
   - [ ] Sample output files written with exact names and format (e.g., single column of numeric values).
   - [ ] Test suite passes and its output matches the verifier’s expected test report (run `test()` and confirm all tests pass).
   - [ ] If a pull request is required: stage the files (`git add`), commit (`git commit -m "Implement ARS"`), and push to the specified remote/branch (`git push`).
   - [ ] If a formal report is required: write a brief report (e.g., `/app/report.md`) summarizing algorithm, parameters, and results.

5. **Verify the output against the verifier’s criteria**
   - Re-read the task description and any verifier specification to ensure file paths, output format, and any extra steps (e.g., creating a pull request) are fully addressed.
   - Do not rely solely on your own tests; confirm that the produced files meet the verifier’s exact expectations (e.g., numeric precision, column spacing, presence of an empty line at end of file).

> **Note:** This alternative use applies when the task explicitly asks for implementation of adaptive rejection sampling in R. If the task is about data merging or other topics, ignore this section.

## Alternative use: Filtering JavaScript from HTML

Use the following procedure when asked to strip JavaScript (e.g., `<script>` tags, event handlers, `javascript:` URIs) from an HTML file while preserving the exact whitespace and formatting of the original document. The safest approach is to use a parser (e.g., BeautifulSoup) rather than regex.

1. **Parse with an HTML parser**  
   Use BeautifulSoup with the built-in `html.parser` (no external dependencies). Open the file and parse into a DOM tree.

2. **Remove dangerous tags**  
   Remove all elements matching a predefined set of dangerous tags: `script`, `iframe`, `object`, `embed`, `applet`, `base` (when `href` contains `javascript:`). Use `tag.decompose()` to remove the element and its contents.

3. **Strip dangerous attributes**  
   For every remaining element, iterate its attributes and remove:
   - All event handlers: any attribute whose name starts with `on` (e.g., `onclick`, `onerror`, `onload`).
   - Any URI attribute (e.g., `href`, `src`, `action`) whose value starts with `javascript:`, `vbscript:`, or `data:text/html`. Remove the entire attribute; do not change the element.

4. **Remove orphaned whitespace nodes**  
   After removing elements, the tree may contain adjacent text nodes that consist solely of whitespace (spaces, newlines). These can create blank lines and alter formatting. To preserve the original layout exactly, walk the tree and for each text node that is a sibling of a removed element (or a direct child of the body/root after removal), check if it contains only whitespace. If so, delete it using `extract()` – but **do not** modify text nodes inside `<pre>` or `<textarea>` elements, where whitespace is meaningful. This step ensures that removing a `<script>` tag on its own line does not leave an empty line.

5. **Re-serialize**  
   Convert the cleaned tree back to string using `str(soup)` and write to the same file (or to a new file as requested).

6. **Verification**  
   Verify that:
   - No `<script>` or `<iframe>` tags remain.
   - No `on*` attributes exist.
   - No `javascript:` URIs are present in links.
   - The overall structure (tables, paragraphs, comments) is intact.
   - The file size is not excessively larger (which would indicate duplication from improper decomposition).

> **Note:** This alternative use applies when the task explicitly asks for filtering JavaScript from HTML. If the task is about data merging or other topics, ignore this section.

## Alternative use: Reverse-engineering a compiled binary (raytracer/path tracer)

Use the following procedure when asked to reverse-engineer a compiled binary that renders a scene (raytracer/path tracer) and produce an equivalent C program. The output must be a self-contained C file that, when compiled with `-static -lm` and run, produces a byte-identical PPM image compared to the original binary's output.

1. **Determine binary format and entry point**  
   Identify the file format (e.g., ELF64) and locate the entry point, usually the `main` symbol. Use tools like `file`, `readelf`, or `nm` (if available) to inspect the binary.

2. **Disassemble and analyze the rendering loop**  
   Disassemble the main function (e.g., with `objdump -d`). Identify the rendering loop (typically nested for-loops over image width and height). Pay attention to:
   - Floating-point constants (e.g., 0.70710678 for normalization, 2.6666667 for aspect ratio, scaling factors)
   - Calls to `sqrt` or other math functions
   - Comparisons and branches that indicate geometry tests (ray-sphere intersection, ground plane, checkerboard pattern)

3. **Extract scene parameters from data sections**  
   Dump the data sections (`.rodata`, `.data`) near the main code. Look for groups of four single-precision floats (12 bytes for x,y,z center, plus radius) that likely encode sphere parameters. Record their exact values.

4. **Deduce camera direction**  
   Examine the initial ray direction calculation. Often it involves normalizing a vector (e.g., `normalize(1,1,-1)`). Identify the exact components and any scaling factors used in the ray direction formula (e.g., `dx = x/width * aspect - offset`, `dy = -1.0`, `dz = 1 - 2*y/height`).

5. **Determine lighting model**  
   Look at how the surface normal is computed (e.g., from sphere center intersection) and how it is used with a light direction (constant or computed). Identify the diffuse shading calculation, any ambient term, and whether a checkerboard pattern or sky gradient is applied.

6. **Reproduce arithmetic in C**  
   Write a C program that replicates the exact arithmetic using single-precision `float`. Use the same constants, same clamping (`fminf(fmaxf(v,0),1) * 255.99f`), and same output format (PPM header `P6\nwidth height\n255\n` followed by binary RGB pixel data). Ensure the output file is written byte-for-byte identical to the original.

7. **Verify correctness**  
   Compile the C program with `gcc -static -o reversed mystery.c -lm` and run it. Compare the output image byte-for-byte with the original binary's output (e.g., `diff` or `cmp`). If not identical, adjust constants or arithmetic details.

> **Note:** This alternative use applies when the task explicitly asks for reverse-engineering a compiled raytracer/path tracer binary. If the task is about data merging, ignore this section.

## Alternative use: Installing legacy Windows 3.11 in QEMU

Use the following procedure when asked to install or boot a legacy Windows 3.11 for Workgroups image under QEMU. The procedure handles compatibility differences between the image's original QEMU version and the currently installed QEMU version.

1. **Select the correct machine type**  
   - Determine the QEMU version the image was created with (e.g., QEMU 5.2.0).  
   - Use a machine type that matches that era, e.g., `-machine pc-i440fx-5.2` for QEMU 5.2 images.  
   - If the machine type is unknown, start with a generic `pc-i440fx-2.0+` and adjust as needed.

2. **Configure CPU and ACPI**  
   - Use `-cpu pentium` or a compatible CPU model. If the desktop appears briefly and then the VM exits to DOS, try `-cpu 486`.  
   - Add `-no-acpi` to disable ACPI, as Windows 3.11 does not support it and may crash or exit.  
   - For additional stability, consider `-global PIIX4_PM.disable_s3=1 -global PIIX4_PM.disable_s4=1`.

3. **Set up VGA and display**  
   - Use `-vga cirrus` (Cirrus Logic GD5446) which is well-supported.  
   - Add `-display vnc=:1` for remote access, and optionally a QMP monitor (`-qmp tcp:localhost:4444,server,nowait`).  
   - Use snapshot mode (`-snapshot`) to avoid modifying the base image.

4. **Boot and verify stability**  
   - Launch QEMU with the above options and the Windows 3.11 image as the first boot drive.  
   - Connect via VNC and observe the boot process. The desktop should appear and remain stable.  
   - **Stability check**: Monitor the framebuffer for non-black pixels over several seconds. If the desktop disappears (returns to black or DOS prompt), the configuration is incorrect.  
   - Alternatively, verify through QMP that the VM remains in a running state (`query-status`) over an extended period (e.g., 30 seconds).  

5. **Troubleshooting**  
   - If the desktop disappears within seconds: try `-cpu 486`, `-no-acpi`, or a different QEMU version (if available).  
   - If the VM fails to boot at all: check the machine type, ensure the disk image is in a supported format (raw or qcow2), and verify the image is not corrupted.  
   - For input delivery, use QMP `send-key` commands (e.g., to send `Alt+F4` to close a window).  

6. **Deliverables checklist (mandatory)**  
   - [ ] QEMU process is running with the correct machine type and CPU.  
   - [ ] VNC or WebSocket bridge is accessible and the desktop is visible.  
   - [ ] VM stays in running state for at least 30 seconds (check via QMP).  
   - [ ] Snapshot mode is active (base image unchanged).  
   - [ ] If the desktop still disappears, a note is added explaining the known compatibility limitation and the attempted workarounds.  

> **Note:** This alternative use applies when the task explicitly asks for installing or booting a Windows 3.11 VM. If the task is about data merging or other topics, ignore this section.

## Alternative use: Sanitizing a git repository of secrets

Use the following procedure when asked to sanitize or remove secrets (e.g., API keys, tokens, passwords) from a git repository. **Important**: Simply editing the current working tree is insufficient – you must rewrite the entire commit history to expunge the sensitive data from all past commits.

1. **Identify secret patterns**  
   - Define regex patterns for secrets to remove (e.g., AWS keys `AKIA[0-9A-Z]{16}`, GitHub PAT `ghp_[0-9a-zA-Z]{36}`, etc.).  
   - For each pattern, capture only the secret value (avoid removing non-secret parts of lines