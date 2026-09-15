# Questions

Statuses: `DECIDED` (user answered) · `ASSUMED` (default taken, correct it if
wrong) · `FORK` (waiting on the user) · `DEFERRED` (not needed this milestone).

Project: **indah** — a Python UI framework for ephemeral cloud notebooks (Colab,
RunPod). See `PLAN.md` for the live plan.

## Open forks

None. The MVP grill round is closed; the post-MVP (Milestone 1) forks were decided
in the 2026-09-15 planning round and are recorded in the register below
(Q-usecase-priority, Q-dynamic, Q-charting, Q-media, Q-design, Q-layout,
Q-theme-switcher).

## Register

| ID | Question | Status | Answer or default | Landed |
|----|----------|--------|-------------------|--------|
| F1 | Real-time transport: WebSocket or SSE+POST? | DECIDED | SSE + HTTP POST, optional WS upgrade (Colab has no WS proxy support) | ADR-0002 |
| F2 | Core programming model? | DECIDED | Reactive signals with granular JSON patches | ADR-0003 |
| F3 | Framework for the pre-built JS shell? | DECIDED | Svelte, bundled in the wheel | ADR-0004 |
| F4 | Hand-written-frontend escape hatch in v0? | DECIDED | Defer tooling; make the JSON protocol a versioned public contract + custom-component seam | ADR-0005 |
| F5 | What does "transition to a real app" mean? | DECIDED | Two exit ramps off the protocol boundary: Composable (primary) + Eject (enabled, not built); north-star priority | ADR-0008 |
| F6 | Should indah own auth? | DECIDED | No — bring-your-own via standard ASGI middleware seams | ADR-0008 |
| F7 | Domain logic vs UI coupling? | DECIDED | Core principle: logic in plain functions indah calls, kept separate from UI | ADR-0009 |
| F8 | State model for external-user production? | DECIDED | Pluggable session-store seam now; only in-memory backend in v0 | ADR-0010 |
| Q-name | Project name and availability? | DECIDED | "indah"; free on PyPI and npm | ADR-0006 |
| Q-docs | Documentation tooling and feel? | DECIDED | Zensical site, FastAPI-grade polish; deferred as build until ~Slice 4 | ADR-0007 |
| Q-user | Primary user and actors? | ASSUMED | AI/ML notebook users first; agents deferred | PLAN §Users |
| Q-scope | Scope boundary for v0? | ASSUMED | See in/out lists | PLAN §Scope |
| Q-data | Core data model and identity? | ASSUMED | UI tree of nodes with stable server IDs; named signals; per-session in-memory | PLAN §Shape (S3, S4), ADR-0003 |
| Q-state | State and storage? | DECIDED | In-process per-session via a pluggable session-store seam; external backend later | ADR-0010 |
| Q-concur | Concurrency and conflict? | ASSUMED | Isolated per-session state; last-write-wins within a session | PLAN §Assumed defaults |
| Q-iface | Interfaces and contracts? | ASSUMED | One ASGI app; JSON protocol is the contract; no CLI in v0 | PLAN §Shape (S1), ADR-0001/0005 |
| Q-fail | Failure behaviour? | DECIDED | Handler error (sync or async) → UI toast + server traceback; session stays live | ADR-0011, Slice V3 |
| Q-deps | External dependencies? | ASSUMED | Starlette/Uvicorn/Pydantic/Svelte, all MIT, offline; optional cloudflared | PLAN §Implementation, ADR-0004 |
| Q-run | Runtime and deployment? | ASSUMED | pip install → launch(); detects Colab/RunPod; Python 3.10+ | PLAN §Shape (S6), ADR-0001 |
| Q-succ | Measurable success? | ASSUMED | Cold start <3s; interaction <150ms local; incremental streaming; no Node; Colab-without-WS | PLAN §... / SLICES demos |
| Q-sec | Security and secrets? | ASSUMED | Dev-tool threat model; no auth in v0; don't log payloads by default | PLAN §Assumed defaults |
| Q-ver | Versioning and migration? | ASSUMED | protocol_version bumped v0→v1 for the append op + error message; shell rejects a mismatch; nothing persisted to migrate | ADR-0005, ADR-0011 |
| Q-agent | Agent-facing control surface? | DEFERRED | Not needed for v0 | n/a |
| Q-auth | Auth / multi-tenant hosting? | DECIDED | Auth via BYO ASGI seams (ADR-0008); multi-tenant hosting still deferred post-v0 | ADR-0008 |
| Q-escape-tooling | Full escape-hatch tooling (scaffold, typed client, HMR)? | DEFERRED | Post-v0; only the protocol seam now | ADR-0005 |
| Q-custom | How does register_component() add a type without runtime Node? | DECIDED | A validated declarative render spec the pre-built shell interprets at runtime; travels on the wire as the `_spec` prop, keyed off the protocol | ADR-0012 |
| Q-market | Component marketplace / plugin distribution? | DEFERRED | Post-v0 | n/a |
| Q-persist | Persistent state / database integration? | DEFERRED | User code owns durable data | n/a |
| Q-children | Dynamic children (grow/reorder a node's child list at runtime)? | DECIDED | Near-term answer is a **data-driven list** (items in one reactive `data` prop, rendered by a shell template — no protocol op), Slice B. A general structural children op (heterogeneous nodes added/removed/reordered) stays DEFERRED until multi-page/dynamic-forms need it (KAN-1396). Supersedes the earlier `repeat`-needs-a-structural-op framing. | ADR-0016 |
| Q-frame-coalesce | Streaming wire overhead: one ~8 KB proxy-flush pad per token frame | DEFERRED | Ship on the current pad for 0.1.0; the chatbot example coalesces tokens in userland as the mitigation. Framework-level coalescing/debounce (or not padding sub-window frames) is a post-0.1.0 optimization; scheduled just before Slice E (streaming chart points amplify it), KAN-1395. | ADR-0002, ADR-0011 |
| Q-usecase-priority | Which use-case half leads post-MVP? | DECIDED | Shared foundation first (layout + list + per-session state), then ML-demo I/O ahead of data-viz (Colab-researcher north star) | PLAN §Post-MVP, SLICES |
| Q-dynamic | Dynamic content: structural protocol op or data-driven list? | DECIDED | Data-driven list first (no wire change); structural op deferred | ADR-0016 |
| Q-charting | Charting: server-PNG, a client lib, or hybrid? | DECIDED | Hybrid — keep server-PNG `Plot` for static, add one bundled client chart for interactive/real-time; no protocol bump | ADR-0018 |
| Q-media | Media I/O and real-time scope? | DECIDED | Upload-and-process now on Tier 0 (SSE+POST, the Colab floor); live video/real-time on Tier 1 (optional WS upgrade, non-Colab) later | ADR-0017 |
| Q-design | Visual language and identity? | DECIDED | "Studio" theme + "Bunga" logo; a design-token layer using Material 3's role architecture but not its look; one theme baked now | ADR-0014 |
| Q-layout | Layout beyond `Column`? | DECIDED | Named container components (Row/Grid/Tabs/Sidebar/Expander) arranging existing children; no protocol change | ADR-0015 |
| Q-theme-switcher | User-selectable themes in the shell? | DEFERRED | One baked theme (Studio) now; a theme is a token-set swap, so a switcher is a cheap later addition | ADR-0014 |

## Coverage

| Category | Covered by |
|----------|-----------|
| Primary user and actors | Q-user |
| Scope boundary | Q-scope |
| Data model and identity | Q-data, F2 |
| State and storage | Q-state, Q-persist, F8 |
| Graduation (prototype to production) | F5, F6, F7, F8 |
| Concurrency and conflict | Q-concur |
| Interfaces and contracts | Q-iface, F1, F4, Q-custom |
| Failure behaviour | Q-fail |
| External dependencies | Q-deps |
| Runtime and deployment | Q-run, F1 |
| Measurable success | Q-succ |
| Security and secrets | Q-sec |
| Versioning and migration | Q-ver, F4 |
| Post-MVP use-case priority | Q-usecase-priority |
| Visual design and identity | Q-design, Q-theme-switcher |
| Layout and dynamic content | Q-layout, Q-dynamic, Q-children |
| Media and real-time transport | Q-media |
| Charting | Q-charting |
