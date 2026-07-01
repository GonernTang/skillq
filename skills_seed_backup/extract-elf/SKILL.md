---
name: extract-elf
description: Extract memory values from an ELF binary by parsing program headers and reading PT_LOAD segments. Use when a task requires mapping virtual addresses to integer values stored in an ELF file, reconstructing a memory image, or producing a JSON object of address→value pairs from a binary.
---

# Extract ELF Memory Values

## When to use

Use this skill when given an ELF binary and a request such as:
- "extract memory values from this ELF"
- "produce a JSON map of virtual addresses to integers"
- "reconstruct the memory image (only the file-backed region)"

The output is always an object whose keys are virtual-address strings and whose values are integers read from the file.

## Procedure

1. **Validate the magic.** Read the first 4 bytes; they must equal `0x7f 'E' 'L' 'F'`. If not, stop — this is not an ELF.

2. **Determine the class and endianness from the ELF header.**
   - Byte 4 (EI_CLASS): `1` = 32-bit, `2` = 64-bit.
   - Byte 5 (EI_DATA): `1` = little-endian, `2` = big-endian. Default assumption is little-endian (the common case); swap byte order for big-endian.
   - These two fields fix the sizes of every offset/length field below. Do not hardcode sizes.

3. **Locate the program-header table from the ELF header.**
   - 64-bit little-endian: `e_phoff` at offset `32` (u64), `e_phentsize` at offset `54` (u16), `e_phnum` at offset `56` (u16).
   - 32-bit little-endian: `e_phoff` at offset `28` (u32), `e_phentsize` at offset `42` (u16), `e_phnum` at offset `44` (u16).
   - For big-endian, decode each multi-byte field big-endian.

4. **Iterate program headers.** For `i` in `[0, e_phnum)`, read the `i`-th entry starting at `e_phoff + i * e_phentsize`:
   - `p_type` (4 bytes, u32). Keep entries where `p_type == 1` (PT_LOAD). Other types are skipped.
   - From each PT_LOAD entry, record:
     - `p_offset` — file offset of the segment (4 or 8 bytes)
     - `p_vaddr`  — virtual address where the segment maps (4 or 8 bytes)
     - `p_filesz` — number of bytes present in the file (4 or 8 bytes)
     - `p_memsz`  — number of bytes in memory (≥ `p_filesz`; ignore zero-initialized tail)

   **Skip any PT_LOAD with `p_filesz == 0`** — there is no file data to read.

5. **Decode the segment contents.** For each kept PT_LOAD, walk the file range `[p_offset, p_offset + p_filesz)`:
   - Read fixed-width words in file order. The common case is 4-byte little-endian words; use 8-byte words only if the task explicitly expects 64-bit values.
   - For word index `k`, the value's virtual address is `p_vaddr + (k * word_size)`.
   - Stop at `p_filesz`; do not synthesize entries for the BSS tail (`p_memsz > p_filesz`).

6. **Emit the result.** Produce a single JSON object:
   - Keys: addresses as strings (e.g. `"0x401000"` or decimal — be consistent across all keys).
   - Values: the integer read at that address.
   - Merge the contributions of every PT_LOAD segment into one object.

7. **Verify coverage.** Before returning, check that the produced map contains addresses spanning the full `[p_vaddr, p_vaddr + p_filesz)` range of every kept segment with no gaps in word strides. If coverage is well below the expected count, re-check the class/endianness assumption and the header offsets in step 3.

## Guard rails

- **Class-aware sizing.** A 64-bit binary misread as 32-bit will silently mis-parse every field after the magic. Always branch on `EI_CLASS` first.
- **No file data ⇒ no entry.** `p_filesz == 0` segments contribute nothing; the BSS region (`p_memsz > p_filesz`) must not be filled in.
- **PT_LOAD only.** Other `p_type` values (PT_DYNAMIC, PT_INTERP, PT_NOTE, PT_PHDR, PT_GNU_*) carry metadata, not the values being extracted.
- **Word stride is uniform.** A PT_LOAD of `p_filesz = N` bytes at 4-byte words yields exactly `N / 4` entries. Off-by-one strides indicate a mis-sized word or a missing tail word.
- **Don't trust default word size.** If the task says "64-bit values" or the addresses are 8 bytes apart, switch the word size; otherwise stick with 4 bytes.

## Minimal Python skeleton

```python
import json, struct

with open(path, "rb") as f:
    data = f.read()

assert data[:4] == b"\x7fELF"
ei_class = data[4]   # 1=32, 2=64
ei_data  = data[5]   # 1=LE, 2=BE
endian = "<" if ei_data == 1 else ">"

if ei_class == 2:  # 64-bit
    e_phoff    = struct.unpack_from(endian + "Q", data, 32)[0]
    e_phentsize = struct.unpack_from(endian + "H", data, 54)[0]
    e_phnum    = struct.unpack_from(endian + "H", data, 56)[0]
    ph_fmt = endian + "IIQQQQQQ"   # p_type,p_flags,...p_offset,p_vaddr,p_paddr,p_filesz,p_memsz,...
elif ei_class == 1:  # 32-bit
    e_phoff    = struct.unpack_from(endian + "I", data, 28)[0]
    e_phentsize = struct.unpack_from(endian + "H", data, 42)[0]
    e_phnum    = struct.unpack_from(endian + "H", data, 44)[0]
    ph_fmt = endian + "IIIIIIII"   # adjust to 32-bit program-header layout

WORD = 4
out = {}
for i in range(e_phnum):
    base = e_phoff + i * e_phentsize
    p_type = struct.unpack_from(endian + "I", data, base)[0]
    if p_type != 1:
        continue
    if ei_class == 2:
        (p_offset, p_vaddr, _, p_filesz, p_memsz, *_) = struct.unpack_from(ph_fmt, data, base)[2:7]
    else:
        (p_offset, p_vaddr, _, p_filesz, p_memsz, *_) = struct.unpack_from(ph_fmt, data, base)[2:7]
    if p_filesz == 0:
        continue
    for k in range(0, p_filesz, WORD):
        v = struct.unpack_from(endian + "I", data, p_offset + k)[0]
        out[str(p_vaddr + k)] = v

print(json.dumps(out, indent=2))
```

Tune `ph_fmt` to the exact 32- vs 64-bit program-header layouts; the offsets shown are the conventional ones, and the important invariant is that you read `p_type` first and gate on `== 1` before consuming the rest of the entry.