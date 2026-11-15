# ADR-0051: DirectUpload, a file sent from the browser to a URL the app chooses

- Status: **Accepted** 2026-11-15
- Date: 2026-11-15
- Deciders: Jian (owner)
- Builds on: ADR-0012 (custom components are declarative, no code), ADR-0017 (`Upload`), ADR-0038 (CSP)
- Driven by: geo-pipeline, which must take dataset zips of several GB. `Upload` buffers the file in
  the indah server and is capped (default 25 MB); a custom component cannot help, because a render
  spec runs no code.

## Decision

Additive, no `protocol_version` bump (ADR-0005).

1. **New node type `directupload`** with static props `label`, `accept` and a reactive prop
   `target`. Python: `DirectUpload(get_target, on_done=None, label="", accept="")`.
2. **Exchange.** The shell sends `pick {filename, size, content_type}` when a file is chosen.
   `get_target(info)` (sync or async) returns `{"url", "headers"?}`; the component publishes it as
   `target {id, url, headers}`. The shell PUTs the file with `XMLHttpRequest` (for upload progress)
   and sends `done {filename, size, ok, status, error}` to `on_done`. `id` increases on every pick, so
   choosing the same file again uploads again.
3. **The server never sees the bytes**, so there is no size cap in indah; the store sets it. The URL
   must be `http(s)` (checked in Python) and reachable from the browser.
4. **CSP.** `connect-src` allows only the page's own origin, so `create_app(csp_connect_hosts=[...])`
   lists the store origins. The store also needs a CORS rule for the page's origin (a non-simple PUT
   sends a preflight).

## Alternatives considered

| Option | Why not |
|---|---|
| Stream the body through the indah server | Spends the server's bandwidth and memory and keeps a hop between the browser and the store. |
| Allow code in render specs | Breaks the data-only guarantee of ADR-0012. |
| `fetch` instead of XHR | `fetch` has no upload progress event. |

## Consequences

- One more node type and one more `create_app` option, both off by default.
- An app that uses it under `csp="strict"` must name the store origin, or the browser blocks the PUT.
