# Demos + Docs Revamp — Round 2 (feedback and plan)

Owner feedback captured 2026-09-17, a second pass over the demos, docs, and (new this
round) public-deployment hardening. Round 1 (`docs/DEMOS-DOCS-REVAMP.md`) rebuilt the
landing page, added the keyed chatbot, new demos (stocks, prettymap), screenshot
thumbnails, and a docs de-competitor + nav regroup (PRs #56–#73). This round refines the
individual demos, reorganizes the docs for **users of indah** (not contributors), scopes
a batch of new demo ideas by feasibility, and adds an abuse-hardening workstream for the
Fly deployment.

Companion artifact: the **chatbot redesign proposal** (visual mockups + decisions) is
published separately; this doc records the plan text.

Related: `docs/DEMOS-DOCS-REVAMP.md` (round 1), `docs/POSITIONING.md` (demo catalogue +
gap analysis G1–G9), ADR-0014 (design system), ADR-0015 (layout set), ADR-0019 (client
heatmap, shipped), ADR-0023 (demo hosting on Fly).

---

## 0. Grounding — what's actually possible today

A capability audit (shell renderer `frontend/src/Node.svelte`, components
`src/indah/components.py`, wire allowlist `src/indah/protocol.py`) settled the feasibility
of every idea below. The load-bearing facts:

- **Audio playback does NOT exist and is not app-level.** `ALLOWED_TAGS`
  (`protocol.py:77-84`) deliberately excludes `audio`/`video`/`canvas`/`script`/`iframe`;
  the custom-component seam can only round-trip an element's `.value`, not inject media.
  A waveform/spectrogram can be **shown** (`Plot` PNG, or the client `Heatmap` for a live
  spectrogram) but **not heard** without a framework change (a new native `audio` node in
  the shell + `make frontend`). This is gap **G8** in POSITIONING.md.
- **No clickable-cell / canvas primitive.** The only click events in the system are
  `Button` (no payload) and `Table`/`Tabs` select (an index). A 3×3 tic-tac-toe board is
  feasible by composing 9 `Button`s in a `Grid`; a large ARC-AGI grid or a drag
  interaction needs a **new native grid/canvas component + shell rebuild**.
- **Play only, no pause/step built in.** Animations are an `async def` loop kicked by a
  Button (`await asyncio.sleep`, mutate signals). Pause/step must be hand-rolled with
  signals the loop polls; there is no framework transport-control widget. The diffusion
  demo today runs to completion with no controls.
- **Nav:** `Sidebar` + `Tabs` + `Expander` exist (ADR-0015) and approximate a side menu /
  top nav. A true click-to-open dropdown menu is a new component. Multi-page routing is
  the deferred gap **G7**.
- **Already shipped and reusable:** `Chart` (client uPlot, streaming), `Heatmap` (client
  2-D field / spectrogram, streaming `push_column`), `Table` (sort/page/row-select),
  `Stat` (KPI card), `ImageOverlay` (read-only boxes/masks), `Upload`/`Download`,
  `Plot` (server matplotlib PNG), `TextInput(password=True)`.

- **Licensing constraint (cross-cutting).** indah is **Apache-2.0**, and the demos are a
  hosted public service, so any library a demo pulls in must be **license-compatible with a
  network service** — MIT / BSD / Apache / PSF are fine; **avoid AGPL / SSPL** (network
  copyleft attaches to the whole hosted app). This is why A8 reimplements the map renderer
  rather than depending on AGPL `prettymaps`/`prettymapp`.

See §5 for the consolidated feasibility matrix.

---

## A. Individual demo changes

### A1. Chatbot — declutter + hide the key (see the proposal artifact)

Current issues (all on the live demo): an explainer line above the chat
(`chatbot.py:294`), the API-key field as the second thing you see (`:297-304`), a second
paragraph on where to get a key (`:307-310`), a raw status string doubling as the empty
state ("Ask me something." `:260`), and seven items stacked with no hierarchy.

Plan (a re-layout of `build_session()` — **no new primitives**):
- Remove the explainer `Text` and the "get a free key" `Text`.
- Move the key + provider into a **settings panel** — an `Expander("⚙︎ Settings")`
  (recommended: one clean column, best on mobile) or a `Sidebar` region on wide screens.
- Replace "Ask me something." with an **empty state**: the Bunga mark + 3 clickable
  **suggestion chips** that seed the box (this is the "tips about how indah works" idea).
- Drop the text status line; the streaming pending bubble (cursor already exists) is the
  status. Optional "stop" affordance.
- **Provider = OpenRouter only** (owner, 2026-09-17). OpenRouter is OpenAI-compatible
  (`https://openrouter.ai/api/v1/chat/completions`, `Authorization: Bearer <key>`, SSE
  streaming), so it swaps in for `gemini_chat_stream` cleanly as `openrouter_chat_stream`.
  The panel offers a small **model `Select`**, **defaulting to a free model** so no one has
  to pay, with a few picks for people who have credits:
  - Default: a free model — prefer the **`openrouter/free` auto-router** (free model IDs
    rotate, so don't hardcode one that may vanish), or a current free model as the label.
  - Cheap paid picks: **DeepSeek** (e.g. `deepseek/deepseek-chat`) and **Qwen**. A handful
    is enough.
  - Still **BYOK**: the user pastes their own OpenRouter key (free tier needs a key too);
    key held per-session, never logged. **No shared key as an open proxy** (round-1
    decision holds — see §D).

### A2. Live training dashboard — fix the mobile overflow

Root cause: the 4 KPI cards are laid out in a **`Row`** (`training_dashboard.py:123`),
which flex-wraps but has no responsive column collapse, so on a phone it crams all four
onto one line and the text overflows each card. `Grid` *does* collapse to 1 column at
560px (shell CSS `index.html:200`).

Plan: switch the KPI row to **`Grid(columns=4)`** (or `Grid(columns=2)` for a 2×2 on
phones) so it collapses cleanly, and/or give `Stat` a sensible `min-width` + wrapping in
the shell CSS. Verify at ~400px. Cheap; likely one demo edit, possibly a small shell CSS
tweak (would need `make frontend`). Everything else about this demo is liked — keep it.

### A3. Image generation (diffusion) — real Runpod run, with transport controls

Current diffusion demo is mock frames, run-to-completion, no controls. Owner wants a
**real diffusion run** showing both **noising (forward)** and **denoising (reverse)**,
with **play / pause / step** buttons. This is round-1 backlog **KAN-1489** plus new
control requirements.

Plan (two parts):
- **Data:** on Runpod, run a real diffusion model and **record** the forward-noising and
  reverse-denoising latents as a frame sequence (decoded to small PNGs). Ship the recorded
  frames with the demo (no key, always-on, no per-run GPU cost) — same "pre-record real,
  replay" decision round 1 took. See `skills/runpod-jobs` for the pod lifecycle.
- **Controls:** add **play / pause / step-forward / step-back / scrub**. The framework has
  no built-in transport controls, so hand-roll them: a `playing` signal the async loop
  polls (`await` while paused), a `frame_index` signal driven by step buttons + a `Slider`
  as a scrubber, `Image` bound to `frames[frame_index]`. This also becomes the reference
  pattern for "animation with controls" (reusable by the Tower-of-Hanoi visualizer, §C).

### A4. Poster generator — keep as is

Liked. No changes.

### A5. Image classifier — pre-loaded pickable images, results out of the box

Current `upload_classify.py` requires an upload before anything shows. Owner wants a
**picker of pre-loaded sample images** with **classification + confidence shown
immediately**, no upload required, and asks about a **lightweight model in the demo**.

Feasibility: in-browser classifiers (Transformers.js / ONNX-Web MobileNet) can't be
injected — the shell blocks arbitrary `<script>`. But a **server-side ONNX MobileNet is
<20 MB and classifies in tens of ms on CPU** (onnxruntime, no Node) — light enough to
bundle in the demo image. This makes a *real* (not mock) classifier feasible.

Plan:
- Ship a handful of **sample images** and render them as a `Gallery` / row of clickable
  thumbnails (each a `Button` with an image, or `Gallery` + a select signal).
- On load, classify the first sample so the **Result card (Image + top-k labels +
  confidence bars) is populated immediately**.
- Keep `Upload` as a secondary "or try your own" path.
- Real model: bundle a small ONNX MobileNet + labels; server-side classify → top-5 with
  confidences (a small `Table` or `Stat` row, or a bar via `Chart`). Fallback to a stub if
  the model isn't present so the wiring stays smoke-testable.

### A6. Hybrid charting — table it; pivot toward an audio showcase (later)

The current `charts.py` is bland (no real use case). Owner: **table it for now**, and
explore evolving it into an **audio showcase** — time-domain waveform, spectrogram, an
audio-visualization dashboard with selectable samples, and the ability to **hear** the
audio.

Feasibility split:
- **Visual-only audio dashboard is feasible today:** pick a bundled sample → show its
  waveform (`Plot`) and a **live/streaming spectrogram** (`Heatmap`, shipped ADR-0019),
  plus level meters (`Stat`/`Progress`). Good showcase of Heatmap + streaming.
- **Playback ("hear the audio") is a GAP (G8).** It needs a new native `audio` node in the
  shell (or adding `audio` to `ALLOWED_TAGS` with a real component) + `make frontend`.
  Small, self-contained framework work; decide whether to build it before the audio demo.

Plan: leave `charts.py` as-is for now (or quietly demote it). **G8 audio playback is
greenlit** (owner, 2026-09-17) — build the small native `audio` component (new shell node +
`make frontend`) so the audio demo can both visualize *and* play. Then draft the
**audio-analysis demo** (selectable sample → waveform `Plot` + streaming spectrogram
`Heatmap` + playback + level meters) on top of it.

### A7. Stock peer analysis — model it on demo-stockpeers

The Streamlit reference (`github.com/streamlit/demo-stockpeers`) is **returns /
price-normalization** focused (not fundamentals). It shows: a normalized price line chart
(all tickers to 1.0), per-stock **vs peer-average small multiples** in a 4-column grid, an
**over/under-performance band** (delta area chart), **best/worst** metric tiles, and a raw
price table. Controls: multiselect over 100+ tickers, a time-horizon "pills" selector.

Feasibility: **all on today's primitives** — `Chart` (normalized lines + delta band),
`Grid` of small-multiple `Chart`s, `Stat` (best/worst), `Table` (raw data), `MultiSelect`
(tickers), `Radio` (time-horizon pills). Live `yfinance` needs network egress (bundle a
cached dataset for the public demo; see §D — don't fetch arbitrary tickers live).

Plan: rebuild `stocks.py` toward this layout — normalized-price hero `Chart`, a
`Grid(columns=4)` of per-stock-vs-peer-average small multiples, an over/under band, and
best/worst `Stat` tiles, with a `MultiSelect` of tickers and a time-horizon `Radio`.
Ship with a **bundled, cached** price dataset (a fixed peer universe) rather than live
fetches.

### A8. Map poster — our own OSM renderer (not prettymaps/prettymapp)

**Licensing decision (owner, 2026-09-17): do NOT depend on `prettymaps` or `prettymapp`.**
`marceloprates/prettymaps` is **AGPL-3.0** — strong network copyleft that would attach to
our whole public demo. indah is **Apache-2.0**; the two don't mix for a hosted service.
(`chrieke/prettymapp` is a derivative rewrite; treat its license the same way and avoid it
too.) The current `examples/prettymap.py` is safe — it's procedural generated-art with no
osmnx/prettymaps dependency; nothing AGPL is in the tree.

Approach: **read prettymaps only to understand the mechanism, then build our own.** The
*pipeline* is not copyrightable — geocode a place → fetch OSM features (buildings, streets,
water, green) → draw styled polygons/lines with matplotlib → export an image — and it rides
entirely on **permissively licensed** libraries: `osmnx` (MIT), `geopandas` (BSD-3),
`shapely` (BSD-3), `matplotlib` (PSF/BSD-style). We write our own layer filtering, styling,
presets, and framing, with a **distinct indah flavor** (Studio palette / Bunga-derived
presets, our own preset names and color roles — not their Peach/Auburn/Citrus/Flannel data).
No prettymaps/prettymapp code or preset tables copied.

Feasibility unchanged: works server-side, outputs a static image into `Plot`/`Image`. The
OSM fetch (Nominatim/Overpass via osmnx) is the catch — seconds of latency, external rate
limits, and a public-demo **abuse / IP-ban surface** for arbitrary addresses (see §D).

Plan:
- Build a small **`osm_poster`** renderer (our code, permissive deps) — geocode + fetch +
  style + export — with our own presets and a distinct look. It's the *user's* dependency
  set (osmnx et al.), not indah's core, like transformers in the chatbot.
- For the **public** demo, restrict to a **curated set of pre-fetched locations** (bundle
  the OSM geometry / aggressively cache), so no arbitrary live OSM calls from the public
  box. Style/shape/preset controls re-render locally and instantly. Keep an "any address"
  path only for the Colab/local version the user runs themselves.
- Keep the current procedural-art `prettymap.py` live until the OSM version is ready (or
  offer both: "generated" vs "real map").

### A9. Remove all "live" indicators

Two real UI indicators exist; the owner's decision (2026-09-17) splits them:
- **Remove the gallery card pill** — `deploy/fly/gallery_app.py:97` emits
  `<span class="live">live</span>`; styled at `landing.html:123`; plus prose at
  `landing.html:5` (meta), `:175`, `:221`, `:255` ("Every demo below is live"). Remove all
  of these (badge + the "live" wording).
- **Keep the per-session SSE connection dot** inside the app demos —
  `frontend/src/App.svelte:202` renders a dot whose text flips "live" / "reconnecting…".
  The owner didn't realize this shows connection health; it stays. No change.

---

## B. Docs (`leejianrong.github.io/indah`) — reorganize for *users*

Audience is **users who `pip install indah`**, not contributors. Current docs (Zensical,
`website/docs/`) are structurally fine but carry contributor-only instructions and an
over-built gallery.

### B1. Gallery page — Colab-only, drop the standalone table

`website/docs/gallery.md` has a big primary button to the live gallery (keep it) and
**two tables**, both with **Live + Colab** columns.
- **Keep only the notebook-native (Colab) table**, and **only the Colab links** — drop the
  "Live" column (the pink "Open the live gallery" button already covers live demos).
- **Delete the "Standalone apps" table** entirely (covered by the live gallery).
- Remove "running live" / "live" phrasing (`gallery.md:1-9`).

### B2. Remove every repo-clone instruction

Users don't clone the repo. Replace these with `pip install indah` + inline code (GitHub
*links* are fine to keep; only clone-dependent *instructions* go):
- `quickstart.md:12-18` — "Prefer to run from a clone" (`git clone … && cd indah`,
  `uv sync`, `make demo`). Remove.
- `gallery.md:33-42` — "Run one locally instead" (`git clone …`, `uv run python
  examples/poster.py`, `make demo`). Remove.
- `chatbot.md:186-188` — `python examples/chatbot.py --mock` etc. (assumes a checkout).
  Replace with the inline `--mock` snippet that's already on the page, or a pip-based path.

### B3. The empty space → playground, or omit

Round 1 backlogged a **Pyodide in-browser playground** (KAN-1490) as a static Zensical
page. If it's not ready, **omit it** (owner: that's fine). Fill the freed space (after the
clone blocks are removed) with a short **"what the code produces"** screenshot per snippet
instead — no dead space, no half-baked playground.

### B4. Fix the notebook naming split

The gallery's chatbot Colab points to `examples/colab/chatbot.ipynb`; the chatbot guide
points to `examples/chatbot_colab.ipynb` — two different notebooks. Pick one canonical
chatbot notebook and link it consistently. Also: `examples/demo.ipynb` and
`smoke_test_rc.ipynb` aren't linked from docs (leave demo.ipynb unlinked or fold it in;
keep smoke_test out of user docs).

