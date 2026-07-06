---
name: xss-filter-evasion
description: When bypassing an HTML sanitizer that strips <script>, event-handler attributes, and frame/embed elements, validate the chosen bypass actually executes JavaScript in the target browser before claiming success. Covers meta refresh with data URL, SVG onload, <link rel=stylesheet> with javascript: URL, <object> with data URL, and CSS expression variants — plus a headless-browser verification checklist.
---

# XSS Filter Evasion — Verifiable Bypass

## The recurring mistake

Picking a sanitiser-bypass technique from a cheat sheet, generating it,
and submitting it as the solution **without confirming that the exploit
actually fires in the target browser**. Many textbook tricks are silently
neutralised by modern browsers (e.g. `meta http-equiv=refresh` → `data:`
URL is blocked in current Chromium/Firefox because of the navigation-to-data
restriction). Generating the payload is not the same as delivering a
working XSS.

## Procedure

1. **Enumerate what the filter removes.** Inspect the sanitiser's source
   or seed it with probes to learn the exact deny-list:
   - `<script>` blocks/inline?
   - event handler attributes (`on*`, e.g. `onload`, `onerror`,
     `onmouseover`)?
   - `<iframe>`, `<frame>`, `<embed>`, `<object>`, `<applet>`?
   - `javascript:` / `data:` URL schemes in `href`, `src`, `action`?
   - `<style>` and `<link>` elements?
2. **Pick bypass categories that survive the deny-list AND the target
   browser's modern defences.** Below is the catalog ordered by survival
   likelihood in a 2026-era browser:
   - **Tag-in-attribute / mutation-XSS**: inject markup via a sink that
     is parsed twice (template engines, innerHTML of inserted nodes,
     DOMParser). Categories like `ng-app`, `srcdoc` in iframes that
     survive stripping, and `<noscript>`-toggle attacks.
   - **SVG / MathML vectors**: `<svg/onload=...>`,
     `<svg><script>...</script></svg>`,
     `<math><mtext><table><mglyph><style>` chains, `<svg><set>`,
     `<svg><animate>` with `onbegin`.
   - **`<link>` / `<style>` smuggling**: `<link rel=stylesheet
     href="javascript:alert(1)">` (preloader does not fetch, parser
     does), `<style>@import 'javascript:...';` (mostly historical),
     CSS `expression()` (IE-only, accept as a fallback).
   - **`<meta http-equiv=refresh content="0;url=data:text/html,...">`**
     — note: blocked by Chromium since 2018 and Firefox since 2019 for
     top-frame navigation; only viable inside `<iframe srcdoc>` or
     older engines.
   - **`<object>` / `<embed>`**: `<object data="data:text/html,...">`
     where allowed — `<object>`-loaded HTML executes scripts in many
     contexts, and DOM access into the embedded document is permitted.
   - **Protocol tricks in `href`**: `javascript:` with whitespace
     (`java\tscript:`), case mixes, HTML-entity escapes inside the
     scheme, leading control chars (`\x01javascript:`), and
     `data:text/html;base64,...` in `iframe` `src` when the scheme is
     allowed.
   - **Encoding mismatches**: UTF-7, over-long UTF-8, percent-encoded
     brackets `[%22]`, NULs, surrogate pairs, backtick-wrapped schemes
     in legacy parsers.
3. **Round-trip the payload through the sanitiser**, not just through
   the agent's text generator. The string you produce must equal the
   string the sanitiser emits *for the same input* — reparse it
   yourself to make sure no double-decode or entity collapse reinstates
   something the filter is meant to remove.
4. **Verify the bypass fires in the real browser.** This is the
   non-negotiable step. See diagnostic checklist below.

## Diagnostic checklist (MUST run before declaring victory)

Run all of the following against the *rendered* DOM of the bypass
payload as it actually appears after sanitisation:

1. **Headless browser load.** Open a page containing the sanitised
   output in headless Chromium (puppeteer/playwright/selenium) and
   confirm the XSS sink actually fires (`alert`, console log, or
   `navigator.userAgent`-style callback). If you cannot run a browser,
   fall back to a DOM/parse-only check (jsdom + dispatch the
   `load`/`error` events) and clearly mark the result as "parse-only,
   not browser-verified".
2. **Mutation-XSS probe.** If the sanitiser sanitises HTML *and then*
   inserts it via `innerHTML` / `jQuery.html` / a template, repeat the
   check on the post-insertion DOM — bypassing the static filter is
   useless if the insertion path rebuilds the dangerous parse.
3. **CSP / sandbox check.** If the page has a Content Security Policy
   (`script-src 'self'`, `script-src nonce-...`, no `unsafe-inline`),
   your bypass may technically parse but never execute. Inspect
   response headers; if CSP blocks the vector, the bypass is a
   false-positive success and the task is unsolved.
4. **Encoding sink check.** Confirm the payload is what the browser
   sees, not what your string literal looks like — open the rendered
   HTML in DevTools, copy the element's `outerHTML`, and re-run the
   headless test on *that* string.

## Stop signal

If you have built **3 candidate payloads across at least 2 distinct
bypass categories** (e.g. SVG + `<meta refresh>`, or `<link>` +
`<object>`), and *all* of them either (a) are stripped by the
sanitiser, or (b) parse but do not execute in a headless Chromium
2024+ browser, **stop iterating on this filter and this category**
and switch tactics:

- re-read the sanitiser to find a different sink the deny-list does not
  cover (e.g. a sink that builds DOM nodes from data attributes, or
  accepts URLs in a different attribute);
- if the page has a strict CSP, accept that reflected XSS is not
  possible on this target and report the constraint instead of
  looping forever on bypass techniques that CSP will always block;
- move to stored XSS, prototype pollution, or a different vuln class
  if the HTML injection sink is genuinely hardened.

Continuing past the threshold on the same architecture is the
"7 versions of the generator" debug spiral — the architecture is wrong,
not the next attempt.

## Common pitfalls

- Trusting a payload because it parses without errors (parsing ≠
  execution under modern browser defences).
- Forgetting that `data:` URL navigation from `<meta refresh>` is
  blocked in current browsers — use it only as a fallback inside
  `<iframe srcdoc>`.
- Forgetting CSP: a perfect bypass that violates `script-src` is not a
  bypass.
- Forgetting mutation-XSS: the agent's payload may be clean while the
  recipient template mutates it into a dangerous form (`{{x}}`
  substitution into `href`, `srcdoc`, etc.).
- Counting "the string contains `<script>`" as evidence of execution —
  only a fired callback (alert / console / network beacon) counts.