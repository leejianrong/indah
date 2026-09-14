# indah: Plan

Status: draft · Milestone: MVP (v0)

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

- **Primary: AI/ML researchers, hobbyists, and engineers** running heavy
  PyTorch/Transformers pipelines in Colab or RunPod who want deploy simplicity
  plus real async performance.
- **Secondary: general Python developers** building small internal tools who want
  something less rigid than Gradio.
- **Deferred: agents / machine callers.** No machine-facing control surface in v0.

When the notebook user's needs conflict with general-purpose polish, the notebook
user wins — Colab/RunPod compatibility is the north star.

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

**Out.**

- WebSockets as the primary transport — Colab's proxy does not support them
  (ADR-0002). Optional upgrade only.
- Auth, multi-tenant hosting, per-user isolation beyond per-session state objects
  — this is a dev tool behind a trusted proxy in v0.
- The full hand-written-frontend escape hatch (scaffolding, typed JS client, HMR)
  — deferred; only the protocol seam is built now (ADR-0005).
- Component marketplace / plugin distribution.
- Persistent storage / database integration — the user's own code owns durable
  data.
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
  WebSockets do not, but this must be proven on real hardware — confronted in
  Slice 1.
- **RunPod's 100s proxy timeout** (R3). Long SSE streams may be cut; needs a
  heartbeat/reconnect strategy — exercised in Slice 3 (streaming).
- **Granular-patch correctness** (R1). The diffing core is the hardest part to get
  right; a wrong patch set silently corrupts the UI — unit + e2e in Slice 2.
- **Notebook inline display** across Colab vs RunPod (JupyterLab) iframe quirks —
  surfaced in Slice 1.
