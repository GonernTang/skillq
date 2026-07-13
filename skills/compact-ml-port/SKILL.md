---
name: compact-ml-port
description: Guidance for writing self-contained, small (<5000 byte) C programs that load and run ML model checkpoints (e.g. TensorFlow .ckpt, .pb, raw weight blobs) — covering binary format parsing, BPE/vocab tokenization, model forward pass, and arg-max sampling. Use when porting a model to C in a code-golf context.
---

# Compact C Port of an ML Checkpoint

Apply when you must embed a pretrained neural network (transformer,
RNN, etc.) into a single small C file that loads weights from disk
and produces output text or token IDs. The goal is end-to-end runtime
correctness, not minimal abstraction — but the source must remain
tiny (typically under ~5 KB) and compile with `gcc -O3 -lm`.

## Diagnostic checklist (run BEFORE writing the C file)

1. **Inspect the checkpoint format.** Confirm whether weights are
   a TensorFlow V2 `.ckpt` (variable shape + offset table inside a
   record file), a frozen `.pb` GraphDef, or a raw serialized array.
   Print the first ~64 bytes and the first few records to identify
   magic numbers, endianness, and the layout of the tensor name →
   offset table. Wrong endianness or wrong record offset is the #1
   silent failure here.
2. **Verify the weight table.** Extract every tensor name and shape
   the checkpoint claims to hold. Cross-check the shape count against
   the architectural spec (e.g. GPT-2 small: wte[50257,768],
   wpe[1024,768], 12× attn q/k/v/out, 12× ln_1/2, etc.). If the
   shapes you read do not match a model of the declared size, the
   offset table or slice order is wrong — stop and reparse.
3. **Test BPE tokenization in isolation first.** Before any forward
   pass, load `vocab.bpe` (or `merges.txt`), build a token-id table,
   and round-trip a known prompt. Given a fixed input string, the
   token IDs must match a reference (Python `tokenizer.encode`)
   byte-for-byte. A wrong regex, missing `Ġ` → space mapping, or
   off-by-one in merge rules will garbage every downstream logit.
4. **Confirm output contract.** Decide and document: argv order,
   whether output is token IDs or decoded text, how many tokens to
   emit, where they go (stdout vs file), and whether BOS/EOS are
   appended. Match exactly what the grader expects — guess here and
   the run is wasted.

## Implementation guardrails

- **CLI surface:** argv[1] = model path, argv[2] = vocab path,
  argv[3] = prompt. Read prompt as a fixed-size buffer; reject
  longer inputs explicitly.
- **Forward pass (transformer):** embed = wte[token] + wpe[pos];
  for each layer — `ln_1 → Q,K,V → causal mask → softmax(QKᵀ/√d)V
  → out proj → residual → ln_2 → 4× MLP (gelu) → residual`; final
  LN; `argmax(wteᵀ · hidden)` to pick next token. Keep all ops on
  flat `float` arrays in one or two statically-sized buffers.
- **Numeric hygiene:** use `float`, not `double`, for weights and
  activations unless the reference demands otherwise. Apply a small
  epsilon (1e-5) inside `sqrt` for the attention scale. Mask future
  positions with `-1e30` (or a large finite negative) before softmax.
- **Output:** emit exactly N tokens (commonly 20), decoded via the
  reverse vocab table. Strip the `Ġ`/`▁`/byte-marker prefixes before
  printing; write to stdout with `printf("%s", ...)` or `fputs`.
- **Termination:** must `return 0` cleanly after N tokens; do not
  loop on EOF or recurse — keep it iterative.

## Stop signal

If, after loading weights, more than 3 architectural elements
(tensor count, tensor shape, position of a known matrix, BPE
output for `print("test")`, or sample output for a fixed seed)
disagree with a reference implementation, **stop and rebuild the
loader from scratch** — patching around the mismatch is faster to
write but produces a number that *looks* like logits and is
nonsense. Reset by re-deriving every (name, shape, dtype, offset)
tuple from the raw bytes before touching the forward pass.