# How indah updates the page

indah does not rerun your script when someone clicks. The script runs once per session, builds a
tree of components, and from then on only the parts that depend on a changed value are recomputed
and sent to the browser. This page explains how that works and what it means for the code you write.
For the exact messages, see the [Protocol](protocol.md) reference.

## The script runs once

Take the app from the [Quickstart](quickstart.md): two sliders and a line of text that shows their
sum. When a session starts, indah calls your code, walks the component tree and gives every
component an id. The browser first receives that tree as a snapshot:

```json
{"id": "n0", "type": "column", "children": [
  {"id": "n1", "type": "slider", "props": {"min": 0, "max": 10, "label": "a", "value": 2}},
  {"id": "n2", "type": "slider", "props": {"min": 0, "max": 10, "label": "b", "value": 3}},
  {"id": "n3", "type": "text",   "props": {"text": "a + b = 5"}}
]}
```

(The real message also has `step` and an empty `children` on every leaf; they are left out here.)

After this, your top-level code is never executed again for that session. What stays is the
tree and the signals, held in memory in the server process.

## Signals know who reads them

Each prop that is bound to a signal or a `computed` becomes an effect. An effect records which
signals it read the last time it ran, so a signal always knows its readers. Here the text's prop
reads `total`, and `total` reads `a` and `b`.

When the user moves slider `a` to 7, three things happen:

1. The slider's event writes `7` to `a`.
2. `a` notifies its readers: the slider's own `value` prop and `total`.
3. `total` recomputes, and its reader, the text, re-renders.

The browser receives only what changed:

```json
[{"target": "n1", "props": {"value": 7}},
 {"target": "n3", "props": {"text": "a + b = 10"}}]
```

Slider `b` and the layout are not mentioned. A change addresses a component by id, so the shell
updates that one node. A `computed` only notifies its readers when its value actually changes, so
a recomputation that gives the same answer sends nothing.

## Why Streamlit-style reruns are not the model

A rerun model is easy to reason about, because the page is a function of the script. It costs a
full execution per interaction, and it puts the awkward cases (a long-lived value, a background
task, a streamed answer) outside the model, which is why those apps grow session-state helpers. In
indah the state is long-lived by construction. A live feed, a streaming reply and a button handler
all do the same thing: write to a signal.

The trade is that indah has to keep a dependency graph and a diff correct, and your code has to
change state through signals instead of rebuilding the page. The decision is recorded in
ADR-0003.

## How the changes travel

The browser opens one long-lived `GET api/stream` and receives messages over Server-Sent Events. It
sends clicks and edits as `POST api/event` requests. Both are plain HTTP, which is the reason for
the choice: Google Colab's proxy does not carry WebSockets, and Colab is a first-class target. The
answer to a POST arrives on the stream, not in the POST response, so the page updates the same way
whether the change came from a click, a timer or a background task. Details and the cost of this
choice are in ADR-0002.

If the connection drops, the shell reconnects and the server resumes from where the stream left
off, so a streamed answer is not lost halfway.

## What this means for your code

- **Put state in signals, not in the page.** Anything the page shows and a handler changes should be
  a `Signal`. Reading `.value` inside a `computed` or a prop's function is what registers the
  dependency, so a plain variable you change will not update anything.
- **A handler changes signals and returns.** It does not return new components. To change what
  the page shows, bind the prop that controls it (a text, the options of a `Select`, the rows of a
  `Table`, a button's `disabled`) to a signal or a function of signals.
- **State lives in the process.** Each tab has its own session, held in memory. A restart rebuilds
  it from your session factory, so keep durable data in your own database. For several processes
  read [Run several replicas](hosting-scale.md).
- **Writes are batched in handlers.** A synchronous handler runs inside `batch`, so two writes
  cause one update. After an `await`, or in a background task, use `indah.batch` yourself.
- **A slow handler should be `async`.** The `POST` returns at once and the work runs as a task,
  so the page stays responsive and results arrive as patches.

## Related

- [Quickstart](quickstart.md) to build the app used above.
- [Protocol](protocol.md) for every message and prop.
- ADR-0002 (transport) and ADR-0003 (the reactive model) in the repository's `docs/adr/`.
