# Demos + Docs Revamp — feedback and plan

Owner feedback captured 2026-09-16. This is the working plan for making the Fly demo
gallery (`indah-demos.fly.dev`) genuinely beautiful, adding real (keyed) example runs,
and reorganizing the docs site (`leejianrong.github.io/indah`). Source of truth for the
revamp until it lands as ADRs + slices.

Related: ADR-0023 (demo hosting: Fly single-app, sub-path mounts), ADR-0007 (Zensical
docs), ADR-0014 (design system + Studio theme + Bunga logo), `docs/POSITIONING.md`.

## Current state (grounding)

- Landing/gallery = a bare inline-HTML string in `deploy/fly/gallery_app.py`
  (`_index_html`): a heading, one paragraph, an emoji card grid. Functional, not
  aesthetic. No hero, no video/GIF, no getting-started, no principles, no comparison,
  no docs link, no favicon.
- Demos are the `examples/*.py` indah apps mounted under `/<slug>` on one Fly machine.
  All run on **mock data** (no live model). Manifest: chatbot, training-dashboard,
  diffusion, poster, image-classify, charts.
- Demos have **no** back-to-gallery affordance and **no** link to source.
- Docs site nav is flat: Home, Gallery, Quickstart, Build a chatbot, Components,
  Custom components, Protocol. Few/no screenshots. Mentions competitors.
- Colab notebooks: confirm they `pip install indah` and lay code out inline (do NOT
  clone the repo). `chatbot_colab.ipynb` exists; audit all.
- Brand assets exist: `assets/brand/favicon.svg`, `indah-mark.svg`, `indah-mark-mono.svg`.

## A. Landing page (`indah-demos.fly.dev/`)

Goal: a beautiful marketing landing page, roughly modeled on Streamlit's, that makes a
first-time visitor understand indah and want to try it within ~10 seconds.

Sections (top to bottom):
1. **Hero** — logo + one-line value prop + primary CTA ("Open a demo" / "Get started")
   and secondary (GitHub, Docs).
2. **Quick video or GIF** — indah spinning up in a Colab and printing a URL; the
   "reactive Python UI, no Node" money shot.
3. **Get started** — the `pip install indah` + ~15-line app snippet, copy button.
4. **Principles** — 3-4 illustrated cards (reactive core, single-port/no-Node,
   built for ephemeral cloud notebooks, streaming). Use small graphics, not walls of text.
5. **Gallery** — cards with **real screenshot thumbnails of each app** (not emoji).
   Each card links to the live demo.
6. **Comparison table** — indah vs Streamlit / Gradio / Reflex, framed to our
   advantages (no Node build, single port, reactive/no full-rerun, runs in transient
   containers). Honest but flattering.
7. **Footer** — GitHub link, Docs link, license.

Also:
- **Favicon = the indah logo** (`assets/brand/favicon.svg`). Currently missing.
- **Playground** (Streamlit-style): an in-page code editor that runs an indah app live.
  Feasibility settled (2026-09-16) after tracing the seam — see below.

### Build technology — recommendation

Options weighed:
- **Static HTML/CSS (+ tiny vanilla JS)** served as the gallery app's `/` index.
  Recommended. The landing is mostly static content; no Node build step (matches the
  no-Node ethos, keeps the Fly deploy simple), full aesthetic control, SEO-friendly,
  fast. Author it as its own file(s), not a Python f-string.
