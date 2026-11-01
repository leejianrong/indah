# Your first dashboard

In this tutorial we build a live request log: a table that fills as requests arrive, in every open
tab, where you can click a row and reject a call. We build it in three steps, and each step is a
complete file you can run.

You need indah installed (see the [Quickstart](quickstart.md)). The later steps also use
Starlette, which indah already depends on.

## A table of requests

Save this as `log.py`:

```python
import indah

rows = [
    {"id": "a1", "result": "hit", "ms": 4},
    {"id": "a2", "result": "miss", "ms": 1200},
    {"id": "a3", "result": "hit", "ms": 6},
]

table = indah.Table(
    rows=rows,
    key="id",
    columns=[
        indah.Col("id", kind="mono"),
        indah.Col("result", kind="badge", tones={"hit": "ok", "miss": "warn"}),
        indah.Col("ms", kind="number"),
    ],
)
page = indah.Column(children=[indah.Text("# Requests", markdown=True), table])

if __name__ == "__main__":
    indah.launch(indah.create_app(session=indah.Session(page)))
```

Run `python log.py` and open the printed URL. You see a heading and a table with three rows. The
`result` column shows each value as a badge, toned `ok` for `hit` and `warn` for `miss`, and `ms` is right-aligned.

`key="id"` tells the table which field identifies a row. Everything later relies on it.

## Make it live

Real requests arrive while the page is open. Replace `log.py` with this file. It publishes a fake
request every half second to a `Topic`, which every tab follows, and mounts the dashboard under
`/ui` of a parent app.

```python
import asyncio
import contextlib
import itertools
import random

import indah
from starlette.applications import Starlette
from starlette.routing import Mount

requests = indah.Topic("requests", replay=500)  # app level: every tab follows it
counter = itertools.count(1)


async def produce():
    while True:
        miss = random.random() < 0.3
        requests.publish(
            {
                "id": f"r{next(counter)}",
                "result": "miss" if miss else "hit",
                "ms": random.randint(900, 2400) if miss else random.randint(1, 9),
            }
        )
        await asyncio.sleep(0.5)


def build(ctx: indah.Context) -> indah.Session:
    rows = ctx.tail(requests, limit=500)  # this tab's bounded, live copy
    table = indah.Table(
        rows=rows,
        key="id",
        follow=True,
        height="20rem",
        columns=[
            indah.Col("id", kind="mono"),
            indah.Col("result", kind="badge", tones={"hit": "ok", "miss": "warn"}),
            indah.Col("ms", kind="number"),
        ],
    )
    return indah.Session(indah.Column(children=[indah.Text("# Requests", markdown=True), table]))


@contextlib.asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(produce())
    try:
        yield
    finally:
        task.cancel()


ui = indah.create_app(session_factory=build, title="requests", spa=True, proxy_flush=False)
app = Starlette(routes=[Mount("/ui", app=ui)], lifespan=lifespan)

if __name__ == "__main__":
    indah.launch(app)
```

Run `python log.py` and open `http://127.0.0.1:<port>/ui/` (the printed URL, with `/ui/` added).
Rows appear about twice a second and `follow=True` keeps the newest in view. Open a
second tab: it shows the same history, and a row you click in one tab is not selected in the other.

Three things changed:

- **`requests` is a `Topic`.** It lives at app level, and anything can `publish` to it. `replay=500`
  keeps the last 500, so a new tab starts with history.
- **`ctx.tail(requests, limit=500)`** gives this tab its own bounded, live copy. Only new rows go
  over the wire, so a long log stays cheap. It is released when the tab closes.
- **The producer starts in the parent's `lifespan`.** A mounted app does not run its own lifespan,
  so background tasks belong to the parent.

!!! note "If the table stays empty"

    The page is at `/ui/`, not `/`. With the mount in place, `/` is the parent app and has no
    route.

## Click a row and act on it

Last, we let the viewer select a call and reject it. Only `build` changes; the rest of the file is
the same, so here is the whole file again:

```python
import asyncio
import contextlib
import itertools
import random

import indah
from starlette.applications import Starlette
from starlette.routing import Mount

requests = indah.Topic("requests", replay=500)  # app level: every tab follows it
counter = itertools.count(1)


async def produce():
    while True:
        miss = random.random() < 0.3
        requests.publish(
            {
                "id": f"r{next(counter)}",
                "result": "miss" if miss else "hit",
                "ms": random.randint(900, 2400) if miss else random.randint(1, 9),
            }
        )
        await asyncio.sleep(0.5)


def build(ctx: indah.Context) -> indah.Session:
    rows = ctx.tail(requests, limit=500)  # this tab's bounded, live copy
    picked = indah.Signal(None)  # the key of the clicked row
    rejected = indah.Signal([])

    def reject(key):  # a row can be gone by the time the click lands
        rejected.set([*rejected.value, key])

    table = indah.Table(
        rows=rows,
        key="id",
        selected=picked,
        follow=True,
        height="20rem",
        actions=[indah.RowAction("Reject", reject, confirm="Reject this call?")],
        columns=[
            indah.Col("id", kind="mono"),
            indah.Col("result", kind="badge", tones={"hit": "ok", "miss": "warn"}),
            indah.Col("ms", kind="number"),
        ],
    )
    detail = indah.computed(
        lambda: f"Selected: {picked.value or 'none'} | rejected: {len(rejected.value)}"
    )
    return indah.Session(
        indah.Column(
            children=[
                indah.Text("# Requests", markdown=True),
                table,
                indah.Card(title="Call", children=[indah.Text(detail)]),
            ]
        )
    )


@contextlib.asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(produce())
    try:
        yield
    finally:
        task.cancel()


ui = indah.create_app(session_factory=build, title="requests", spa=True, proxy_flush=False)
app = Starlette(routes=[Mount("/ui", app=ui)], lifespan=lifespan)

if __name__ == "__main__":
    indah.launch(app)
```

Click a row. The card under the table says `Selected: r1 | rejected: 0`, with the id of the row you
clicked. Press **Reject** on a row and a confirmation appears: "Reject this call?". Confirm it and
the card reads `rejected: 1`.

- **`selected=picked`** binds the clicked row's key to a signal, so anything can read it.
- **`RowAction("Reject", reject, confirm=...)`** adds a button on each row. `reject` gets the row's
  key. A row can be gone by the time the click lands (the log trims old rows), so a real handler
  must tolerate a key it no longer has.
- **`indah.computed`** builds the card's text from the two signals, and only the card re-renders when
  either changes.

## Recap

- Give a `Table` rows with a stable `key` and typed `Col`s.
- Publish app-wide data to a `Topic` and follow it per tab with `ctx.tail`.
- Mount the UI under a parent app and run background tasks from the parent's lifespan.
- Bind `selected=` to a signal, and add `RowAction`s for things people do to a row.

## Next

- [Dashboard recipes](dashboards.md) for everything beyond this: a refresh loop per tab, a big
  table with `remote=`, overlays and a command palette, routing, split panes and theming.
- [Host an app for real users](hosting.md) before you put a dashboard on a network.
