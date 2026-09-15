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

### R2 smoke test on real hardware - PASSED (0.1.0, 2026-09-15)

The proxy behaviour (R2) cannot be reproduced by a local test - it needs a run on
the actual Colab and RunPod runtimes. `examples/smoke_test_rc.ipynb` is the
ready-to-run check: it `pip install indah==0.1.0`, confirms no Node is needed,
launches one app that exercises every proxy-sensitive path (SSE streaming, live
slider/select patches, a custom-component round-trip), and carries a checklist to
tick.

Results (indah 0.1.0):

| Check | Colab | RunPod |
|-------|-------|--------|
| Inline iframe renders | ✓ | n/a¹ |
| Slider patches live | ✓ | ✓ |
| Select patches live | ✓ | ✓² |
| Streaming arrives incrementally | ✓ | ✓² |
| Custom component round-trips | ✓ | ✓² |
| Survives a ~2 min idle gap | ✓ | ✓ |
| No Node in the runtime | ✓ | ✓ |

**Colab** - full browser run of the checklist by the owner (all boxes).
**RunPod** - an automated curl smoke against the pod's `proxy.runpod.net` URL: the
SSE stream served the `init` tree, delivered 8 heartbeats over a 130s stream (so it
survived past the ~100s Cloudflare cap), and round-tripped a slider event to a live
`patch`; the pod ran `python:3.12-slim` with no Node. The recipe is in the
`runpod-jobs` skill (`references/http-service-pods.md`).

¹ No browser in the RunPod curl smoke, so the inline-iframe render is a Colab-only
check. ² These per-widget rows were not separately driven on RunPod; they ride the
same SSE/patch path already proven through the proxy (init + heartbeat + patch).

**Colab runs on 0.1.0rc1:** install/import fine, but the shell would not render -
Colab's proxy forwards the SSE response in fixed-size windows and holds any frame
that does not fill one. First symptom: stuck on "connecting..." (even the `init`
was held); with a lead-in flush added, second symptom: "live" but empty (the lead
flushed, but the `init` after it sat in a fresh window). Fixed by emitting ~8 KB of
ignored SSE comment padding on connect and after every frame, so each frame fills a
window and flushes (ADR-0002 real-hardware note). Reproduced and guarded locally by
a window-buffering TCP proxy in `tests/e2e/test_proxy_buffering.py` (no Colab
needed). Re-confirmed on real Colab on `0.1.0` - the shell renders and every
checklist row passes (results table above).

Any proxy fixes discovered here update ADR-0002/0011 and the R2 note in
`docs/PLAN.md`.

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

## V4: Packaging and the component starter set — DONE

**Delivers:** R4 (fully), R5 (remaining), R6, R7

> **As built.** The starter set is complete: `Select` (a `<select>` two-way bound
> to a `Signal[str]`), `Image` (a URL / `data:` URI / raw PNG bytes), `Plot` (a
> Matplotlib `Figure`, duck-typed on `savefig` and rasterised to a PNG `data:` URI,
> so it reuses the `image` renderer with no browser-side plotting), and `DataFrame`
> (a pandas frame duck-typed via `to_dict(orient="split")`, a `{columns,rows}`
> dict, or a list of record dicts). Neither pandas nor matplotlib is a hard
> dependency — each is duck-typed only if you pass it, keeping R4's dependency
> story clean. `TextInput` shipped in V3 and was left as-is.
>
> `register_component()` (ADR-0012) is the R7 seam. Because the shell ships
> pre-built (ADR-0004) and R4 forbids runtime Node, a custom type cannot ship new
> Svelte code; instead it ships a validated, declarative **render spec** the
> shell's generic renderer interprets at runtime. The spec travels on the wire as
> the reserved `_spec` prop (so it is part of the public protocol), and
> `custom(type, **props)` builds value-bearing instances that round-trip like a
> built-in. The worked example is a `colorpicker`. The protocol is documented as a
> public contract in `docs/protocol.md` (R6).

**Build plan (as built)**

1. CI builds the Svelte shell and bundles the assets into the wheel; a check fails
   the build if committed assets are stale (ADR-0004). (In place since V2.5.)
2. Completed the starter components: Select, Image, Plot, DataFrame (TextInput
   shipped in V3). Each is added to `components.py` and `frontend/src/Node.svelte`,
   with the shell rebuilt via `make frontend`.
3. Documented the JSON protocol (`docs/protocol.md`) and shipped
   `register_component()` + `custom()` with a worked custom component and a generic
   `Custom.svelte` renderer (ADR-0005, ADR-0012).
4. Built the wheel and `pip install`ed it into a fresh venv with `node`/`npm`/
   `npx`/`bun`/`yarn`/`pnpm` tripwires first on `PATH`; confirmed zero invocations
   at install and at runtime, and that the app served the pre-built shell.

**Demo (as built):** `make demo` now shows, below the streaming box, a `Select` that
switches a reactive `DataFrame` and a registered colour picker (a custom component)
two-way bound to a signal. `examples/starter_components.py` is the ~20-line app used
for the clean-env check.

**Rests on assumptions:** protocol is stable enough to document (ADR-0005).

### Test plan (as built)

