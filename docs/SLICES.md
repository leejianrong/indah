# indah: Slices

Vertical increments. Each ends in something demonstrable. Slice 1 confronts the
riskiest unknown — whether SSE state sync actually survives Colab's and RunPod's
proxies, which the whole architecture rests on (ADR-0002).

---

## V1: Live pixel through the proxy

**Delivers:** R0, R2 (the transport half), part of R4

**Build plan**

1. Single ASGI app (Starlette + Uvicorn): static route for a minimal shell,
   `GET /api/stream` (SSE), `POST /api/event` (ADR-0001, ADR-0002).
2. Minimal hand-written HTML/JS shell (not yet Svelte) that opens the SSE stream
   and renders one server-pushed value into one DOM node.
3. One hardcoded interaction: a button POSTs an event; the server increments a
   counter and pushes the new value over SSE; the shell updates the node.
4. `launch()` skeleton: bind a port, detect Colab (`google.colab`) / RunPod (env),
   print the proxy URL, render inline via iframe in a notebook.
5. Add an SSE heartbeat.

**Demo:** In a real Colab notebook and a real RunPod pod, run `launch()`, open the
printed proxy URL, click the button, and watch the number update live — with no
Node installed and no WebSocket.

**Rests on assumptions:** ADR-0002 (SSE passes Colab's proxy). If wrong, the
fallback is Cloudflared or long-polling, decided here before building further.

### Test plan

#### End-to-end
- On Colab, a click updates the displayed value within 1s over SSE, no Node
  present.
- On RunPod, the same flow works through `proxy.runpod.net`.

#### Integration
- `POST /api/event` triggers a patch on the SSE stream containing the new value.
- The SSE stream emits heartbeats and the client stays connected past 30s idle.

#### Unit
- The env detector returns the correct URL shape for Colab, RunPod, and local.

---

## V2: Reactive core with granular patches — DONE

**Delivers:** R1, R5 (starter inputs)

> **Resequenced:** the Svelte shell (originally step 5) moved to its own slice
> (V2.5). Building the shell against a still-moving protocol was the wrong order;
> V2 nails the reactive contract behind a generic **vanilla-JS** renderer, then
> V2.5 swaps in Svelte behind the same stable protocol boundary (ADR-0004 allows
> this). We also replaced the planned "tree diff engine" with **fine-grained
> reactivity**: effects tied to signals emit patches for exactly the dependent
> nodes, so no whole-tree diff is needed — a strictly better realisation of R1.

**Build plan (as built)**

1. `reactive.py`: signals, computeds, effects, batching, a FIFO scheduler
   (ADR-0003).
2. `components.py`: Text, Button, Slider, Column; each serialises to a JSON node
   with a stable id; the tree carries `protocol_version` (ADR-0005).
3. `session.py`: assigns ids, snapshots the tree for `init`, wires one effect per
   reactive prop so a signal change emits a minimal patch, dispatches events.
4. Generic vanilla-JS renderer in `static/index.html`: renders the JSON tree and
   applies patches by node id, with a protocol-version check.

**Demo:** A two-slider form where a computed label depends on both; dragging one
slider patches the label (and that slider's own value), never the other slider.

### Test plan (as built)

#### End-to-end
- Dragging slider A patches the dependent label with the right value and never
  touches the unrelated slider B (real server + real SSE).

#### Integration
- A signal change emits patches for exactly its dependent nodes; the unrelated
  slider is never patched; a no-op set emits nothing.
- The label (bound to a computed over two signals) updates when either changes.

#### Unit
- Signal write reruns only effects that read it; a computed notifies only when its
  result changes; batch coalesces; a signal→computed→effect chain sees fresh
  values.

---

## V2.5: Svelte shell (replaces the vanilla renderer) — DONE

**Delivers:** R4 (frontend build path), part of R5

**Build plan (as built)**

1. `frontend/`: a Svelte 5 + Vite project using `vite-plugin-singlefile`, so the
   whole shell (JS + CSS) inlines into one `index.html` — no external asset
   requests to break behind proxy base paths (ADR-0001, ADR-0004).
2. Reimplemented the generic renderer in Svelte against the existing JSON protocol
   (no protocol change): `App.svelte` manages the SSE connection and a flat
   id->props store; recursive `Node.svelte` renders by type and applies patches;
   a protocol-version mismatch shows a clear message.
3. `make frontend` builds and copies the bundle to `src/indah/static/index.html`
   (committed, so `pip install` needs no Node). CI rebuilds and fails on a stale
   bundle.
4. `python -m indah` / `make demo` runs the built-in demo on the first free port.

**Demo:** The two-slider app rendered by the Svelte shell; verified end to end
against a real launched server (init tree + minimal patches over SSE).

### Test plan (as built)

#### End-to-end
- The full app is driven against a real server: init tree, and a slider event
  patches the label (and that slider) but never the other slider.

#### Integration
- The served index is the Svelte shell (opens the SSE stream against the protocol
  endpoints); the built shell ships in the wheel; no Node at install or runtime.

---

## V3: Async work and LLM token streaming - DONE

**Delivers:** R3, R5 (StreamText)

> **As built.** The wire protocol went 0 -> 1 (ADR-0011): a patch `change` gained
> an `append` op alongside `props`, and an `error` message drives the toast. Async
> handlers are detected as coroutines and run as background tasks, so `POST
> /api/event` returns immediately and tokens flow over the existing SSE channel -
> the request is never held open for the generation. Resume rides SSE's native
> `Last-Event-Id`: the hub sequences state-bearing messages with an offset (the
> SSE `id:`), buffers recent ones, and replays what a reconnecting client missed,
> falling back to a full `init` on a buffer gap (always correct because a
> `StreamText` snapshot carries its full text). Added `TextInput` for the prompt
> box (part of R5's starter set, brought forward for the demo).

**Build plan (as built)**

1. Async event handlers: a `Button` `on_click` may be `async def`; it runs in the
   background so it never blocks the request, the event loop, or other sessions.
   The reactive core stays synchronous, so no locking is needed (ADR-0011).
2. `StreamText`: holds a plain accumulating string (so snapshots are complete);
   `feed(token)` emits an `append` patch carrying only the delta, `reset()` a
   replace. Fed by a plain async generator the caller wraps (ADR-0009).
3. Reconnect/resume over `Last-Event-Id`: hub offsets + bounded history +
   `replay_since`; a `skip_upto` threshold stops an append being double-applied
   across the reconnect seam (ADR-0011). The 15s heartbeat keeps the connection
   under RunPod's ~100s cut; if it does drop, resume recovers it.
4. Error path: a sync or async handler exception is logged with its traceback and
   pushed as a short `error` toast; the session keeps handling events (Q-fail).

**Demo (as built):** `make demo` opens a prompt box + Generate button that streams
a mock LLM response token-by-token into a `StreamText`, with a live slider+label
below to show the rest of the UI stays responsive during generation. The mock LLM
is a plain async generator (ADR-0009), swappable for a real model.

**Rests on assumptions:** RunPod heartbeat/reconnect is sufficient. If wrong, TCP
exposure or a WebSocket upgrade is the escalation. (The 100s survival is proven
locally by a disconnect + `Last-Event-Id` reconnect; the real-hardware RunPod
smoke check rides along with the R2 notebook check.)

### Test plan (as built)

#### End-to-end
- Clicking Generate renders tokens as many append frames (not one final dump), and
  a slider event mid-stream is accepted and patched - the UI stays live while
  streaming (tests/e2e/test_live_server.py, real launched server).

#### Integration
- An async handler emits append patches in order over the hub; the POST returns
  immediately while the work streams in the background.
- A raised handler exception (sync and async) produces an `error` toast and a
  logged traceback; the session stays alive and handles the next event.

#### Unit
- `replay_since` resumes from the last-seen offset without duplication, and reports
  a gap (-> resend init) when messages were evicted.
- `StreamText.feed` accumulates text and emits append deltas; a snapshot carries
  the full accumulated text for a resume.
- SSE framing: state-bearing frames carry an `id:`, init/ping do not, replay
  precedes live, and a frame at or below `skip_upto` is dropped.

---

## V4: Packaging and the component starter set

**Delivers:** R4 (fully), R5 (remaining), R6, R7

**Build plan**

1. CI builds the Svelte shell and bundles the assets into the wheel; a check fails
   the build if committed assets are stale (ADR-0004).
2. Complete the starter components: TextInput, Select, Image, Plot/DataFrame
   display.
3. Document the JSON protocol and ship `register_component()` with one worked
   custom component (ADR-0005).
4. `pip install indah` from a built wheel in a clean env; confirm no Node/npm is
   invoked at install or runtime.

**Demo:** From a fresh Colab runtime, `pip install indah`, write a ~20-line app
using the starter components plus one registered custom component, and it runs —
no Node anywhere in the process trace.

**Rests on assumptions:** protocol is stable enough to document (ADR-0005).

### Test plan

#### End-to-end
- A clean-env `pip install` + example app renders all starter components; a
  process trace shows zero Node/npm invocations.
- A registered custom component renders and responds to events.

#### Integration
- Each starter component round-trips its value (set from Python → shown; changed
  in UI → readable in Python).
- The stale-asset CI check fails when the shell source changes without a rebuild.

#### Unit
- `register_component()` rejects a type that violates the protocol schema.
