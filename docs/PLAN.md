# indah: Plan

Status: MVP shipped (0.1.0, 2026-09-15) · Active milestone: post-MVP (Milestone 1) —
see [Post-MVP roadmap](#post-mvp-roadmap-milestone-1) at the end of this file. The
sections below record the MVP (v0) plan as delivered.

## Problem

Streamlit and Gradio make it trivial to put a UI in front of a Python script,
which is exactly why AI/ML researchers reach for them inside Google Colab and
RunPod. But both break down past the demo stage. Streamlit reruns the entire
script on every interaction, so an app holding a large model in memory becomes
sluggish or falls over. Gradio's block layout and `gr.State` chaining make
anything beyond inputs-left/outputs-right awkward, and it is tied to the Hugging
Face way of doing things. The alternatives that fix the architecture — Reflex in
particular — need a Node.js build step that is a logistical nightmare to
initialize inside a transient cloud container.

The result is a real gap: there is no tool with Streamlit's zero-config,
single-port, fast-startup deploy story that also has the async performance of an
actual full-stack app, and that runs cleanly through the network proxies of Colab
and RunPod without a local JavaScript toolchain.

## Solution

A `pip install`, then a single `app.launch()` in a notebook cell (or `python
app.py`) brings up a live UI — either inline in the cell or at a public proxy URL
the framework prints for you. No Node, npm, or bun is ever invoked, at install or
at runtime; the frontend ships pre-built inside the wheel. You describe UI in
Python using reactive state: you declare components, bind them to state
variables, and when your code mutates a variable only the affected components
update, with no full-script rerun. Heavy work (a PyTorch pipeline, an LLM
generating tokens) runs async and streams into the UI instead of freezing it.

It feels like Streamlit to start and like a real application framework as the app
grows — custom layouts, long-lived in-memory state, incremental updates — and it
works the same in Colab, on RunPod, and locally.

## Users and actors

The core scenario has two personas with a handoff between them (ADR-0008):

- **Primary: the prototyper** — a junior dev, ML engineer, or data scientist
  running heavy PyTorch/Transformers pipelines in Colab or RunPod. They wrap a
  pipeline (RAG chatbot, image bounding-box tool) in a few lines and share a
  working demo the same day, without touching auth, deployment, or JS.
- **Secondary: the engineering team** — picks up a validated prototype and turns
  it into a real app for external users (auth, hosting, custom frontend,
  multi-user state). They are served by the *graduation path*, not by v0 features.
- **Secondary: general Python developers** building small internal tools who want
  something less rigid than Gradio.
- **Deferred: agents / machine callers.** No machine-facing control surface in v0.

When the prototyper's needs conflict with general-purpose polish, the prototyper
wins — Colab/RunPod compatibility is the north star.

### User stories

**Prototyper**

- As an ML engineer, I wrap my RAG pipeline in ~30 lines of indah and `launch()`
  it in Colab, so I can share a working demo URL with my team the same afternoon.
- As a data scientist, I build an "upload an image, see bounding boxes" tool
  without writing any JavaScript or setting up a server.

**Engineering team — Composable path**

- As a backend engineer, I mount the prototype's indah app inside our FastAPI
  service and put our existing OAuth middleware in front of it, so it sits behind
  our SSO without rewriting the UI (ADR-0008).
- As a frontend engineer, I replace one auto-generated component with our
  design-system Svelte component via the registration seam, while the rest of the
  app keeps working (ADR-0005).
- As a backend engineer, I point session state at a shared store so the app
  survives restarts and runs multiple replicas (ADR-0010).

**Engineering team — Eject path**

- As a backend engineer, because the prototyper kept the RAG logic in plain Python
  functions indah merely called, I lift those functions straight into our own
  FastAPI endpoints and drop indah (ADR-0009).
- As a frontend lead, I generate a Svelte project wired to indah's public JSON
  protocol as a starting point, then evolve it independently (ADR-0008).

## Scope

**In this milestone (v0).**

- Single-file Python app → live UI, inline in a Colab/RunPod cell or in a browser
  tab.
- Single-port ASGI app serving the pre-built frontend and the dynamic API
  (ADR-0001).
- SSE + HTTP POST transport that works through Colab's proxy with no extra
  dependencies (ADR-0002).
- Reactive-signal programming model with granular JSON-patch updates (ADR-0003).
- A starter component set: text/markdown, button, text input, slider, select,
  image, plot/dataframe display, and a streaming text container for LLM tokens.
- A `launch()` helper that detects Colab/RunPod and prints the correct proxy URL.
- A versioned JSON UI protocol documented as a public contract (ADR-0005).

The **graduation path** (prototype → production) is a v0 *design constraint*, not
a v0 feature set: v0 keeps the doors open (public protocol, mountable ASGI app,
auth/state/logic seams) but builds no production machinery. See ADR-0008/0009/0010.

**Out.**

- WebSockets as the primary transport — Colab's proxy does not support them
  (ADR-0002). Optional upgrade only.
- A built-in auth system — auth is bring-your-own via standard ASGI seams
  (ADR-0008); indah owns no security-critical subsystem.
- Multi-tenant hosting and an external (Redis/DB) state backend — the state seam
  is designed now, but only the in-memory backend ships in v0 (ADR-0010).
- Eject codegen (scaffolding a standalone frontend project) — enabled by the
  public protocol but not built until demand appears (ADR-0008).
- Component marketplace / plugin distribution.
- Persistent application/domain storage — the user's own code owns durable data.
- Any runtime Node/npm/bun dependency.

## Requirements

| ID | Requirement | Status |
|----|-------------|--------|
| R0 | A single-file Python app launches a live, interactive UI in Colab with no build step and no Node | Core goal |
| R1 | Interactions update only affected components; no full-script rerun | Must-have |
| R2 | Real-time updates work through Colab's and RunPod's HTTP proxies | Must-have |
| R3 | Heavy/long-running work runs async and streams into the UI without freezing it | Must-have |
| R4 | Frontend ships pre-built in the wheel; zero Node/npm/bun at install or runtime | Must-have |
| R5 | A starter component set sufficient for a typical AI demo (input → run → streamed output) | Must-have |
| R6 | The JSON UI protocol is a versioned, documented public contract | Nice-to-have |
| R7 | Custom components can be registered without forking the framework | Nice-to-have |
| R8 | A validated prototype can graduate (mount behind auth, custom frontend per-component, shared state) with no rewrite of its domain logic | North-star |

## Shape

| Part | Mechanism | ADR |
|------|-----------|-----|
| S1 | Single ASGI app (Starlette + Uvicorn): static route serves the pre-built shell; `/api/*` routes serve UI JSON, accept events, and stream updates — all on one port | ADR-0001 |
| S2 | Transport: SSE stream (server→client patches) + HTTP POST endpoint (client→server events), with an optional WebSocket upgrade probed at connect time | ADR-0002 |
| S3 | Reactive core: named signals; a dependency graph maps each signal to the component nodes and handlers that read it; mutating a signal enqueues a minimal patch set | ADR-0003 |
| S4 | UI tree: Pydantic component models with stable server-assigned node IDs; serialized to JSON for the shell, which renders/patches by node ID | ADR-0003, ADR-0005 |
| S5 | Svelte shell: pre-compiled SPA bundled as static assets in the wheel; reads UI JSON and applies patches; no virtual DOM | ADR-0004 |
| S6 | `launch()`: binds a port, detects Colab (`google.colab`) / RunPod (env), prints the proxy URL, and renders inline via iframe when in a notebook | ADR-0001 |
| S7 | Custom-component registry: a Python-side registration seam maps a user component type to a shell renderer, keying off the public protocol | ADR-0005 |
| S8 | Session-store seam: the reactive core reads/writes state through a small interface; only the in-memory backend ships in v0, a shared backend is a later drop-in | ADR-0010 |
| S9 | Graduation seams: indah is a mountable ASGI sub-app, auth is standard ASGI middleware the user supplies, and domain logic stays in plain functions indah calls | ADR-0008, ADR-0009 |

## Affordances

**UI (the Python-authored surface).**

| Affordance | Place | Wires to |
|------------|-------|----------|
| Text / Markdown | anywhere in the tree | a signal or static string |
| Button | anywhere | an `on_click` handler |
| TextInput / Slider / Select | anywhere | a two-way-bound signal |
| Image / Plot / DataFrame | anywhere | a signal holding the value |
| StreamText | anywhere | an async generator streaming tokens over SSE |

**Non-UI.**

| Affordance | Kind | Wires to |
|------------|------|----------|
| `app.launch()` | entry point | binds port, detects env, serves S1 |
| Signal | store | S3 reactive graph |
| Event endpoint `POST /api/event` | handler | validates payload, runs bound handler, emits patches |
| SSE endpoint `GET /api/stream` | stream | pushes patches + streamed generator output |
| `register_component()` | registry | S7 custom-component seam |

## Implementation decisions

- **One ASGI app, one port** (ADR-0001). Starlette for routing, Uvicorn as the
  server. Static assets mounted from the package; API under `/api`. This is what
  makes Colab/RunPod proxying work.
- **Transport is SSE + POST, not WebSocket** (ADR-0002). The client opens one SSE
  connection for server→client patches and POSTs events back. A WebSocket upgrade
  is attempted only when the environment advertises support; the reactive core is
  transport-agnostic so this is a swap behind one interface.
- **Reactive signals over reruns** (ADR-0003). The public API centers on signals
  and components that bind to them. Handlers mutate signals; the core diffs and
  emits JSON patches addressed by node ID. No user code is re-executed top to
  bottom.
- **UI as versioned JSON** (ADR-0005). Component models are Pydantic; the wire
  format carries a `protocol_version` the shell checks on connect and rejects on
  mismatch. This contract is documented as public so a hand-written frontend
  could target it later, and so custom components can register against it.
- **Svelte shell, pre-built** (ADR-0004). The frontend is a Svelte SPA built in
  CI and committed/bundled as static assets in the wheel. Building the wheel needs
  Node; installing and running it never does.

## Testing approach

Test at the highest seams that stay honest about the cross-language boundary:

- **End-to-end through a headless browser** against a real launched app is the
  primary seam — it is the only place that proves the Python core, the wire
  protocol, and the Svelte shell agree, and that updates are granular.
- **Integration at the HTTP/SSE boundary** (drive `/api/event`, assert the patch
  stream) covers the protocol without a browser and is where most behaviour is
  pinned cheaply.
- **Unit tests on the reactive core** (signal → dependency graph → patch set)
  because the diffing logic is the novel, breakable part.
- **A Colab/RunPod smoke check** — an actual notebook run — guards R2, since the
  proxy behaviour cannot be reproduced by a local test.

## Assumed defaults

| ID | Assumed | Cost if wrong |
|----|---------|---------------|
| Q-user | Primary user is the AI/ML notebook user; humans before agents | Medium — reprioritizes the component set |
| Q-state | Session state lives in-process, per session, not persisted | Medium — adds a storage layer later |
| Q-concur | Single-user / few-viewer; isolated per-session state, last-write-wins | Medium — multi-writer needs a merge story |
| Q-fail | Handler errors show a UI toast + server traceback; UI stays live | Low — localized change |
| Q-sec | Dev-tool threat model, no built-in auth in v0 | Medium — auth is a v1 addition, documented |

## Open risks

- **Colab proxy + SSE reliability** (R2). SSE should pass Colab's proxy where
  WebSockets do not. Status: **proven on real hardware** on `0.1.0` (2026-09-15) -
  a full Colab browser run of `examples/smoke_test_rc.ipynb` (every checklist row)
  plus an automated RunPod curl smoke through `proxy.runpod.net`; the Colab
  window-buffering fix is guarded locally by `tests/e2e/test_proxy_buffering.py`
  (see the results table in `docs/SLICES.md`).
- **RunPod's 100s proxy timeout** (R3). Long SSE streams may be cut. Status:
  **confirmed handled** - the RunPod smoke held an SSE stream open past the ~100s
  Cloudflare cap on 8 heartbeats (15s interval), with `Last-Event-Id` resume as the
  backstop (Slice 3 streaming, ADR-0011).
- **Granular-patch correctness** (R1). The diffing core is the hardest part to get
  right; a wrong patch set silently corrupts the UI — unit + e2e in Slice 2.
- **Notebook inline display** across Colab vs RunPod (JupyterLab) iframe quirks —
  surfaced in Slice 1.

---

# Post-MVP roadmap (Milestone 1)

The MVP proved the architecture (single-port SSE+POST through Colab/RunPod proxies,
reactive patches, streaming, the starter set). Milestone 1 answers "what do people
actually reach for Streamlit and Gradio to do, and what does indah need to serve
those well without losing its Colab / zero-Node / single-port / reactive north
star." Worked backwards from use cases to the missing primitives (planning round,
2026-09-15).

