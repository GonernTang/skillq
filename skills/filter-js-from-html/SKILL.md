---
name: filter-js-from-html
description: "Sanitize HTML by removing all JavaScript vectors. Use when a task requires stripping JS from HTML (XSS prevention, content sanitization, allowlist cleaning). Covers script tags, event handlers, javascript: URIs, and dangerous embed elements (iframe, embed, object, applet, frame, noscript)."
---

# Filter JavaScript from HTML

When the task is "remove all JavaScript from this HTML, leave everything else intact", the easy failure mode is removing only the obvious `<script>` tag and missing a dozen other vectors. Use this procedure.

## Procedure

1. **Enumerate the JS vectors** before writing any code. The full list:
   - **Script-bearing tags**: `script`, `noscript`, `iframe` (including `srcdoc`), `frame`, `frameset`, `object`, `embed`, `applet`, `svg` (with `onload` etc.), `math` (with handlers), `base` (can hijack URLs), `meta` (with `http-equiv="refresh"` to `javascript:`), `template` (can be cloned into the DOM as executable).
   - **Event-handler attributes** on *any* tag: `on*` (onclick, onerror, onload, onmouseover, onfocus, onblur, onsubmit, onkeydown, …). Also `formaction`, `srcdoc` on iframe.
   - **JavaScript URI scheme** in any URL-typed attribute: `href`, `src`, `action`, `formaction`, `data`, `xlink:href`, `poster`, `background`, `codebase`, `cite`. Match both `javascript:` and case/space-encoded variants (`JaVa\tscript:`, `&#106;avascript:`, `java\nscript:`).
   - **`src` attribute on script/iframe/embed/frame**: remove the attribute itself (the element may be kept, but the source reference must go).
   - **CSS `expression()`** and `behavior:` URLs (legacy IE) inside `style` attributes / `<style>` tags.
   - **HTML comments** that contain `<script>` (browsers may parse them out in quirks mode).

2. **Match case-insensitively** for tag names and attribute names. Use `re.IGNORECASE` (Python) or the `i` flag everywhere.

3. **For void elements** (no closing tag: `script`/`iframe`/`embed` etc. are *not* void, but `embed`, `meta`, `base`, `img`, `br` are): remove the entire opening tag. For non-void tags, remove both opening and closing tag and everything in between. Use a non-greedy match for the content.

4. **Do not reformat the rest of the document.** Whitespace, attribute order, attribute quoting style, and the exact bytes between deletions should be preserved. If the task says "byte-identical except for removals", you must not "pretty-print".

5. **Prefer a real HTML parser** (`html.parser.HTMLParser`, BeautifulSoup, lxml, `html5lib`, `DOMParser`) over regex once you have more than 2-3 vectors. A parser is harder to bypass by nested or malformed HTML. If you must use regex, anchor patterns to `<` or whitespace, not to arbitrary text.

6. **For inline `<script>` blocks**: remove the entire block, including any `</script>` that may be missing or upper-cased. Handle the case `<!--<script>...` where a comment is opened before a nested script.

## Diagnostic checklist

Run **all** of these on your output before declaring the task done. Each must return zero matches:

1. **Tag inventory** — case-insensitive regex `<(script|noscript|iframe|frame|frameset|object|embed|applet|svg|math|base|meta|template)\b` finds nothing.
2. **Event-handler scan** — regex `\bon[a-z]+\s*=` (with word boundary) finds nothing on any tag.
3. **JS-URI scan** — regex `javascript\s*:` finds nothing inside any `href`, `src`, `action`, `formaction`, `data`, `xlink:href`, `poster`, `codebase`, or `style` value. Test both raw and HTML-entity–decoded forms.
4. **Src-on-script-like scan** — `<(?:script|iframe|frame|embed)\b[^>]*\bsrc\s*=` finds nothing.
5. **Nested/encoded variants** — feed a sample that includes `<!--<script>`, `<SCRIPT>`, `<scr` + `ipt>`, `<script/x>`, `<script >` (trailing space), `<script\t\n>`, `<a href="java\tscript:...">`, `<a href="&#106;avascript:...">`, `<svg/onload=...>`, `<iframe srcdoc="<script>...</script>">`. All must be neutralised.
6. **Preservation check** — non-script content (text, `<p>`, `<a href="https://...">`, attributes, comments that don't contain script, DOCTYPE, `<style>` with plain CSS) must be byte-identical to the input.

## Stop signal

- If you have rewritten the filter 3 times and the diagnostic checklist still flags any of checks 1–4, **abandon the regex-or-naive approach** and switch to a real HTML parser (`html.parser.HTMLParser` in the stdlib, or BeautifulSoup with `html.parser` / `html5lib`). Do not iterate a fourth time on the same architecture.
- If check 5 (nested/encoded variants) keeps slipping through even on a parser, you are probably mutating a serialized form rather than operating on the parse tree — switch to mutating `handle_starttag` / `handle_data` callbacks, not `str.replace` on the serialized output.
- If check 6 (preservation) fails, you are reformatting; back out the reformatting pass and do *only* deletions/replacements, never insertions of whitespace or new attribute ordering.