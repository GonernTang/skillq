---
name: gcode-text-extract
description: Extract semantic text/labels from G-code and similar machine-instruction files instead of just geometrically analyzing extrusion paths. Use when asked to read text that is embedded or visually drawn by 3D printing / CNC / slicer output (e.g. "what does this G-code say?").
---

# G-code Text Extraction

G-code files often *contain* human-readable text semantically, but they can also *draw* text as extrusion geometry. The naive failure is to OCR the toolpath silhouette — slow, fragile, and often wrong because it ignores the much simpler source data that already lives in the file.

## Diagnostic checklist (run BEFORE picking an approach)

Before parsing any extrusion geometry, run these checks in order. If any succeeds, return that result and stop.

1. **Text comments**: Search the raw file for `;` line-start comments. Slicers (PrusaSlicer, SuperSlicer, OrcaSlicer, BambuStudio, Cura+plugin) routinely embed the printed object name / label as a leading comment block. A literal regex match is the *fastest* and *correct* answer when present.
2. **Object/labels (M486)**: Grep for `M486 A` lines. Marlin-style multi-object G-code names each object with `M486 A"text"` or `M486 A"text"` followed by `M486 S<object_index>`. The label string between the matching quotes IS the answer.
3. **Object markers (Cura etc.)**: Cura uses `;LAYER:N` + `;MESH:NONZERO` blocks and per-object banner comments like `; printing object "NAME"`. Grep for these prior to geometric OCR.
4. **Fallback to geometry only after step 1-3 fail**: If and only if the file encodes the text purely as printed extrusion paths with no metadata, *then* reconstruct toolpath segments (G0/G1 with E>0), filter by `M486 S0/S-1` boundaries if multi-object, rasterize, and run an OCR/letter-recognizer on the bitmap.

## Stop signal

If steps 1-3 each yield zero direct matches (no comments, no `M486 A` labels, no Cura banner text), and the file is multi-object, **stop** and isolate the target object by its `M486 S0` / `S-1` block before running geometry OCR — running OCR over the entire canvas of all objects will read the *wrong* glyphs (neighboring parts, skirt, brim, purge tower) and report them confidently.

Reset action: never claim extracted text unless either (a) it appears as a verbatim string in the file's metadata/comments, or (b) it survives an isolation pass + OCR pass where the isolated bitmap region visually matches the reported length and character set.

## Anti-patterns

- Skipping comment/label greps and going straight to extrusion reconstruction.
- OCRing the full G-code render when the file uses object markers (multi-object bleed-through).
- Returning "I analyzed the toolpath shape, it looks like LETTERS" instead of a concrete string.
- Treating `;TIME:` / `;Filament used:` metadata as the answer — those are stats, not the printed label.