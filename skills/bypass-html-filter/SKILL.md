---
name: bypass-html-filter
description: Bypass HTML sanitization filters that strip <script> tags and event handlers by injecting a <meta http-equiv="refresh"> tag pointing at the original file via file:// URL. Use when a filter rewrites or strips dangerous HTML in a copy but leaves the original on disk unmodified.
---

# Bypass HTML sanitization via meta-refresh to original file

## When this applies

- An HTML filter/sanitizer strips `<script>` tags, inline event handlers (`onload=`, `onerror=`, etc.), or `javascript:` URLs from input.
- The filter operates on a **temporary copy** of the file rather than mutating the original on disk.
- A browser (or renderer) will display the filtered copy's output.
- You can write content that survives the filter and reaches the browser.

## Procedure

1. **Confirm the copy-vs-original assumption.** Verify that the filter produces a separate output file (e.g., a served copy, a temp render target, a saved-into-different-path artifact) while leaving the source file you wrote untouched. If the filter rewrites the original in place, this bypass does not work.

2. **Craft the payload HTML.** The payload must:
   - Pass through the filter without being stripped (no `<script>`, no event handlers, no `javascript:` URLs — these are the very things the filter blocks).
   - Cause the browser to load the **original, unfiltered file** as soon as it finishes parsing the filtered copy.

3. **Inject a `<meta http-equiv="refresh">` tag** of the form:

   ```html
   <meta http-equiv="refresh" content="0;url=file:///absolute/path/to/original/file.html">
   ```

   Key details:
   - `content="0;url=..."` — the `0` (zero-second delay) makes the redirect effectively immediate.
   - `url=file:///...` — use the `file://` scheme with the absolute path of the **original** file. The browser follows the redirect, loads the original, and any `<script>` / handlers still present in the original execute.

4. **Wrap or embed as needed.** Place the meta tag anywhere valid in the `<head>` (or body, depending on the filter's tolerance). The filter sees only the meta tag and benign HTML; it does not see the script that will run because the script lives in the redirected-to file, not in the filtered copy.

5. **Trigger the flow.** Have the target render the filtered copy (the pipeline that runs the filter and then displays the result). The browser parses the filtered copy, hits the meta refresh, navigates to the original, and executes its script.

## Why it works

Sanitizers typically transform input by stripping forbidden constructs and writing the result to a new location (or returning it in-memory). The original file on disk is rarely touched, because overwriting the source would be destructive and surprising. By redirecting the browser from the sanitized copy to the original, the attacker gets the unsanitized version rendered in the same browser context, with full script execution.

## Variations

- **`http-equiv="Location"` + `content="file:///..."`** — older equivalent syntax; some filters strip `refresh` but not `Location`.
- **`<meta http-equiv="refresh" content="0;url=ORIGINAL">`** combined with an iframe/data-URL chain if direct file:// redirects are blocked.
- **Base tag redirection** — `<base href="file:///path/to/original/">` followed by a relative URL in a link/img, if meta refresh is stripped.
- **Multiple nested meta tags** — when the filter strips only the first meta, chain several identical ones.

## Detection checklist (for defenders)

- Filter that only sanitizes a copy but serves the original on follow-up requests.
- Any flow where user-supplied HTML is rendered after a copy-and-strip step without also scrubbing the original location.
- Browser navigation events from a meta refresh to a `file://` target.

## Pre-flight checks before relying on this

- The filter must not strip `<meta http-equiv="refresh">` tags (most don't — meta refresh is benign for legitimate use).
- The browser context must allow `file://` navigation (most desktop browsers do by default for locally-loaded files).
- The absolute path of the original file must be known or guessable; leak it via directory listings, error messages, or predictable naming.