- Svelte + Vite: nicer component ergonomics, but adds a Node build to CI/deploy for a
  single page. Not worth it here (the framework's whole pitch is no-Node-at-runtime).
- indah itself: strong dogfooding narrative, but indah is a reactive *app* framework,
  not a static-content site generator; a hero/video/table page is awkward as an SSE
  app. Reserve dogfooding for the demos and the **playground** (a genuine indah use).

Proposed: static landing page; playground as a separate indah-powered sub-app.

## B. Real (keyed) demo runs

Every demo stays on mock data by default (zero-config, always-on), but offers an
**"add your API key" toggle** to run a real example.

- **Chatbot** — accept a key and chat with a real small model. Candidate free
  providers to evaluate: Google AI Studio (Gemini free tier), Hugging Face Inference
  API, NVIDIA NIM/build.nvidia.com, Groq, OpenRouter free models. Key stays per-session
  in memory, never logged/stored (dogfoods per-session state, ADR-0010).
- **Diffusion** — either a real image API (keyed) or **pre-record generation steps**
  from a real diffusion model and replay them (cheaper, always-on, no key needed).
  Decide per cost/latency.
- Security: keys are user-supplied, held in session state only, redacted from logs;
  clear "your key is used only for this session" note.

## C. Individual demo polish

- **Back to gallery** on every demo: the indah logo (top-left) is clickable -> `/`,
  or a back button. Implement once in the shell/layout so all demos get it.
- **Link to source** on every demo -> the specific `examples/*.py` on GitHub.
- **Live training dashboard** — the big text for step / train+val metrics / LR is ugly.
  Redesign: either compact animated stat cards / sparklines with subtle number
  transitions, or drop the big numbers and let the charts carry it. Prefer small,
  moving, elegant metric tiles over giant text.
- **Chat box stretches as messages arrive (fix).** The `Chat` container (`.chat` in
  `frontend/index.html`, the shell's global `<style>`) uses `max-height: 22rem` with no
  fixed `height`, so it starts collapsed and grows bubble-by-bubble until it finally
  scrolls — off-putting. Fix: `height: 22rem` (fixed) so the space is pre-allocated and
  the box only ever scrolls (autoscroll-to-bottom already exists via the `autoscroll`
  action in `Node.svelte`). Matches ChatGPT/Gemini (fixed message viewport, input below).
  Shell-level -> fixes every chatbot demo at once. Requires `make frontend` (Node) +
  commit the regenerated `src/indah/static/index.html`. Optional follow-up: expose the
  height as a `Chat(height=...)` prop instead of hard-coding 22rem.
- **New demos to add** (model on these Streamlit gallery apps, visually):
  - **Stocks peer analysis** — cf. https://demo-stockpeers.streamlit.app
  - **Prettymapp** (pretty map generator) — cf. https://prettymapp.streamlit.app

## D. Docs (`leejianrong.github.io/indah`)

- **Reorganize** into clear sections (research proper IA; candidate grouping:
  Getting started / Guides / Components reference / Concepts / Reference/protocol).
  Current nav is a flat list.
- **Remove all competitor mentions.** Docs focus purely on indah and how to build with
  it; comparisons live only on the landing page.
- **More screenshots** — minimally show what each code sample produces. Stretch: link
  to / embed the playground.
- **Colab & all demos**: `pip install indah` and show code inline in the notebook.
  Never clone the repo. Audit every notebook.

## E. Cross-cutting

- Record this feedback (done: this doc + memory).
- Independent critique: a fresh, indah-naive subagent reviews landing, docs, demos, and
  the GitHub README (visually where possible) for anything unfriendly/unpersuasive and
  any cross-property discrepancies. (Running.)

## Decisions (owner, 2026-09-16)

1. **Landing tech = static HTML/CSS (+ vanilla JS).** indah-itself is ruled out. Plain
   HTML/CSS fully covers the media needs: `<video muted autoplay loop playsinline>` for
   the hero clip, `<img>` for GIF/WebP/APNG, `<picture>` for responsive/screenshots — no
   framework needed. Svelte+Vite is not justified for one page. Author as real
   `.html`/`.css` files served by the Fly gallery `/` route (not a Python f-string).
2. **Keyed chatbot = bring-your-own-key, provider-agnostic plumbing.** Primary default
   for generosity + availability: **Google AI Studio (Gemini Flash)** or **Groq** —
   both large free tiers; keep the client swappable so we can point at whichever holds
   up. Ship BYOK + clear "get a free key" instructions.
   - **Do NOT embed the owner's own key as an open public proxy.** Server-side it won't
     *leak* the key, but it becomes an unauthenticated free proxy anyone can hammer:
     quota exhaustion, prompt abuse, ToS risk, and cost risk if a model ever tips paid.
     Default to BYOK + instructions. A shared key is only acceptable later behind strict
     per-session/IP rate limiting + a hard cap + free-models-only — a separate, deliberate slice.
   - **Secure key input needs a small component addition.** `TextInput` has no masked
     mode (renders `<input type=text>`). Add `TextInput(password=True)` (or a thin
     `SecretInput`) -> `<input type=password>`. Real security is server-side: hold the
     key in session state only (ADR-0010), never echo it in a reactive prop, never log it.
3. **Diffusion = pre-recorded real denoising steps, replayed.** No key, always-on, no
   per-run cost.
4. **Playground = feasible; do the cheap one now, spike the good one.** The seam is
   clean: `protocol.py` (`init_message`/`patch_message`) emits plain JSON dicts with no
   network knowledge, `Session.dispatch()` returns `.changes`, and `transport.py` (Hub /
   SSE / POST) is only the carrier. All deps are pure Python (micropip-installable).
   Graded options:
   - **Server-side arbitrary-code playground — feasible but rejected.** User Python on
     our box = RCE-as-a-service; needs gVisor/nsjail/per-session containers + caps. Not
     worth the security/ops on one Fly machine.
   - **Pyodide in-browser playground — feasible, recommended as a spike.** Run the whole
     Python core in a Pyodide worker (`micropip install indah`, `exec` the user app to
     build a `Session`, emit `init_message`, pipe frames to the existing Svelte shell over
     `postMessage`, feed shell events back into `session.dispatch`). **No server exec = no
     RCE.** This is the real Streamlit-playground UX. NOT the "full WASM rewrite" ADR-0023
     parked: keep the Python core AND the Svelte shell; only write a `postMessage`
     transport shim replacing `fetch`/`EventSource`. Real spike (~days): async/streaming
     edge cases, micropip boot (~seconds), bundle size — lazy-load on interaction. Great
     dogfood ("indah runs client-side in your tab").
   - **Code + live-preview pairing (no exec) — ship now.** Source shown next to the
     already-deployed running demo + a few switchable variants. Zero risk; doubles as the
     docs "show what the code produces" win.
   Plan: ship the pairing now (folds into the docs slice); roadmap the Pyodide spike.

## Independent critique findings (indah-naive reviewer, 2026-09-16)

A fresh reviewer inspected all four properties (gallery HTML, docs, live demo SSE trees
+ a real chatbot round-trip, README). The transport genuinely works (tokens streamed
live). Highest-value findings — several are **urgent factual bugs**, cheap to fix and
separable from the big redesign:

- **"Hosted gallery is coming" is stated in 3 places, all wrong / contradictory.**
  README says "coming (Hugging Face Spaces)"; docs gallery says "coming (Fly.io)";
  reality: it's **live** at `indah-demos.fly.dev`. And **nothing links to the live
  gallery** — README/docs only link out to GitHub. Pick one true story; link in.
- **Docs Components page is a full milestone behind.** It documents only the 10-item
  starter set and **none** of: Chart, Heatmap, Table, Stat, ImageOverlay, Sidebar, Grid,
  Card, Radio, Upload, Download, Progress, Spinner, Chat — all shipped in 0.2.0 and used
  by live demos. Docs make the product look half as capable as it is. (Docs even
  self-contradict: home banner says charting shipped; Components page predates it.)
- **Chatbot demo contradicts itself:** header says "a small local LLM" but output is a
  mock echo ("This is a mock reply… Pass a real model to chat_stream()").
- **3 of 6 demos are mocks (chatbot, image generation, image classifier) with no
  card-level disclosure** — the two most "AI" framings are the fakest. Add a
  "mock — swap in your own" badge; fix contradictory headers.
- **No back-to-gallery or view-source link on any demo** (confirms C above).
- **Every demo tab `<title>` is identical ("indah")**; gallery is "indah demos". Give
  each a distinct title for tabs/bookmarks/SEO.
- **Landing page has no pitch, no `pip install`, no docs link, no CTA** — one GitHub
  link, dead-ends into six demos. Fails the 10-second "why care" test.
- **Branding split:** gallery landing is flat `system-ui`; demos use the Studio serif +
  Bunga theme + favicon. Front door doesn't look like the product.
- **README:** no live-gallery link, no badges (PyPI/license/CI/Python), status banner
  reads as changelog not benefit; lead with a screenshot/GIF. Demo names drift across
  README/docs/gallery (e.g. "Streaming chatbot" vs "Streaming LLM chatbot"). `pip
  install indah`, version 0.2.0, and `requires-python` are consistent (good).

### Quick factual fixes (do first — cheap, high-trust, mostly independent of the redesign)

1. Replace all "hosted gallery is coming" copy (README + docs) with the live Fly URL;
   link the gallery from README top, docs home, docs gallery.
2. Bring the docs Components page up to 0.2.0 (add the 14 missing components).
3. Fix the chatbot demo's "small local LLM" header (it's a mock until keyed).
4. Give each demo a distinct `<title>`.
5. Add README credibility badges (PyPI, license, CI, Python).
6. Canonicalize each demo's name across README/docs/gallery.

## Rough slicing (draft)

- Slice 1: Static landing page (hero, video slot, get-started, principles, comparison,
  gallery grid w/ screenshot thumbnails, favicon, footer) — replaces `_index_html`.
- Slice 2: Demo shell polish — clickable logo back-to-gallery + source link, shared.
- Slice 3: Training dashboard metric redesign.
- Slice 4: Keyed real runs (chatbot first) + session-state key handling.
- Slice 5: New demos — stocks peer analysis, prettymapp.
- Slice 6: Docs IA reorg + de-competitor + screenshots.
- Slice 7: Diffusion real/replay.
- Slice 8 (stretch): Playground.

## Status (2026-09-16)

Landed on `main` (each its own squash-merged PR):

- **#56** Chat box fixed-height scroll viewport (no more stretch).
- **#57** This plan doc + factual fixes: live-gallery links (README/docs), Components
  reference up to 0.2.0, canonical demo names, chatbot header, README badges.
- **#58** Demo shell chrome: clickable logo -> gallery, view-source link, per-demo
  `<title>` (via `create_app(title=/home_url=/source_url=)`, wired per demo in the gallery).
- **#59** Training dashboard: `Stat` KPI cards instead of the big metric string.
- **#60** Docs de-competitored (comparisons live only on the landing page now).
- **#61** Landing page rebuilt: hero, get-started, principles, gallery grid, comparison
  table, on-brand Studio theme + Bunga favicon (in `deploy/fly/landing.html`).
- **#62** Colab demos: `pip install indah` from PyPI + full source inline (no clone/wget).
- **#63** Docs nav grouped into Get started / Guides / Reference.

Not the live site yet: the landing page, demo chrome, dashboard, and chat fix reach
`indah-demos.fly.dev` only after a **Fly redeploy** (owner step), and PyPI users need a
**0.2.1** (owner: PyPI token). Batch the chat fix + this wave into one 0.2.1.

Remaining — needs a decision or an asset I can't produce solo:

- **Keyed real chatbot (BYOK).** Needs: a `SecretInput`/`TextInput(password=True)`
  component (buildable now), a provider choice (most free usage/availability), and a real
  key to test. Decision: provider + confirm BYOK-only (no embedded shared key).
- **New demos (stocks peer analysis, prettymapp).** The owner referenced specific
  Streamlit apps to match *visually*; building blind risks missing the mark. Need the
  owner's eye or acceptance of a mock-data interpretation.
- **Real screenshots** (gallery thumbnails currently styled placeholders) and a **hero
  video/GIF** — need browser/screen capture.
- **Diffusion pre-recorded real steps** — need a real diffusion run to record frames.
- **Playground** — Pyodide spike, roadmapped.
