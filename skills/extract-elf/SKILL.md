---
name: extract-elf
description: Extract memory values from ELF binaries by parsing program headers, mapping virtual addresses to file offsets via PT_LOAD segments, and outputting integer values as JSON.
---

# Extract ELF Memory Values

When you need to read specific virtual addresses from an ELF binary's loaded segments and emit their integer contents as JSON, follow this procedure.

## 1. Parse the ELF Header

Read the first bytes of the file and identify:

- **EI_CLASS** (offset 4): `1` = ELF32, `2` = ELF64. Pick the matching struct layout for all subsequent fields.
- **EI_DATA** (offset 5): `1` = little-endian (LE), `2` = big-endian (BE). Apply to every multi-byte field.
- **e_phoff**: offset to the program header table.
- **e_phentsize**: size of one program header entry.
- **e_phnum**: number of program header entries.

Reject or branch if the magic `\x7fELF` is missing.

## 2. Iterate Program Headers

For each entry at `e_phoff + i * e_phentsize`, read its `p_type`, `p_flags`, `p_offset`, `p_vaddr`, `p_filesz`, `p_memsz`.

Keep only entries where:
- `p_type == PT_LOAD` (constant value `1`)
- the readable flag is set (bit `PF_R = 0x4` is present in `p_flags`)

For ELF64, all `p_*` fields are 64-bit (`Elf64_Phdr`); for ELF32 they are 32-bit (`Elf32_Phdr`). Do not mix widths.

## 3. Map Virtual Address → File Offset

For every loadable readable segment, the file range `[p_offset, p_offset + p_filesz)` corresponds to virtual addresses `[p_vaddr, p_vaddr + p_filesz)`.

To resolve any target virtual address `vaddr`:

```
file_offset = p_offset + (vaddr - p_vaddr)
```

Only addresses satisfying `p_vaddr <= vaddr < p_vaddr + p_filesz` are backed by file bytes; addresses outside that range are not initialized in the file.

## 4. Read 32-bit Little-Endian Values

For each target address, aligned to 4 bytes, read 4 bytes starting at `file_offset` and decode them as a **little-endian unsigned 32-bit integer** — regardless of the ELF's own data encoding, the JSON output format is fixed.

Skip or error the address if `file_offset + 4` exceeds the file length.

## 5. Emit JSON

Produce a JSON object whose keys are virtual addresses formatted as **decimal strings** and whose values are the decoded integers:

```json
{
  "1048576": 27089,
  "1048580": 0
}
```

Do not emit addresses that could not be mapped to any readable PT_LOAD segment.

## 6. Sanity Check

After extraction, verify that **at least 75%** of the requested addresses were successfully resolved from PT_LOAD readable segments. If coverage is lower, re-check segment selection (readable flag, `p_filesz` vs. `p_memsz`) and the vaddr→offset math before declaring success.

## Guardrails

- Branch on `EI_CLASS` early; using ELF32 field widths on a 64-bit binary (or vice versa) silently corrupts every subsequent offset.
- Honor endianness when reading `e_phoff`, `e_phnum`, etc.
- A segment with `p_filesz == 0` has no file bytes — skip it even if readable.
- `p_memsz > p_filesz` means the tail is zero-initialized (BSS); do not read past `p_filesz`.
- Iterate every PT_LOAD readable segment; do not stop after the first match — different segments cover disjoint address ranges.