### B5. More guides — ideation (plan only)

There's currently one guide (`chatbot.md`). Split future guides by audience, per the
owner's rule: **Colab notebooks = ML / data-analysis focused; standalone apps =
fullstack / business / general.** Candidate guides:

- *Colab / ML-data:* "Stream a Hugging Face model's tokens", "Show a training run live
  (loss curves + KPIs)", "Classify an uploaded image with a small ONNX model", "Visualize
  a dataset (Chart + Table + Heatmap)", "Build a spectrogram/audio-analysis view".
- *Standalone / fullstack-business:* "A dashboard with a Sidebar + KPI tiles", "A data
  explorer (filter/sort/select with Table)", "A form-driven internal tool", "A
  generative-art / poster maker with Download", "A choropleth map (static Plot today,
  interactive Map when G5 lands)".

Don't write them yet — this is the backlog to draw from.

---

## C. New demo ideas — scoped by feasibility

Owner ideas, triaged against §0. Split by audience where relevant.

**Ship on today's primitives (P1):**
- **More maps — Singapore GRC boundaries over time + population.** Official multi-year
  GeoJSON exists on data.gov.sg (2011/2015/2020/2025, WGS84, open licence). A **static
  choropleth per year** via `geopandas.plot()` → `Plot` PNG, with a `Select`/`Radio` for
  year and `Slider`/`Table` for the population overlay, is feasible **now**. Caveat:
  population/electorate is **not** in the boundary files — it's a manual join (EBRC
  electorate counts / SingStat by planning area, approximate name reconciliation). *Data
  prep is the real work; the UI is easy.* Interactive pan/zoom needs **G5** (below).
