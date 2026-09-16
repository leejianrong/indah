# indah: positioning & competitive landscape

A living reference for where indah sits among Python UI frameworks, how we pitch it,
and the demo strategy that both showcases it and dogfoods it. Companion to `PLAN.md`
(roadmap) and `SLICES.md` (increments). Written 2026-09-16 after a competitor
research round; revisit when the field shifts.

## The wedge

indah is the **SSE-first, no-Node, Colab/Runpod-native** Python UI framework:

- **Single-port SSE + POST transport** (ADR-0002) that passes Colab's and Runpod's
  proxies, where WebSocket-based frameworks stall.
- **No Node at install or runtime** (ADR-0004) — a pre-built shell ships in the
  wheel; nothing compiles in a transient container.
- **Reactive, not full-rerun** (ADR-0003) — granular patches for exactly the nodes
  that changed, so per-frame/streaming interactions stay cheap.
- **Per-session state** (ADR-0010) and **native streaming** (ADR-0011) built in.

Two things happened in the market that sharpen this wedge:

1. **Mesop (Google) — indah's closest architectural cousin — was discontinued
   2026-09-30.** Mesop shipped the *same* bet: HTTP SSE as the default transport, a
   server-driven render loop where generator handlers `yield` incremental UI diffs.
   Google shut it down. indah can claim the "SSE-first Python UI" ground Mesop
   validated and then vacated — and do it with a notebook-native story Mesop never had.
2. **Reflex's Node/bun build step fails in transient cloud containers.** `reflex init`
   downloads its own bun (from GitHub releases) and Node; it breaks without npm/GitHub
   access — the exact failure indah was built to avoid. This is indah's sharpest,
   most provable single differentiator.

## Two audiences

indah plays in two arenas at once; every demo should be tagged to one (or both).

- **(a) Colab-notebook ML demos — vs Gradio.** Inline in a notebook cell, a model
  behind a UI, a share link. Gradio owns this loop (inline render + auto share link
  in Colab). indah matches it on Tier 0 and adds reactivity, per-session state, and
  no tunnel-expiry — over a single port that survives the proxy.
- **(b) Standalone Python-frontend apps — vs Streamlit.** A real app you run and
  deploy: dashboards, data explorers, internal tools. Streamlit owns mindshare here
  but reruns the whole script per interaction; indah's reactivity is the anti-rerun
  pitch (the same one Shiny for Python uses to good effect).

## Competitive landscape

| Framework | Node/build step | Default transport | Colab-proxy friendly | Notebook story | Reactivity | Status |
|-----------|-----------------|-------------------|----------------------|----------------|------------|--------|
| **indah** | **No** (pre-built shell) | **SSE + POST, single port** | **Yes (design goal, proven on real HW)** | **Colab/Runpod-native** | Granular patches, no rerun | Early / MVP+ |
| Streamlit | No | WebSocket | Weak | Weak (standalone `streamlit run`) | **Full script rerun** | Dominant, Snowflake-owned |
| Gradio | No | WebSocket + queue | Yes (inline + auto share link) | **Strong, native inline** | Function-per-event | Dominant for ML demos (HF) |
| Plotly Dash | No (runtime); build for custom comps | Callbacks over HTTP; WS needs FastAPI/Quart | Weak | Weak | Callbacks (Input→Output) | Mature, enterprise BI |
| Shiny for Python | No (Shinylive = WASM) | WebSocket | Weak | Good (Jupyter + Express) | **Reactive engine** | Mature (Posit) |
| Panel (HoloViz) | No | Bokeh server (WS) | Weak | **Strongest (first-class)** | Param reactive + callbacks | Mature, big-data viz |
| Reflex | **YES** (bun+Node at init; breaks in containers) | WebSocket | **Poor** | None | Server State classes | Active, enterprise pivot |
| NiceGUI | No (ships Vue/Quasar) | Socket.IO (WS + long-poll) | Weak (needs root_path/tunnel) | None | Vue reactivity | Active |
| Mesop | No (ships Angular) | **HTTP SSE** (+exp. WS) | Better (SSE) | None | Generator-`yield` render loop | **Discontinued 2026-09-30** |
| Voila | No (Jupyter stack) | WebSocket to kernel | Weak; JupyterHub/Binder-native | **Is the notebook-to-app tool** | ipywidgets observers | Active |

