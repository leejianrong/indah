# The indah JSON UI protocol

This is the wire contract between the Python backend and the browser shell. It is
a **versioned, public contract** (ADR-0005): the shell checks the version on every
message and refuses a mismatch, so a hand-written frontend or a custom component
can target it without reading the framework's internals.

Current `protocol_version`: **1**.

The reference implementation lives in `src/indah/protocol.py`; where this document
and the code disagree, the code wins and this document is the bug.

## Transport

One SSE stream carries server → client messages; client → server events are plain
HTTP POSTs. Both ride one port so Colab's and Runpod's proxies pass them
(ADR-0001, ADR-0002).

- `GET /api/stream` — the SSE stream (server → client).
- `POST /api/event` — one UI event (client → server).
- `POST /api/upload` — a multipart file upload (client → server); see
  [File upload and download](#file-upload-and-download).
- `GET /api/file/{sid}/{token}` — download a file the app handed back (server →
  client); see [File upload and download](#file-upload-and-download).
- `GET /api/editor.js` — the code editor module (ADR-0032), an ES module the shell
  `import()`s on the first `codeeditor` render; an asset route, not a protocol message.
- `GET /api/brand/favicon/{name}` — a favicon registered with `create_app(favicons=)` (IND-152), served
  with `Content-Security-Policy: sandbox`; `404` for a name that is not registered. Only mounted when
  at least one is registered.
- `GET /api/components/{type}.js` — the ES module of a module component (ADR-0039), served from
  memory under a strict name pattern; see [Module components](#module-components-_module).
- `GET /health` — liveness: `200 {"status":"ok"}` while the process runs.
- `GET /ready` — readiness (IND-201): `200 {"ready":true}` while the process takes new tabs, `503
  {"ready":false,"draining":true}` with `Retry-After` once it is draining. No login, never touches a
  session, `Cache-Control: no-store`. See [Drain](#drain).

Every message on the SSE stream is a JSON object with a `v` field (the protocol
version) and a `type`. The upload and file routes carry bytes, not JSON messages,
so they are outside the versioned message schema (they are additive routes, not a
wire-format change).

### Base path and deep links

The shell resolves every URL (`api/stream`, `api/event`, `api/file/...`) relative to the
document's base, never absolutely, so the app works under a `Mount` or behind a proxy
that adds or strips a prefix (ADR-0001). That holds at the app root. With
`create_app(spa=True)` the server also serves the shell for any in-app GET path other
than `api/*` (so `/projects/auth/entries/01J` can be opened or reloaded) and injects a
**relative** `<base href="../../">` pointing back at the app root, so `api/*` still
resolves there. At the root no `<base>` is injected. This is HTML served to the shell,
not a protocol message, so `protocol_version` is unaffected.

### Sessions

Each browser tab drives its own isolated server-side session (its own signals and
its own patch stream, ADR-0010). The shell mints a per-tab **session id** and sends
it on both endpoints: as `?sid=<id>` on the stream URL and as a `sid` field in the
event body (below). Requests that carry the same id share one session; distinct ids
are isolated. An id-less request (a hand-written client, a curl) falls back to a
single default session. The `sid` is a transport detail, not a UI message — it does
not change any message schema, so `protocol_version` is unaffected.

### Transport tiers

indah declares two transport tiers (ADR-0017); everything shipped today is Tier 0.

- **Tier 0 — SSE + POST.** The Colab-compatible floor: an SSE stream, small JSON
  POSTs, and the multipart upload / file-download routes above. This is the only
  tier Colab's proxy supports (it blocks WebSockets, ADR-0002), so **everything in
  this document runs on Tier 0.** Upload and record-*snapshot* media (a single
  frame, a recorded clip) fit here.
- **Tier 1 — an optional streaming upgrade (WebSocket), not built.** Reserved for
  continuous high-frequency binary (live webcam, real-time detection), enabled only
  where the environment supports it (non-Colab). It is declared to keep that door
  open without weakening Tier 0; nothing here depends on it, and it does not change
  the Tier 0 contract.

## Nodes

The UI is a tree of nodes. A node is:

```json
{ "id": "n3", "type": "slider", "props": { "...": "..." }, "children": [] }
```

- `id` — a stable, server-assigned identifier (`n0`, `n1`, … in tree pre-order).
  Patches and events address nodes by this id.
- `type` — the component type (see the table below), which tells the shell how to
  render the node.
- `props` — the node's current properties.
- `children` — child nodes (only container types use them).

## Server → client messages (over SSE)

| Type | Shape | When |
|------|-------|------|
| `init` | `{"v","type":"init","root":<node>}`, plus `"chrome":{"title","favicon"}` when the session has changed them (see `chrome`), plus `"route":{"hint","node","transport"}` when the route hint is on (see "Route hint") | On connect, or a resume that fell back to a full snapshot. It can also arrive mid-stream (with an SSE id): an `async def` session factory that outlived `factory_timeout` showed a `skeleton` first, and this `init` replaces the whole tree with the real one (IND-153). The shell already handles a second `init` |
| `patch` | `{"v","type":"patch","changes":[<change>,...]}` | Granular updates to existing nodes |
| `error` | `{"v","type":"error","message":"..."}` | A handler failed; the shell shows a toast |
| `navigate` | `{"v","type":"navigate","path","replace"}` | `ctx.navigate(...)`: the shell pushes (or, with `replace`, rewrites) its history entry to the in-app `path`. An older shell ignores it |
| `toast` | `{"v","type":"toast","message","kind","ttl"}`, plus `"action":{"id","label"}` when given | Feedback from `ctx.toast(...)`: `kind` is `info`/`success`/`warn`/`error`, `ttl` seconds (`0` = until dismissed). Sent to the calling session only; an older shell ignores it. With `action`, the shell shows a button that posts `{"component":"__toast__","event":"action","payload":{"id":<action id>}}` to `POST /api/event` and dismisses the toast. The server runs the handler once (as a normal event: `guard()`, audit and async handlers apply) and answers `200` for an id it no longer holds. An older shell shows the message without the button (additive; `protocol_version` stays 1) |
| `ping` | `{"v","type":"ping"}` | Heartbeat, so idle-timeout proxies keep the stream open |
| `chrome` | `{"v","type":"chrome","title","favicon"}` | `ctx.title` / `ctx.favicon` changed (IND-152): the shell sets the tab's title and icon. `title` is the whole title, or `null` for the app's own; `favicon` is a same-origin URL `api/brand/favicon/<name>` (relative to the document) or `null` for the app's own icon. It is sent to the session that changed them only, and a fresh `init` carries the current values in its `chrome` key (and resets them to the app's own when the key is absent), so a reconnect or a new session never shows a stale title. The shell applies only a favicon under `api/brand/favicon/`. An older shell ignores the message and the key (additive; `protocol_version` stays 1) |
| `reconnect` | `{"v","type":"reconnect","after_ms"}` | This process is draining for a rollout (IND-201): the shell closes the stream and opens a new one after `after_ms` (plus up to half a second of jitter), landing on whichever process the platform sends it to next. It has no SSE `id` (it is not state, nothing resumes from it). While the old process still listens, the new stream is refused with `503` and the shell retries with a growing delay, then shows "Still reconnecting…" once. An older shell ignores the message and is simply disconnected when the drain ends, then reconnects as for any dropped stream (additive; `protocol_version` stays 1) |
| `signed_out` | `{"v","type":"signed_out"}` | The caller's login ended (`ctx.sign_out()` or `Principal.expires_at`); the server closes the stream after it, and the shell stops reconnecting and shows a signed-out page (secure apps, ADR-0033) |

A patch `change` is one of:

```json
{ "target": "n3", "props": { "text": "hello" } }        // replace/merge props
{ "target": "n7", "append": { "text": "next token " } } // append a delta onto a prop
{ "target": "n9", "append": { "items": [ ... ] }, "trim": { "items": 1000 } } // bounded
```

`props` merges the given keys into the node's current props. `append` concatenates
a delta onto an existing prop: a **string** delta grows a streamed string prop
(a `streamtext`'s `text`, token by token) and a **list** delta grows a streamed
list prop (a `chart`'s `data`, point by point). Either way a streamed value costs
O(delta) rather than resending the whole prop (ADR-0011, ADR-0018).

An optional `trim` on a change (`{"<prop>": N}`) caps each named array prop to its
newest `N` entries after the append, so a live log stays bounded in the browser. It is
additive: a shell that ignores it only keeps more rows. A `Stream`-bound prop (a `list`
fed by `indah.Stream`) is sent this way, and the server holds a burst of appends for
about 100 ms and sends them as **one** patch, so tens of rows a second make about ten
frames a second (ADR-0026).

### Resume

State-bearing messages (`patch`, `error`, `toast`) are tagged on the wire with an SSE
`id:` — `<epoch>-<offset>`: the per-stream offset, qualified by a random id for the
server-side hub that issued it. When an `EventSource` reconnects it sends the last id
back as `Last-Event-Id`, and the server replays the messages the client missed. If
the client's offset has been evicted from the buffer, **or the epoch is not this
hub's** (the server restarted, so the offset means nothing), the server falls back to a
fresh `init` (always correct, because a `StreamText` snapshot carries its full
accumulated text). A bare integer id (no epoch) is still accepted and skips the epoch
check. `ping` and the `init` sent on connect carry no id (a mid-stream `init`, above, does). See ADR-0011.

### Drain

A process that is shutting down for a rollout (SIGTERM under `launch()` or `uvicorn app:app`, or the
app's own `await app.state.drain.run()`) drains for `create_app(drain_seconds=)` (default 10):

- `GET /ready` answers `503`.
- A new `GET /api/stream`, and a `POST /api/event` for a session the process does not hold, are refused
  with `503 {"ok":false,"error":"draining"}` and `Retry-After: 1`, before any session is built.
- `POST /api/event` for a session the process already holds still works, so a tab can finish what it
  was doing.
- Every open stream is sent one `reconnect` message with its own `after_ms` (between 100 ms and 5 s,
  spread over the first half of the drain), so tabs do not all arrive at the next process at once.
- When no stream is open any more, or `drain_seconds` have passed, the streams still open are ended
  and the process exits. With no stream open the drain is over at once.

`POST api/session` (a secure app's token exchange) keeps working while draining: it creates no
session, and a reconnecting tab needs it to reach the next process.

## Client → server events (HTTP POST)

`POST /api/event` with:

```json
{ "component": "n3", "event": "input", "payload": { "value": 7 }, "sid": "…" }
```

- `component` — the node id the event came from.
- `event` — the event name (e.g. `click`, `input`, `change`).
- `payload` — event data; value-bearing inputs send `{ "value": ... }`.
- `sid` — the sender's session id (see [Sessions](#sessions)). Required, except on an app
  built on one explicit shared `Session` (`create_app(session=)`), where an omitted `sid` lands
  on that session. On any other app an event with no `sid` is rejected `400`; nothing falls
  through to a shared `default` session.

The body must be sent as `Content-Type: application/json` (parameters such as `charset` are
fine). Anything else, including `text/plain`, a form or multipart type, or no type at all, is
rejected `415` before the body is read. That keeps a cross-site "simple" request (one a browser
sends without a preflight) from reaching the handler.

A handler that refuses the caller (`guard(...)` or `ctx.require(...)`, ADR-0035) makes the
request answer `403`; the tab also receives a `toast` of kind `warn`.

The stream is what makes a session, so an event (and an upload) whose `sid` this process does not
hold is answered `409` with `{"ok": false, "error": "unknown_session"}`, and nothing is created.
That happens after a restart or an eviction, and with several processes and no affinity when the
request reaches a process that does not hold the tab's session. The shell reacts by opening
`api/stream` again (a fresh `init`) and showing one toast; it recovers at most once every few
seconds. The refusals above come first on a secure app (`401`, `403`), and a signed id is bound to
its principal, so the `409` says nothing about anyone else's sessions. An app built on one shared
`Session` (`create_app(session=)`) has nothing to be unknown and is unchanged. A new status on an
existing route is additive: `protocol_version` stays 1.

### Route hint

With several machines behind one address, an event must reach the machine that holds the tab's
stream. When the server's route hint is on (Fly, with `INDAH_CLUSTER_SECRET` set; ADR-0043, IND-197),
every `init` carries `"route": {"hint", "node", "transport"}`. `hint` is the machine id (letters and
digits, up to 32), `node` is the process's opaque node id, and `transport` is `"fly"`: the client
should send the hint back on every `POST api/event` and `POST api/upload` as the request header
`X-Indah-Route: <hint>` and, for `"fly"`, also `fly-force-instance-id: <hint>`, which Fly Proxy
obeys. The client keeps the latest hint in memory; each `init` replaces it, and an `init` without
`route` clears it. A file URL the server mints carries `?r=<hint>`; a GET for it that reaches a
machine that does not hold the session is answered with `fly-replay: instance=<hint>` (status
`409`, so it is loud where there is no Fly Proxy to replay it) and never replayed twice. The
server ignores `X-Indah-Route` itself: it does not forward.

A client that gets `409` `owner_unreachable` (reserved for the Kubernetes forwarder, not sent yet),
`409` `unknown_session`, or, when it sent `fly-force-instance-id`, a `400` that is not indah's own
JSON (Fly's answer for a machine that no longer exists) should open `api/stream` again for a fresh
`init`; the shell does, once every few seconds. Everything here is additive: an older shell ignores
`route` and sends no hint, which behaves as before. `protocol_version` stays 1.

An app with `Limits` (ADR-0037) may also answer `429` (with `Retry-After`) on `api/event`,
`api/upload` and `api/stream` when an address is over its rate, or has too many streams open;
nothing is created for such a request. A client should back off for `Retry-After` seconds.

A malformed body is rejected `400`; a body that does not validate, `422`; an event
for an unknown component or event, `400`. A body larger than `max_event_bytes`
(`create_app` argument, default 1 MiB) is rejected `413` before it is parsed. A handler that raises does not take the
UI down: the traceback is logged server-side and an `error` message is pushed.

### Ephemeral props

A component can mark a prop *ephemeral* (ADR-0036; `SecretReveal.value` is the one built in).
The server sends it to the open stream as a normal `patch`, but never keeps it: it is left out
of the `init` snapshot, and the patch gets an SSE offset but is not put in the resume history.
A client that reconnects, resumes or reloads therefore never receives it, and the shell shows
nothing until the app sets it again. Clearing (`null`) carries no secret and is replayed like any
patch. A client needs no special handling beyond treating an absent ephemeral prop as empty.

### Secure apps

With `create_app(secure=True)` (ADR-0033) the session id is a signed token, not a browser-minted
id. The shell first calls `POST /api/session` with `{"resume": <old token or null>}` and
receives `{"ok": true, "token": "<sid>.<signature>", "user": {"id", "name"}}`; a `resume` that
still verifies for the same caller comes back unchanged (so a reload keeps its session). The
shell learns the app is secure from `"secure": true` in `window.__INDAH_CHROME__`, and sends the
token wherever it would send a `sid`. Every route then identifies the caller first. A request
with no authenticated principal, or with no session id, is rejected `401` (an id-less request
never falls back to the default session). A token that does not verify for the caller (forged,
tampered, or another user's) is rejected `403`. A secure app also rejects a cross-origin request (a cross-site `Sec-Fetch-Site`, or an `Origin` that is neither its own nor in `allowed_origins`) with `403` on every state-changing route, `api/stream` and `api/file`; a download of another principal's file is `404`. These are plain
HTTP statuses on the existing routes, not protocol messages.

## File upload and download

Binary rides its own routes, not the JSON event path, so a file never bloats an
event or the reactive path (ADR-0017). Both are Tier 0.

### Upload (`POST /api/upload`)

A `multipart/form-data` body with these fields:

- `component` — the id of the `upload` node the file is for (required).
- `sid` — the sender's session id (optional; the default session otherwise).
- `file` — the uploaded file part; repeat the field for several files (a `multiple`
  upload).

The server hands the bytes to that component's handler as the app's `upload` event,
and the result flows back over that session's SSE stream (e.g. `patch`es setting an
image, a label, a download link). The response is JSON: `{"ok": true, "files":
[<filename>, ...]}`.

A missing/unknown `component` is rejected `400`; a file larger than the server cap
(`create_app(max_upload_mb=…)`, default 25 MB) is rejected `413` before it is
buffered.

### Download (`GET /api/file/{sid}/{token}`)

When the app hands a file back (a generated CSV, an image), indah stores the bytes
in that session and exposes them at this URL. The response body is the bytes, with
the file's `Content-Type` and a `Content-Disposition: attachment; filename="…"`.
The `token` is unguessable and the file lives in one session's store, so it is
reachable only through that session (an unknown `sid` or `token` is `404`). The URL
is document-relative, so it resolves behind Colab/Runpod proxy base paths. With the route hint on
(see "Route hint") the URL ends in `?r=<machine id>`; the owner ignores it.

## Built-in component types

| `type` | Kind | Key props | Events (payload) |
|--------|------|-----------|------------------|
| `column` | container | optional `gap` (a CSS length) | — |
| `card` | container | `title` (a surface panel); optional `variant` (`flat` / `tonal`; absent = outlined) and `padding` (a CSS length) | — |
| `spacer` | layout | optional `size` (a CSS length; absent = grows to fill the free space) | — |
| `divider` | layout | optional `vertical` | — |
| `skeleton` | display | optional `lines` (default 3), `height` (a CSS length, default 1rem): grey placeholder bars, the last one shorter; announced as busy | — |
| `text` | display | `text`, or `markdown:true` + `blocks:[node]` (a safe tree); optional `variant` (plain text only: `title` / `label` / `caption` / `mono` / `readout`; absent = body text, ADR-0040) | — |
| `button` | input | `label`, `variant` (`filled` default / `tonal` / `ghost`), `confirm` (text: the shell asks first and posts `click` only once accepted) | `click` |
| `slider` | input | `value`, `min`, `max`, `step`, `label` | `input` `{value}` |
| `textinput` | input | `value`, `placeholder`, `label` | `input` `{value}` |
| `textarea` | input | `value`, `placeholder`, `label`, `rows` | `input` `{value}` (debounced 150 ms, flushed on blur) |
| `codeeditor` | input | `value`, `language` (`json`/`yaml`/`text`), `readOnly`, `lint`, `height`, `label`, `placeholder`, `format` (a Format button), `save` (Ctrl/Cmd-S) | `input` `{value}` (debounced 150 ms, flushed on blur), `format` `{value}` (JSON re-indent, key order kept), `save` `{value}` |
| `select` | input | `value`, `options:[{value,label}]`, `label` | `change` `{value}` |
| `checkbox` | input | `checked`, `label` | `change` `{value}` |
| `switch` | input | `checked`, `label` (a `role=switch` toggle) | `change` `{value}` |
| `shortcuts` | invisible | `keys:[{keys,label}]` (canonical key specs, see `indah.keys`) | `press` `{keys}` |
| `secretreveal` | display, event | `label`; `value` (**ephemeral**, see below) | `dismiss` |
| `badge` | display | `text`, `tone` (`neutral`/`ok`/`warn`/`err`/`info`) | — |
| `code` | display | `text`; optional `language` (a header label), `label` (accessible name, default "Code"), `copy` (`false` hides the Copy button; sent only when false). Copy is handled in the shell: the plain text goes to the clipboard and a local "Copied" toast shows, with no event to the server | - |
| `marked` | display | `runs:[[text], [text, tone], [text, tone, label], ...]` (the texts joined are the plain text; `tone` is `neutral`, `ok`, `warn`, `err` or `info`; a run is built on the server by `indah.marked_runs`, offsets in code points); optional `label` (accessible name) | - |
| `steps` | display | `items:[[label, state, detail], ...]` (`state` is `done`, `current`, `skipped`, `off` or `pending`; built on the server by `indah.steps_items`); optional `orientation` (`horizontal`; vertical is the default), `size` (`compact`; normal is the default), `label` (accessible name). Display only | - |
| `empty` | display | `title`, `body`; `hasAction` when the first child is the action. Children render between the text and the action | - |
| `number` | input | `value`, `min`, `max`, `step`, `label` | `input` `{value}` |
| `radio` | input | `value`, `options:[{value,label}]`, `label` | `change` `{value}` |
| `multiselect` | input | `value:[...]`, `options:[{value,label}]`, `label` | `change` `{value:[...]}` |
| `chips` | input | `value` (or `[...]` with `multi:true`), `options:[{value,label,count?,tone?}]`, `multi?`, `label` | `change` `{value}` or `{value:[...]}` |
| `segmented` | input | `value`, `options:[{value,label,count?,tone?}]`, `label` | `change` `{value}` |
| `date` | input | `value` (ISO `YYYY-MM-DD`), `label` | `change` `{value}` |
| `upload` | input | `label`, `accept`, `multiple` | file(s) via `POST /api/upload` (not the event path) |
| `download` | display | `label`, `href`, `filename` | — (a link to `GET /api/file/...`) |
| `image` | display | `src`, `alt` | — |
| `imageoverlay` | display | `src`, `alt`, `boxes:[{x,y,w,h,label?,color?,score?}]`, `points:[{x,y,label?,color?}]`, `masks:[{src,opacity}]` (coords in `[0,1]`) | — |
| `audio` | display | `src` (a URL or `data:` URI) | — |
| `chart` | display | `data:[[x,y0,...],...]`, `series:[{label,stroke?}]`, `title`, `xLabel`, `yLabel`, `height` (px or `"fill"`), `points`, `label` | — (grows via `append` patches) |
| `heatmap` | display | `z:[[...],...]` (column-major), `colormap`, `zmin`, `zmax`, `title`, `xLabel`, `yLabel`, `height` (px or `"fill"`), `label` | — (grows via `append` patches) |
| `map` | display | `center:[lat,lon]`, `zoom`, `markers:[{lat,lon,label?,color?,radius?}]`, `polygons:[{points:[[lat,lon],...],label?,color?,fillOpacity?}]`, `polylines:[{points:[[lat,lon],...],label?,color?,weight?}]`, `tileUrl`, `attribution`, `height`, `label` | — (pan/zoom is client-side only, not reported back) |
| `dataframe` | display | `data:{columns:[...],rows:[[...]]}`, `label` | — |
| `table` | display/input | classic: `data:{columns,rows}`, `pageSize`, `selectable`, `value` (selected row index). Rich: `columns:[{field,title,kind,width?,sortable,tones?,timeFormat?,render?,sortKey?,truncate?,maxWidth?,wrap?}]`, `rows:[{...}]`, `rowKey`, `height`, `search`, `columnToggle`, `follow`, `pageSize`, `selectable`, `value` (selected row key) | `select` `{index}` or, in rich mode, `{key}` |
| `stat` | display | `value`, `label`, `delta`, `help` | — |
| `streamtext` | display | `text`, `label` | — (grows via `append` patches) |
| `barstrip` | display | `series` (a list of bars, each a list of segment values), optional `height` (px, default 32), `tones` (a tone per segment; default `info`, then `neutral`), `names` (a name per segment), `labels` (a label per bar), `max` (a fixed scale), `label` | — |
| `infotip` | display | `text` (the note, may be reactive), optional `label` (the icon's accessible name, default "More information") | — |
| `progress` | display | `value` (`null` = indeterminate), `max`, `label` | — |
| `spinner` | display | `active`, `label` | — |
| `list` | display / input | `items:[...]` (a `Signal[list]`), `template` (item render spec), `empty`, `keyField` (when keyed) | each template event, as named in the spec's `on`, with `{value, key, index}` (keyed lists only) |
| `chat` | display | `messages:[{role,content}]`, `pending`, `label` | — |
| `gallery` | display | `images:[{src,alt,caption}]`, `columns`, `label` | — |
| `row` | container | `gap`, `wrap`, `align`; optional `justify` (`start` / `center` / `end` / `between` / `around`) | — |
| `grid` | container | `gap`, and `columns` (a count) or `tracks` (a CSS track list such as `760px 1fr`); optional `rows` (a track list) | — |
| `cell` | container | optional `columns` and `rows` (spans, default 1); its child fills it | — |
| `frame` | container | `width`, `height` (the design box, px), `tracks`, `gap`, `padding`; optional `rows`, `fit` (`shrink` / `width`; absent = contain) and `kiosk` | — |
| `tabs` | container | `labels:[...]`, `active` (index) | `select` `{index}` |
| `sidebar` | container | — (first child is the side region, the rest is main) | — |
| `appshell` | container | optional `railWidth` (a CSS length, default `256px`), `hasTop` (children are `[rail, main]`, plus the top bar third when `hasTop`) | — (the drawer is client-side) |
| `jsontree` | display | `doc:{data,error}` (JSON-safe document or an error line), `expanded`, `search`, `label` | — (all client-side) |
| `diff` | display | `diff:{rows,stats,same,truncated,approximate}`, `mode` (`split`/`unified`), `labels` | — (the layout toggle is client-side) |
| `router` | container | `routes:[pattern]`, `notFound`, `active` (index of the shown child, -1 for none) | `navigate` `{path}` (Back/Forward) |
| `link` | input | `label`, `to` (an in-app path), `active` (the page is showing) | `navigate` `{path}` |
| `navitem` | input | `label`, `to` (an in-app path), `active`, optional `icon` (a short glyph) and `badge` (a count as text; absent or empty means hidden) | `navigate` `{path}` |
| `splitpane` | container | `direction`, `initial`, `min`, `key`, `height` (exactly two children) | — (resize is client-side) |
| `masterdetail` | container | `initial`, `min`, `key`, `title`, `open` (two children: master, detail) | `close` |
| `expander` | container | `label`, `open` | `toggle` `{value?}` |
| `modal` | overlay | `open`, `title`, `size` (`sm`/`md`/`lg`) | `close` |
| `drawer` | overlay | `open`, `title`, `side` (`left`/`right`) | `close` |
| `commandpalette` | input | `shortcut` (one key or combo, canonical form; default `mod+k`), `commands` (`[{id, label, group?, shortcut?, keywords?, confirm?}]`; a live source patches it), optional `placeholder`, `label` | `run` `{command}` (the command's `id`); filtering is client side and never leaves the browser |
| `menu` | input | `trigger`, `items` (`[{id, label, danger?, shortcut?, confirm?, disabled?}]`; a live source patches it), optional `label`, `variant`, `align` (`end`) | `select` `{item}` (the item's `id`) |

`Plot` serialises to an `image` node whose `src` is a PNG `data:` URI rendered on
the Python side, so the shell needs nothing extra to show it.

`imageoverlay` draws model output over an image: detection `boxes`, keypoint
`points`, and segmentation `masks`. All coordinates are **fractions of the image**
(`[0, 1]`), so they line up at any rendered size (the shell positions them as a
percentage of the displayed image). `boxes` and `points` carry an optional `label`
and `color` (a box also an optional `score`); `masks` are overlay images
(`{src, opacity}`) drawn over the base image. The shapes are ordinary reactive props,
so streaming a model's per-frame output is a `props` update over the existing `patch`
op - no new op, no version bump. It is display-only; interactive annotation (the user
*drawing* shapes) is a planned follow-up (ADR-0020).

`map` is a client-side Leaflet map (G5): the shell fetches raster tiles from
`tileUrl` directly in the **viewer's browser**, not through indah's server. `center`/
`zoom` are the map's initial (and, on a later Python-driven change, its "fly to")
view - the viewer's own pan/zoom is not reported back. `markers`, `polygons`, and
`polylines` are plain reactive lists, redrawn wholesale on change, same shape as
`imageoverlay`'s boxes/points; no protocol change to add a marker, since it's still
one prop update. `polylines` renders as an open Leaflet `L.polyline` (not
auto-closed, not filled) - the shape a real route/track needs; `polygons` closes
back to its first point and fills, for a closed area instead.

Charting is **hybrid**
(ADR-0018): `Plot` stays the zero-JS static path (a server PNG, good for static
figures, heatmaps, and spectrograms), while `chart` is the interactive/real-time
path — a client-side chart the pre-built shell draws with a bundled library (uPlot,
inlined at build time; not a Python or runtime dependency, ADR-0004). Both carry
their data in ordinary props, so neither adds a wire capability or moves
`protocol_version`.

A `chart` node holds a line / time-series chart. Its `data` is a list of rows
`[[x, y0, y1, ...], ...]` — the x value first, then one value per y-series — and
`series` names those y-series (`[{"label": "loss", "stroke": "#b5296b"}, ...]`;
`stroke` is optional). `title`, `xLabel`, `yLabel`, `height` (px), and `points`
(show per-point markers) are static encoding props. A whole-dataset change is a
`props` merge of a new `data`; a streamed series grows `data` with an `append`
whose delta is a list of new rows (`{"append": {"data": [[x, y0, ...]]}}`), so a
live curve costs O(point) on the wire. Interactive zoom (drag), hover, and live
redraw run in the browser. The full snapshot always carries the accumulated `data`,
so a resume that falls back to `init` re-renders the whole curve.

A `heatmap` node holds a 2-D field — the interactive/real-time counterpart to a
server-PNG raster `Plot` (spectrograms, heatmaps, attention maps). Its `z` is
**column-major**: a list of columns, `z[x][y]` (so the shell draws column `x` at
horizontal position `x` and colours cell `(x, y)` by `z[x][y]`, with `y = 0` at the
bottom). `colormap` picks a built-in ramp (`"magma"`, `"viridis"`, `"gray"`); `zmin`
/ `zmax` fix the colour scale (omit/`null` to auto-scale). A whole-field change is a
`props` merge of a new `z`; a streamed spectrogram grows `z` with an `append` whose
delta is a list of new columns (`{"append": {"z": [[...]]}}`), so it costs O(column)
on the wire. The snapshot carries the full field for a resume.

The layout containers (`row`, `grid`, `tabs`, `sidebar`, `appshell`, `expander`, `splitpane`) only arrange
existing `children`, so they add no protocol capability: show/active/open state
rides ordinary reactive props merged by the `patch` op. `tabs` and `expander`
render only the active/open region; `textinput`'s `submit` event (Enter) carries no
payload.

`jsontree` carries its whole document in `doc.data`; the shell opens nodes lazily (children are
created only when a node is opened, in chunks of 100), searches in the browser and copies a
JSONPath. A document over 8 MB, or text that is not JSON, arrives as `doc.error`. See ADR-0028.

`diff` carries rows the server computed (`eq`, `del`, `add`, `chg` with `ai`/`bi` character spans,
`skip` with a count); the shell draws them in chunks of 500, split or unified. See ADR-0028 for
the line cap, the clipping and the approximate fallback.

`router` renders only its `active` child. The stream URL carries `&path=<in-app path>`; on a
fresh connect the server starts (or moves) the session there, an automatic reconnect keeps
its current page. An in-app path is the URL path after the app's mount point and must be a
plain `/a/b` (no `//host`, query, fragment or control characters). `link` is a real `<a
href>`; a plain click navigates without a page load. See ADR-0029.

`shortcuts` renders nothing: while mounted it listens for the listed keys (a space-separated
sequence, `mod` = Ctrl/Cmd) and posts `press`. Bare keys are ignored while typing in a field,
and everything is ignored under a `role=dialog`. `?` opens a help overlay of every mounted
map. A map is scoped by where it sits in the tree.

Any node may carry a `tooltip` prop (string): the shell shows it on hover or keyboard
focus, dismissible with Esc, linked by `aria-describedby`; it adds no layout box.

`modal` and `drawer` (ADR-0030) render their `children` only while `open` is true, as a
`role=dialog` `aria-modal` layer with a focus trap; Esc, the backdrop and the close button
post `close`, which clears `open` server-side. Their children stay in the snapshot while
closed, so never put a secret in one. `button.confirm` is a UX guard, not authorization:
the server runs any `click` it receives.

`table` is the interactive superset of `dataframe`: it takes the same
`data:{columns,rows}` and adds sorting and paging (both **client-side** in the shell,
no round-trip) plus row selection. When `selectable` is set (the app bound a
selection signal), clicking a row emits `select` `{index}` — the index into the
source rows — and the server patches back `value` (the selected row index) so the
selection can drive other components. `pageSize` (0 = no paging) sets the page size.
**Rich table (ADR-0027).** A `table` whose props carry `columns` is the rich form: `rows`
is a list of objects (replacing `data`), each with a stable `rowKey` field, and `value`
is the selected row's **key**, so a selection survives sorting and new rows. A column's
`kind` picks a shell-side renderer that never interprets HTML: `text`, `mono`, `badge`
(`tones` maps a value to `ok|warn|err|info|neutral`), `time` (ISO string or epoch ms/s,
shown relative and refreshed live unless the column sets `timeFormat: "clock"`
(`09:14:22.318`) or `"datetime"` (`2026-10-21 09:14:22`), shown in the viewer's local time)
`number`, and `cell`. A `cell` column carries a `render` spec once, in the column (the `List` item
vocabulary and tag allowlist, display only: no `on`), and draws one per row from that row's fields,
so a Stream-fed table sends it once, not per row. It sorts and is searched by `sortKey` (a row
field; for a remote table that is the field the `query` sort names). `truncate` (with `maxWidth`,
default `32ch`) clips a text or cell value with an ellipsis and a tooltip, and `wrap` lets it wrap
(not in a `virtual` table, which has one row height); all are optional and omitted at their
defaults, so `protocol_version` stays 1. `height` makes the body scroll under a
sticky header. `search`, `columnToggle` and `follow` switch on a toolbar that is entirely
client-side (no event): a case-insensitive filter over every column (so streamed rows are
filtered as they land), a column picker remembered in the browser, and follow-the-tail
that pauses when the viewer scrolls up. `actions:[{id,label,variant,confirm?}]` adds a button
per row that posts `action` `{action,key}` (a `confirm` text asks in a dialog first, a UX
guard only); `checkable` adds a checkbox column whose full set of checked keys is posted as
`check` `{keys:[...]}` (and, on a remote table, `check_all` `{}`, which makes the server tick every row matching the current query up to the advertised `checkAllMax`) and echoed back in the reactive `checked` prop. Neither changes
`select`. **Remote mode** (`remote: true`, no `rows`): the shell debounces (150 ms) search, sort
and paging into `query` `{search, filters, sort:[field,"asc"|"desc"]|null, offset, limit, seq}`
and the server answers through one reactive prop, `window` `{rows, total, offset, seq}`, so
rows, total and the window they belong to always arrive together. The shell shows a `window`
only if its `seq` is at least the last `seq` it sent; the server drops a superseded query,
clamps `limit` to 1..500, and pulls an offset past `total` back to the last window.
A table may carry `density` (`comfortable`/`compact`), which sets `data-density` on it; the
app-wide default is `data-density` on `<html>` (`create_app(density=)`, ADR-0014).
`keyboard: true` (rich and remote tables) makes the table one tab stop (`role=grid`, an active row
named by `aria-activedescendant`) driven by `j`/`k`, the arrows, `Home`/`End`, `PageUp`/`PageDown`,
Space (ticks a `checkable` row) and Enter; moving the active row is client-side and posts nothing.
Enter posts `open` `{key}` when `openable: true` (`Table(on_open=)`), else it selects like a click.
Both props are omitted by default, so `protocol_version` stays 1 and an existing table is unchanged.
`virtual: true` (needs `height`) renders only the rows in view plus an overscan between two
spacer rows, at one fixed row height (`--row-h`, 36px). In remote mode the shell requests
block-aligned windows as the viewer scrolls (the same `query`, `limit` up to 500), keeps the
last eight windows, shows placeholders for rows not fetched yet, and discards the cache on a
search or sort change. When the rows are a `Stream` they grow by `append` patches on `rows`
with a `trim`. All of it is additive props, so no `protocol_version` bump.
`stat` is a metric card: a `value` with a `label`, an optional `delta` (the shell
colours it by sign — red when it starts with `-`, otherwise green), and an optional
`help` line. Both carry their data in ordinary props, so no `protocol_version` bump.

The data-driven lists (`list`, `chat`, `gallery`) hold their items in one reactive
prop (a `Signal[list]`), so growing, shrinking, or reordering is an ordinary prop
change over the `patch` op -- no structural children op and no version bump (ADR-0016).
`list` renders each item through an optional `template` (the same render-spec
vocabulary as `_spec`, binding the item's fields) or as text; `chat` and `gallery`
use a built-in per-item template.

A **keyed** list (`keyField` set, IND-110) renders each row under `item[keyField]`, so
adding, removing or reordering keeps the other rows' DOM nodes. A template event carries
the row it came from as `key` and `index` beside `value`; the server refuses a `key` that is
not a current row. A bound `value` on an `input`, `textarea` or `select` in a template is
client-owned while that element has focus (ADR-0013), so a late echo never overwrites typing.
Additive: an older shell ignores `keyField` and renders by `key`/`id`/index as before.

A `text` node with `markdown:true` carries a `blocks` tree instead of `text`: the
backend parses a safe subset of Markdown (server-side) into nodes the shell renders
through its safe DOM builder. A block node is either a string (a text leaf the shell
escapes) or `{"tag": <name>, "children": [node,...]}` (with `href` on an `a`); only
an allowlisted set of tags is ever produced, and raw HTML in the source stays
literal text, so nothing can inject script. This is a prop shape, not a new op — no
version bump.

## Custom components (`_spec`)

A component registered with `register_component()` (ADR-0012) uses a `type` the
shell does not know natively. Its node carries a reserved static prop, `_spec`, a
declarative render spec the shell's generic renderer interprets at runtime — no
shell rebuild, no runtime Node.

```python
import indah

indah.register_component(
    "colorpicker",
    render={
        "tag": "input",  # one allowlisted element
        "attrs": {"type": "color"},  # static attributes
        "bind": {"value": "value"},  # element attr <- node prop
        "on": {"input": {"event": "input", "prop": "value"}},  # DOM event -> round-trip
    },
)

colour = indah.Signal("#ff8800")
picker = indah.custom("colorpicker", value=colour)  # value-bearing, two-way
```

Render spec fields:

| Field | Meaning |
|-------|---------|
| `tag` | The HTML element to create (from a safe allowlist; no `script`/`iframe`/`style`/…). Exactly one of `tag` and `component` |
| `component` | Instead of a tag, a built-in leaf component to draw (`marked` or `steps`; ADR-0016 amendment). It takes only `bind`, `{componentProp: prop}` (for `marked`, `{"runs": "<field>"}`; for `steps`, `items`, and optionally `orientation` and `size`, which are compact and horizontal in a spec unless bound), and no attrs, class, text, literal, `on` or children. Additive: a spec without it is unchanged |
| `attrs` | Static attributes `{name: value}` |
| `class` | A static class string |
| `text` | A node prop name (in a `list`, an item field name) whose value becomes the element's text content |
| `literal` | Fixed text content, shown as written (use it for a button label such as `"Remove"`; not together with `text`) |
| `bind` | `{attribute: prop}` — the element attribute follows the node prop (patched reactively) |
| `on` | `{domEvent: {event, prop}}` — a DOM event posts the indah `event` with `{value}`; `prop` names the bound signal that value is written into, giving the round-trip |
| `children` | Nested render specs (recursive), for a small composite. A nested spec's `on` round-trips like the top-level one |

The spec is validated on registration; a disallowed tag, a type that collides with
a built-in, or a malformed spec is rejected with a `ValueError`. Because the spec
is data (not code) and the tag set is inert, a custom component cannot inject
script or fetch remote code — the dev-tool threat model (Q-sec) is preserved.

The spec cannot express loops or conditionals by design; a component that needs
those is the signal to reach for the deferred hand-written-frontend escape hatch
(ADR-0005/0008), not a larger spec language.

## Module components (`_module`)

A component registered with `module=` instead of `render=` (ADR-0039) carries a reserved static
prop, `_module`, in the `init` snapshot (like `_spec`, once, never in a patch). It tells the shell
which ES module to load and how to wire the element it defines:

```json
{"id": "n7", "type": "tier-rail", "props": {
  "_module": {"url": "api/components/tier-rail.js?v=3f9a1c2b4d5e6f70", "tag": "indah-x-tier-rail",
              "events": ["pick", "change"], "twoWay": ["value"], "fallback": "steps"},
  "steps": ["Seed", "Sprout", "Bloom"], "value": 2}}
```

| Field | Meaning |
|-------|---------|
| `url` | The module, relative to the app root (so it works under any mount prefix), with a content hash in `?v=` so it is cached for good and a new version is fetched at once |
| `tag` | The custom-element name the shell defines, `indah-x-<type>`; the module never names itself |
| `events` | CustomEvent names the shell forwards, each as `POST api/event` with `{"detail": <JSON>}`; others stay in the browser |
| `twoWay` | Props whose value the viewer edits: the shell does not set them while focus is inside the element and applies the latest value on blur (ADR-0013) |
| `fallback` | A prop shown as plain text if the module cannot load or run |

The module's default export is an `HTMLElement` class. The shell sets every other prop as a
property before the element is attached and again on each patch (coalesced to one pass per
frame), and sets `el.cspNonce` to the page's nonce. The route, `GET /api/components/{type}.js`,
answers only for a registered module and a name matching `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`
(anything else is `404`), with an `ETag`, `Cache-Control: public, max-age=31536000, immutable`
when `?v=` matches the module's hash and `no-cache` otherwise. Nothing a client sends becomes a
file path. A module is code that runs with the app's origin: register only your own files. An
older shell ignores `_module`, so this is additive and `protocol_version` stays 1.

## Versioning

`protocol_version` is bumped whenever the wire format changes in a way an older
shell could not parse. The shell rejects a message whose `v` does not match the
version it was built against, showing "protocol mismatch, reload" rather than
silently misrendering. History: `0 → 1` added the `append` op and the `error`
message (Slice V3, ADR-0011); the `_spec` custom-component field was added within
version 1 (Slice V4, ADR-0012) as an additive, backward-compatible extension, and so were the
`_module` field (ADR-0039) and the spec's `component` field with the `marked` type (IND-157) and the `steps` type (IND-163).
