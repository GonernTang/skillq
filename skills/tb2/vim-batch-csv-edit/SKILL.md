---
name: vim-batch-csv-edit
description: Perform large-scale CSV/structured-text transformations using Vim macros executed headlessly under strict keystroke and command constraints. Use when tasked with bulk CSV normalization, column reordering, case conversion, delimiter conversion, or appending constants across many lines.
---

# Vim Batch CSV Edit

Transform a large structured-text file (CSV, TSV, etc.) using chained Vim macros executed headlessly. Designed for constrained environments that limit which Vim commands may appear in a script and cap total keystrokes.

## When to use

- Input and expected output are both line-oriented, delimited records.
- Transformations include: whitespace stripping, delimiter change, case change, column reorder, appending a constant, removing blank lines, normalizing separators.
- Only a small whitelist of commands is permitted (e.g. `setreg()`, `:%normal! @<reg>`, `:wq`).
- The full macro must fit under ~200 total keystrokes across all registers.
- Final execution must be headless: `vim -Nu NONE -n -Es <input> -S <script>`.

## Procedure

### 1. Diff input vs. expected output

Read several rows of input and the matching expected output. List every atomic transformation as a separate item:

- whitespace strip (`^\s*`, `\s*$`, `\s*,\s*`)
- delimiter change (`,` → `;`, `|` → `,`, etc.)
- case change (upper / lower / title)
- column reorder
- constant suffix / prefix append
- blank-line removal
- BOM / quoting cleanup

### 2. Assign one transformation per register

Chain the transforms across distinct registers (`a`, `b`, `c`, …). One register = one concept. This keeps each macro small and the chain debuggable.

Typical register responsibilities:

| Register | Job | Example body |
|----------|-----|--------------|
| `a` | Trim & re-delimit | `:s/^\s*\|\s*$//g<CR>:%s/\s*,\s*/;/g<CR>` |
| `b` | Case change | `:%s/.*/\U&/g<CR>` or `gUU` |
| `c` | Reorder + append constant | `:%s/\v([^;]+);([^;]+);([^;]+)/\3;\2;\1;OK/g<CR>` |

Build each register's body using only allowed commands. Prefer `:%s/.../.../g` for line-wide structural edits (they survive headless mode and operate on every line in one shot). Use `gUU` only when the case change must run per-line inside a normal-mode macro.

### 3. Count keystrokes

Sum the literal characters of every register body plus the `setreg()` calls plus the `:%normal! @x` invocations. If the total exceeds the budget, do not split the work into more registers — instead merge adjacent transforms into a single `:%s/.../g` substitute, since one global substitute replaces work that would otherwise need per-line motion.

### 4. Test on a small sample first

Run the script on 3–5 input lines before the full file. Confirm the output matches expected line-for-line; mismatches almost always come from:

- A regex that doesn't escape the delimiter (`;` inside `[^;]+` is correct; `,` inside `[^,]+` is correct only if you remembered to switch the delimiter first).
- A case-change step running before re-delimiting, which can shift columns if values contain the delimiter.
- A trailing constant that overwrites rather than appends — use `&` or capture the original in `\0` and append: `\0;OK`.

### 5. Run headlessly

Invocation pattern:

```
vim -Nu NONE -n -Es <input> -S <script>
```

Flags explained:

- `-Nu NONE` — skip all user/system vimrcs.
- `-n` — no swap file (safe in CI / temp dirs).
- `-Es` — silent Ex mode, the right mode for batch Ex commands; messages suppressed, no UI.
- `-S <script>` — source the script after loading the file.

The script body must contain only the whitelisted commands — nothing else survives the sandbox.

### 6. Final script shape

```vim
" Clean & re-delimit
call setreg('a', ":s/^\\s*\\|\\s*$//g\<CR>:%s/\\s*,\\s*/;/g\<CR>")
" Upper-case everything
call setreg('b', "gUU")
" Reorder columns and append constant
call setreg('c', ":%s/\\v([^;]+);([^;]+);([^;]+)/\\3;\\2;\\1;OK/g\<CR>")

:%normal! @a
:%normal! @b
:%normal! @c

:wq
```

## Pitfalls

- **Escaping inside `setreg()`** — double-escape backslashes (`\\s` not `\s`) and use `\<CR>` for the literal carriage return that ends a normal-mode command.
- **Don't rely on remapped keys** — the sandbox runs with `-Nu NONE`, so only built-in motions work. Avoid `;`-style mappings and custom operators.
- **Use `:%normal!`** — the `!` prevents remap lookup and aborts cleanly on errors.
- **Order matters** — run whitespace + delimiter fixes before any regex that captures by field, otherwise capture groups are misaligned.
- **Headless output** — don't add `:print` or `:echo`; use `:wq` and inspect the file.
- **Constant-appending substitute** — anchor the replacement at end-of-line if you only want to add a trailing field: `\0;OK` (where `\0` is the whole match) keeps the original line intact.