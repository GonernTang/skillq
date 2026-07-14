---
name: meta-refresh-bypass
description: Bypass an HTML sanitizer that strips <script> tags and inline event handlers but allows <meta http-equiv="refresh">. Use a two-file pattern where a clean host file redirects via meta refresh to a payload file containing the unsanitized JavaScript.
---

# Meta-Refresh Sanitizer Bypass

## When to use

Apply this technique when an HTML filter:

- Removes `<script>` tags
- Strips inline event handler attributes (e.g. `onload`, `onerror`, `onclick`)
- **Does not** strip `<meta http-equiv="refresh" content="...">` tags
- Processes content from a known source (e.g. user input, an upload) before storage or rendering

The filter's missing coverage of `<meta http-equiv="refresh">` is the vulnerability: the browser follows the meta-refresh redirect and loads the target document with full JavaScript execution enabled, including any tags the filter would otherwise remove.

## Procedure

### 1. Create the payload file

Write a separate HTML file that contains the malicious JavaScript directly. Place this file in a location the filter does not process — typically outside the upload/filter directory, or write it after the filtering step completes.

```html
<!DOCTYPE html>
<html>
<body>
<script>alert('XSS');</script>
</body>
</html>
```

### 2. Create the host file

Write the HTML that is submitted to the filter. Use `<meta http-equiv="refresh">` to redirect to the payload file. The filter will see no `<script>` and no event handlers and pass it through.

```html
<!DOCTYPE html>
<html>
<head>
  <meta http-equiv="refresh" content="0; url=file:///absolute/path/to/payload.html">
</head>
<body>
</body>
</html>
```

### 3. Use absolute URLs

Use an absolute `file://` URL in the `url=` attribute. Relative paths break because sanitizers and test harnesses often run from ephemeral or temporary working directories. An absolute path removes any ambiguity about the payload's location.

```
file:///home/user/payloads/payload.html
```

### 4. Submit the host file

Submit the host file to the filter. Verify (e.g. by reading the filter's output or by opening the result in a browser) that:

- The `<meta>` tag survived filtering
- The `url` attribute points at the payload file
- No `<script>` or event handler was reintroduced

### 5. Trigger execution

When a browser loads the filtered host file, the meta refresh fires, the browser navigates to the payload file, and the JavaScript in the payload file executes outside the filter's scope.

## Why it works

The filter only sees the host file. It cannot inspect what the meta refresh will load, because that resource is fetched only at render time in the browser. By splitting malicious content across two files and using a redirect primitive the filter allows, the sanitization boundary is bypassed while the browser still executes the payload in the same origin.

## Defensive notes

Filters should also strip or neutralize `<meta http-equiv="refresh">`, `<meta http-equiv="set-cookie">`, `<base href>`, `<link>`, and `<iframe src>` — any of these can shift the rendering context to attacker-controlled content. Whitelist-based sanitizers (e.g. DOMPurify with strict config) catch these by default; regex-based sanitizers often miss them.