#### End-to-end
- The registered custom component (the demo's colour picker) ships its render spec
  in the init tree and round-trips an input event over a real launched server. The
  full clean-env `pip install` proof is reproducible as `make cleanroom`
  (`scripts/cleanroom.sh`: install the wheel in a throwaway venv with node/npm/npx/
  bun/yarn/pnpm/vite/svelte/esbuild tripwires first on `PATH`, assert zero
  invocations at install and runtime); its invariants are pinned by the packaging
  unit test.
- **(post-MVP hardening)** `tests/e2e/test_browser.py` renders the shell in a real
  headless Chromium (Playwright) and asserts the DOM patches through the SSE
  round-trip: the init tree renders, a slider and a select patch the live DOM, and
  the registered colorpicker round-trips a value. This is the only layer that
  exercises the V4 shell additions (the generic `Custom.svelte` renderer, Select,
  DataFrame) in a real DOM; it runs in a dedicated `browser-e2e` CI job.

#### Integration
- Each value-bearing component round-trips (set from Python → snapshot/patch;
  changed in UI → readable in Python): Select and the custom colorpicker both ways,
  Image and DataFrame in the display direction. The stale-asset check runs in CI.

#### Unit
- `register_component()` rejects a disallowed tag, a built-in type collision, an
  empty type, and a malformed spec. The pre-built shell ships in the package and
  runtime deps stay Python-only. Select/Image/Plot/DataFrame serialise and
  round-trip their values.

---

# Post-MVP slices (Milestone 1)

Planned increments from the 2026-09-15 planning round (see `docs/PLAN.md` §Post-MVP
roadmap). Each still ends in something demonstrable. Foundation first (Slice 0, A,
B, C), then the two specialisations (D, E). None bumps `protocol_version` except
where noted.

## Slice 0: Design system & identity

**Delivers:** the token substrate every later component is drawn to; indah's visual
identity (ADR-0014).

**Build plan**

1. A design-token layer in the shell (CSS custom properties): colour roles, type
   scale, shape, elevation, state layers — Material 3's role architecture, seeded to
   the "Studio" identity, wired so a theme is a token-set swap (no rebuild).
2. Restyle the existing components (`frontend/`) to the tokens; drop the indigo look.
3. Add the "Bunga" mark + "indah" wordmark to the shell header; wire the favicon.
   Assets from `assets/brand/`.
4. Point the Zensical docs site (`website/`) at the Studio palette and the
   Bunga logo/favicon, replacing the indigo defaults (ADR-0007).
5. Rebuild the shell (`make frontend`), commit the regenerated
   `src/indah/static/index.html`.

**Demo:** `make demo` renders the existing app in the Studio theme with the Bunga
mark in the header; the docs site (`make docs-serve`) shares the identity.

**Test sketch:** the built shell still ships in the wheel and passes the stale-asset
check; the browser e2e still renders and patches (styling change, no behaviour
change); no Node at install/runtime.

## Slice A: Layout & the input set

**Delivers:** arrangement for both halves; the rest of the common inputs (ADR-0015).

**Build plan**

1. Container components: `Row`, `Grid`, `Tabs`, `Sidebar`, `Expander` — arrange
   existing children; active/expanded state rides reactive props (no protocol
   change).
2. Complete the basic inputs: `Checkbox`, `Number`, `Radio`, `MultiSelect`, `Date`
   (each mirrors `Select`'s two-way pattern).
3. Markdown/code rendering in `Text` (sanitised); progress/spinner; Enter-to-submit
   on `TextInput` (KAN-1399).

**Demo:** a multi-panel form/dashboard — tabs + sidebar, inputs left, output right —
in one app.

**Test sketch:** each container renders/nests and collapses responsively; each new
input round-trips its value; Tabs shows only the active child; markdown renders and
cannot inject script.

## Slice B: Data-driven list

**Delivers:** chat, galleries, logs (ADR-0016).

**Build plan**

1. `List`/`Repeat` driven by a `Signal[list]`, rendered via an item template; add/
   remove/reorder is a prop change over the existing `patch` op (no protocol bump).
2. Specialisations `Chat` (role bubbles, auto-scroll) and `Gallery` (image grid).
3. Rebuild the chatbot example on `Chat` (KAN-1398), replacing the single-StreamText
   transcript.

**Demo:** the chatbot with real message bubbles; a gallery of generated images.

**Test sketch:** appending/removing/reordering items patches exactly the list;
snapshot on resume carries the full list; Chat bubbles render per role.

## Slice C: Per-session state

**Delivers:** honest multi-user; the prerequisite for per-user uploads (ADR-0010,
EPIC-205).

**Build plan**

1. Implement the ADR-0010 session-store seam so each viewer gets isolated
   signals/session instead of the single shared session (session.py note).
2. Keep the in-memory backend; the seam stays open for an external store later.

**Demo:** two browser tabs drive independent state on the same app.

**Test sketch:** two sessions do not see each other's signal writes; a handler in one
session emits patches only to that session's stream.

## Slice D: File/media upload

**Delivers:** the classic upload → run → show demo (ADR-0017). Depends on Slice C.

**Build plan**

1. A multipart upload endpoint separate from `POST /api/event`; an `Upload`
   component (image/audio/file). Bytes go to a plain handler (ADR-0009); results
   return over SSE.
2. Download / file-out (a served blob URL).
3. Document the endpoint in `docs/protocol.md` (additive; confirm whether
   `protocol_version` moves — expected not, it is a new route not an SSE change).

**Demo:** upload an image → run a classifier (mock or real) → show the result.

**Test sketch:** an upload reaches the handler and its result patches the UI; size/
type limits enforced; a user's upload is isolated to their session (rides Slice C).

## Slice E: Hybrid charting

**Delivers:** the data-viz half (ADR-0018). Rides after the transport pad fix
(KAN-1395).

**Build plan**

1. Keep server-PNG `Plot` for static; add one bundled client chart component
   (recommended uPlot) built into the shell; data/encoding ride reactive props;
   streaming points use the `append` op.
2. Land the per-frame proxy-pad fix (KAN-1395) first — streaming points amplify it.

**Demo:** a live-updating line chart (streaming points) beside a static Matplotlib
plot; a heatmap.

**Test sketch:** the chart renders from props and updates on patch; streaming points
append at O(point); static Plot still rasterises unchanged; wheel has no Node/Python
chart dep (build-time only).
