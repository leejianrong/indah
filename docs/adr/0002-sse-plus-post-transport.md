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

Fix: emit a block of ignored SSE comment padding (`_SSE_FLUSH_PAD`, ~8 KB, one
window) **on connect and again after every frame**, so each frame fills a window
and is flushed immediately. This keeps SSE as the transport - the WebSocket-upgrade
escalation was not needed. It is reproduced and guarded locally by a
window-buffering TCP proxy in `tests/e2e/test_proxy_buffering.py`. Cost: ~8 KB per
frame; fine for init and interactive input, and a later token-coalescing pass can
trim it for high-rate streaming if needed.
