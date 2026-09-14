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

## V2: Reactive core with granular patches

**Delivers:** R1, R5 (starter inputs)

**Build plan**

1. Implement signals + the dependency graph mapping signals → node IDs
   (ADR-0003).
2. Pydantic component models with stable server-assigned node IDs; serialize the
   tree to JSON carrying `protocol_version` (ADR-0005).
3. Diff engine: on signal mutation, compute the minimal patch set by node ID.
4. Wire three components — Text, Button, Slider — to signals via the V1 transport.
5. Replace the throwaway shell with the Svelte shell that renders the JSON tree
   and applies patches by node ID (ADR-0004).

**Demo:** A two-slider form where a computed label depends on both; dragging one
slider updates only the label node (verifiable in devtools: no other node
re-renders, no script rerun).

**Rests on assumptions:** ADR-0003 patch correctness. If the diff is wrong the UI
corrupts silently — hence the heavy unit + e2e coverage below.

### Test plan

#### End-to-end
- Dragging slider A updates the dependent label and nothing else in the DOM.
- A mismatched `protocol_version` makes the shell refuse to render and shows a
  clear message.

#### Integration
- Mutating a signal produces a patch set touching exactly the dependent node IDs.
- A component bound to two signals updates when either changes.

#### Unit
- Signal write → dependency graph yields the correct dependent set.
- Diff of two UI trees produces the minimal patch list (add/remove/update).

---

## V3: Async work and LLM token streaming

**Delivers:** R3, R5 (StreamText)

**Build plan**

1. Async event handlers: a handler may `await` long work without blocking the
   server or other sessions.
2. `StreamText` component fed by an async generator; tokens stream over the
   existing SSE channel as append patches.
3. Reconnect/resume logic so a stream survives RunPod's 100s proxy timeout
   (ADR-0002).
4. Error path: a handler exception yields a UI toast + a server-side traceback;
   the rest of the UI stays live.

**Demo:** A prompt box + "Generate" button streams a (mock or real) LLM response
token-by-token into the UI while the rest of the page stays responsive, and it
keeps streaming past the 100s mark on RunPod.

**Rests on assumptions:** RunPod heartbeat/reconnect is sufficient. If wrong, TCP
exposure or a WebSocket upgrade is the escalation.

### Test plan

#### End-to-end
- Clicking Generate renders tokens incrementally (not one final dump); the UI
  accepts other input meanwhile.
- A stream on RunPod survives beyond 100s via reconnect without visible breakage.

#### Integration
- An async generator handler emits append patches in order over SSE.
- A raised handler exception produces a toast patch and a logged traceback; the
  session stays alive.

#### Unit
- Reconnect logic resumes a stream from the last-acked offset without duplication.

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
