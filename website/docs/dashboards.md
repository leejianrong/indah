# Build a dashboard

indah's dashboard features are for apps that live inside a bigger service: a live log, a
queue people act on, a big table, several pages, forms that edit data. The semula demos in
the repo (`make demo-review` serves all of them) are the worked examples, and every snippet
below is taken from them.

## Mount it under your app

Create the UI as its own ASGI app and mount it at a prefix of your service. `spa=True` makes
a deep link such as `/ui/projects/auth` serve the page, so a URL can be opened or reloaded.

```python
from starlette.applications import Starlette
from starlette.routing import Mount
import indah

ui = indah.create_app(
    session_factory=build,  # called once per open tab
    title="my service",
    theme=indah.Theme(light={"primary": "#1f6feb"}, dark={"primary": "#79b8ff"}),
    density="compact",  # tighter tables across the app
    spa=True,
    proxy_flush=False,  # no window-buffering proxy in front of you
)
app = Starlette(routes=[Mount("/ui", app=ui)])
```

A mounted app does not run its own lifespan, so start background tasks from the parent's
lifespan. Pass `proxy_flush=False` only when no proxy such as Colab's sits in front.

`session_factory` may take no argument or one `Context`. The `Context` is the per-tab handle
for everything below: toasts, live feeds, the current route.

```python
def build(ctx: indah.Context) -> indah.Session:
    ...
    return indah.Session(root)
```

## Push live data to every tab

A `Topic` lives at app level. Any task publishes to it, and each tab follows it, so every tab
updates while per-tab state (filters, selection) stays per tab.

```python
requests = indah.Topic("requests", replay=1000)  # app level, keeps the last 1000

requests.publish({"id": "01J...", "result": "hit"})  # from a task on the event loop
requests.publish_threadsafe({...})  # from any other thread


def build(ctx):
    rows = ctx.tail(requests, limit=1000)  # a bounded Stream, seeded from history
    waiting = ctx.latest(pending, initial=[])  # a signal with the newest item
```

A `Stream` sends only new rows to the browser, so a growing log costs O(new rows), not
O(all rows). Both calls are released when the tab closes.

## Show and act on rows with `Table`

The rich `Table` takes dict rows with a stable key and typed columns.

```python
from indah import Table, Col, RowAction, Signal

checked = Signal([])
table = Table(
    rows=rows,  # a list, a signal, or a Stream
    key="id",
    columns=[
        Col("ts", "When", kind="time"),  # "3s ago", refreshed live
        # Col("ts", "At", kind="time", time_format="clock"),  # 09:14:22.318, viewer's local time
        Col("id", kind="mono"),
        Col("result", kind="badge", tones={"hit": "ok", "miss": "warn", "error": "err"}),
        Col("ms", kind="number"),
    ],
    height="24rem",  # the body scrolls under a sticky header
    search=True,  # a filter box
    column_toggle=True,
    follow=True,  # keep the newest row in view (streamed rows)
    actions=[RowAction("Reject", reject, confirm="Reject this call?")],
    checked=checked,  # a checkbox column plus select-all
)
```

- `RowAction(label, on_click, confirm=)` calls `on_click(key)`. A row can be stale by the time
  the click lands, so the handler must tolerate a key that no longer exists.
- `density="compact"` shrinks one table. Pass a `Signal[str]` to let the viewer toggle it.

### Tens of thousands of rows: `remote=` and `virtual=`

For more rows than one prop should carry, give the table a loader. It is asked for one window
at a time, with the viewer's search, sort and offset.

```python
def loader(q: indah.TableQuery):
    rows, total = db.page(search=q.search, sort=q.sort, offset=q.offset, limit=q.limit)
    return rows, total


table = Table(
    columns=[Col("id", kind="mono"), Col("name")],
    key="id",
    remote=loader,  # sync loaders run in a worker thread
    virtual=True,  # render only the rows in view
    height="30rem",
    search=True,
    reload_on=[project],  # re-run the last query when a signal changes
)
```

Things to know about a remote table:

- Sorting and search are the loader's job. A loader that ignores them is a bug in your app.
- `follow=True` is not available with `remote=` and raises a `ValueError`.
- The header checkbox ticks only the rows on screen. With `checked=` the table shows
  "N of M selected" and a **Select all M** button that gathers every match for the current
  search, up to 10,000 rows. Over that, the table asks the viewer to narrow the search.
- `query=` mirrors the latest `TableQuery` into a signal, and `page_size` sets the window.

## Slow handlers: keep the loop free

indah serves every tab from one event loop. A plain `def` handler runs on that loop, and a
blocking call inside an `async def` handler does too, so while it runs **no tab on the server
updates**. A `time.sleep(5)`, a `requests.get`, a synchronous database driver or a model call
all stall everyone. Awaiting is fine: `await asyncio.sleep(5)` yields to the other tabs.

Run blocking work in a thread and await it:

```python
import asyncio
import sqlite3

import indah

rows = indah.Signal([])


def query(sql: str) -> list:  # blocking: never call it on the loop
    with sqlite3.connect("app.db") as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(sql)]


async def refresh():
    rows.set(await asyncio.to_thread(query, "select id, text from entries limit 100"))


page = indah.Column(
    children=[
        indah.Button("Refresh", on_click=refresh),
        indah.Table(rows=rows, key="id", columns=[indah.Col("id"), indah.Col("text")]),
    ]
)
```

