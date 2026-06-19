---
name: encoded-content-extraction
description: When asked to extract text or semantic content from a file format that encodes it non-obviously (gcode toolpaths, CAD geometry, plotter commands, vector graphics, raster images), use a layered check — metadata first, then the format's actual encoding mechanism — before concluding the message is absent. Use this whenever a file's primary data is non-textual but is suspected to carry a hidden message, label, or name.
---

# Extracting Semantic Content from Encoded File Formats

When asked to find a hidden text, message, or label inside a file whose primary data is *not* text (gcode toolpaths, CAD geometry, plotter commands, vector graphics, embedded bitmaps, etc.), follow this procedure. The message is almost always somewhere — your job is to find the right layer.

## The Guard Rail

### 1. Check obvious metadata first
Most formats carry the answer in human-readable comments or metadata. Examples:
- Lines starting with `;` (gcode comments), `#` (some interpreters), `//`
- XML/SVG: `<text>`, `<desc>`, `<title>`, comments
- CAD: title block, layer names, custom properties
- PDF: annotations, document properties
- Image: EXIF, IPTC, XMP

If the message is here, stop — you're done.

### 2. Do NOT mistake structural labels for content
Many formats have marker commands that name regions. These label *what* something is, not *what it says*.
- Object-cancel / object-label markers name the object — they are NOT the printed message.
- Layer/group names describe organization.
- Block, section, or entity identifiers label structure.

**A label like "object: greeting_card" tells you the object *is* a greeting card. It is NOT the message printed on the card.** You must still read the data inside the labeled region. If you find only the label and report it as the answer, you have failed.

### 3. If metadata is empty, identify the actual encoding mechanism
The content is encoded in the file's primary data. Match the decoder to the encoding:

| Encoding type              | Signal                                           | Decoder                          |
|----------------------------|--------------------------------------------------|----------------------------------|
| Geometric / toolpath       | Movement commands tracing shapes                 | Render to image, then OCR / read |
| Pixel / raster             | Binary image data                                | View as image, then OCR          |
| Coordinate sequences       | Ordered (x, y) points                            | Plot them and OCR                |
| Byte / binary stuffing     | Hidden in unused fields, LSBs, padding bytes     | Bit-pattern analysis             |
| Procedural / parametric    | Math expressions that resolve to shapes          | Evaluate and render              |

For geometric / toolpath / plotter formats, **rendering is almost always the answer** — the data was authored to produce a visual output, so the visual output *is* the content. A 30-second render beats 30 minutes of coordinate arithmetic.

### 4. Reconstruct systematically
- Process commands in execution order (top-to-bottom for gcode, draw-order for SVG, layer order for CAD).
- Group related commands; reset state at natural boundaries (object markers, layer changes, color changes, pen-up events).
- Render one labeled group at a time so a wrong decoder doesn't mask a right one.
- Verify by checking that the reconstructed shape "looks like" what the file was meant to produce — if letters look right, you're done; if they look like noise, you grouped wrong.

### 5. Use the right tools
- Geometric: matplotlib / Pillow / Cairo / online gcode visualizer / `gcode-sender` style tools.
- OCR: tesseract, easyocr, or a vision-capable model on the rendered image.
- Parsing: a real parser for the format beats regex — regex on coordinate languages is brittle.

## Failure Modes to Avoid

- **Stopping at metadata.** "No comments found" ≠ "no message." Move to step 3.
- **Confusing labels with content.** An object name is not the message; the rendered shape is.
- **Assuming textual encoding.** If the format's purpose is visual/physical output, the message is almost always visual, not textual. Don't grep for words in coordinate streams.
- **Skipping visualization.** For geometric formats, render first, decode second.
- **Quitting after the first plausible match.** If a label and the rendered content disagree, the label is the red herring.

## Quick Decision Tree

```
File given → extract text?
  ├─ Comments / metadata / annotations contain it? → Done.
  ├─ Structural labels present? → They're names, not the message. Read inside.
  ├─ Primary data is geometric (paths, moves, points)? → Render → OCR / read.
  ├─ Primary data is raster? → View as image → OCR.
  ├─ Primary data is parametric? → Evaluate → render.
  └─ None of the above? → Parse the format spec; the encoding is documented.
```