# Plan: enhancements requested by semula

- Status: **Approved 2026-10-19 and in progress.** Cards are filed on board IND as epics
  IND-E19..E26 (label `semula`). See "Progress" below for what is built and where the build
  differs from this plan.
- Date: 2026-10-19 (indah 0.2.2, `main` at `1365d95`)
- Scope: the 15 requested items (E1-E8 local MVP, H1-H7 hosted) for semula's dashboard.
- Method: `plan-new-project`, one round. The forks that need the owner are in section 6, each with a recommendation. Everything else is stated as a default and marked `ASSUMED` where it matters.
- "Existing no decisions are open this round" is applied throughout: where a request conflicts with an ADR, section 4 names it and proposes an amendment or a superseding ADR.

## Progress (updated as slices land)

| Epic | Slice | State |
|------|-------|-------|
| IND-E19 | S0 mount, context, theme | **Done** (PRs #106-#109) |
| IND-E20 | S1 live push + live log | **Done** (PRs #110-#114); `make demo-semula` |
| IND-E21 | S2 overlays + pending queue | **Done** (PRs #116-#122); `make demo-pending` |
| IND-E22 | S3 big tables, panes | **Done** (PRs #124-#127); `make demo-entries` |
| IND-E23 | S4 routing | **Done** (PRs #128-#130); `make demo-routes` |
| IND-E24 | S5 editors, dynamic rows | In progress (IND-108 JsonTree, IND-109 Diff, IND-110 keyed `List` done; IND-112 demo next; IND-111 held for Q4) |
| IND-E25 | H-A identity | Not started (gated by Q1 checkpoint after S3) |
| IND-E26 | H-B authz, secrets, hardening | Not started |

Where the build differs from the plan text below: the context ADR is **0025**, push is
**0026** and Table v2 is **0027** (as planned); app theming became an **amendment to
ADR-0014**, not a new 0031; the additive-change rule is an amendment to ADR-0005; IND-29
and IND-75 are closed as superseded; Table search/column toggle/follow are client-only
and `Table` gained `search=`, `column_toggle=`, `follow=`.
`LaunchHandle.stop()` used to leave uvicorn running while an SSE stream was open (IND-123,
fixed with `timeout_graceful_shutdown`); the browser e2e that needs a real restart still kills a
subprocess.

## Q1 checkpoint (2026-10-20, after S3): numbers for the stay-or-leave call

Scored against the section 8 criteria with what runs today. The plan names no numeric
thresholds ("your thresholds"), so this records the numbers and a read, and the owner decides.
Everything here is **local**: no gateway, one machine, demo data. Nothing is measured on the
hosted path yet.

| Criterion | Measured | Read |
|-----------|----------|------|
| Server memory per open tab | 7 to 22 KB per session (reactive graph + hub, no socket), over 300 sessions of each demo: log 14 KB, pending 22 KB, entries 7 KB, routes 13 KB. Excludes per-tab rows held by a `ctx.tail` Stream (up to its limit) and the hub's 512-message history | Small for hundreds of tabs. The per-tab row copies and history are the real cost to measure under load. Browser-side memory not measured |
| p95 interaction latency | POST `/api/event` to the patch on the SSE stream, 300 samples: p50 1.6 ms, p95 3.5 ms, max 5.6 ms on localhost | Says nothing about the gateway; the Colab proxy added round trips that ADR-0013 exists for. Needs the same probe through the real gateway |
| Bundle growth vs plan | Shell 502 KB raw / 219 KB gzip, from 460 / 208 KB (+9% raw, +5% gzip) for overlays, toasts, shortcuts, tables (remote, virtual), panes, routing, JsonTree and Diff. `CodeEditor` (the +80% item) is not built | Well under the plan's worst case |
| Effort vs estimates | S2 (20 pts), S3 (15), S4 (10) and the JsonTree/Diff half of S5a (8) delivered at their planned points, 15 cards plus one bug (IND-123), as PRs #116 to #132 | On plan in points. Calendar days are not tracked here |
| Screens wanting something the set lacked | Six gaps surfaced while building the three demos, each fixed in its slice: `Link(to=)` as a callable, `Table(density=)` as a signal, no untracked read in the switcher effect (`peek` existed), single-segment deep links resolving `api/*` wrongly, `LaunchHandle.stop()` with an open stream, a sort whitelist for SQL | None blocked a screen. Two are gaps a SPA does not have (pages run their reactive code even when hidden; select-all on a remote table covers loaded rows only) |

Still true from section 8, not changed by building: every interaction is a round trip, state
lives per tab on the server, authorization stays in-process and hidden pages are in the
snapshot, and there is no optimistic or offline UX. IND-E25 and IND-E26 remain gated on the
owner's decision; nothing in the build so far argues for leaving, and nothing yet argues for
committing to H2b or H4 either, because the gateway numbers are missing.

## Summary

- Nothing on the list is already possible in the form semula needs. Seven items have a real userland workaround (section 1), but each one drops something the dashboard needs (tab isolation, large payloads, focus safety).
- The mount at `/ui` works today (I ran it: `Mount("/ui", create_app())` serves `/ui/`, redirects `/ui`, and the shell's relative URLs resolve). **It breaks for any path deeper than `/ui/`**: `/ui/projects/auth/entries/01J` is a 404, and relative `api/...` URLs would resolve wrongly even if it were served. That is the E4 blocker, and it is cheap to fix early (S0).
- I found one existing bug that hits semula on day one: after a server restart an open tab reconnects with a `Last-Event-Id` larger than the fresh hub's offset, and `Hub.replay_since` treats it as "already current", so the tab is never re-sent an `init` snapshot (section 2.0, S0). Per repo convention it gets a failing test first.
- No item needs a `protocol_version` bump under the current rule (section 2.0). The first plausible bump is a structural children op, which I recommend not building.
- Order: I keep E1 then E2 first, but put a small foundations slice (S0: mount, `Context`, resume fix, E8 theme) ahead of them, move E5 ahead of E3 (the pending queue needs a drawer and a toast, not an editor), and split E3 so the heavy code editor lands last.
- Total for E1-E8 plus foundations: about 36 engineer-days (7 weeks, one engineer working with agents), 99 points. First usable drop for semula (S0+S1, the live log) is about 2.5 weeks in.

---

## 1. Readiness verdict

Verdicts: **F** = needs framework work, **U** = possible in userland today (workaround given), **A** = already possible. Sizes are mine (S about 1 day, M 3-4, L 6-10), engineer-days in brackets.

| ID | Verdict | Evidence | Workaround today, and what it costs | My size |
|----|---------|----------|-------------------------------------|---------|
| E1 Push channel | **F** (U with caveats) | `Hub` is created per session in `InMemorySessionStore.get_or_create` (`session_store.py:118`); `SessionStore` has `get/get_or_create/discard` only, no enumeration. A task can push into one *known* session via `app.state.store.get(sid).hub`, but cannot find all sessions. ADR-0010. | (a) `create_app(session=...)` shares one `Session` across tabs: every tab updates, but selection/tab/filter state is shared too, so isolation is lost. (b) The factory appends each new `Session`'s signals to a module-level `WeakSet`; a background task sets them on the event loop. Works, but there is no teardown hook (`discard` only cancels tasks, `session.py:218`) and signals are not thread-safe (`reactive.py` docstring). | M [3.5] |
| E2 Table v2 | **F** | `Table` (`components.py:1085`) takes `page_size`, `selected: Signal[int]`, `label`. Sort and paging are client-side (`Table.svelte`); ADR-0021 "As built" says server-side events were **not** built. Rows are `list[list]`, selection is a row index, all rows render (no virtual scroll), `append` cannot reach `data.rows` because the shell only concatenates a top-level array prop (`App.svelte:43-55`). **Confirmed: there is no filter prop**, despite the IND-68 title. | Server-side paging works today with plain signals: a `TextInput` filter, a `Select` sort, Prev/Next `Button`s, a computed that slices a list into `Table(page_size=0)`, and a closure mapping row index to ULID. 50 rows per page, no virtual scroll, no streaming. For the log, `List` with a render-spec template and `items.set(items.value[-200:] + [row])` works to about 200 rows and 2 updates/s (each update re-sends the whole list). | L [7] |
| E3 Editors and viewers | **F** (U for textarea and read-only) | `TextInput` is `<input>` (`components.py:194`). `textarea` is already in `ALLOWED_TAGS` (`protocol.py:81`), so `custom("textarea", ...)` with `bind` + `on` works. `Text(markdown=True)` renders fenced code (`markdown.py`). | Multiline: a registered `textarea` custom component. **Untested by me**, and it has no ADR-0013 focus ownership (`Custom.svelte` binds props unconditionally), so a laggy echo can clobber typing. Read-only JSON/diff: fenced code in `Text`. No folding, colour, or side-by-side. | L [8] |
| E4 Routing | **F** (U for nav) | Shell has no `history` integration. `apiUrl()` resolves against `location.href` (`api.js:7`); `serve_file` returns relative `api/file/...` URLs (`session.py:125`); the app has only `GET /` (`app.py:509`). I ran `/ui/projects/auth/entries/01J` -> 404. | In-app navigation with `Sidebar` + `Tabs`/signal (no URL, no back button, no deep link). | M [4] |
| E5 Overlays, small controls | **F** | Only an error toast exists (`App.svelte:62`, message type `error`). No modal, drawer, badge, switch, tooltip, shortcuts. | Two-step confirm (a `Button` that reveals a second `Button` via a signal); `Expander` for inline detail. Nothing for toasts from handlers except raising an exception. | M [4] |
| E6 Panes, density | **F** | `Sidebar`, `Row`, `Grid`, `Expander` only (ADR-0015); no drag. | `Sidebar` for a fixed master-detail. | S [2] |
| E7 Dynamic children | **F** (U display-only) | `List` (ADR-0016) shipped, and `Q-children` defers the structural op. Template events post only `{value}` with the **list's** node id (`Custom.svelte:23`), so a row cannot tell which item fired. IND-29 as titled is the deferred structural op. | A `List` replaced whole per change renders a message stack. Editable rows (tool-call editor) are not possible: no per-item events. | M [3] |
| E8 App theme tokens | **F** (partial) | Tokens are plain CSS variables in `frontend/index.html:23-70`. `create_app` already takes `title`, `home_url`, `source_url` (`app.py:470-472`). A light/dark/system toggle **already shipped** (ADR-0014 amendment); only a user-selectable *theme switcher* and per-app overrides are missing. | None without forking the shell. | S [1.5] |
| H1 Identity in context | **F** | `session_factory: Callable[[], Session]` (`app.py:466`). The browser mints the sid (`api.js:28`). An id-less request falls through to the shared `"default"` session (`app.py:87`, `670`). Nothing ties a sid to a principal. | A Starlette `AuthenticationMiddleware` in front sets `scope["user"]`, but nothing inside indah can read it when building a session, and any holder of a sid can use it. | M [5] |
| H2 Login and protection | **F** (U for login) | ADR-0008: no auth in indah, bring-your-own via ASGI. No Origin/CSRF check on `/api/event` or `/api/upload` (`app.py:709`, `742`). Multipart upload is a CORS "simple request", so it is CSRF-able on a cookie-auth deployment. | Login is fully doable outside indah (authlib in a parent app). The guard and the session binding are not. | M [3] for guard + seams, L [8] for an OIDC module |
| H3 Authorization | **F** (depends on H1) | The factory cannot see the user (H1). | After H1 most of it is plain Python in the factory. | S/M [3] |
| H4 External store | **F** | The seam exists (ADR-0010) but is "id in, handle out" with a live `Session`/`Hub` pair, which cannot be serialised: signals are anonymous closure objects. `Hub` offsets and history are process-local. | Sticky sessions on the gateway plus in-memory (section 6, Q7). | L [10] |
| H5 Hardening in core | **F** (U: copy gallery code) | `_SecurityHeadersMiddleware` and `_RateLimitMiddleware` live in `deploy/fly/gallery_app.py:159,185`, not in the wheel. **Correction: connection caps and CSP are not "moves"**: the connection cap is `fly.toml` config and the CSP is explicitly deferred in ADR-0024. `request.json()` and `request.form()` have no size cap except `max_upload_mb`. | Copy the gallery middleware. | M [4] |
| H6 Secret and token UI | **F** (partial) | `TextInput(password=True)` masks input only. A revealed secret set through a signal is stored in `Hub._history` (512 messages) and replayed on resume. Token list is `Table` + `Badge` + row actions once E2/E5 land. | Show the secret in a `Text` once. It stays in the hub history and in the init snapshot. | S/M [2] |
| H7 Base path, proxy | **A** for base path, **U** for the rest | Base path under a `Mount` works (`tests/integration/test_gallery_mount.py`). The gallery limiter trusts `Fly-Client-IP`/`X-Forwarded-For` unconditionally (`gallery_app.py:195`), which is spoofable once the origin is reachable (ADR-0024 says it is). | uvicorn `--proxy-headers --forwarded-allow-ips` for client IP and scheme; an ASGI middleware for the audit log. | S [1.5] |

### Corrections to the request

1. **E1.** "Nothing outside a session can push in" is slightly too strong: a task can publish into one known session through the store. What is missing is enumeration, fan-out, and lifecycle.
2. **E2.** Confirmed the `Table` has no filter. Also note a second gap: rows have no keys, and `append` cannot target rows nested inside `data`.
3. **E4.** IND-75 is a *decision* card ("multi-page routing - DECISION"); this plan is the decision (ADR-0029 below). The routing mechanism must also fix the base-URL problem above, which the request does not mention.
4. **E7.** IND-29 predates ADR-0016 and as titled asks for the structural children op that ADR deferred. I propose retitling it (keyed `List` with item events) rather than building the op.
5. **E8.** "Theme switcher is deferred in ADR-0014" is stale: light/dark/system shipped in the 2026-09-16 amendment. What is deferred is a *theme* switcher; E8 (per-app token override) is a different, smaller feature.
6. **H5.** See the table: only rate limiting and baseline headers exist, and they are deploy code.
7. **Live data volume.** `Q-frame-coalesce` is listed `DEFERRED` in `docs/QUESTIONS.md`, but `sse_events` already coalesces a queued burst and pads to the next window boundary (KAN-1395, `app.py:101-140`, `640-662`). The register is stale. What is still missing is *time-based* coalescing of rows published from background tasks (section 2.E1).
8. **Restart bug (not in the request).** See section 2.0.

---

## 2. Design sketches

### 2.0 Shared pieces

**`Context`.** One object handed to the session factory, replacing the zero-argument call. It is where E1, E4, E5, H1 and H3 hang their per-session behaviour, so I define it once.

```python
@dataclass
class Context:
    sid: str
    user: Principal | None  # H1
    conn: ConnectionInfo  # frozen copy of headers, cookies, client ip, initial path
    app: Starlette
    path: Signal[str]  # E4

    def toast(self, message: str, *, kind="info", ttl=4.0) -> None: ...  # E5
    def latest(self, topic, *, initial=None) -> Signal: ...  # E1
    def tail(self, topic, *, limit=1000) -> Stream: ...  # E1
    def on_close(self, fn: Callable[[], None]) -> None: ...
    def can(self, perm: str) -> bool: ...  # H3
```

`create_app(session_factory=...)` accepts `()` or `(ctx)`; arity is checked once with `inspect.signature`, so every existing factory keeps working. ADR-0009 holds: `ctx` is for the UI-building layer; domain logic stays plain functions that take plain values.

**Session-store seam.** The protocol is "id in, handle out" (`SessionStore.get_or_create(session_id)`). I change it to `get_or_create(session_id, ctx_info=None)`, add `SessionHandle.owner: str | None`, add `store.discard_where(owner=...)`, and make `discard` call a new `Session.close()` that cancels tasks **and** runs `on_close` callbacks (today it only cancels tasks). All new parameters default to the current behaviour. This is an amendment to ADR-0010, and the base for E1, H1 and H4.

**Resume bug (S0).** `_stream` computes `replay = hub.replay_since(last_event_id)` and sends `init` only if `replay is None`. After a restart the store creates a fresh `Hub` (offset 0); a reconnecting `EventSource` sends `Last-Event-Id: 500`; `replay_since(500)` returns `[]` ("already current", verified by running it), so `init_payload` is `None` and the tab keeps a stale tree. Fix: the hub carries a random `epoch` and event ids become `<epoch>-<offset>`; a mismatched epoch forces an `init`. Plain integer ids stay accepted for tests and old clients. This also removes the multi-replica hazard in H4. Write the failing test first (`tests/integration/test_streaming.py`: restart, reconnect with a high id, expect `init`).

**Protocol versioning (no bump needed).** ADR-0005 bumps `protocol_version` "when the wire format changes in a way an older shell could not parse". Every change below is additive and ignorable by an older shell, as `_spec`, charts, tables and maps were: new component types and props, a `toast` message type (`applyMessage` already ignores unknown types), a `trim` key on an `append` change, a `<epoch>-<offset>` SSE id, new routes. The shell ships inside the same wheel as the backend, so skew only occurs with an ejected or third-party client. I recommend writing this rule down in ADR-0005 (amendment) and documenting each addition in `docs/protocol.md`. Bump to **v2** only for (a) a structural children op, (b) making the signed-session handshake mandatory for all apps, or (c) any change to an existing field's meaning. None is in this roadmap. If you prefer to bump once up front to be safe, say so (section 6, Q2).

### 2.E1 Server push channel

```python
# indah/push.py
class Topic(Generic[T]):
    def __init__(self, name: str, *, replay: int = 0): ...
    def publish(self, item: T) -> None             # on the event loop
    def publish_threadsafe(self, item: T) -> None  # from any thread (call_soon_threadsafe)
    def recent(self, n: int | None = None) -> list[T]
    subscriber_count: int

class Stream(Signal[list]):                        # append-only reactive list
    def __init__(self, items=(), *, limit: int = 1000): ...
    def append(self, *rows) -> None                # emits an append patch, trims to limit
    def clear(self) -> None
```

```python
log = Topic("log", replay=1000)  # app level; semula's core publishes to it


def build(ctx: Context) -> Session:
    rows = ctx.tail(log, limit=1000)  # Stream, seeded from log.recent(), per tab
    selected = Signal(None)  # still per tab
    return Session(Table(rows=rows, key="id", selected=selected, columns=LOG_COLS))
```

- `ctx.latest(topic)` is a `Signal` holding the last item (badge counts). `ctx.tail(topic)` is a `Stream`. Both subscribe on creation and unsubscribe via `ctx.on_close`, so the store's eviction and `discard` clean up. `Topic.subscriber_count` makes a leak testable.
- Delivery runs on the event loop with no dispatch sink active, so it takes the existing live path (`Session._emit` -> `hub.publish`), the same path async handlers use. Sync dispatch cannot interleave because it never awaits.
- **Protocol/shell:** the shell already concatenates arrays on `append`. Add `trim` so a long tail stays bounded in the browser: `{"target": id, "append": {"rows": [...]}, "trim": {"rows": 1000}}`.
- **Coalescing (answers `Q-frame-coalesce`).** `Session.emit_append` buffers per `(node, prop)` and flushes on a 100 ms timer (`call_later`), or immediately before any non-append publish so order is preserved. At 40 events/s of about 350 B rows that is 14 KB/s of payload in at most 10 frames/s. With the proxy-flush padding to the next 8 KB boundary (the frames are 100 ms apart, so the queue-drain coalescing in `sse_events` will not merge them) the worst case is about 80 KB/s per tab, versus roughly 330 KB/s without time coalescing. Add `create_app(proxy_flush=True)` as a knob: semula's local container sets `False` and pays only payload plus framing; the default stays `True` so Colab keeps working. Hub history (512 messages) then covers about 50 s of resume at 10 frames/s; a longer gap falls back to an `init` with the capped list (about 1000 rows).
- **Cross-replica fan-out** is out of scope until H4; the `Topic` class is the seam a Redis pub/sub backend replaces.

### 2.E2 Table v2

```python
Table(rows=stream_or_source, columns=[...], key="id", selected=Signal | None,
      checked=Signal[list] | None, query=Signal[TableQuery] | None, total=Source | None,
      actions=[RowAction(...)], follow=False, page_size=0, label="")
Col("result", title="Result", kind="badge", tones={"hit": "ok", "miss": "warn"}, sortable=True)
Col("id", kind="mono", width="12ch"); Col("ts", title="When", kind="time"); Col("score", kind="number")
RowAction("Delete", on=lambda key: delete(key), confirm="Delete this entry?")
@dataclass class TableQuery: search: str = ""; filters: dict = {}; sort: tuple | None = None; offset: int = 0; limit: int = 50
```

- **Backward compatible.** `Table(source, page_size=, selected: Signal[int])` behaves as today (index semantics) when `key` is not set. New props are additive on the `table` node: `rows` (list of dicts), `columns` (specs), `rowKey`, `total`, `query`, `checked`, `actions`, `follow`, `density`. I recommend extending `Table` rather than adding `DataTable` (section 6, Q8).
- **Cell renderers** are shell-side, closed set, no HTML: `badge` (tone map), `mono` (truncate + tooltip), `time` (ISO or epoch ms, shown relative, refreshed by one 1 s timer shared by all cells), `number`, `text`.
- **Three data modes, one component.** (1) *Static*: as today, client sort/filter/page. (2) *Streaming*: `rows=Stream`, append + trim, optional `follow` (auto-scroll to newest; pauses while the user scrolls up), client-side search/filter over the rows in memory (at most the stream limit). (3) *Remote*: the shell debounces (150 ms) and posts `query {search, filters, sort, offset, limit}`; `Table.handle` writes the `query` signal; the app loads that window and sets `rows` and `total`. History beyond the tail uses this mode against semula's 50k-row store.
- **Virtual scroll** (remote and large static): fixed row height per density, a spacer of `total x rowHeight`, window fetched when the viewport is within one page of the edge, a small LRU of fetched windows to avoid flicker. Keyed `{#each}` so streamed rows create only new DOM.
- **Row actions, multi-select, column toggle:** actions post `action {name, key}`; checkboxes bind `checked` (list of keys); column visibility is client-local, persisted in `localStorage` keyed by the table's label. Sticky header is CSS.
- **Not building:** AG Grid or any grid library (ADR-0021 rejected that, and measurement in 2.E3 shows why), cell editing, grouping, pivot.

### 2.E3 Editor and viewer family

```python
TextArea(value: Signal[str], *, rows=6, mono=False, label="", placeholder="",
         debounce_ms=250, max_chars=1_000_000, read_only=False)
CodeEditor(value: Signal[str], *, language="json", read_only=False, lint=True, height="24rem")
JsonTree(value: Source, *, expanded=1, search=True)          # object or JSON text, read-only
Diff(a: Source, b: Source, *, mode="split", normalise="json", context=3, labels=("incoming", "candidate"))
```

- **TextArea** is native `<textarea>`, zero bundle cost, two-way, **focus-owned per ADR-0013** (extend that rule; add a browser e2e like the existing two). Large bodies: the shell debounces and flushes on blur, and the server gains `max_event_bytes` (default 2 MB; today `request.json()` is unbounded) in the same story.
- **JsonTree** is a small own Svelte component (collapse, expand-to-depth, copy path, text search); no dependency.
- **Diff is computed in Python** with stdlib `difflib.SequenceMatcher` over pretty-printed, key-sorted JSON (or raw text), producing hunks `[{t: eq|del|add|chg, a: [n, text], b: [n, text], inline: [[s, e], ...]}]` that the shell renders side by side or unified with plain DOM. No JS diff library, testable in pytest, and the same function can render semula's "why this matched" tokens. Capped at 5k lines (shows the first 5k with a notice); worst case is quadratic.
- **CodeEditor is the expensive one.** I measured CodeMirror 6 (MIT, as are its json/yaml/merge packages) with esbuild minify in a scratch directory, tree-shaken, no `basicSetup`:

  | Bundle | Raw | gzip |
  |--------|-----|------|
  | Current shell `index.html` (fonts, uPlot, Leaflet included) | 460 KB | 208 KB |
  | CM6 slim: view, state, commands, language, lint, lang-json, lang-yaml | +367 KB | +122 KB |
  | CM6 with `basicSetup` | +430 KB | +142 KB |
  | `@codemirror/merge` alone (not needed, see Diff) | +255 KB | +84 KB |

  Inlined, the editor adds about 80% to the shell for **every** app's first load, and the shell is inlined into one file by `vite-plugin-singlefile`. Recommendation: build it as a **second static file** (`static/editor.js`) loaded with `import()` on the first `codeeditor` render, served from the same origin by an indah route, so the wheel grows by about 120 KB compressed while apps that never use it pay nothing. This is a small wording change to ADR-0004 ("fetches nothing at runtime" becomes "nothing from a third party"). **Gate:** keep `TextArea` + `JsonTree` + `Diff` as the first deliverable (they cover every screen except syntax highlighting and folding) and build `CodeEditor` only after the entry-editor demo shows `TextArea` is not enough (section 6, Q4).

### 2.E4 Routing and deep links

```python
Router(routes={"/": home, "/projects/{project}/entries/{entry_id}": entry_page}, not_found=nf)
Link("Entries", to="/projects/auth", active_class="active")  # a real <a href>, click intercepted
ctx.path: Signal[str]
ctx.params: Signal[dict]
ctx.navigate("/projects/auth", replace=False)
```

```python
def build(ctx):
    entry_id = computed(lambda: ctx.params.value.get("entry_id"))
    entry = computed(lambda: store.get(entry_id.value) if entry_id.value else None)
    ...Router(routes={...})
```

- **Static tree, signal params.** All page subtrees are built at session creation (as `Tabs` children are today); the shell renders only the active one. Params are signals, so a page is a function of data, not of structure. No structural op, no bump. Cost: every page's effects exist from the start (cheap for semula's six screens). Lazy or heterogeneous page construction would need the deferred structural op.
- **Shell:** inject `<base href="{root_path}/">` into the served HTML (computed from `scope["root_path"]`, which Starlette sets for a mounted app), so every relative URL (`api/*`, `api/file/*`, thumbnails) resolves correctly at any in-app path. `pushState` on `Link`, `popstate` -> `navigate {path}` event; the shell sends its current in-app path as `&path=` on the stream URL so a new session starts on the right page.
- **Server:** an opt-in SPA fallback (`GET /{path:path}` returns the shell for non-`api/` paths), switched on when the tree contains a `Router` or `spa=True`. This also covers semula's `/v1`, `/api/v1`, `/mcp` because those live outside the `/ui` mount.
- **Mount check (answers the request).** Works today at `/ui/` (verified, starlette 1.6.0); `/ui` 307-redirects to `/ui/`. Needs: `<base>` fix and SPA fallback (above); behind an HTTPS-terminating proxy the 307 needs uvicorn `--proxy-headers` to keep the scheme (H7). Starlette does not run a mounted sub-app's lifespan; indah has none, and `Topic` captures the loop lazily on first use instead of at startup. FastAPI `app.mount("/ui", indah_app)` is the same mechanism. `tests/integration/test_gallery_mount.py` covers mounting only for the root page.
- **Authorization caveat:** hidden pages are still in the snapshot. Anything role-restricted must be omitted at build time (H3), never merely not shown.

### 2.E5 Overlays and small controls

```python
Modal(children, *, open: Signal[bool], title="", size="md", on_close=None)
Drawer(children, *, open: Signal[bool], side="right", title="", on_close=None)
Button("Delete", on_click=delete, confirm="Delete this entry?")   # dialog shown before the click is posted
Badge(text_or_source, *, tone="neutral")                          # ok | warn | err | info | neutral
Switch(value: Signal[bool], *, label="")                          # Checkbox variant
Shortcuts({"g l": go_log, "a": approve, "mod+k": palette})        # invisible; ignored while typing
ctx.toast("Released 01J...", kind="success")                      # from any handler
```

- Any component accepts `tooltip="..."` (generic prop handled in the `Node.svelte` wrapper).
- **Wire:** a new top-level message `{"v":1,"type":"toast","message":..,"kind":..,"ttl":..}`. The existing `error` message stays and shares the toast UI.
- **A11y requirements in Done-when:** focus trap and return focus, Esc, `aria-modal`, `role="dialog"`, shortcuts do not fire inside inputs and are listed in a `?` overlay.
- Modal and drawer children live in the tree while closed (their props are in the snapshot), so they are not for secrets (H3, H6).

### 2.E6 Panes and density

```python
SplitPane(first, second, *, direction="horizontal", initial=0.4, min=0.2, key="log")
MasterDetail(master, detail, *, open: Signal[bool] | None = None)    # SplitPane + Drawer fallback on narrow widths
create_app(density="compact");  Table(density="compact")
```

Client-only drag with keyboard resize (arrow keys); the ratio persists in `localStorage` by `key`; no server round trip. Density is a token set (row height, padding) under `data-density`, in the same mechanism as the theme. Sticky headers come with E2.

### 2.E7 Dynamic children (keyed rows with item events)

```python
List(items, *, key="id", item=spec_with_inputs, on_item=lambda key, event, value: ...)
# template `on` entries post {value, key, index}; List.handle routes them to on_item
```

I recommend satisfying semula's two uses (playground message stack, tool-call editor rows) with **homogeneous, keyed rows**, not a structural op: template events carry `key` and `index`, the list renders with a keyed `{#each}`, and in-list inputs get the ADR-0013 focus rule so a patch cannot clobber the row being typed in. Add and remove are `items.set(...)`. This keeps ADR-0016's deferral intact and needs no bump. IND-29 is retitled accordingly (section 7). If you want true heterogeneous children, that is the v2 op (section 6, Q3).

### 2.E8 App-level theme tokens

```python
create_app(
    ...,
    title="semula",
    logo="assets/semula.svg",
    theme=Theme(
        light={"primary": "#1f6feb", "bg": "#f7f7f9"},
        dark={"primary": "#79b8ff"},
        radius="8px",
        font="system-ui, sans-serif",
    ),
)
```

The server injects `<style id="indah-theme">:root{--primary:...}:root[data-theme="dark"]{...}</style>` after the shell CSS in `_chrome_html`. Token names are validated against the documented set (`--bg --surface* --text --muted --outline* --primary* --secondary* --ok --warn --err --shadow --radius*`); values reject `; { } < >`, `url(`, `@import`, `expression`. The logo is served as an `<img src="api/brand/logo">` (SVG in an `<img>` cannot run script) with `Content-Security-Policy: sandbox`. Fonts stay the bundled Studio faces; `font=` selects a system stack only. Amends ADR-0014.

### 2.H1 Identity in context (and the session-store seam)

```python
@dataclass(frozen=True)
class Principal:
    id: str
    name: str = ""
    email: str = ""
    roles: frozenset = frozenset()
    workspace: str | None = None
    claims: Mapping = ...


Authenticator = Callable[[Request], Principal | None | Awaitable[Principal | None]]
create_app(session_factory=build, auth=my_auth, secret=os.environ["INDAH_SECRET"], secure=True)
```

`secure=True` turns on: no `default` session (an id-less request is 401), required signed token, Origin guard (H2), owner binding. A default `auth` reads Starlette's `request.user` when `AuthenticationMiddleware` is installed, so a parent app can supply identity with no indah-specific code.

Flow:

1. `GET /` is authenticated and served (cacheable shell, no session yet).
2. The shell calls `POST api/session {resume: <old token or null>}` -> `{token}`. The server authenticates the principal, and if `resume` verifies against the same principal and the session is still alive it returns the same token, otherwise it mints a new one. This keeps today's "reload resumes your tab state" behaviour.
3. `token = sid + "." + b64(HMAC-SHA256(secret, sid | principal.id | workspace))`, `sid` = 128 random bits. `secret` may be a list for rotation.
4. `/api/stream`, `/api/event`, `/api/upload`, `/api/file` re-authenticate and verify the token against the principal; a mismatch is 403, and the store never sees a forged id (so an attacker cannot create sessions by guessing ids).
5. `get_or_create(sid, ctx_info)` builds the session with `Context.user`; `handle.owner = principal.id`; sign-out calls `store.discard_where(owner=...)`.

I considered keeping browser-minted ids and only binding the owner at first use; that is secure enough against hijack but lets a client choose `default` or flood the store with ids, which is why the signed form is worth the one extra round trip. Non-secure apps (notebooks, the gallery) are unchanged: same ids, no handshake.

**Open edge:** a long-lived SSE stream outlives a cookie. The server checks `Principal.expires_at` on each heartbeat and ends the stream with a `401` event; the shell shows a "signed out" state.

### 2.H2 Login and request protection

Split in two, because semula's headless core must already own tokens, workspaces and API auth, so indah building an OIDC client duplicates it.

- **H2a (core, M).** `Authenticator` seam (H1), an **Origin/Host and `Sec-Fetch-Site` guard** on every POST route plus the stream GET (required for `/api/upload` because multipart is a simple request), cookie-flag guidance, `ctx.sign_out()`, a "signed out" shell state, and an `examples/oidc_login.py` recipe (authlib in the parent app, `Principal` from the ID token). No new runtime dependency in indah.
- **H2b (optional module, L, only if the decision is to stay on indah).** `pip install indah[auth]`: `/auth/login` (PKCE, state, nonce), `/auth/callback`, `/auth/logout`, a signed `HttpOnly; Secure; SameSite=Lax` cookie via `itsdangerous`, built on authlib (BSD-3). Not enabled unless `auth=indah.auth.oidc(...)` is passed. Amends ADR-0008: indah still owns no auth by default.

### 2.H3 Authorization

```python
ctx.can("entries:write") -> bool           # Principal.roles + create_app(policy=Policy({...}))
ctx.require("admin")                       # raises Forbidden -> toast; POST gets 403
guard("editor")(delete)                    # handler wrapper, evaluated at dispatch time
Button("Delete", on_click=guard("editor")(delete), disabled=not ctx.can("editor"))
children += [admin_panel] if ctx.can("admin") else []        # omission at build time
```

Indah supplies the mechanism, not the policy. **Security rule:** restricted components are omitted when the tree is built for that principal, because anything merely hidden is still in the snapshot and the patches. `guard` re-checks at dispatch so a role revoked mid-session fails closed; `store.discard_where(owner=...)` forces a rebuild. Roles are per workspace: one session per `(principal, workspace)` (a path segment via E4), and `ctx.switch_workspace(ws)` ends the session and has the shell navigate. Generic `disabled=` and `visible=` props ship for UX only and are documented as not a control.

### 2.H4 External session store

Honest scope: L, about two weeks plus a Redis service in CI. It is more than a store backend because signals are anonymous objects and `Hub` offsets are process-local.

- `ctx.state("name", default)` creates a named, JSON-serialisable signal that the store can snapshot (`{name: value, path: ...}`); unnamed signals are documented as non-durable. The factory must be deterministic from `(ctx, state)` so any replica can rebuild.
- `HubBackend` seam (`publish(sid, msg) -> offset`, `replay(sid, since)`, `subscribe(sid)`) with a Redis Streams implementation; epoch-qualified ids (S0) make cross-replica resume safe.
- `TopicBackend` (Redis pub/sub) so E1 fans out across replicas.
- Process-local work cannot migrate: an in-flight async handler dies with its process (the tab shows an "interrupted" toast).
- **Recommended alternative (Q7):** keep UI-session state disposable, durable state in semula's database, and use sticky sessions on the gateway. A restart rebuilds the session (the S0 fix makes the tab re-init cleanly) and loses only filters and selection.

### 2.H5 Hardening in core

```python
create_app(
    ...,
    limits=Limits(
        rate={"/api/event": Rate(per_ip=20, burst=40), "/api/upload": Rate(per_ip=2, burst=4)},
        max_event_bytes=2_000_000,
        max_streams_per_ip=8,
        max_sessions=1000,
        session_idle_seconds=900,
        max_upload_mb=25,
    ),
    csp="strict",
)  # None | "strict" | custom string
```

- Move `_RateLimitMiddleware` and `_SecurityHeadersMiddleware` into `indah/hardening.py` (the gallery imports them back). Add the two limits that do not exist anywhere: an event-body cap and a per-IP SSE connection cap (a token bucket cannot bound a long-lived stream).
- **CSP.** The shell has two inline `<script>` and two inline `<style>` tags (I counted them in the built file) and no external fetches except map tiles from the `Map` component's `tile_url`. `_chrome_html` already rewrites the document, so add a per-response nonce to those four tags and send `default-src 'none'; script-src 'nonce-N'; style-src 'nonce-N'; style-src-attr 'unsafe-inline'; img-src 'self' data: blob: <tile hosts>; font-src 'self' data:; connect-src 'self'; frame-ancestors 'self'`. Tile hosts are registered by `Map` at build time. `style-src-attr 'unsafe-inline'` is needed for Svelte's inline `style="..."`. **Verification:** a Playwright test fails on any `securitypolicyviolation` event across the e2e suite. Off by default and in `launch()` (Colab embeds the app in an iframe).
- Client IP comes from `request.client` only; deployments behind a proxy use uvicorn's proxy-header handling (H7). This removes the unconditional `X-Forwarded-For` trust.

### 2.H6 Secret and token UI

```python
SecretReveal(value: Signal[str | None], *, label="", on_dismiss=None)
# token list = Table(rows, key="id", columns=[Col("name"), Col("last_used", kind="time"), Col("status", kind="badge")],
#                    actions=[RowAction("Revoke", on=revoke, confirm="Revoke this token?")])
```

The value is shown once with a copy button (`navigator.clipboard`) and an "I have saved it" dismiss. **Ephemeral props:** a component can mark a prop ephemeral; `Session._emit` then publishes with `record=False` (not kept in `Hub._history`) and `snapshot()` omits it, so reconnect cannot replay the secret. If the connection drops before dismissal the user rotates the token. The prop is cleared on dismiss and in `Session.close()`. Never put a secret in an exception message (the `error` toast echoes it); document that.

### 2.H7 Base path and proxy support

Base path under a mount needs nothing beyond the S0 `<base>` fix. `X-Forwarded-Prefix` is honoured only when `trusted_proxies` is set (never by default). For client IP and scheme, document `uvicorn --proxy-headers --forwarded-allow-ips` rather than re-implementing it. Audit hook: `create_app(audit=fn)` calls `fn(AuditEvent(ts, sid, user, component, event, payload_keys))` after dispatch; payload **values** are excluded unless `audit_payloads=True`, and components flagged `sensitive` (password `TextInput`, `SecretReveal`) are never included.

---

## 3. Slices

Each ends in something demonstrable. Points are per slice (stories in section 7). Days assume one engineer working with agents. `ASSUMED` marks decisions a slice rests on.

### S0: Mount, context, theme (foundations) - 11 pts, about 4 days

**Build plan**
1. Failing test, then fix, for resume after restart (hub epoch, `<epoch>-<offset>` ids).
2. `<base href>` injection and opt-in SPA fallback; mount tests under a parent Starlette/FastAPI app with `/v1/*`.
3. `Context`, factory arity detection, `Session.close()` with `on_close`, store-seam amendment (`ctx_info`, `owner`).
4. E8: `Theme`, `logo`, validated token injection.
5. Fix the stale `Q-frame-coalesce` row in `QUESTIONS.md`.

**Tests**
- *End-to-end:* a mounted app at `/ui` loads in Chromium, the stream connects, a click round-trips; kill and restart the server and the open tab re-inits without a manual reload; themed app shows the semula colours and logo.
- *Integration:* parent app with `/v1/health`, `/mcp` stub and `Mount("/ui")` (index, stream, event, upload, file URLs, deep path serves shell); zero-arg and `(ctx)` factories both work; theme CSS rejects `url(`/`;`/`{`.
- *Unit:* `Hub` epoch/offset parsing and mismatch -> `None`; `Context` lifecycle runs `on_close` on `discard` and eviction; token-name allowlist.

**Demo:** `examples/semula_shell.py`: a FastAPI parent with `/v1/health` JSON and the indah app mounted at `/ui`, themed in semula colours with a sidebar of placeholder pages; restart the process and the tab recovers by itself.

### S1: Live push and the live log (E1 + E2 core) - 19 pts, about 7 days

**Build plan:** `Topic` and `ctx.latest/tail`; `Stream` with the 100 ms coalescer and the `trim` patch; `proxy_flush` knob; `Table` keys, `Col` renderers, sticky header, client search and column toggle, `follow`; the demo.

**Tests**
- *End-to-end:* two tabs on the log with a publisher at 40 events/s for 10 s: both show the newest row within 1 s, DOM rows never exceed the limit, a background-and-return tab catches up, selection in one tab does not move the other.
- *Integration:* fan-out to N sessions with isolated per-tab state; measured SSE frames at 40 events/s stay at or under 10 per second, and bytes per second stay under a stated budget with `proxy_flush` on and off; `discard`/eviction leaves `Topic.subscriber_count == 0`; `publish_threadsafe` from a thread delivers in order.
- *Unit:* `Stream.append/trim`; coalescer flushes appends before any replace; `Table` serialisation with keys and renderers; client filter predicate.

**Demo:** `examples/semula_log.py`: a background task generates fake calls (ULID, time, project, tier `exact|norm|bm25|embed|miss`, hit/miss, score, latency, snippet); the table shows badge, mono and relative-time cells; search box, follow-tail toggle; click a row for a detail panel. Open it in two tabs. *This is the first drop semula can use.*

### S2: Overlays and the pending queue (E5 + E3 TextArea + E2 actions) - 20 pts, about 7 days

**Build plan:** `Modal`, `Drawer`, `Button(confirm=)`, `ctx.toast` + `toast` message, `Badge`, `Switch`, `tooltip`, `Shortcuts`; `TextArea` with focus ownership and `max_event_bytes`; `Table` row actions and multi-select; the demo.

**Tests**
- *End-to-end:* drawer opens from a row, focus is trapped and returns on Esc, the toast appears, `a`/`r` shortcuts fire and do not fire inside the textarea, typing 2 KB quickly through an artificial 300 ms echo loses no characters.
- *Integration:* a 3 MB event body is rejected with 413; toast reaches only the sender's session; `confirm` posts nothing until accepted; row actions dispatch with the key.
- *Unit:* component serialisation, shortcut parser, `guard` of overlay open state.

**Demo:** `examples/semula_pending.py`: a task "parks" calls (each waits on an `asyncio.Event`); every tab shows a live badge count; click a row to open a drawer with the request, write a reply in the textarea, Submit (releases the event, toast, row disappears in all tabs); Reject with a confirm.

### S3: Big tables and panes (E2 remote + virtual scroll, E6) - 15 pts, about 5.5 days

**Build plan:** remote mode (`TableQuery`, `total`, window events); virtual scroll with a window cache; `SplitPane`, `MasterDetail`, density; the demo.

**Tests**
- *End-to-end:* 20k rows scroll with fewer than 200 DOM row nodes and no frame over 100 ms in a trace; sorting/filtering round-trips and the scrollbar height stays correct; dragging the divider persists after reload.
- *Integration:* window requests are debounced (one query per burst); stale responses are dropped; `total` change re-clamps the window.
- *Unit:* window arithmetic, LRU cache, `TableQuery` parsing and validation (limit clamp).

**Demo:** `examples/semula_entries.py`: 20k fake entries in stdlib SQLite with a project `Select`, server-side sort/search, hit counts, pinned/fuzzy badges, a split pane previewing the selected entry, a compact-density toggle.

### S4: Routing and deep links (E4) - 10 pts, about 3.5 days

**Build plan:** `Router`, `Link`, `ctx.path/params/navigate`, history integration, route patterns, 404, `&path=` on the stream; sidebar nav.

**Tests**
- *End-to-end:* paste `/ui/projects/auth/entries/01J...` into a fresh tab and it opens that entry; back/forward work; a link opened in a new tab works; all of it under the `/ui` mount in a parent app.
- *Integration:* SPA fallback returns the shell for in-app paths and a 404 for `api/` paths; `serve_file` URLs resolve under a deep path; route matching and param typing.
- *Unit:* pattern compiler, `navigate` replace vs push.

**Demo:** `examples/semula_routes.py`: sidebar, project switcher in the URL, entry deep link, working back button, a 404 page, all mounted at `/ui` in the FastAPI parent.

### S5: Editor family and dynamic rows (E3 rest, E7) - 24 pts, about 8.5 days (split S5a/S5b)

**Build plan (S5a, 14 pts):** `JsonTree`, server-side `Diff` + shell renderer, keyed `List` with item events and focus-safe in-list inputs. **S5b (10 pts, gated by Q4):** lazy `CodeEditor`.

**Tests**
- *End-to-end:* diff shows added/removed/changed lines and inline spans; editing one tool-call row while a patch arrives keeps focus and text; `CodeEditor` loads lazily (no `editor.js` request on a page without one) and shows a JSON lint error.
- *Integration:* `Diff` on 5k-line input returns within 500 ms or truncates with a notice; keyed list reorder preserves row identity; the editor file is served from the wheel with the right type and the page works offline.
- *Unit:* `difflib` hunk mapping and inline spans; item-event payload routing; wheel contents test updated (no Node at install or runtime).

**Demo:** `examples/semula_editor.py`: the entry editor (JSON request/response, pin `Switch`, Save), a simulated version conflict opening a `Modal` with `Diff`; a review-queue card with a split `Diff` and score `Badge`; a playground message stack (keyed rows: role `Select`, `TextArea`, remove) that streams a reply into `StreamText`.

### H-A: Identity, signed sessions, proxy (H1 + H7 + H2a) - 18 pts, about 6.5 days

**Build plan:** `Principal`/`Authenticator`/`ctx.user`; `secure=True`; `POST api/session` handshake and signed token; owner-bound handles and `discard_where`; Origin/CSRF guard; trusted proxies; audit hook; two-user demo.

**Tests**
- *End-to-end:* two logins; one cannot attach to the other's session, stream or file URL; reload resumes your own session; sign-out ends it and the shell shows "signed out".
- *Integration:* forged, replayed (other principal), expired and id-less requests all fail with 401/403 and create no session; cross-origin multipart POST without a matching Origin is rejected; the stream ends on principal expiry.
- *Unit:* token sign/verify with rotation; Origin matching (scheme, port, `allowed_origins`).

**Demo:** `examples/semula_hosted.py`: a header-based fake IdP (`X-User`) in a parent middleware, two browser profiles, each sees its own session and cannot open the other's.

### H-B: Authorization, secrets, hardening in core (H3 + H6 + H5) - 19 pts, about 6.5 days

**Build plan:** `ctx.can/require/guard`, workspace-scoped sessions; `SecretReveal` + ephemeral props; `indah.hardening` (`Limits`, headers, rate limit, event cap, stream cap) and the gallery switched to import it; CSP with nonces; OIDC recipe.

**Tests**
- *End-to-end:* viewer sees no admin subtree in the DOM or in the SSE init; a revoked role fails the next action; a revealed secret is absent from a reconnect's replay and snapshot; the whole e2e suite runs under CSP with zero violations.
- *Integration:* limits return 429/413; per-IP stream cap holds; `Limits` defaults reproduce today's behaviour when unset.
- *Unit:* policy evaluation, ephemeral emit skips history, CSP builder and nonce rewrite.

**Demo:** extend `semula_hosted.py` with viewer/editor/admin roles and a token screen: create token (reveal once), list, revoke with confirm.

### Conditional (do not file yet): H2b OIDC module (8 pts), H4 external store (13 pts)

Gated by the stay-or-leave checkpoint (section 6, Q1).

---

## 4. ADRs

**Existing ADRs in conflict (all treated as open):**

| ADR | Conflict | Proposal |
|-----|----------|----------|
| 0008 (no auth) | H1-H3 | **Amend.** Auth stays out of core by default; core gains the seams (Principal, Authenticator, `ctx.user`, session binding, Origin guard). An optional `indah[auth]` OIDC module only if Q1 says stay. |
| 0010 (in-memory only, "id in, handle out") | H1, H4, E1 | **Amend.** Seam becomes `get_or_create(sid, ctx_info)`, handles gain `owner`, `discard` runs `close()`. External backend stays deferred behind "UI state is rebuildable" (new ADR). |
| 0016 / Q-children (structural op deferred) | E7 | **Keep.** Satisfy E7 with keyed `List` + item events; amend 0016 to document item events. |
| 0021 (Table, client-side, no heavy grid) | E2 | **Supersede in part** by a Table v2 ADR (streaming, remote, keys). Still no grid library. |
| 0014 (one baked theme; switcher deferred) | E8 | **Amend:** per-app token override and logo are allowed; the user-facing theme *switcher* stays deferred. |
| 0004 (shell fetches nothing at runtime) | E3 CodeEditor | **Amend wording:** a lazily loaded same-origin editor bundle is fine; nothing from a third party. |
| 0005 (versioned public protocol) | all | **Amend:** write down the additive-change rule (section 2.0). |
| 0013 (focused inputs client-owned) | E3, E7 | **Extend** to `TextArea`, `CodeEditor`, in-list inputs. |
| 0011 (streaming) | E1 | **Extend:** `trim`, time coalescing. |
| 0024 (hardening deferrals, rate limit "in the gallery") | H5, H7 | **Supersede in part:** limits and CSP move into core; origin-IP hiding stays deferred. |
| 0001, 0002, 0009, 0017 | none | Consistent. 0001 gains an explicit mount contract in the routing ADR. |

**New ADRs (titles; next number is 0025, 0022 is an unused gap):**

- 0025 Context object and identity-aware sessions (H1, seam amendment)
- 0026 Server push: `Topic`, `Stream`, coalescing and the `proxy_flush` knob (E1, closes `Q-frame-coalesce`)
- 0027 Table v2: keyed rows, streaming and remote modes, virtual scroll (E2)
- 0028 Editor family: native textarea, server-side diff, lazily loaded CodeMirror (E3)
- 0029 Routing: static tree, signal params, `<base>` and SPA fallback, mount contract (E4; resolves IND-75)
- 0030 Overlays, toasts and shortcuts (E5)
- 0031 App-level theming (E8)
- 0032 Authentication seams, request guard, optional OIDC module (H2)
- 0033 Authorization: omission at build time, guards at dispatch (H3)
- 0034 Core hardening: `Limits`, CSP nonces, trusted proxies, audit hook (H5, H7)
- 0035 UI session state is rebuildable; external store criteria (H4, drafted but `Proposed`)

I would draft first, before S1 starts: 0025, 0026, 0027, 0031. Before S4: 0029. The rest at the start of their slice.

---

## 5. Order and dependencies

```
S0 foundations+theme ──► S1 live log ──► S2 pending+overlays ──► S3 big tables+panes ──► S4 routing ──► S5a/S5b editors
        │                                         │
        └──► H-A identity (needs ctx, store seam) ┴──► H-B authz/secrets/hardening
```

- **Critical path for the semula dashboard:** S0 -> S1 -> S2 -> S3 -> S4 -> S5. Screen coverage: live log after S1, pending queue after S2, entries browser after S3, entry editor and review after S5 (deep links after S4), playground after S5.
- **My changes to your order:** (1) S0 first: the `/ui` mount, deep-link base fix and restart bug are go/no-go for the MVP and cost 4 days; E8 rides along because it is S and lets semula's look land from the start. (2) E5 before E3: the pending queue needs a drawer, toast and textarea, not a code editor, so S2 is `E5 + TextArea`. (3) E3 is split: `TextArea` (S2), `JsonTree` and `Diff` (S5a), and the heavy `CodeEditor` last and gated (S5b). (4) E7 is last because only the entry editor and playground need it. (5) E4 after the remote table: the entries browser works with a project `Select`; the URL is a refinement.
- **Parallel:** the CodeMirror lazy-bundle build spike (measure, wire the second file) can run any time after S0; H-A needs only S0's `Context` and seam, so it can run beside S2-S3 if a second pair of hands exists; H5's "move gallery middleware into core" is independent and can land any time; ADR drafting runs one slice ahead of the code.
- **Semula's slice 3:** S0 + S1 (about 2.5 weeks) is the earliest usable drop; S2 follows about 1.5 weeks later. If semula's third slice needs more than the live log, say so and I will pull `Badge`/`Drawer` forward.
- **Total:** E1-E8 plus foundations about 36 days (about 7 weeks). Hosted H-A and H-B about 13 more days; H2b and H4 about 18 more if they are ever approved.

---

## 6. Risks and open questions

Each leads with my recommendation. Only the first four are expensive to get wrong.

1. **Q1: When do hosted items start, and what gates them?** *Recommend:* build E1-E8 now; start H-A (identity seams, small and useful either way) after S2; **do not** build H2b or H4 until a checkpoint after S3, where you score the section 8 criteria against real numbers from the dashboard. A wrong default here is weeks of build on the wrong frontend.
2. **Q2: Additive-change rule vs one bump to v2 now.** *Recommend:* keep v1 and write the additive rule into ADR-0005; bump only for a structural op or a mandatory handshake. Alternative: bump to v2 once in S1 (`trim`, `toast`, epoch ids) so any skew fails loudly. Cost of being wrong is low for first-party use (the shell ships in the wheel) and moderate if semula ever runs an ejected client.
3. **Q3: E7 as keyed rows or as the structural children op (IND-29 as written)?** *Recommend:* keyed rows (3 days, no bump). The op is about 8+ days, forces v2, and semula's two uses do not need it. Revisit if a future screen needs mixed component types added at runtime.
4. **Q4: Is `CodeEditor` needed, and may the wheel grow by about 120 KB gzip?** *Recommend:* ship `TextArea` + `JsonTree` + server `Diff` first and judge on the entry-editor demo; if CodeMirror is needed, load it lazily from a second same-origin file (measured +122 KB gzip, MIT). Inlining would add about 59% to every app's shell for a feature most never use.
5. **Q5: Should indah ship OIDC?** *Recommend:* no; ship the seams, the Origin guard and a recipe (H2a). semula's core already needs tokens, workspaces and API auth, and an indah OIDC client would duplicate it. Reversible: H2b can be added later without breaking H2a.
6. **Q6: Change the `proxy_flush` default?** *Recommend:* keep it `True` (Colab needs it), add the `proxy_flush=False` knob for semula's local container, and rely on the 100 ms coalescer. Auto-detecting the environment would silently change the Fly gallery's behaviour.
7. **Q7: Is external session state (H4) worth building?** *Recommend:* no for now: treat UI-session state as disposable, keep durable state in semula's database, use gateway sticky sessions. The S0 resume fix makes a restart re-init cleanly. Build H4 only if you need tab continuity across deploys or more than one replica without affinity.
8. **Q8: Extend `Table` or add a new `DataTable`?** *Recommend:* extend `Table` with new props and keep index semantics when `key` is unset, so IND-68's shipped contract and tests are untouched. A separate component would duplicate the shell's sorting and select code.

**Risks that need no decision, for awareness:** (a) semula's screen designs are unwritten; S1-S2 are safe, but hold the S3+ stories until `semula/docs/design/` exists. (b) My day estimates assume one engineer with agents and the current e2e infrastructure; the biggest uncertainty is shell work (virtual scroll, focus handling), which I would measure after S1 and re-estimate. (c) The `Diff` server cost is quadratic on pathological input; the 5k-line cap bounds it. (d) The restart bug is believed real from code and a one-line reproduction of `replay_since`; the failing integration test in S0 is what confirms it.

---

## 7. Draft cards

Not filed. Board IND, after your confirmation. Pandan form: title, points, Why / Do / Done when / Not in scope. Epic titles are named outcomes with a done-when. IND-29 and IND-75 already exist and are retitled/closed here instead of duplicated.

### Epic 1. S0 Mount, context, theme: semula's shell loads under `/ui`, themed, and survives a restart
*Done when:* `examples/semula_shell.py` runs under a FastAPI parent at `/ui`, themed, and recovers from a server restart.

**1.1. Resume after server restart re-sends the init snapshot** (2)
- Why: a restarted server's fresh hub treats a high `Last-Event-Id` as current, so open tabs keep a stale tree.
- Do: failing integration test first; add a hub epoch and `<epoch>-<offset>` ids; keep integer ids accepted.
- Done when: the test passes and the browser e2e shows a tab re-initialising after a restart.
- Not in scope: external stores, cross-replica resume.

**1.2. Mount-safe shell: `<base href>` and opt-in SPA fallback** (3)
- Why: deep `/ui/...` paths 404 and relative URLs break; routing and file URLs need a base.
- Do: inject `<base>` from `root_path`; add the SPA fallback switch (excludes `api/`); mount tests under a parent app.
- Done when: a deep path serves the shell and `api/*` and `api/file/*` resolve under it.
- Not in scope: the router itself (Epic 5).

**1.3. `Context` and `session_factory(ctx)`** (3)
- Why: one per-session object for push, toast, route and identity.
- Do: arity-detecting factory call; `Session.close()` with `on_close`; store seam gains `ctx_info` and `owner`.
- Done when: zero-arg factories still work and `discard`/eviction run `on_close`.
- Not in scope: any feature that uses `ctx` (later epics).

**1.4. App-level theme tokens, logo and title (E8)** (3)
- Why: semula's look must not be locked to Studio.
- Do: `Theme`, `logo`; validated `<style>` injection; `api/brand/logo` route; docs.
- Done when: a themed example shows custom colours in light and dark, and hostile values are rejected.
- Not in scope: a user-facing theme switcher, custom fonts.

### Epic 2. S1 Live push: a background task updates a live log in every open tab
*Done when:* the live-log demo meets its frame and latency budgets in two tabs.

**2.1. `Topic` and `ctx.latest` / `ctx.tail` (E1)** (3)
- Why: nothing outside a session can fan out to all sessions today.
- Do: app-level `Topic` (loop-thread and threadsafe publish, `recent`); per-session subscribe with unsubscribe on close.
- Done when: N sessions receive in order, state stays per tab, and `subscriber_count` returns to 0 after eviction.
- Not in scope: cross-process fan-out.

**2.2. `Stream`, `trim` patch and the 100 ms append coalescer** (5)
- Why: tens of events per second must not mean tens of frames per second or an unbounded DOM.
- Do: `Stream` (append, limit); `emit_append` buffering with ordered flush; shell handles `trim`; `proxy_flush` knob; document in `protocol.md`.
- Done when: at 40 events/s there are at most 10 frames/s and rows stay at the limit.
- Not in scope: padding changes in `sse_events`.

**2.3. Table keys, typed cell renderers, sticky header (E2 part)** (5)
- Why: rows need ids and the log needs badges, mono ids and relative times.
- Do: `key=`, `Col` specs, `badge|mono|time|number`, key-based `selected`, sticky header; legacy index mode untouched.
- Done when: old `Table` tests pass unchanged and the log table renders typed cells.
- Not in scope: remote mode, actions.

**2.4. Table client search, column toggle, follow-tail** (3)
- Why: the log needs quick filtering and a tail that follows new rows.
- Do: in-memory search/filter, persisted column visibility, `follow` that pauses on scroll-up.
- Done when: filtering a streaming table keeps new matching rows appearing.
- Not in scope: server-side filtering.

**2.5. Demo: fake live request log** (3)
- Why: shows semula's first screen end to end.
- Do: `examples/semula_log.py`, integration and e2e as in S1.
- Done when: two tabs show the same live rows and the budgets pass.
- Not in scope: a real semula backend.

### Epic 3. S2 Overlays and the pending queue: a parked call is released from a drawer
*Done when:* the pending-queue demo works in two tabs including toast, confirm and shortcuts.

**3.1. `Modal`, `Drawer`, `Button(confirm=)` (E5 part)** (5)
- Why: approve/reject/delete need dialogs.
- Do: components with focus trap, Esc, aria; confirm on `Button`.
- Done when: keyboard-only use works and the e2e passes.
- Not in scope: stacking multiple modals.

**3.2. `ctx.toast` and the `toast` message** (2)
- Why: handlers need feedback beyond the error toast.
- Do: new message type, kinds and ttl, session-local delivery.
- Done when: a toast reaches only the sender's tab.
- Not in scope: persistent notifications.

**3.3. `Badge`, `Switch`, generic `tooltip=`** (3)
- Why: status chips, pin toggle, hints.
- Do: three small components/props with tokens.
- Done when: each renders and round-trips where bound.
- Not in scope: icon set.

**3.4. `Shortcuts`** (2)
- Why: queue triage by keyboard.
- Do: scoped key map, ignored while typing, `?` help overlay.
- Done when: shortcuts fire outside inputs only.
- Not in scope: user-rebindable keys.

**3.5. `TextArea` with focus ownership and an event-size cap** (3)
- Why: multiline input; today's `TextInput` is single line and request bodies are unbounded.
- Do: native textarea, debounce, blur flush, ADR-0013 rule, `max_event_bytes`.
- Done when: the 300 ms-echo typing test loses nothing and a 3 MB event gets 413.
- Not in scope: code highlighting.

**3.6. Table row actions and multi-select** (3)
- Why: per-row Delete/Pin and bulk approve.
- Do: `RowAction` (with confirm), `checked` signal.
- Done when: actions dispatch with the row key.
- Not in scope: inline cell editing.

**3.7. Demo: pending queue** (2)
- Why: second semula screen.
- Do: `examples/semula_pending.py` as in S2.
- Done when: release in one tab clears the row everywhere.
- Not in scope: real parked HTTP calls.

### Epic 4. S3 Big tables and panes: 20k rows scroll smoothly with server-side query
*Done when:* the entries demo meets its scroll and latency budgets.

**4.1. Table remote mode (`TableQuery`, `total`)** (5)
- Why: thousands of rows per project cannot ride one prop.
- Do: debounced `query` events, window responses, stale-response drop.
- Done when: sort/search round-trip and `total` drives the scrollbar.
- Not in scope: server cursors, grouping.

**4.2. Virtual scroll in the shell** (5)
- Why: DOM size must stay bounded.
- Do: fixed row height per density, spacer, window cache.
- Done when: fewer than 200 row nodes at 20k rows and no frame over 100 ms.
- Not in scope: variable row heights.

**4.3. `SplitPane`, `MasterDetail`, density** (3)
- Why: log list with detail pane; compact operator view.
- Do: client-only drag with keyboard resize and persisted ratio; density tokens.
- Done when: ratio survives reload and compact mode shrinks rows.
- Not in scope: multi-pane docking.

**4.4. Demo: entries browser** (2)
- Why: third semula screen.
- Do: `examples/semula_entries.py` as in S3.
- Done when: budgets pass on 20k SQLite rows.
- Not in scope: ULID generation beyond the demo.

### Epic 5. S4 Routing: URLs map to state and deep links open entries (closes IND-75)
*Done when:* a pasted deep link opens the entry under `/ui` and back/forward work.

**5.1. `Router`, `Link`, `ctx.path`, history integration** (5)
- Why: shareable links and a working back button.
- Do: static page subtrees, active-page render, `pushState`/`popstate`, `&path=` on stream.
- Done when: back/forward and new-tab links work.
- Not in scope: lazy page construction, nested routers.

**5.2. Route params as signals, nav, 404** (3)
- Why: pages are functions of data.
- Do: pattern compiler, `ctx.params`, sidebar `Link` active state, `not_found`.
- Done when: `/projects/{p}/entries/{id}` drives a computed entry.
- Not in scope: redirects, guards (H-B).

**5.3. Demo: projects and entries by URL** (2)
- Why: proves the mount plus routing together.
- Do: `examples/semula_routes.py` under the FastAPI parent.
- Done when: the e2e in S4 passes.
- Not in scope: semula's real routes.

*IND-75 closes as decided (ADR-0029).*

### Epic 6. S5 Editor family and dynamic rows: edit an entry, resolve a conflict, review a diff
*Done when:* the editor demo shows a conflict diff, a review diff and a playground stack.

**6.1. `JsonTree` viewer** (3) - Why: inspect large JSON. Do: collapsible read-only tree with search and copy path. Done when: 1 MB JSON expands lazily without a long task. Not in scope: editing.

**6.2. Server-side `Diff`** (5) - Why: review and conflict screens. Do: `difflib` hunks over normalised JSON or text, split/unified shell renderer, 5k-line cap. Done when: add/remove/change and inline spans render. Not in scope: three-way merge.

**6.3. Keyed `List` with item events (retitles IND-29)** (5) - Why: tool-call and message rows are editable. Do: `key=`, template events carry `key`/`index`, keyed render, ADR-0013 in rows, `on_item`. Done when: editing a row while a patch arrives keeps focus. Not in scope: heterogeneous children, structural op.

**6.4. Lazy `CodeEditor` (json/yaml)** (8, gated by Q4) - Why: syntax and folding for entry bodies. Do: build `static/editor.js` (CodeMirror 6 slim), lazy `import()`, lint, focus rule. Done when: no editor request on pages without one and the wheel growth is at or under the measured budget. Not in scope: autocomplete, merge view.

**6.5. Demo: entry editor, conflict, review, playground** (3) - Why: last three semula screens. Do: `examples/semula_editor.py`. Done when: all four flows work in the e2e. Not in scope: real semula data.

### Epic 7. H-A Identity: users cannot open each other's sessions
*Done when:* the two-profile demo passes and forged requests create nothing.

**7.1. `Principal`, `Authenticator`, `ctx.user`, `secure=True`** (5) - Why: sessions must know who owns them. Do: seam, `request.user` default, `default` session refused. Done when: factory sees the user. Not in scope: login UI.

**7.2. Signed session token and `POST api/session`** (5) - Why: stop id guessing and cross-user attach. Do: HMAC token with rotation, resume, owner-bound handles, `discard_where`. Done when: wrong principal gets 403 and reload resumes. Not in scope: external store.

**7.3. Origin/CSRF guard and sign-out** (3) - Why: multipart upload is CSRF-able. Do: Origin/`Sec-Fetch-Site` check on POST routes and stream, `ctx.sign_out()`, "signed out" state, stream ends on expiry. Done when: cross-origin upload is rejected. Not in scope: OIDC.

**7.4. H7 trusted proxies, forwarded prefix, audit hook** (3) - Why: gateway deployment and an audit trail. Do: `trusted_proxies`, `X-Forwarded-Prefix`, `audit=` without payload values. Done when: spoofed headers from untrusted peers are ignored. Not in scope: log shipping.

**7.5. Demo: two users, one app** (2) - Why: shows isolation. Do: `examples/semula_hosted.py`. Done when: e2e passes. Not in scope: real IdP.

### Epic 8. H-B Authorization, secrets, core hardening
*Done when:* roles, reveal-once tokens and core limits/CSP pass their e2e.

**8.1. `ctx.can/require`, `guard`, workspace-scoped sessions (H3)** (3) - Why: viewer/editor/admin. Do: policy, build-time omission, dispatch guard, workspace in session key. Done when: viewer's snapshot has no admin subtree. Not in scope: policy authoring UI.

**8.2. `SecretReveal` and ephemeral props (H6)** (3) - Why: show a token once without replaying it. Do: ephemeral prop skips hub history and snapshot; copy and dismiss. Done when: reconnect never replays the secret. Not in scope: secret storage.

**8.3. `indah.hardening`: `Limits`, headers, rate limit, event and stream caps (H5)** (5) - Why: public hosting. Do: move gallery middleware into core, add the two missing caps, gallery imports it. Done when: defaults reproduce today's behaviour and caps return 429/413. Not in scope: Cloudflare config.

**8.4. CSP with nonces and a violation-free e2e** (5) - Why: tested CSP was deferred in ADR-0024. Do: nonce rewrite in `_chrome_html`, policy builder, tile-host registration, e2e fails on violations. Done when: full e2e suite has zero violations. Not in scope: on by default.

**8.5. OIDC recipe** (3) - Why: show login without owning it. Do: authlib example and docs page. Done when: example logs in against a test IdP. Not in scope: `indah[auth]`.

### Not filed until the checkpoint
H2b `indah[auth]` OIDC module (8), H4 external store: named state, hub and topic backends (13).

---

## 8. Hosted take: indah vs Svelte + Vite + TypeScript

**Where indah would still be weaker after this roadmap**

- **Every interaction is a server round trip.** Typing, filtering and drag all cross the gateway; ADR-0013 exists because of it. A SPA does these locally and talks to the API only when data changes.
- **Per-tab server memory and affinity.** Each tab holds a reactive graph of every screen on the server. A stateless SPA with REST holds nothing per tab, scales by adding replicas, and deploys without losing sessions. indah needs sticky sessions or H4 (about two weeks plus Redis) to approach that.
- **The authorization boundary is in-process.** indah screens call Python directly, so authorization has to be enforced in a service layer shared with `/api/v1`, or it lives in two places and drifts. An SPA must go through the API, which enforces it once. Hidden-but-present components (snapshot contents) are a footgun a SPA does not have.
- **No component ecosystem.** Accessible date pickers, virtualised grids with editing, rich editors, i18n, charting beyond uPlot: all hand-built or absent. The render spec has no loops or conditionals by design.
- **Tooling for the UI layer.** No type-checked UI contract, no component devtools or hot reload for the UI, and the shell's accessibility is unaudited. Testing the UI is Playwright only.
- **Auth plumbing is hand-built** (cookie, CSRF, session binding, expiry on a long-lived stream) where an SPA + BFF pattern is well trodden and widely reviewed.
- **No client-side routing state, optimistic updates, or offline.**
- The "no Node at install or runtime" advantage mostly vanishes for a hosted product, because the hosted build has CI with Node anyway. It was built for ephemeral notebooks.

**Where indah would be stronger**

- **One language and one process** for logic and UI, with no API layer to design, version and keep in sync. Pydantic models are shared with the domain.
- **Live server state is native.** SSE push, resume, per-tab isolation, streaming tokens and rows exist now and are tested against real proxies.
- **Time to a working screen.** The first six semula screens are about 7 weeks including framework work; a SPA is typically comparable for the first screen and faster for the sixth, but needs a separate backend contract throughout.
- **A small team that is Python-first** keeps one set of skills and one deployment unit.
- **Escape hatch exists:** the protocol is public (ADR-0005, ADR-0008) and a Svelte frontend can replace the shell later without rewriting the Python logic if ADR-0009 is honoured.

**How I would decide**

Stay on indah if the hosted product is an operator console: a few screens, hundreds of concurrent tabs at most, one region, Python-first team, live data a core feature. Leave if you need public-product polish, an editable grid, offline or optimistic UX, many concurrent users per instance without affinity, or a second client (mobile, CLI-driven UI). The Q1 checkpoint after S3 should score these with numbers from the dashboard: memory per open tab, p95 interaction latency through the real gateway, bundle growth versus plan, effort versus the estimates above, and how often the screens wanted something the component set lacked. If two or more come in worse than your thresholds, leave before H2b and H4.
