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

The first Colab run on `0.1.0rc1` surfaced the R2 risk in a concrete form: the
shell loaded but sat on "connecting...", because Colab's front-end proxy buffered
the SSE response and held the small first `init` frame below its flush threshold -
so `EventSource` never saw a byte and stayed in `CONNECTING`. `X-Accel-Buffering:
no` alone did not prevent it. Fix: every stream now opens with an ~8 KB SSE comment
preamble (`_SSE_PREAMBLE`), which is ignored by the client but pushes the proxy
past its buffer so it flushes immediately. This keeps SSE as the transport; the
WebSocket-upgrade escalation was not needed.
