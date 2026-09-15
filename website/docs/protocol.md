# The JSON UI protocol

This is the wire contract between the Python backend and the browser shell. It is a
**versioned, public contract**: the shell checks the version on every message and
refuses a mismatch, so a hand-written frontend or a custom component can target it
without reading the framework's internals.

Current `protocol_version`: **1**.

!!! note "Source of truth"
    The reference implementation lives in `src/indah/protocol.py`. Where this page
    and the code disagree, the code wins and this page is the bug.

## Transport

One SSE stream carries server → client messages; client → server events are plain
HTTP POSTs. Both ride one port so Colab's and Runpod's proxies pass them.

- `GET /api/stream` - the SSE stream (server → client).
- `POST /api/event` - one UI event (client → server).

Every message is a JSON object with a `v` field (the protocol version) and a
`type`.

## Nodes

The UI is a tree of nodes. A node is:

```json
{ "id": "n3", "type": "slider", "props": { "...": "..." }, "children": [] }
```

- `id` - a stable, server-assigned identifier (`n0`, `n1`, ... in tree pre-order).
  Patches and events address nodes by this id.
- `type` - the component type, which tells the shell how to render the node.
- `props` - the node's current properties.
- `children` - child nodes (only container types use them).

## Server → client messages (over SSE)

| Type | Shape | When |
|------|-------|------|
| `init` | `{"v","type":"init","root":<node>}` | On connect, or a resume that fell back to a full snapshot |
| `patch` | `{"v","type":"patch","changes":[<change>,...]}` | Granular updates to existing nodes |
| `error` | `{"v","type":"error","message":"..."}` | A handler failed; the shell shows a toast |
| `ping` | `{"v","type":"ping"}` | Heartbeat, so idle-timeout proxies keep the stream open |

A patch `change` is one of:

```json
{ "target": "n3", "props": { "text": "hello" } }
{ "target": "n7", "append": { "text": "next token " } }
```

`props` merges the given keys into the node's current props. `append` concatenates
a delta onto a single string prop, so a streamed value costs O(delta) per token
rather than resending the whole string.

### Resume

State-bearing messages (`patch`, `error`) are tagged on the wire with an SSE `id:`
- a per-stream offset. When an `EventSource` reconnects it sends the last id back
as `Last-Event-Id`, and the server replays the messages the client missed. If the
client's offset has been evicted from the buffer, the server falls back to a fresh
`init` (always correct, because a `StreamText` snapshot carries its full
accumulated text). `init` and `ping` carry no id.

## Client → server events (HTTP POST)

`POST /api/event` with:

```json
{ "component": "n3", "event": "input", "payload": { "value": 7 } }
```

- `component` - the node id the event came from.
- `event` - the event name (`click`, `input`, `change`).
- `payload` - event data; value-bearing inputs send `{ "value": ... }`.

A malformed body is rejected `400`; a body that does not validate, `422`; an event
for an unknown component or event, `400`. A handler that raises does not take the
UI down: the traceback is logged server-side and an `error` message is pushed.

## Built-in component types

| `type` | Kind | Key props | Events (payload) |
|--------|------|-----------|------------------|
| `column` | container | - | - |
| `text` | display | `text` | - |
| `button` | input | `label` | `click` |
| `slider` | input | `value`, `min`, `max`, `step`, `label` | `input` `{value}` |
| `textinput` | input | `value`, `placeholder`, `label` | `input` `{value}` |
| `select` | input | `value`, `options:[{value,label}]`, `label` | `change` `{value}` |
| `image` | display | `src`, `alt` | - |
| `dataframe` | display | `data:{columns,rows}`, `label` | - |
| `streamtext` | display | `text`, `label` | - (grows via `append`) |

`Plot` serialises to an `image` node whose `src` is a PNG `data:` URI rendered on
the Python side, so the shell needs nothing extra to show it.

## Custom components (`_spec`)

A component registered with `register_component()` uses a `type` the shell does not
know natively. Its node carries a reserved static prop, `_spec`, a declarative
render spec the shell's generic renderer interprets at runtime - no shell rebuild,
no runtime Node. See [Custom components](custom-components.md) for the spec fields
and the safety model.

## Versioning

`protocol_version` is bumped whenever the wire format changes in a way an older
shell could not parse. The shell rejects a message whose `v` does not match the
version it was built against, showing "protocol mismatch, reload" rather than
silently misrendering.

History: `0 → 1` added the `append` op and the `error` message; the `_spec`
custom-component field was added within version 1 as an additive,
backward-compatible extension.