`Table(remote=loader)` already does this for you: a plain `def` loader runs in a worker thread,
so a blocking database call there is fine. An `async def` loader runs on the loop, so the same
rule applies inside it.

## Overlays, toasts and keys

```python
open_ = indah.Signal(False)

indah.Button("Delete", delete, confirm="Delete this entry?")  # asks first
indah.Modal(title="Conflict", open=open_, size="lg", children=[...])
indah.Drawer(title="Review", open=open_, side="right", children=[...])

ctx.toast("Saved", kind="success")  # info, success, warn or error; ttl=0 sticks
indah.Badge(lambda: f"{n.value} waiting", tone="warn")
indah.Switch(pinned, label="Pinned")
indah.Text("hover me", tooltip="Shown on hover and on keyboard focus")

indah.Shortcuts(
    {
        "j": (next_row, "Next call"),  # the optional text feeds the ? help
        "a": (approve, "Approve"),
        "g l": (go_log, "Go to the log"),  # a sequence
    }
)
```

`confirm=` is a UX guard only: the server still runs any click it receives, so check
authorization in your handler. A toast goes to the current tab only, never put a secret in
one. `Shortcuts` bare keys are ignored while the viewer types or a dialog is open, and a map
is active only while it is in the rendered tree.

## Several pages with `Router`

```python
def build(ctx):
    pages = indah.Router(
        ctx,
        routes={
            "/": overview,
            "/projects/{project}": project_page,
            "/projects/{project}/entries/{entry_id}": entry_page,
        },
        not_found=indah.Text("No such page"),
    )
    nav = indah.Column(
        children=[
            indah.Link(ctx, "Overview", to="/"),
            indah.Link(ctx, "Projects", to="/projects", match="prefix"),
        ]
    )
    return indah.Session(indah.Sidebar(children=[nav, pages]))
```

`ctx.path` is the current page, `ctx.params` holds the route's values, and `ctx.navigate("/x")`
goes there from code. A `Link` is a real `<a href>`, so open-in-new-tab works.

!!! warning "Hidden pages still run"
    Every page is built up front, so a page's reactive code runs even when its route is not
    showing, with no params. Read params with `ctx.params.value.get("project")`, never
    `ctx.params.value["project"]`, and keep expensive work behind a `computed`. Do not put
    anything role-restricted in a page: hidden pages are in the page snapshot.

`{id:int}` converts a segment to an integer. After a server restart an open tab reopens on the
page it is on now.

## Split panes and master-detail

```python
indah.SplitPane(left, right, direction="horizontal", initial=0.4, height="30rem")
indah.MasterDetail(table, detail, open=drawer_open)  # a drawer on a narrow screen
```

## Viewers: `JsonTree` and `Diff`

```python
indah.JsonTree(lambda: entry.value, expanded=2)  # search, collapse all, copy path
indah.Diff(
    old_text,
    new_text,
    mode="split",  # or "unified"
    labels=("cached", "incoming"),
)
```

`Diff` is computed in Python over pretty-printed, key-sorted JSON (text that is not JSON is
compared as it is), so the browser only draws rows. A very large input is truncated and
marked as such.

## Forms that edit data

`TextArea(signal, label=, rows=)` is a multi-line input. Like every input, the browser owns
the text while the viewer is typing in it, so a late echo from the server never overwrites it.

### `CodeEditor` for JSON and YAML

```python
body = indah.Signal('{"model": "gpt-4o"}')

indah.CodeEditor(
    body,
    language="json",  # "json" (default), "yaml" or "text"
    label="Request",
    height="24rem",
    format_button=True,  # JSON only: re-indent, keeping key order
    on_save=save,  # Ctrl/Cmd-S, called with the signal already up to date
)
indah.CodeEditor(old_revision, read_only=True)  # a history snapshot
```

It highlights, indents, closes brackets and quotes, folds, searches, and for JSON marks a
parse error with its position. It is loaded the first time an editor appears, so apps without
one never download it (about 180 KB compressed). A very large body is limited by
`create_app(max_event_bytes=)`, 1 MiB by default. Tab indents; press Ctrl/Cmd-M to switch
that off so the keyboard can leave the editor. If the editor cannot load, a plain text area
with the same binding is shown.

For a variable number of editable rows, use a keyed `List`:

```python
rows = indah.Signal([{"id": "m1", "role": "user", "content": "hi"}])


def on_item(key, event, value):  # sync or async
    if event == "remove":
        rows.set([r for r in rows.value if r["id"] != key])
    elif event == "content":
        rows.set([{**r, "content": value} if r["id"] == key else r for r in rows.value])


indah.List(rows, key="id", item=ROW_SPEC, on_item=on_item)
```

Every item is a dict with a unique `id`. Adding, removing or reordering keeps the other rows,
and the cursor in a row being typed in. `ROW_SPEC` is a render spec (see
[Custom components](custom-components.md)); each `on={...}` event reaches `on_item` with the
row's key. A keyed list takes a signal or a callable, not a `Stream`.

## Theme and density

`indah.Theme(light={...}, dark={...}, radius=, font=)` overrides the design tokens, and
`create_app(density="compact")` tightens tables. See [Design system](design-system.md) for the
token names and what each is for.

## Hosted use

indah keeps one session per open tab, in memory, on the server. Authentication,
authorization and rate limits belong in the app that mounts it for now; the ADRs under
`docs/adr/` (0025 to 0030) describe the decisions behind each feature above.
