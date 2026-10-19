# ADR-0026: Server push: `Stream`, coalesced appends, and `Topic`

- Status: Accepted (`Stream` and coalescing built in IND-90; `Topic` in IND-89)
- Date: 2026-10-19
- Deciders: Jian (owner)

## Context

The semula dashboard (`docs/SEMULA-REQUESTS-PLAN.md`, E1/E2) needs a live request log: rows
arrive from a background task at tens per second and every open tab should show them
within a second. Three things were missing. A `Signal[list]` re-sends the whole list on
every change (O(n) per row). The browser had no way to stay bounded while a log grows.
And every `hub.publish` made its own SSE frame, so 40 rows a second meant 40 frames a
second, each padded up to the proxy's 8 KB window (ADR-0002).

## Decision

- **`indah.Stream`**: an append-only `Signal[list]` bounded by `limit`. `append` adds
  rows, `set`/`clear` replace. Anything can read it like a signal (a `computed` follows
  appends); a component that declares it in `stream_props()` (`List` now, `Table` next)
  is fed by **append patches** instead of whole-prop replaces.
- **`trim`**: an additive key on an `append` change, `{"trim": {"items": N}}`, so the
  browser keeps only the newest `N`. The server sets it to the stream's `limit`.
- **Coalescing lives in the `Hub`**, the single sequencer: `queue_append` holds rows per
  `(node, prop)` for 100 ms and publishes one patch; `publish` flushes held rows first,
  so order is preserved for every publisher; a new connection flushes before it takes
  its snapshot, so held rows are neither lost nor sent twice. Without a running event
  loop it publishes immediately. Token and chart streaming (`emit_append`) is unchanged
  and unbatched: it is latency-sensitive and already coalesced by `sse_events`.
- Inside a synchronous dispatch an append is folded into the response as a full replace
  (correct, and rare).
- **`indah.Topic`** (IND-89): an app-level channel. Any task publishes (`publish` on the
  event loop, `publish_threadsafe` from another thread, marshalled onto the loop the
  subscribers live on); a session follows it through `ctx.latest(topic)` (a signal of the
  newest item) or `ctx.tail(topic, limit)` (a `Stream` seeded from the topic's `replay`
  history). Each session subscribes for itself, so per-tab state stays per tab, and
  `ctx.on_close` releases the subscription on eviction. A raising subscriber is logged
  and does not stop the others. Cross-process fan-out is out of scope; `Topic` is the
  seam a Redis pub/sub backend would replace.
- **`create_app(proxy_flush=True)`**: the SSE padding stays on by default (Colab needs it)
  but a deployment with no window-buffering proxy can turn it off.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Coalesce in `Session.emit_append` | Other publishers (the POST handler's sync patch) bypass the session and would reorder around held rows; the hub sees every message |
| Coalesce all appends, tokens included | Adds up to 100 ms to token latency for no bandwidth gain worth it |
| Change the SSE padding instead | Frames 100 ms apart are not queued together, so queue-drain coalescing in `sse_events` cannot merge them |
| A bump to `protocol_version` | `trim` is ignorable by an older shell (it only keeps more rows); see ADR-0005 |

## Consequences

- 40 rows/s of about 350 B is about 14 KB/s of payload in at most 10 frames/s; with proxy
  padding the worst case is about 80 KB/s per tab, against roughly 330 KB/s without
  time coalescing. A row can wait up to 100 ms (`Hub(coalesce_seconds=...)`).
- The hub's replay history (512 messages) now covers about 50 s of resume at 10 frames/s.
- `Stream` listeners are released by `Session.close()`, so an evicted session leaves no
  subscription behind.
