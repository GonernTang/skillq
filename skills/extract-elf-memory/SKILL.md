---
name: extract-elf-memory
description: Extract memory from ELF64 binaries or fit Raman G and 2D peaks from spectroscopic data.
---

# Extract ELF64 Memory Image as Address→Value JSON

## When to use

Use this skill when you need to read a 64-bit little-endian ELF binary and produce a dictionary mapping virtual addresses to 4-byte little-endian unsigned integers found in its loadable segments. Common triggers:

- Building an initial memory image for an emulator or VM
- Reverse-engineering embedded constants in a binary
- Diffing two binaries' loadable data

**Important:** This skill is solely for extracting memory from ELF64 binaries. Do not use it for tasks unrelated to ELF binary analysis, such as implementing an interactive terminal, writing a web server, creating polyglot Rust/C++ files, or any other non-ELF procedure. For example, do not use this skill for building POV‑Ray from source. If the task does not involve a 64-bit little-endian ELF file, stop and select a different skill.

## Preconditions / Assumptions

- Target binary is **ELF64** (ELF class 2) and **little-endian** (data encoding 1).
- Values of interest are **4-byte aligned**, **little-endian unsigned** integers (range 0..2^32-1).
- You have a synchronous file API that can read arbitrary byte ranges (e.g., Node.js `fs.readSync`, Python `mmap`, Go `os.File.ReadAt`).

If the binary is ELF32, big-endian, or values are wider than 4 bytes, this procedure must be adapted (offsets, field sizes, and read width change).

## Procedure

### 1. Validate and parse the ELF header

Read the first **64 bytes** (ELF64 header size).

| Offset | Size | Field           | Required value                         |
|--------|------|-----------------|----------------------------------------|
| 0      | 4    | magic           | `0x7F 'E' 'L' 'F'`                     |
| 4      | 1    | ei_class        | `2` (ELFCLASS64)                       |
| 5      | 1    | ei_data         | `1` (ELFDATA2LSB)                      |
| 32     | 8    | e_phoff         | Program header table file offset       |
| 54     | 2    | e_phentsize     | Size of one program header entry (56)  |
| 56     | 2    | e_phnum         | Number of program header entries       |

Abort with an error if magic/class/endianness checks fail.

### 2. Walk the program header table

For each entry `i` in `0..e_phnum`, read **56 bytes** starting at `e_phoff + i * e_phentsize`. For ELF64 each entry's layout is:

| Offset | Size | Field     |
|--------|------|-----------|
| 0      | 4    | p_type    |
| 8      | 8    | p_offset  |
| 16     | 8    | p_vaddr   |
| 32     | 8    | p_filesz  |
| 40     | 8    | p_memsz   |

Keep only entries where `p_type == 1` (`PT_LOAD`). Skip segments where `p_filesz == 0` (e.g., uninitialized `.bss`); they have no file data to read.

### 3. Scan each LOAD segment for 4-byte words

For each kept segment:

1. Read `p_filesz` bytes from file offset `p_offset` into a buffer.
2. Iterate `offset_in_segment` from `0` to `p_filesz - 4` inclusive, stepping by `4`.
3. At each step read the 4 bytes as a **little-endian unsigned** integer.
4. Compute `vaddr = p_vaddr + offset_in_segment` and store `dict[str(vaddr)] = value`.

Use **unsigned** reads (e.g., `Buffer.readUInt32LE` in Node, `struct.unpack('<I')` in Python) — signed reads will produce negatives for values ≥ 2^31.

### 4. Emit JSON

Serialize the dictionary with `JSON.stringify` (or `json.dumps`) and write to stdout or the requested output path.

## Implementation notes

- Read the **exact** number of bytes requested; truncated reads cause silent data loss. For large segments, chunk or `mmap` rather than relying on single-call reads of arbitrary size.
- Use the binary's **virtual** addresses as keys (not file offsets) so the output is meaningful to emulators/loaders that address memory by VA.
- Multiple segments may map overlapping or nearby VA ranges; the later segment's data wins for shared addresses — decide whether you need to merge or overwrite based on the use case.
- Values are emitted as JSON numbers; JavaScript numbers are safe up to 2^53, which is well above 2^32, so no precision loss.

## Verification