## Decisions taken this round

- **Shared foundation first.** Build the primitives both the ML-demo and data-viz
  halves need (layout, a list, per-session state) before specialising.
- **Dynamic content is a data-driven list, not a structural protocol op** (ADR-0016).
  Chat/gallery/logs ride one reactive `data` prop like `DataFrame` already does — no
  wire-format change. A true structural children op stays deferred (reframes
  Q-children / KAN-1396).
- **Charting is hybrid** (ADR-0018): keep server-PNG `Plot` for static, add one
  bundled client chart for interactive/real-time. No protocol bump (data rides
  props).
- **Media is upload-and-process now; live video later for non-Colab** (ADR-0017).
  Transport tiers are explicit: Tier 0 = SSE+POST (the Colab floor); Tier 1 = an
  optional WS upgrade for continuous media, non-Colab only, declared now and built
  later.
- **Visual identity locked** (ADR-0014): the "Studio" theme (warm porcelain,
  bougainvillea magenta, deep teal; Bricolage Grotesque / IBM Plex) and the "Bunga"
  four-petal logo. A design-token layer lands *before* the new components so each is
  drawn to it once. One theme baked now; a switcher is deferred but cheap.

## Use-case clusters (worked backwards to gaps)

| Cluster | Missing primitive | Cost |
|---------|-------------------|------|
| A · Dashboards & tables | layout containers; rich Table (sort/page/select/edit); metric cards | cheap–medium |
| B · Charts & viz (static/real-time/interactive, heatmaps, spectrograms, maps) | client-side charting (Plot is a server PNG/frame) | expensive |
| C · Media I/O (upload image/audio/file, gallery, download) | upload input + multipart endpoint; download | medium |
| D · Chat / RAG / streaming | data-driven list (bubbles, citations, logs) | cheap–medium |
| E · Annotation / canvas (boxes, masks) | interactive canvas + pointer round-trip | expensive (deferred) |
| F · Real-time media (webcam, live detection) | transport Tier 1 (non-Colab) | expensive (deferred) |
| G · App structure (multi-page, per-session) | per-session state; layout; (later) structural op | medium–expensive |

