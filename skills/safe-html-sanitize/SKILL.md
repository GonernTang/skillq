---
name: safe-html-sanitize
description: Use a real HTML parser (not regex) to strip JavaScript vectors from HTML. Triggers when the task is to sanitize, clean, or filter HTML — especially removing <script>, event handlers, javascript: URLs, or other active content. Regex-based HTML stripping is fragile and bypassable.
---

# Safe HTML Sanitization

When the task is to remove JavaScript (or other active content) from HTML, do **not** attempt to write a regex or string-substitution sanitizer. HTML is not a regular language and regex-based stripping is bypassable in dozens of well-known ways.

## Diagnostic checklist (run BEFORE committing to an approach)

Before writing any sanitization code, confirm ALL of the following:

1. **Parser-based approach selected.** The implementation must use a real HTML/DOM parser (e.g. Python `html.parser`/`html5lib`, `BeautifulSoup`, `lxml`, `bleach`, `DOMPurify`, `sanitize-html`). If the chosen language has no parser available, fetch/install one — do not fall back to regex.
2. **JavaScript vector enumeration complete.** The sanitization rules explicitly cover each of the following vectors:
   - `<script>` elements (including `<script src=...>`, inline, JSON, and `type="module"` variants)
   - Event handler attributes (`onclick`, `onerror`, `onload`, `onmouseover`, `on*` prefix — any of the ~100+ HTML event attributes)
   - `javascript:`, `vbscript:`, `data:text/html`, and other dangerous URI schemes in `href`, `src`, `action`, `formaction`, `xlink:href`, `background`, `poster`, `srcdoc`, etc.
   - `<iframe>`, `<object>`, `<embed>`, `<applet>` (can load/embed active content)
   - `<style>` and CSS `expression(...)`, `@import`, `behavior:`, `-moz-binding` (legacy IE vectors)
   - `<svg>` and `<math>` event handlers (e.g. `<svg onload=...>`)
   - `<base href="javascript:...">` (changes relative URL resolution for the whole document)
   - `<meta http-equiv="refresh" content="0;url=javascript:...">` redirects
   - CDATA sections, HTML comments containing scripts, and `<!--<script>-->`-style hiding
   - Mixed-case tags (`<ScRiPt>`), embedded NUL bytes, and overlong attribute values
3. **Output is re-serialized from the parsed tree**, not text-edited. The parser must traverse a DOM tree, drop/modify nodes and attributes, and emit fresh markup. Never mutate the raw string with `replace`/`sub`/`gsub`.
4. **Round-trip test plan exists.** At minimum, the implementation must be exercised against inputs that contain: nested script tags, uppercase/mixed-case tags, script inside an attribute (e.g. `onmouseover="alert(1)"`), a `javascript:` href, an `<svg onload>`, and an `<iframe src=javascript:...>`. If any of these is not covered, the approach is unsafe.

## Stop signal

**Stop and reconsider the approach** if any of the following is true:

- The implementation contains a regex like `/<script.*?>/i`, `re.sub(r"<script.*?</script>", ...)`, or any pattern that tries to match HTML tags/substrings across line boundaries or case-insensitively. **Threshold: even one such regex in the sanitizer is grounds to abandon the approach and switch to a parser.**
- The implementation relies on a denylist of "known bad" attributes/tags without also enforcing a structural-validity invariant (e.g. "parse first, then walk").
- The output is produced by string substitution on the original input rather than by re-serializing a parsed tree.

**Reset action:** replace the sanitizer with a parser-based implementation. In Python, `BeautifulSoup(html, "html.parser")` plus an allowlist/denylist applied during traversal is a safe baseline; in JS, use `DOMPurify`; in any language, prefer a battle-tested library over a hand-rolled walker unless the threat model is explicit and reviewed.

## Reference skeleton (Python)

```python
from bs4 import BeautifulSoup

DANGEROUS_TAGS = {"script", "style", "iframe", "object", "embed",
                  "applet", "base", "meta", "link", "form"}
EVENT_ATTR_PREFIX = "on"

def sanitize(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.find_all(True):
        if el.name and el.name.lower() in DANGEROUS_TAGS:
            el.decompose()
            continue
        # Strip event-handler attributes and javascript: URLs.
        for attr in list(el.attrs):
            if attr.lower().startswith(EVENT_ATTR_PREFIX):
                del el.attrs[attr]
            elif isinstance(el.attrs[attr], str) and \
                 el.attrs[attr].strip().lower().startswith(("javascript:", "vbscript:", "data:text/html")):
                del el.attrs[attr]
    return str(soup)
```

Adapt the tag/attribute/URI lists to the actual threat model — but the **shape** (parse → walk → re-serialize) is non-negotiable.