After producing the dictionary:

1. **Round-trip**: parse a known constant location from a reference (e.g., a documented symbol address) and confirm the value matches the binary.
2. **Count sanity check**: for a segment of `p_filesz` bytes, expect exactly `p_filesz / 4` entries (after rounding down — partial trailing bytes are intentionally ignored).
3. **Spot-check bounds**: the minimum key should be ≥ `p_vaddr` for the lowest segment; the maximum should be ≤ `p_vaddr + p_filesz - 4`.

## Minimal Node.js sketch

```javascript
const fs = require('fs');
const fd = fs.openSync(path, 'r');
const header = Buffer.alloc(64);
fs.readSync(fd, header, 0, 64, 0);
// validate magic, class=2, data=1
const e_phoff    = Number(header.readBigUInt64LE(32));
const e_phentsize = header.readUInt16LE(54);
const e_phnum    = header.readUInt16LE(56);
const mem = {};
for (let i = 0; i < e_phnum; i++) {
  const ph = Buffer.alloc(56);
  fs.readSync(fd, ph, 0, 56, e_phoff + i * e_phentsize);
  const p_type   = ph.readUInt32LE(0);
  const p_offset = Number(ph.readBigUInt64LE(8));
  const p_vaddr  = Number(ph.readBigUInt64LE(16));
  const p_filesz = Number(ph.readBigUInt64LE(32));
  if (p_type !== 1 || p_filesz === 0) continue;
  const seg = Buffer.alloc(p_filesz);
  fs.readSync(fd, seg, 0, p_filesz, p_offset);
  for (let off = 0; off + 4 <= p_filesz; off += 4) {
    mem[String(p_vaddr + off)] = seg.readUInt32LE(off);
  }
}
console.log(JSON.stringify(mem));
```

---

## Alternate Use: Raman G and 2D Peak Fitting

Use this section when the task is to fit Raman G and 2D peaks from spectroscopic data.

### Procedure

1. **Load the spectrum data**  
   - Handle locale-specific decimal separators (comma-to-dot conversion) and tab delimiters.
   - The data should be two columns: wavenumber (cm⁻¹) and intensity.

2. **Identify approximate peak positions**  
   - G peak: search the window **1500–1700 cm⁻¹** for the maximum intensity.
   - 2D peak: search the window **2600–2800 cm⁻¹** for the maximum intensity.

3. **Fit the G peak**  
   - Model: Lorentzian (amplitude, gamma, x₀) + linear background (m, b).  
   - Parameters:
     - x₀: within the G window (1500–1700)
     - gamma > 0
     - amplitude > 0
   - Use appropriate bounds to keep parameters physically meaningful.
   - Fit using a least-squares optimizer (e.g., Levenberg–Marquardt).

4. **Fit the 2D peak**  
   - Model: Lorentzian with a constant offset (no linear slope).  
   - Parameters:
     - x₀: within the 2D window (2600–2800)
     - gamma > 0
     - amplitude > 0
   - Bounds as above.

5. **Validate results**  
   - Check x₀ lies inside the expected range.
   - Check gamma > 0, amplitude > 0.
   - Compute RMS residual relative to the data mean.
   - If the fit fails to converge, re-run with adjusted bounds.

6. **Output JSON**  
   - Keys: `"G"` and `"2D"`.
   - Each key maps to an object with four parameters: `x0`, `gamma`, `amplitude`, `offset` (or `m`, `b` for the G peak’s linear background).
   - Save to the requested output path (e.g., `results.json`).

### Implementation Notes

- For the fitting, use a library such as SciPy (`curve_fit`) or a custom gradient‑descent implementation if no external libraries are available.  
- Ensure that the fitter supports parameter bounds (e.g., `scipy.optimize.curve_fit` with `bounds`).  
- The Lorentzian function: \( L(x) = \frac{A}{\pi} \frac{\gamma}{(x-x_0)^2 + \gamma^2} \) (with amplitude \(A\) and half‑width \(\gamma\)). The offset/background is added separately.

### Verification

- Plot the data and the fitted curve (if graphics are available) to visually confirm the fit quality.
- Compare fitted x₀ to the approximate peak location from step 2; they should be close.
- Ensure the RMS residual is small relative to the peak height.