Also folded in as cheap wins: complete the basic input set
(checkbox/number/radio/multiselect/date), markdown/code in `Text`, progress/spinner,
Enter-to-submit, download.

## Highest-leverage primitives

The recurring insight: **almost all new UI can be first-class shell components
carrying data in ordinary props over today's protocol.** The wire format only needs
to change for a genuine structural-children op (deferred) — not for lists, layout, or
charts. The foundation primitives, most-shared first: **layout containers**,
**data-driven list**, **per-session state**, then the two specialisations
**file/media upload** and **hybrid charting**.

## Slice sequence

| Slice | Delivers | New primitives | Protocol | ADR |
|-------|----------|----------------|----------|-----|
| 0 · Design system & identity | the token substrate + brand | Studio tokens, theming seam, Bunga logo/favicon (shell + docs) | none | 0014 |
| A · Layout & input set | foundation for both halves | Row/Grid/Tabs/Sidebar/Expander; checkbox/number/radio/multiselect/date; markdown in Text; progress; Enter-to-submit | none | 0015 |
| B · Data-driven list | chat, galleries, logs | List/Repeat + Chat + Gallery; chatbot rebuilt on Chat | none | 0016 |
| C · Per-session state | honest multi-user; prereq for upload | implement the ADR-0010 session-store seam | none | 0010 |
| D · File/media upload | the classic ML demo | Upload + multipart endpoint; download | +endpoint (additive) | 0017 |
| E · Hybrid charting | data-viz half | bundled client chart (interactive/real-time) alongside server-PNG Plot | none | 0018 |

Deferred with a recorded boundary: structural-children op (KAN-1396), interactive
canvas annotation, real-time video (Tier 1), multi-page routing. Transport hardening
(KAN-1395, the per-frame pad) rides just before Slice E, which amplifies it.

Sequenced into demoable increments in `docs/SLICES.md`; open questions and their
resolutions in `docs/QUESTIONS.md`.