- **Recipes app (standalone/business).** Forms + `List`/`Gallery` + `Image` + `Card`.
  **No persistence store** (owner, 2026-09-17): ship a **set of built-in templates that are
  always there**, and let users **create their own in-session** using per-session state
  (ADR-0010, exists) — new entries live only until the app refreshes/restarts. Feasible
  today; no store to build.
- **Tic-tac-toe vs an imitation-learned policy (Colab/ML).** 3×3 board = 9 `Button`s in a
  `Grid`, each with its own `on_click`; the policy is user Python. "How many games until
  you can't beat it" is a nice framing. Feasible today. (Owner has ARC/Hanoi projects to
  reuse ML from; the *game env* is small enough to redo.)
- **Tower-of-Hanoi RL visualizer (playback).** Render each state (pegs/disks) as a `Plot`
  or `Image` frame and replay with the **A3 transport-control pattern** (play/pause/step).
  Non-interactive playback is feasible today; **drag-to-move is not** (no pointer/drag
  primitive). Reuse the owner's existing Hanoi solver/agent; indah just renders frames.

**Need one new primitive (P2):**
- **Interactive maps (GRC pan/zoom, markers).** Gap **G5** — owner already approved
  building a bundled client `Map` (Leaflet at build time, like uPlot). Unblocks the
  richer GRC map and any geospatial demo. Static maps work meanwhile.
