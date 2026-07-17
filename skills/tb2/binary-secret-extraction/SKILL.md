---
name: binary-secret-extraction
description: Extract a hidden secret from an unknown binary by combining static analysis (strings, objdump, section dumping) with dynamic exploitation (buffer overflow to trigger a code path). Use when given an ELF/PE binary that "does something" only when a condition is met, and you need to recover the protected string.
---

# Binary Secret Extraction

A repeatable procedure for pulling a protected/hidden string out of a compiled binary when source is unavailable and the binary only reveals the secret after a specific condition is satisfied.

## Workflow

### 1. Triage with `strings`

```bash
strings <binary>
```

Look for:
- Dangerous input functions: `gets`, `scanf`, `strcpy`, `sprintf` — these signal a buffer-overflow entry point.
- Nearby sentinel/check strings (e.g. a flag literal the program compares against).
- Any readable hint of an obfuscated payload (you usually won't see it here — that's the point).

### 2. Confirm the vulnerability with a dynamic probe

If `gets`/`scanf` is present, feed a deliberately oversized input and watch for a behavioral change:

```bash
python3 -c "print('A' * 200)" | ./<binary>
```

A segfault, an extra print, a "you win" branch, or any output that wasn't there with normal input confirms the overflow actually overwrites a control value or return path.

### 3. Disassemble and dump the data sections

```bash
objdump -d <binary>            # assembly
objdump -s -j .data <binary>  # initialized globals
objdump -s -j .rodata <binary>  # read-only constants
```

Focus your eyes on:
- The function containing the dangerous read — its stack frame layout tells you the offset needed to overwrite the check variable / return address.
- `.rodata` and `.data` for blocks of non-ASCII bytes adjacent to short constants. Obfuscated payloads often sit next to the key used to obfuscate them.

### 4. Identify the encoding scheme

Common patterns to look for:
- **XOR key as a nearby constant** — a single byte, a short string, or a repeated trailing byte.
- **Length byte / null-terminator boundaries** giving you the exact payload size.
- **A "decrypt" loop** in the disassembly that walks a buffer and XORs each byte.

If you see a small constant used inside a loop that touches a large blob of non-ASCII data, the constant is almost certainly the XOR key (or part of a multi-byte key).

### 5. Decode

Reproduce the decode in Python:

```python
data = bytes.fromhex("...")   # from objdump -s output
key  = 0x...                  # the byte/bytes you identified
plaintext = bytes(b ^ key for b in data)
print(plaintext)
```

For multi-byte keys, repeat the key cyclically: `key[i % len(key)]`.

### 6. Verify by exploitation

Use the decoded secret as the trigger:

- If the secret is the value a check variable must equal, craft an input whose overflow writes that exact value at the right offset and re-run the binary. The "protected" output should appear.
- Alternatively, run the binary under a debugger, set a breakpoint on the print/comparison, and feed the secret directly.

The secret is confirmed only when the binary actually emits it in response.

## Generalization tips

- The exact overflow offset and the exact data-section name vary by binary; the **shape** of the procedure (strings → overflow probe → objdump sections → XOR decode → exploit to verify) does not.
- If `strings` shows no dangerous input function, look for format-string bugs (`printf(user_input)`) or hardcoded backdoors before assuming static extraction alone will work.
- When the obfuscated blob is in `.data` (writable) rather than `.rodata`, check whether the binary patches it at runtime — decoding the on-disk bytes may give garbage until the patch is applied first.