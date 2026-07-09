---
name: use-specified-format
description: Parse and emit the exact file/data format named in the task spec; do not substitute a more convenient converted format as a workaround.
---

The task spec names a specific input format (and usually an output format). The
solution must read that format directly and emit the named output format. A
common failure is to "simplify" by converting the input to an intermediate
format (e.g. a flat binary blob, JSON dump, numpy array, single .bin) and
operating on the converted form. The verifier then rejects the solution
because it no longer matches the contract the spec defined.

## Diagnostic checklist

Before committing to an implementation, run these checks:

1. **List named formats.** Quote every format token in the spec — extensions
   (`.ckpt`, `.pb`, `.bin`, `.safetensors`, `.npy`), container words
   ("protobuf", "MessagePack", "NDJSON"), and shape/encoding hints ("little
   endian", "varint", "LZF compressed"). Write them down so the plan can be
   cross-checked.
2. **Confirm read path is direct.** The read path in the plan must open the
   named file(s) and parse their bytes. If any step between "open file" and
   "produce output" performs a format conversion that the spec did not
   authorize, that step is a contract violation, not an optimization.
3. **Confirm write path is direct.** Output bytes must serialize to the
   named format. A different extension or serialization is a contract
   violation even if the data values are correct.
4. **Search spec for conversion allowances.** If the spec says "you may
   convert" or "input may be preprocessed", the substitution is allowed.
   Absence of such language means it is not.

## Stop signal

**Threshold:** the plan introduces any pre-processing step that converts the
named input into a different format, or any output step that emits a format
other than the one named in the spec.

**Reset action:** stop, re-read the spec verbatim, extract the exact format
tokens, and redesign the solution to parse/serialize those tokens directly.
If direct parsing is genuinely infeasible in the chosen language, the fix is
to add a real parser for the named format — not to change the format.
Surface the infeasibility to the user instead of silently substituting.

## Worked anchor (from failure record)

The task named a TensorFlow checkpoint (`.ckpt`). The agent produced a
converted flat binary and read that instead of parsing the protobuf-based
`.ckpt` stream directly. The values may have been correct; the contract was
not, and the verifier rejected the submission. The fix was to implement a
real protobuf/ckpt reader, not to keep the converter.