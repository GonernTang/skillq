---
name: binary-image-reverse
description: Reusable procedure for reverse-engineering a static binary that generates an image (PNG/PPM/etc.) — guardrails for moving from initial exploration to disassembly, math-trace, and bit-identical reimplementation, without invoking the original binary in the final solution.
---

## When to use

The task gives you a static binary whose only observable output is an image file (PNG, PPM, BMP, etc.), and asks you to either (a) reimplement its rendering in source code, (b) reproduce the same image, or (c) explain what it draws. The binary is the spec — you cannot just run it and submit the output.

## Why this skill exists

In the originating failure, the agent explored the binary superficially (file headers, strings, `file`/`nm`) and never advanced to disassembly or reimplementation, so it produced nothing verifiable. The trap is *exploration without commitment*: each tool call feels productive, but no rendering code ever gets written. The guard rails below force forward motion.

## Procedure

1. **Establish the output spec first.** Before touching the binary, determine what file it produces, its dimensions, format (PNG/PPM/P6/raw bytes), and pixel layout (RGB vs RGBA, top-down vs bottom-up). This is your comparison ground truth for every later iteration.
2. **Static analysis pass (one bounded round).** Run `file`, `strings`, `nm`/`readelf`, `objdump -d`, and `objdump -s -j .rodata` ONCE. Record: entry point, presence of `main`, libc vs static, strings that hint at the algorithm ("ray", "fractal", "mandel", "trace"), and any embedded constants (palette tables, magic numbers, dimension hints).
3. **Locate the render loop.** Disassemble `main` (or `_start` if statically linked with no `main`). Identify the outer pixel loop, the inner per-pixel computation, and the call to the file-write syscall (`write`, `fwrite`, or the PNG/PPM writer). Mark the bounds of the loop — this is where the algorithm lives.
4. **Trace the math.** Inside the per-pixel loop, enumerate every floating-point op (`sin`, `cos`, `sqrt`, `pow`, `atan2`, `fmod`) and every integer op that shapes coordinates (`<<`, `&`, `%`, divisions). Map them to: input coords (x, y, possibly z), a transform to "world" space, the color/intensity formula, and the output byte packing. Recreate the formula symbolically before writing C.
5. **Reimplement in clean C.** Write a standalone C file using the same math, same dimensions, same output format, same byte order. Compile with `-O0 -fno-fast-math` initially so the bit pattern matches what `objdump` shows; only enable fast-math after a baseline match.
6. **Verify by byte/hash comparison, not by visual inspection.** Hash both images (e.g. `sha256sum`, or `cmp` for raw PPM). Pixel diff tools are useful for diagnosis but a single-pixel-off failure usually means a coordinate transform bug, not an aesthetic one. Aim for byte-identical output on the first correct reimplementation.
7. **Never call the original binary in the final solution.** Your submitted code is the reimplementation. The original binary is a reference oracle used only during development to generate the comparison target.

## Diagnostic checklist (run BEFORE committing to your first C draft)

1. Did you confirm the output file's exact dimensions and format (header bytes for PPM, IHDR for PNG) by reading the binary's output, not just guessing from the task description?
2. Can you point to the instruction address in `objdump -d` where the per-pixel computation begins, and to the address where the output syscall is called?
3. Have you listed every transcendental/elementary math function called inside the render loop, and do you know which inputs feed each one?
4. Have you written a 1×1 or 10×10 test harness in C that exercises your reimplementation, hashed its output, and compared against the original binary's hash for the same size before scaling up to full resolution?

## Stop signal

If you have spent more than 3 tool calls on static analysis (`file`, `strings`, `nm`, `readelf`, first `objdump`) without having identified the render loop's instruction range, **stop exploring and start a C reimplementation from what you already know** — even a stub. Refine against the binary's output hash rather than continuing to read the binary.

If you have written 2 full-resolution reimplementations and both fail the hash comparison with mismatches in scattered pixels (not a global shift), abandon the per-pixel formula and re-read the disassembly: the bug is almost certainly a coordinate transform (off-by-one in the loop bound, swapped x/y, or a missing `-1` in the world-space mapping), not in the color math.

## Common pitfalls

- **Treating `strings` output as algorithm description.** A string like `"mandelbrot"` in `.rodata` is a hint, not a contract. Always verify against the disassembly.
- **Confusing coordinate systems.** Image y often runs top-down while math y runs bottom-up. Check whether the binary flips y (`height - 1 - y`) before passing to the formula.
- **Floating-point mode mismatches.** If the original uses x87 or strict IEEE and you compile with `-ffast-math`, you'll get bit-identical-looking but hash-different output. Match the original's FP semantics first.
- **Premature optimization.** Skipping the small-test step (item 4 of the checklist) means a full-resolution mismatch tells you nothing — you don't know if the bug is in 1 pixel or 1 million.
- **Submitting the binary's output instead of the reimplementation.** The task wants your code; running the binary once and saving the image is not a solution.

## Reference shell snippets (for development only, never in the final answer)

```
file ./mystery
strings ./mystery | grep -iE 'ray|trace|fract|mandel|ppm|png'
nm ./mystery | grep -i ' T '
objdump -d ./mystery > disasm.txt
sha256sum reference.ppm candidate.ppm
```