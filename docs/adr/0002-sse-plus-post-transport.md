# ADR-0002: Use SSE + HTTP POST as the transport, not WebSockets

- Status: Accepted
- Date: 2026-09-14
- Deciders: Jian (owner)

## Context

The original plan assumed a single WebSocket for real-time state sync. A checkable
fact overrides it: **Google Colab's `proxyPort` does not support WebSockets** (and
blocks large transfers). RunPod's proxy does support WebSockets, but enforces a
100s Cloudflare timeout and force-disconnects on long transfers. Since Colab is a
first-class target (R2), a WebSocket-primary design fails on the flagship
environment unless every user installs a Cloudflared tunnel.

## Decision

The transport is Server-Sent Events for server→client updates (one long-lived
`GET /api/stream`) plus HTTP POST for client→server events (`POST /api/event`).
Both are plain HTTP and pass Colab's and RunPod's proxies with no extra
dependency. A WebSocket upgrade is *probed* at connect time and used only where
the environment supports it. The reactive core (ADR-0003) is transport-agnostic,
so the transport sits behind one interface.

## Alternatives considered

| Option | Why not |
|--------|---------|
| WebSocket primary + Cloudflared fallback on Colab | Adds a binary dependency and startup delay on the flagship target |
| WebSocket only, drop Colab | Abandons a stated headline use case |
| HTTP long-polling | Works but is chattier and worse for token streaming than SSE |

## Consequences

- Buys Colab compatibility with zero extra dependencies and native LLM-token
  streaming (SSE is built for it).
- Costs a clean bidirectional channel: client→server goes over separate POSTs,
  and high-frequency client input (e.g. a dragged slider) needs debouncing.
- Requires an SSE heartbeat + auto-reconnect to survive RunPod's 100s timeout
  (proven in Slice 3).
- Forecloses nothing: the WebSocket upgrade path remains available behind the same
  interface.

## Real-hardware note: Colab proxy buffering (2026-09)

The first Colab runs on `0.1.0rc1` surfaced the R2 risk concretely. Colab's
front-end proxy forwards the upstream response in fixed-size **windows**, releasing
a window to the browser only once it fills - it does not honour `X-Accel-Buffering:
no`. A small SSE frame lands in a window that never fills on its own, so it is held:

- **Symptom 1** - the shell sat on "connecting...": even the response and first
  `init` frame were held, so `EventSource` never opened.
- **Symptom 2** - after a lead-in flush was added, the status went "live" but the
  page stayed empty: the lead-in filled one window (so headers flushed and
  `onopen` fired), but the `init` frame after it sat in a fresh unfilled window.

Fix: emit ignored SSE comment padding (an `_SSE_FLUSH_PAD` lead-in of one window on
connect, then a pad after each frame) so each frame fills a window and is flushed
immediately. This keeps SSE as the transport - the WebSocket-upgrade escalation was
not needed. It is reproduced and guarded locally by a window-buffering TCP proxy in
`tests/e2e/test_proxy_buffering.py`.

### Streaming wire optimisation (KAN-1395, 2026-09-16)

The first cut padded a full ~8 KB window after *every* frame. Under token or
chart-point streaming that is ~8 KB per token, amplifying bandwidth on the exact
platform (Colab) the pad exists for. Two changes in `sse_events` cut it without
weakening the guarantee (the proxy still releases every frame):

- **Coalesce a burst.** After a blocking read, drain everything already on the
  queue (`get_nowait`) and emit it back to back, then flush *once*. A run of rapid
  appends - streamed tokens emitted between an async handler's awaits, or chart
  points pushed in a loop - now shares one pad instead of paying a window each.
- **Pad only to the next window boundary.** Track bytes emitted since the last
  flush and pad out just the tail (`_boundary_pad`), so a large frame or a coalesced
  burst that already crossed a boundary pays little or nothing, not a whole fresh
  window.

A lone small frame (a single slider patch, a slowly-arriving token) still costs
~one window - that is irreducible for a window-buffering proxy - but the per-token
amplification is gone. `_SSE_FLUSH_PAD` doubles as the on/off knob (setting it to
`""` disables padding, which the negative proxy-buffering e2e relies on). Guarded by
the coalesce/boundary unit tests in `tests/unit/test_sse_events.py` and the
unchanged proxy-buffering e2e.

## Amendment: the stream's session id travels in a cookie (IND-238)

`?sid=<signed session id>` put the id in every access log, proxy log and browser history, so every
app on indah had to know to scrub it. The shell now sets a cookie `indah_sid_<key>` (one per tab:
the key is random and kept in `sessionStorage` next to the id; `Path` is the stream route,
`SameSite=Strict`, `Secure` on https, 30 minutes, refreshed every minute while the page is open)
and opens `api/stream?k=<key>`. `EventSource` cannot set a header but the browser sends cookies on
it, and resends them on its own reconnects, which is why this beats a single-use stream ticket:
a ticket would not survive an automatic reconnect, and a signed reusable one needs a secret that
every replica shares (a plain app has none). The cookie is stateless, so ADR-0043 is unaffected
(any replica reads it; routing still uses the hint on events). In a secure app it holds the same
signed token ADR-0033 already verifies against the current principal, so another person's cookie is
`403` and creates nothing.

- A tab that names a cookie it does not have (it lapsed) is refused with `400`, never attached
  to the shared `default` session.
- `?sid=` still works for one release. `create_app(allow_sid_in_url=)` controls it: on by default,
  off for an app that sets `limits` or `security_headers`.
- A page framed by another site (a Colab or Jupyter output) cannot rely on a `Strict` cookie, so the
  shell sets `SameSite=None; Secure` there. Where the browser still does not send it, the stream is
  refused before it ever opened and the shell falls back to `?sid=` for that load.
- Not covered: `api/file/<sid>/<token>` download URLs still carry the id in their path.
