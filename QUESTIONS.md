# Questions

Statuses: `DECIDED` (user answered) · `ASSUMED` (default taken, correct it if
wrong) · `FORK` (waiting on the user) · `DEFERRED` (not needed this milestone).

Project: **indah** — a Python UI framework for ephemeral cloud notebooks (Colab,
RunPod). See `PLAN.md` for the live plan.

## Open forks

None — the grill round is closed.

## Register

| ID | Question | Status | Answer or default | Landed |
|----|----------|--------|-------------------|--------|
| F1 | Real-time transport: WebSocket or SSE+POST? | DECIDED | SSE + HTTP POST, optional WS upgrade (Colab has no WS proxy support) | ADR-0002 |
| F2 | Core programming model? | DECIDED | Reactive signals with granular JSON patches | ADR-0003 |
| F3 | Framework for the pre-built JS shell? | DECIDED | Svelte, bundled in the wheel | ADR-0004 |
| F4 | Hand-written-frontend escape hatch in v0? | DECIDED | Defer tooling; make the JSON protocol a versioned public contract + custom-component seam | ADR-0005 |
| Q-name | Project name and availability? | DECIDED | "indah"; free on PyPI and npm | ADR-0006 |
| Q-user | Primary user and actors? | ASSUMED | AI/ML notebook users first; agents deferred | PLAN §Users |
| Q-scope | Scope boundary for v0? | ASSUMED | See in/out lists | PLAN §Scope |
| Q-data | Core data model and identity? | ASSUMED | UI tree of nodes with stable server IDs; named signals; per-session in-memory | PLAN §Shape (S3, S4), ADR-0003 |
| Q-state | State and storage? | ASSUMED | In-process per-session; no persistence in v0 | PLAN §Assumed defaults |
| Q-concur | Concurrency and conflict? | ASSUMED | Isolated per-session state; last-write-wins within a session | PLAN §Assumed defaults |
| Q-iface | Interfaces and contracts? | ASSUMED | One ASGI app; JSON protocol is the contract; no CLI in v0 | PLAN §Shape (S1), ADR-0001/0005 |
| Q-fail | Failure behaviour? | ASSUMED | Handler error → UI toast + server traceback; UI stays live | PLAN §Assumed defaults, SLICES V3 |
| Q-deps | External dependencies? | ASSUMED | Starlette/Uvicorn/Pydantic/Svelte, all MIT, offline; optional cloudflared | PLAN §Implementation, ADR-0004 |
| Q-run | Runtime and deployment? | ASSUMED | pip install → launch(); detects Colab/RunPod; Python 3.10+ | PLAN §Shape (S6), ADR-0001 |
| Q-succ | Measurable success? | ASSUMED | Cold start <3s; interaction <150ms local; incremental streaming; no Node; Colab-without-WS | PLAN §... / SLICES demos |
| Q-sec | Security and secrets? | ASSUMED | Dev-tool threat model; no auth in v0; don't log payloads by default | PLAN §Assumed defaults |
| Q-ver | Versioning and migration? | ASSUMED | protocol_version from v0; nothing persisted to migrate | ADR-0005 |
| Q-agent | Agent-facing control surface? | DEFERRED | Not needed for v0 | n/a |
| Q-auth | Auth / multi-tenant hosting? | DEFERRED | Post-v0; dev tool behind trusted proxy for now | n/a |
| Q-escape-tooling | Full escape-hatch tooling (scaffold, typed client, HMR)? | DEFERRED | Post-v0; only the protocol seam now | ADR-0005 |
| Q-market | Component marketplace / plugin distribution? | DEFERRED | Post-v0 | n/a |
| Q-persist | Persistent state / database integration? | DEFERRED | User code owns durable data | n/a |

## Coverage

| Category | Covered by |
|----------|-----------|
| Primary user and actors | Q-user |
| Scope boundary | Q-scope |
| Data model and identity | Q-data, F2 |
| State and storage | Q-state, Q-persist |
| Concurrency and conflict | Q-concur |
| Interfaces and contracts | Q-iface, F1, F4 |
| Failure behaviour | Q-fail |
| External dependencies | Q-deps |
| Runtime and deployment | Q-run, F1 |
| Measurable success | Q-succ |
| Security and secrets | Q-sec |
| Versioning and migration | Q-ver, F4 |
