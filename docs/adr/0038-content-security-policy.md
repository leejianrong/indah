# ADR-0038: Content-Security-Policy with per-response nonces

- Status: Accepted (IND-121)
- Date: 2026-10-22
- Deciders: Jian (owner)

## Context

ADR-0024 deferred a CSP until the shell's origins were audited. The shell is one HTML document
with inline `<script>` and `<style>` tags (the Svelte bundle and the Studio stylesheet), an
optional inline theme and chrome block that `_chrome_html` injects per app, a lazily imported
same-origin editor module (ADR-0032), and no third-party fetches except a `Map`'s tile images.
A policy that allows only that is achievable, and it is the main defence against an injected
script on a hosted dashboard, so it needs to be tested rather than hoped for.

## Decision

- **`create_app(csp=None | "strict" | "<policy>")`, off by default.** `"strict"` builds the
  policy per response; any other string is used as the policy with `{nonce}` replaced; `None`
  sends no policy. `launch()` never enables it: Colab and similar hosts frame the app and bring
  their own origins.
- **Nonce rewrite.** `_index` takes a fresh 128-bit nonce, adds `nonce="..."` to every
  `<script>` and `<style>` opening tag of the finished document (so the injected theme and chrome
  blocks are covered too), and sends the policy with `Cache-Control: no-store`: a cached page
  would reuse its nonce.
- **The strict policy:** `default-src 'none'; script-src 'nonce-N' 'self'; style-src 'nonce-N';
  style-src-attr 'unsafe-inline'; img-src 'self' data: blob: <tile hosts>; media-src 'self'
  data: blob:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'self';
  form-action 'self'; report-uri <relative>/api/csp-report`.
  - `script-src` has no `'unsafe-inline'` and no `'unsafe-eval'`; `'self'` is there for the
    lazily `import()`ed editor module.
  - `style-src-attr 'unsafe-inline'` is the one concession. Svelte writes `style="..."`
    attributes; an inline style attribute cannot run script.
  - CodeMirror creates `<style>` elements at run time, so the editor reads the page's nonce and
    passes it to `EditorView.cspNonce`.
- **Image hosts.** A `Map` registers its `tile_url` host in a process-wide registry at
  construction, the stock OpenStreetMap host included; with no `Map` the policy carries no third-party
  image host (IND-239). `create_app(csp_media_hosts=[...])` declares hosts up front. The registry
  has a limit worth knowing: the page's policy is fixed when it is served, so in a per-session app
  a `Map` first constructed *after* the first page load (its session opens after the page) is
  allowed from the next load, and indah logs a warning naming the host. Declare it with
  `csp_media_hosts` to avoid that. A host is only accepted if it is a plain `http(s)://host[:port]`,
  so a hostile `tile_url` cannot inject a directive.
- **Violations are reported and counted.** `POST api/csp-report` (mounted only for `"strict"`) is
  the `report-uri` target, resolved relative to the document so a deep link under a mount works.
  The body is untrusted: capped at 8 KB, parsed leniently, reduced to four fields, kept in a
  bounded `app.state.csp_violations` deque and logged. It always answers `204`.
- **Verified by the e2e suite.** `tests/e2e/conftest.py` runs every e2e test under `csp="strict"`
  and fails any test whose page fires a `securitypolicyviolation` event or whose app received a
  report. A shell or component change that needs inline code now fails CI.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Hash-based `script-src` | The inline content changes with the theme and chrome, so hashes would be computed per response anyway; a nonce is simpler and the standard. |
| `'strict-dynamic'` | Not needed: the only dynamic import is same-origin and covered by `'self'`. |
| Policy on by default | Breaks notebooks (framed by Colab) and any app showing remote images. Hosted apps opt in. |
| `report-to` / Reporting API | More moving parts for the same signal; `report-uri` is still supported by the browsers we test. |
| Per-session policy that tracks `Map` hosts | Impossible: the policy is sent before the session exists. |

## Consequences

- An app with remote images (an `Image` with an `https://` source) must list the host in
  `csp_media_hosts`, or use a custom policy.
- A custom policy string is the operator's responsibility; the nonce is filled in, nothing else is
  checked, and no report route is mounted.
- No wire change; `protocol_version` stays 1. Supersedes the "CSP deferred" part of ADR-0024.