- **Audio analysis + playback.** Visual works today (Heatmap spectrogram + Plot waveform);
  **playback is G8** (small native `audio` component + shell rebuild). See A6.
- **Markdown notes + knowledge graph (Obsidian-like, standalone).** Notes:
  `Text(markdown=True)` renders; same **templates-plus-ephemeral-in-session** model as
  recipes (no store). The **knowledge-graph view is a GAP** — a force-directed node/link
  graph needs a new visualization component (canvas is blocked; would be a native SVG/graph
  node). Scope the notes app first; treat the graph as a follow-on component.

**Heavier / needs new native interaction (P3) — parked (owner, 2026-09-17):**
The **interactive-grid component is deferred** ("no need for now, revisit some other
time"). That parks the two demos that depend on it:
- **ARC-AGI 1 editor.** A paintable grid of cells with per-cell click + color state is the
  core interaction, which the framework **cannot express today** (no clickable-cell /
  canvas primitive; custom seam can't carry a click coordinate). It needs a new native
  interactive-grid component + shell rebuild — that component would also unlock games and
  pixel editors generally, so revisit it (with an ADR) when ARC is back on the table. The
  owner's existing ARC editor work can inform the data model.
- **ARC-AGI 3 (interactive game env).** Depends on the interactive-grid component above
  plus real-time interaction; heavier than ARC-1. Parked with it.
- **Nav — side menus / top-nav dropdowns.** Approximate today with `Sidebar` + `Tabs`. A
  true dropdown-menu component and **multi-page routing (G7)** are deferred; build only if
  a standalone multi-page app demo justifies them.

---

## D. Public-deployment hardening (new this round)

The Fly app (gallery `/` + each demo under `/<slug>`) is public and unauthenticated, on
(today) a single machine. We should expect abuse. This is a new workstream — recommend an
**ADR (≈0024) + its own slice.**

### Risks

1. **Resource exhaustion / DoS.** SSE streams are long-lived; the async loops
   (chatbot generation, diffusion/training loops) hold CPU/memory. Many concurrent
   sessions accumulate per-session signal state with **no eviction/TTL** today — a cheap
   way to OOM one machine. Opening many streams ties up workers.
2. **Upload abuse.** The image-classifier's `/api/upload` (multipart) is an unbounded-size,
   arbitrary-file ingress → memory/decode pressure, malicious payloads.
3. **Outbound egress abuse.** The chatbot POSTs to a **fixed** Gemini host (fine, keep it
   fixed — never user-controlled). But a **real prettymapp** would make **live OSM calls
   for arbitrary user addresses** → latency, external rate-limits, IP bans, and a proxy/
   SSRF-ish surface. (This is why A8 restricts the public demo to curated locations.)
4. **Cost / bandwidth.** Bandwidth + machine-hours; autoscaling without a cap can turn an
   attack into a bill.
5. **Content / reputation.** LLM output served from our domain (BYOK = the user's key and
   quota, which limits this, but it's still our front door).

### Defenses (layered — cheapest/highest-leverage first)

- **Edge proxy — yes, put Cloudflare (free) in front of Fly.** Fly already terminates TLS
  via its own `fly-proxy`, so we're not un-proxied, but Fly's edge doesn't give abuse
  controls. Cloudflare (free tier) adds: DDoS protection, WAF, **Bot Fight Mode**,
  **rate-limiting rules**, caching for static assets (landing, thumbnails), and it **hides
  the origin IP**. This is the direct answer to "should we have a reverse proxy in front?"
  — Cloudflare in front of Fly is the pragmatic, no-cost layer.
- **App-level rate limiting.** Starlette middleware, per-client-IP token bucket on the
  expensive endpoints (SSE stream start, `/api/event`, `/api/upload`). Read the real client
  IP from `Fly-Client-IP` (or `X-Forwarded-For` behind Cloudflare), not the socket peer.
- **Concurrency + lifecycle caps.** `fly.toml` `soft_limit`/`hard_limit` concurrency per
  machine; a global + per-IP cap on concurrent SSE; an **idle-session reaper (TTL)** and an
  **LRU cap on live session count**; bound each async loop's iterations and total
  generation time.
- **Upload hardening.** Max body size (e.g. 4 MB), content-type allowlist (images only),
  bounded decode, **never persist to disk**, strip metadata.
- **Egress hardening.** Keep the chatbot's outbound host fixed (Gemini only); for
  prettymapp, **no arbitrary live OSM** on the public box (curated/cached — A8); if we ever
  add user-supplied URLs, allowlist hosts.
- **Secrets.** BYOK stays per-session, never logged (already true); **no shared key as an
  open proxy** (round-1 decision holds).
- **Platform limits + observability.** Fly machine memory/CPU limits, a hard **machine-count
  cap** (no runaway autoscale), billing alerts; structured (redacted) logs and an alert on
  sustained high connection counts.
- **Headers.** Security headers + a CSP on the gallery; no directory listing.

### Do we also need nginx / Traefik? — No (owner Q, 2026-09-17)

These are **different layers, not alternatives**, and Fly already covers the reverse-proxy
layer:

- **nginx / Traefik** are reverse proxies *you run yourself* as part of a deployment: TLS
  termination, routing/path dispatch to backends, load balancing, static serving, header
  rewriting, basic rate limiting. They matter when you operate raw VMs and have to build
  your own edge.
- **Fly already gives us that layer.** Fly Machines sit behind **fly-proxy** (Anycast, TLS
  termination, routing to machines, load balancing, health checks), and our **Starlette
  gallery app is itself the router** — it path-dispatches `/<slug>` to each demo via
  `Mount` (`gallery_app.py`). So the nginx/Traefik *function* is already handled by
  fly-proxy + the app. Adding nginx or Traefik in front on Fly would be **redundant** —
  another hop that duplicates fly-proxy.
- **Cloudflare is complementary, not a replacement.** It's a hosted global edge *outside*
  Fly: DDoS absorption, WAF, bot management, edge rate limiting, CDN caching, and origin-IP
  hiding — the abuse controls fly-proxy doesn't give. The chain is:
  **client → Cloudflare (security/CDN edge) → Fly Anycast + fly-proxy (TLS, routing, LB) →
  Starlette gallery app (path routing, app-level rate limit, session caps) → indah demos.**
- **Where Traefik still fits here: local dev only.** `make demo-traefik` +
  `docs/DEV-DOCKER.md` use a machine-wide Traefik to give each local stack an
  `indah.localhost` name — a developer convenience, unrelated to production Fly.
- **One caveat for "hide the origin":** a Fly app still has a directly reachable public IP,
  so to make Cloudflare's origin-hiding real, either front the app with a **Cloudflare
  Tunnel (`cloudflared`)** or have the app **reject requests that don't carry a shared
  Cloudflare secret header** / restrict to Cloudflare IP ranges. Otherwise Cloudflare
  protects the front door while the side door stays open.
- **Rate limiting lives in two places on purpose:** at Cloudflare (edge, blocks abuse
  before it reaches the box — cheapest) *and* in the app (Cloudflare doesn't understand our
  SSE/session semantics, so per-session/connection caps have to be app-level). Both; edge
  first.

**Bottom line:** keep Cloudflare + fly-proxy + the Starlette app. **No nginx/Traefik in
production.**

Sequence: the edge (Cloudflare) + `fly.toml` concurrency caps + upload size limit are
same-day wins; app-level rate limiting + session TTL/eviction are the next slice; egress
curation ties into A8 (prettymapp).

---

## E. Decisions taken (owner, 2026-09-17)

1. **SSE connection dot (A9):** **keep** the per-demo connection-status dot (it shows
   connection health); **remove** the "live" pill + wording from the gallery cards/landing.
2. **Chatbot settings surface (A1):** **`Expander`**. Suggestion chips replace the raw
   status string; the streaming bubble is the status.
3. **Chatbot provider (A1):** **OpenRouter only**, model `Select` defaulting to a free
   model, with DeepSeek + Qwen as cheap paid picks. BYOK (OpenRouter key), no shared key.
4. **Framework investments:** **build G8 audio playback and G5 interactive `Map`** now.
   **Interactive-grid component deferred** (revisit later) → ARC-1/ARC-3 parked.
5. **Persistence:** **no store.** Recipes/notes ship **built-in templates** + let users
   create their own **in-session only** (lost on refresh/restart).
6. **Hardening:** **Cloudflare in front of Fly**, **no nginx/Traefik in production** (Fly's
   fly-proxy + the Starlette app already cover the reverse-proxy layer — see §D). Cloudflare
   + `fly.toml` caps + upload limits first; app-level rate limiting + session TTL next.

---

## F. Proposed slices (draft sequence)

Quick wins and de-clutter first; framework investments gated on §E decisions.

- **R2-1 · Chatbot redesign** — declutter, settings panel, suggestion chips, drop status
  line (A1). No new primitives.
- **R2-2 · Docs for users** — Colab-only gallery table, drop standalone table + Live
  column, remove all clone instructions, fix notebook naming, "live" wording (B1–B4, A9
  wording).
- **R2-3 · Training dashboard mobile fix** — `Row` → `Grid`; verify at 400px (A2).
- **R2-4 · Remove "live" indicators** — card pill + landing prose; shell dot per §E (A9).
- **R2-5 · Image classifier** — pre-loaded pickable samples, immediate results, bundled
  ONNX MobileNet (A5).
- **R2-6 · Stocks rebuild** — demo-stockpeers layout on cached data (A7).
- **R2-7 · Deployment hardening (edge + caps)** — Cloudflare + `fly.toml` concurrency +
  upload limits; then rate limiting + session TTL (§D). ADR-0024.
- **R2-8 · Prettymapp real renderer** — curated/cached locations for the public demo (A8);
  depends on R2-7's egress stance.
- **R2-9 · Diffusion real + controls** — record Runpod frames, play/pause/step (A3).
- **R2-10 · GRC maps (static)** — choropleth per year via Plot; data-join is the work (C).
- **Framework investments (greenlit):** **G8 audio playback** → audio demo (A6); **G5
  client `Map`** → interactive GRC map (C). Interactive-grid component is **deferred**.
- **Backlog / later:** recipes + notes (templates + ephemeral in-session, no store),
  knowledge-graph component, Tower-of-Hanoi visualizer (reuses A3 controls), nav dropdowns /
  multi-page; ARC-1/ARC-3 (parked behind the interactive-grid component).

---

## Status (2026-09-17)

Planning only — nothing built this round yet. Chatbot proposal artifact published and
updated to the decided design. **Owner decisions taken (§E) — ready to slice R2-* into
PRs.** Suggested first cut: R2-1 (chatbot), R2-2 (docs), R2-3 (dashboard mobile), R2-4
(remove card "live"), since none need framework work.
