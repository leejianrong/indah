# ADR-0011: Streaming protocol - append op, SSE offset resume, async handlers

- Status: Accepted
- Date: 2026-09-14
- Deciders: Jian (owner)

## Context

R3 requires heavy or long-running work (an LLM generating tokens, a PyTorch
pipeline) to run async and stream into the UI without freezing it, and R5 asks
for a `StreamText` container fed by that stream. Slice 2 gave us a synchronous
reactive core over SSE + POST (ADR-0002, ADR-0003): a client event runs a handler
synchronously, the mutated signals produce one coalesced patch, and the patch is
broadcast. Three gaps stand between that and streaming:

1. A handler cannot `await`, so it cannot drive an async generator.
2. A patch only *replaces* a prop, so streaming N tokens would resend the whole
   growing string N times (O(n^2) on the wire).
3. RunPod's proxy cuts a connection at ~100s (ADR-0002); a long stream must
   survive a reconnect without losing or duplicating tokens.

## Decision

**Append patch op.** A patch `change` gains an alternative to `props`:
`{"target": "<id>", "append": {"text": "<delta>"}}` concatenates a delta onto a
prop rather than replacing it, so a token costs O(token) on the wire. The wire
protocol version bumps 0 -> 1; the shell ships with the backend and rejects a
mismatch (ADR-0005). A new `error` server->client message carries a short
handler-failure string for a UI toast.

**Async handlers as background tasks.** A component handler may return a
coroutine (a `Button` whose `on_click` is `async def`). The session detects it and
`POST /api/event` schedules it with `asyncio.create_task`, then returns
immediately; the work streams over the existing SSE channel. The POST is never
held open for the duration, so it cannot hit the proxy timeout, block the event
loop, or stall other sessions. The reactive scheduler stays synchronous and never
awaits mid-flush, so async handlers only mutate signals at quiescent points and
concurrent handlers need no locking. Signal mutations in an async handler, and
`StreamText.feed`, emit each change to clients immediately (the "live" emit mode)
rather than collecting into the sync-dispatch sink.

**SSE offset resume.** The hub sequences every state-bearing message (patch,
error) with a monotonically increasing offset, keeps a bounded history buffer, and
emits the offset as the SSE `id:` line. A browser `EventSource` resends
`Last-Event-Id` on reconnect natively, so the server replays the buffered messages
after that id with no client code. If the needed message has been evicted from the
buffer, the server falls back to a full `init` snapshot - always correct because a
`StreamText` snapshot carries its full accumulated text. A `skip_upto` threshold
(the offset the client is caught up to after init/replay) drops any live message
already covered, so an append is never double-applied across the reconnect seam.

**Error path.** A handler exception (sync or async) is caught, its traceback is
logged server-side, and a short `error` message is pushed as a toast; the session
stays alive and keeps handling events (Q-fail).

## Alternatives considered

| Option | Why not |
|--------|---------|
| Replace-only patches, resend the whole string per token | O(n^2) wire cost; the append op is the whole point of streaming over SSE |
| Hold the POST open and stream tokens in its response body | Hits RunPod's ~100s POST timeout and couples request lifetime to generation; SSE is the built-for-it channel (ADR-0002) |
| App-level reconnect protocol (custom resume handshake) | Reinvents SSE's native `Last-Event-Id`; more client code, more to get wrong |
| Make the reactive core async/thread-safe | Large, risky change to the novel core (ADR-0003) for no gain: single-threaded asyncio with synchronous flushes is already safe |
| Bump nothing (append/error are additive) | A shell that did not understand `append` would silently drop tokens; ADR-0005 wants a loud mismatch |

## Consequences

- Buys token streaming at O(token) wire cost, non-blocking async work (R3), and a
  stream that survives RunPod's timeout via native SSE resume (R5).
- Costs the hub a bounded per-stream history buffer and an offset counter, and the
  stream handler a small subscribe-then-snapshot ordering discipline (`skip_upto`)
  to avoid double-applying appends.
- The append op assumes the client applies deltas in order; SSE over one TCP
  connection preserves order, and synchronous publish keeps tokens ordered even
  when emitted from between an async handler's awaits.
- Keeps domain logic portable: the streamed work is a plain async generator indah
  wraps, with no indah imports, so it lifts out unchanged on graduation (ADR-0009).
- Still one shared session/hub per app in v0; the offset/buffer/resume machinery
  lives in the hub and moves cleanly to a per-session hub when the state seam
  lands (ADR-0010).

## Update: streaming wire optimisation (KAN-1395, 2026-09-16)

The append op keeps a token O(token) on the wire, but each frame also carried the
Colab proxy-flush pad (ADR-0002), so streaming paid ~8 KB per token. `sse_events`
now coalesces a queued burst into one flush and pads only up to the next window
boundary, so the pad no longer scales with the token (or chart-point) rate. This is
transport-only: the protocol, the append op, and resume are unchanged. See ADR-0002's
"Streaming wire optimisation" note for the mechanics.
