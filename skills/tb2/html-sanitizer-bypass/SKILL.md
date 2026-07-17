---
name: html-sanitizer-bypass
description: Bypass HTML/script-tag sanitizers by exploiting parser differential between BeautifulSoup's html.parser and the browser HTML5 parser using raw-text element nesting.
---

# HTML Sanitizer Bypass via Parser Differential

## When to use
- A server-side sanitizer (e.g. BeautifulSoup with `html.parser`, html5lib's stricter modes, custom regex strippers) is removing dangerous tags like `<script>`, `<iframe>`, or event-handler attributes.
- The sanitizer's output is then served back to browsers as HTML.
- You need a payload that survives sanitization but still renders/executes as a script (or other blocked content) in the browser.

## Core idea
Two parsers see the same bytes differently. The sanitizer walks one tree; the browser builds another. Find a raw-text element boundary (where one parser stops parsing tags but the other continues) and place the blocked tag just past that boundary so only the browser sees it.

## Reusable technique: `<noscript>` + `<style>` confusion
Most HTML sanitizers correctly model `<script>` and `<style>` as raw-text / RCDATA elements whose contents are never parsed for tags. They also correctly model `<noscript>` as a raw-text element *only when JavaScript is enabled in the parser*. In Python's `html.parser` (and therefore BeautifulSoup's `html.parser` backend) `<noscript>` is treated as ordinary content with normal children — but `<style>` *is* still raw-text.

Payload template:
```
<noscript><style></noscript><SCRIPT_TAG>PAYLOAD</SCRIPT_TAG></style></noscript>
```

### How each parser sees it
- **BeautifulSoup (`html.parser`)**: parses `<noscript>` as a normal element, then `<style>` switches to raw-text mode. Everything from after `<style>` up to `</style>` is opaque text — including the `</noscript>`, `<SCRIPT_TAG>`, and `</SCRIPT_TAG>` you want to inject. The serializer then re-emits the raw text, so `soup('SCRIPT_TAG')` finds nothing and the script is dropped... wait, no: the serializer preserves the raw text inside `<style>`, but the script tag will appear *inside the style element's text content* in the output HTML. See "Output shape" below.
- **Browser (HTML5 parser, JS enabled)**: `<noscript>` opens raw-text mode. The first `</noscript>` closes it. Then `<SCRIPT_TAG>` is parsed as a real element and executes. The trailing `</style>` and `</noscript>` are stray close tags that the browser ignores or error-recovers through.

### Output shape
After BeautifulSoup round-trips the input, the emitted HTML contains a real `<script>` (or whichever target tag) tag because the bytes pass through as raw text inside `<style>`. The browser, when re-parsing the *output*, sees `<noscript>` → `</noscript>` → `<script>...</script>` and executes the script. The sanitizer saw a tree with no script tag; the browser sees one.

### Concretely, the winning payload
```html
<noscript><style></noscript><script>alert(1)</script></style></noscript>
```

## Steps to adapt this to a new sanitizer
1. **Identify the parser**: read the code. If it's BeautifulSoup with `html.parser` or `lxml`, the differential above usually works. If it's `html5lib`, the parser is browser-faithful and this specific trick fails — try another.
2. **Identify the deny-list**: which tags/attrs are stripped? Common targets: `script`, `iframe`, `object`, `embed`, event-handlers (`on*`), `javascript:` URLs.
3. **Pick a raw-text boundary**. Candidates per HTML5 spec: `<script>`, `<style>`, `<textarea>`, `<title>`, `<noscript>`, `<noframes>`, `<xmp>`, `<plaintext>`. Confirm the sanitizer treats them as raw text — if it parses `<script>` looking for nested tags, this trick won't help.
4. **Pick an outer "switch" element** whose closing tag the sanitizer will believe but the browser will respect. `<noscript>` is best because server-side sanitizers almost never emulate its scripting-aware behavior.
5. **Assemble**: `<SWITCH><RAW></SWITCH><TARGET_TAG>PAYLOAD</TARGET_TAG></RAW></SWITCH>`.
6. **Verify**: feed the payload in, capture the serializer output, confirm (a) the deny-listed tag appears in the output bytes and (b) re-parsing the output with `html.parser` still fails to extract the tag as an element. That second check is what proves the bypass survives a round trip.

## Why it works (mental model)
- Sanitizers operate on a tree produced by *one* parser. Browsers use *another*. Any construct where the two parsers disagree on where an element ends is a candidate bypass.
- The disagreement must be in a direction the sanitizer trusts the closing tag of an inner element *more* than the browser does. `<style>` swallows `</noscript>` for the sanitizer but not for the browser — exactly the right direction.
- The trick generalizes: substitute `<textarea>` or `<title>` for `<style>`, or `<noframes>` for `<noscript>`, and retest.

## Limitations / when this fails
- Sanitizers that use `html5lib` (browser-faithful parsing) close `</noscript>` correctly, so the differential collapses.
- Sanitizers that **string-match** `<script` and substring-strip it will catch the raw bytes even inside `<style>` text. Try alternate encodings, casing, or `<scr<script>ipt>` if needed.
- CSP (Content-Security-Policy) on the response can block inline script execution regardless of what HTML the sanitizer emits — that is a separate layer and out of scope here.
- Output sanitizers that re-parse with a browser-equivalent parser will catch the round-trip. Always run step 6's second parse on the *sanitized output*, not the input.

## Quick checklist
- [ ] Determined sanitizer's parser backend.
- [ ] Confirmed `<style>` (or chosen raw-text element) is raw-text to the sanitizer.
- [ ] Confirmed `</noscript>` (or chosen switch) is *not* honored as a switch by the sanitizer.
- [ ] Crafted payload with outer-switch → inner-raw-text → `</switch>` → blocked tag → blocked content → close tags.
- [ ] Verified blocked tag appears in serialized output.
- [ ] Re-parsed serialized output to confirm blocked tag still slips past a second `html.parser` pass.