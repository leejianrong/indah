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

Every message on the SSE stream is a JSON object with a `v` field (the protocol
version) and a `type`. The upload and file routes carry bytes, not JSON messages,
so they are outside the versioned message schema (they are additive routes, not a
wire-format change).

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
| `init` | `{"v","type":"init","root":<node>}` | On connect, or a resume that fell back to a full snapshot |
| `patch` | `{"v","type":"patch","changes":[<change>,...]}` | Granular updates to existing nodes |
| `error` | `{"v","type":"error","message":"..."}` | A handler failed; the shell shows a toast |
| `ping` | `{"v","type":"ping"}` | Heartbeat, so idle-timeout proxies keep the stream open |

A patch `change` is one of:

```json
{ "target": "n3", "props": { "text": "hello" } }        // replace/merge props
{ "target": "n7", "append": { "text": "next token " } } // append a delta onto a prop
```

`props` merges the given keys into the node's current props. `append` concatenates
a delta onto an existing prop: a **string** delta grows a streamed string prop
(a `streamtext`'s `text`, token by token) and a **list** delta grows a streamed
list prop (a `chart`'s `data`, point by point). Either way a streamed value costs
O(delta) rather than resending the whole prop (ADR-0011, ADR-0018).

### Resume

State-bearing messages (`patch`, `error`) are tagged on the wire with an SSE
`id:` — a per-stream offset. When an `EventSource` reconnects it sends the last id
back as `Last-Event-Id`, and the server replays the messages the client missed. If
the client's offset has been evicted from the buffer, the server falls back to a
fresh `init` (always correct, because a `StreamText` snapshot carries its full
accumulated text). `init` and `ping` carry no id. See ADR-0011.

## Client → server events (HTTP POST)

`POST /api/event` with:

```json
{ "component": "n3", "event": "input", "payload": { "value": 7 }, "sid": "…" }
```

- `component` — the node id the event came from.
- `event` — the event name (e.g. `click`, `input`, `change`).
- `payload` — event data; value-bearing inputs send `{ "value": ... }`.
- `sid` — the sender's session id (optional; see [Sessions](#sessions)). Omitted, the
  event lands on the default session.

A malformed body is rejected `400`; a body that does not validate, `422`; an event
for an unknown component or event, `400`. A handler that raises does not take the
UI down: the traceback is logged server-side and an `error` message is pushed.

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
is document-relative, so it resolves behind Colab/Runpod proxy base paths.

## Built-in component types

| `type` | Kind | Key props | Events (payload) |
|--------|------|-----------|------------------|
| `column` | container | — | — |
| `card` | container | `title` (a surface panel) | — |
| `text` | display | `text`, or `markdown:true` + `blocks:[node]` (a safe tree) | — |
| `button` | input | `label`, `variant` (`filled` default / `tonal` / `ghost`) | `click` |
| `slider` | input | `value`, `min`, `max`, `step`, `label` | `input` `{value}` |
| `textinput` | input | `value`, `placeholder`, `label` | `input` `{value}` |
| `select` | input | `value`, `options:[{value,label}]`, `label` | `change` `{value}` |
| `checkbox` | input | `checked`, `label` | `change` `{value}` |
| `number` | input | `value`, `min`, `max`, `step`, `label` | `input` `{value}` |
| `radio` | input | `value`, `options:[{value,label}]`, `label` | `change` `{value}` |
| `multiselect` | input | `value:[...]`, `options:[{value,label}]`, `label` | `change` `{value:[...]}` |
| `date` | input | `value` (ISO `YYYY-MM-DD`), `label` | `change` `{value}` |
| `upload` | input | `label`, `accept`, `multiple` | file(s) via `POST /api/upload` (not the event path) |
| `download` | display | `label`, `href`, `filename` | — (a link to `GET /api/file/...`) |
| `image` | display | `src`, `alt` | — |
| `chart` | display | `data:[[x,y0,...],...]`, `series:[{label,stroke?}]`, `title`, `xLabel`, `yLabel`, `height`, `points`, `label` | — (grows via `append` patches) |
| `heatmap` | display | `z:[[...],...]` (column-major), `colormap`, `zmin`, `zmax`, `title`, `xLabel`, `yLabel`, `height`, `label` | — (grows via `append` patches) |
| `dataframe` | display | `data:{columns:[...],rows:[[...]]}`, `label` | — |
| `table` | display/input | `data:{columns,rows}`, `pageSize`, `selectable`, `value` (selected row index) | `select` `{index}` |
| `stat` | display | `value`, `label`, `delta`, `help` | — |
| `streamtext` | display | `text`, `label` | — (grows via `append` patches) |
| `progress` | display | `value` (`null` = indeterminate), `max`, `label` | — |
| `spinner` | display | `active`, `label` | — |
| `list` | display | `items:[...]` (a `Signal[list]`), `template` (item render spec), `empty` | — |
| `chat` | display | `messages:[{role,content}]`, `pending`, `label` | — |
| `gallery` | display | `images:[{src,alt,caption}]`, `columns`, `label` | — |
| `row` | container | `gap`, `wrap`, `align` | — |
| `grid` | container | `columns`, `gap` | — |
| `tabs` | container | `labels:[...]`, `active` (index) | `select` `{index}` |
| `sidebar` | container | — (first child is the side region, the rest is main) | — |
| `expander` | container | `label`, `open` | `toggle` `{value?}` |

`Plot` serialises to an `image` node whose `src` is a PNG `data:` URI rendered on
the Python side, so the shell needs nothing extra to show it. Charting is **hybrid**
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

The layout containers (`row`, `grid`, `tabs`, `sidebar`, `expander`) only arrange
existing `children`, so they add no protocol capability: show/active/open state
rides ordinary reactive props merged by the `patch` op. `tabs` and `expander`
render only the active/open region; `textinput`'s `submit` event (Enter) carries no
payload.

`table` is the interactive superset of `dataframe`: it takes the same
`data:{columns,rows}` and adds sorting and paging (both **client-side** in the shell,
no round-trip) plus row selection. When `selectable` is set (the app bound a
selection signal), clicking a row emits `select` `{index}` — the index into the
source rows — and the server patches back `value` (the selected row index) so the
selection can drive other components. `pageSize` (0 = no paging) sets the page size.
`stat` is a metric card: a `value` with a `label`, an optional `delta` (the shell
colours it by sign — red when it starts with `-`, otherwise green), and an optional
`help` line. Both carry their data in ordinary props, so no `protocol_version` bump.

The data-driven lists (`list`, `chat`, `gallery`) hold their items in one reactive
prop (a `Signal[list]`), so growing, shrinking, or reordering is an ordinary prop
change over the `patch` op -- no structural children op and no version bump (ADR-0016).
`list` renders each item through an optional `template` (the same render-spec
vocabulary as `_spec`, binding the item's fields) or as text; `chat` and `gallery`
use a built-in per-item template.

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
| `tag` | The HTML element to create (from a safe allowlist; no `script`/`iframe`/`style`/…) |
| `attrs` | Static attributes `{name: value}` |
| `class` | A static class string |
| `text` | A node prop name whose value becomes the element's text content |
| `bind` | `{attribute: prop}` — the element attribute follows the node prop (patched reactively) |
| `on` | `{domEvent: {event, prop}}` — a DOM event posts the indah `event` with `{value}`; `prop` names the bound signal that value is written into, giving the round-trip |
| `children` | Nested render specs (recursive), for a small composite |

The spec is validated on registration; a disallowed tag, a type that collides with
a built-in, or a malformed spec is rejected with a `ValueError`. Because the spec
is data (not code) and the tag set is inert, a custom component cannot inject
script or fetch remote code — the dev-tool threat model (Q-sec) is preserved.

The spec cannot express loops or conditionals by design; a component that needs
those is the signal to reach for the deferred hand-written-frontend escape hatch
(ADR-0005/0008), not a larger spec language.

## Versioning

`protocol_version` is bumped whenever the wire format changes in a way an older
shell could not parse. The shell rejects a message whose `v` does not match the
version it was built against, showing "protocol mismatch, reload" rather than
silently misrendering. History: `0 → 1` added the `append` op and the `error`
message (Slice V3, ADR-0011); the `_spec` custom-component field was added within
version 1 (Slice V4, ADR-0012) as an additive, backward-compatible extension.