Sources: the framework sites, docs, galleries, and GitHub issues, captured 2026-09-16
(see the research briefs archived with this planning round). Gallery rosters rotate;
named apps below were present at fetch time.

## Positioning statements to adopt

- **Headline (sharpen Streamlit's "in minutes, all in pure Python, no front-end
  experience required"):** "Reactive Python UIs for cloud notebooks — no Node, one
  port, streaming by default. Works in Colab where WebSockets don't."
- **Anti-rerun (borrow Shiny's proven line):** "Reactive, not full-rerun — and it
  doesn't need a Node build that dies in your container."
- **Notebook-native (borrow Panel's "same code, notebook or standalone"):** one app
  runs inline in Colab and deploys as a standalone app, unchanged.
- **The Mesop note (for the technical audience):** "SSE-first, like Mesop — which
  Google just retired. indah carries that architecture forward, notebook-native."

## What to follow (patterns proven by the incumbents)

- A **bundled `indah hello` starter set** — the first-run wow, like `streamlit hello`.
- A **categorised, screenshot-rich gallery** of named demos grouped by domain — every
  serious framework earns credibility this way; build it early on the docs site.
- A **flagship LLM chat with live token streaming** — every framework now leads with
  one; indah's is already `examples/chatbot.py`, and it runs *in Colab*.
- **Generator/`yield`-style streaming UX** (Mesop's spinner→token pattern) — indah's
  async handlers already do this; make it visible.
- A **serious dashboard** (stock/portfolio) to prove indah is not just a notebook toy.
- A **prettymapp-style poster/artifact generator** — the most-shared community app
  archetype; visually striking and self-contained, it drives organic sharing.

---

# Demo catalogue (dogfooding backlog)

Each demo showcases indah **and** probes its rough edges. Columns: audience
(Colab / standalone / both), the indah primitives it needs, and whether those exist
today or are a **GAP** (see the gap analysis below). Priority: **P1** = high showcase
value that lands on today's primitives (validate fast); **P2** = needs one new
primitive; **P3** = heavier / needs Tier 1 or several gaps.

| # | Demo | Audience | Primitives | Status | Prio |
|---|------|----------|------------|--------|------|
| 1 | Real LLM chat, live token streaming | Colab | Chat, StreamText, TextInput | **exists** (`chatbot.py`) | P1 |
| 2 | Image classify: upload → predict → show | both | Upload, Image, Text/DataFrame | **exists** (`upload_classify.py`) | P1 |
| 3 | Live training loss-curve dashboard (Runpod) | both | Chart (streaming), Progress, DataFrame | **exists** (Slice E) | P1 |
| 4 | prettymapp-style poster / artifact generator | standalone | inputs, Image, Download | **exists** (render is user's lib) | P1 |
| 5 | Diffusion image-gen with streamed progress | both | Button, Progress, Image (streamed), StreamText | mostly exists | P1 |
| 6 | Audio analysis + spectrogram (+ streaming ASR) | Colab | Upload(audio), **heatmap**, StreamText, audio playback | **GAP** G1, G8 | P2 |
| 7 | Object detection with bounding boxes | both | Upload, Image + **box overlay** | **GAP** G2 | P2 |
| 8 | Image segmentation (masks) | both | Upload, Image + **mask overlay** | **GAP** G2 | P2 |
| 9 | Stock / peer-analysis dashboard | standalone | Chart, **rich Table**, Select, **metric cards** | **GAP** G3, G4 | P2 |
| 10 | DataFrame explorer (filter/sort/plot) | standalone | **rich Table**, Select, Chart | **GAP** G3 | P2 |
| 11 | RAG chat with citations | both | Chat, List (citations), Upload | mostly exists | P2 |
| 12 | Video object detection, stepped frame-by-frame | both | Upload(video/frames), Slider, Image + **box overlay** | **GAP** G2 | P3 |
| 13 | Map-style app (GPX viewer / geospatial) | standalone | **interactive map** (static map works today) | **GAP** G5 | P3 |
| 14 | Real-time webcam detection | standalone (non-Colab) | **Tier 1 WS**, live video, overlay | **GAP** G6, G2 | P3 |
| 15 | Streaming ASR from live mic | standalone (non-Colab) | **Tier 1 WS** (uploaded audio works on Tier 0) | **GAP** G6 | P3 |
| 16 | Multi-page internal tool | standalone | **multi-page routing** | **GAP** G7 | P3 |

---

# Gap analysis

Worked backwards from the catalogue. Each gap: what it unblocks, the decision, and
whether it is **for the demo push** or **still deferred**. New ADRs are proposed
where a genuine decision exists; cheap wins skip the ADR.

| ID | Gap | Unblocks demos | Decision | ADR |
|----|-----|----------------|----------|-----|
| G1 | **Client heatmap / 2-D field** (spectrograms, heatmaps, attention maps) | 6 | **Build — prioritised** (owner, 2026-09-16). Line `Chart` shipped in Slice E; raster is on server-PNG `Plot` today, too heavy for real-time/interactive. | **ADR-0019** (Proposed) |
| G2 | **Image overlay / annotation** (boxes, masks, keypoints) | 7, 8, 12, 14 | **Build — read-only overlay first** (draw boxes/masks over an image from props), interactive annotation (pointer round-trip to *create* boxes) as a second step. | **ADR-0020** (Proposed) |
| G3 | **Rich Table** (sort / page / filter / select / edit) | 9, 10 | **Build.** `DataFrame` renders a static table today; dashboards/explorers need interaction. Data rides props (like the list family), so no wire change expected. | **ADR-0021** (Proposed) |
| G4 | **Metric / KPI cards** (stat tiles) | 9 | **Build — cheap.** A `Stat`/`Metric` display component (value + label + delta); no new protocol capability. Fold into the rich-Table slice or a cheap-wins card; no ADR needed. | — |
| G5 | **Interactive maps** (pan/zoom, markers) | 13 | **Build — bundled client `Map`** (owner, 2026-09-16). Bundle Leaflet at build time (like uPlot) as a client `Map` mirroring the `Chart` pattern; no Node at runtime. Static maps keep working via `Plot`/`Image`. | ADR to follow (~0022) when built |
| G6 | **Tier 1 WebSocket transport** (continuous live media) | 14, 15 | **Still deferred, non-Colab only.** Already the declared boundary (ADR-0017). Build a Tier-1 ADR when we commit to a live-webcam/mic demo; uploaded audio/video and frame-stepping cover most of the value on Tier 0. | ADR when built |
| G7 | **Multi-page routing** | 16 | **Decide at review.** A recorded deferred boundary (PLAN.md). Needed only for larger standalone apps; most demos are single-page. Likely P3. | pending |
| G8 | **Audio playback + waveform** component | 6 | **Build — small.** Play uploaded/returned audio, optional waveform. Pairs with G1 for the audio demo. Likely folds into the audio-demo slice. | pending/small |
| G9 | **Structural-children op** (KAN-1396) | — | **Stay parked.** The data-driven list family (ADR-0016) covers dynamic content for every demo above; no demo yet forces a structural op. | parked |

## Recommended build order (pending owner review)

1. **Validate on today's primitives (P1):** demos 1, 2, 3, 4, 5. These need nothing
   new and prove the pitch immediately — and 3 exercises the just-shipped streaming
   `Chart`.
2. **First new primitives (P1/P2 gaps):** G1 heatmap (prioritised), G3 rich Table +
   G4 metric cards, G2 overlay (read-only). Each unblocks a cluster of P2 demos.
3. **P2 demos on the new primitives:** 6 (audio+spectrogram), 9 (stock dashboard),
   10 (explorer), 7/8 (detection/segmentation), 11 (RAG citations).
4. **P3 / heavier:** 12 (video frame-stepping), 13 (maps, if G5 approved), and the
   Tier-1 items 14/15 last (non-Colab, real WebSocket work), 16 (multi-page) if
   needed.

The backlog is tracked on board 30 as epics split by audience plus a framework-gaps
epic; the gap ADRs (0019–0021) are Proposed.

### Review outcome (2026-09-16)

The owner reviewed this plan and decided:

- **Build the P1 demos first** (1–5): they land on today's primitives and validate
  the pitch immediately.
- **G5 interactive maps — build a bundled client `Map`** (Leaflet at build time, like
  uPlot); static maps keep working meanwhile.
- **G7 multi-page routing — stay deferred** (the demo push is single-page).

---

# Go-to-market: landing page & hosted demo gallery

The demos are only half the showcase; people have to find them, understand why indah
is different, and *try one in one click*. Two pieces, both planned here.

## Landing page

The Zensical docs site (`website/`, ADR-0007) is the home; its index becomes a proper
landing page (FastAPI-style: the docs home doubles as the marketing page). Grow
`website/docs/index.md` into:

- **Hero** — the Bunga mark + wordmark, a one-line tagline ("Reactive Python UIs for
  cloud notebooks — no Node, one port, streaming by default"), and a primary CTA
  (Quickstart / Try a demo).
- **Why indah / how it's different** — the wedge (no-Node, SSE-first Colab-native,
  reactive-not-rerun, per-session, streaming) and a condensed differentiation table
  vs **Gradio** (notebook ML demos) and **Streamlit** (standalone apps), drawn from
  the landscape table above. One honest "when to reach for indah vs them" paragraph.
- **See it** — an embedded live demo (the streaming chart or the chatbot) or a short
  GIF, so the reactive/streaming feel is visible above the fold.
- **Demo gallery** — a screenshot grid of the built demos, each linking to a hosted,
  try-it-now instance *and* an "Open in Colab" button (below). This is the piece that
  mirrors Streamlit's and Gradio's galleries.
- **Get started** — the install snippet, links to docs, the protocol contract, and the
  GitHub repo.

## Hosted demo gallery (try-it-now)

Goal: like Streamlit's hosted demos — click and it is already running, no install.
The on-brand baseline is free and matches indah's whole story; a persistent host is
the decision to make.

- **"Open in Colab" (baseline, every demo).** A one-click badge on each demo opens its
  notebook straight from GitHub in the user's Colab (already the manual-e2e path, see
  the `indah-colab-manual-e2e` note). Zero hosting cost, and it *is* the pitch — indah
  runs in a throwaway Colab and prints a URL. Ship this regardless of the host choice.
- **A persistent hosted gallery (the decision).** For "already running, nothing to
  do", options with real trade-offs:
  - **Hugging Face Spaces (Docker Space per demo)** — free tier, persistent URL,
    instant try, and it plants indah on the same turf as Gradio/Streamlit demos. A
    Docker Space runs indah's ASGI app directly.
  - **Self-hosted gallery (Fly.io / small VPS / Runpod)** — one indah "gallery app"
    hosting every demo behind one domain (dogfoods per-session state and single-port);
    more control, but ongoing cost + ops.
  - **In-browser WASM (Shinylive/Panel-style)** — not viable near-term: indah is a
    server (SSE + POST), so this would need a substantial rework. Note and park.

**Decided (owner, 2026-09-16):** Colab one-click on every demo **+ a persistent
self-hosted gallery on Fly.io** (a Docker app per demo, machines auto-stopping when
idle). We first chose HF Spaces, but HF now requires **PRO** for Docker Spaces
(`402`), so we took the ADR's Fly fallback - the same Docker image runs there. WASM
is parked. See **ADR-0023**. The Docker recipe is in `deploy/spaces/`, the Fly deploy
in `deploy/fly/`; the deploy is an owner step (needs a Fly account).

Tracked on board 30 as **EPIC-220 (landing page & hosted demos)**.
