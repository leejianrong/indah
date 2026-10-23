# Build a dashboard

indah's dashboard features are for apps that live inside a bigger service: a live log, a
queue people act on, a big table, several pages, forms that edit data. The semula demos in
the repo (`make demo` serves all of them in the Studio, under Full apps) are the worked examples, and every snippet
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

Try it live. Nothing downloads until you press **Run it**.

<indah-live page="overlays/context"></indah-live>

<indah-live page="extend/context"></indah-live>

### Load data before the first paint

The factory may be `async def`. It is awaited, so its data is in the very first snapshot and the
page never shows a dash and then the number:

```python
async def build(ctx: indah.Context) -> indah.Session:
    stats = await fetch_overview()  # a database or HTTP call
    return indah.Session(indah.Column(children=[indah.Stat(stats["entries"], label="Entries")]))


app = indah.create_app(session_factory=build, factory_timeout=1.0)
```

If the factory takes longer than `factory_timeout` (1 second by default), the tab starts on a
`Skeleton` and the real page replaces it, on the same stream, when the factory finishes.
`factory_placeholder=` sets a different placeholder. A factory that raises shows the error and the
next connection tries again; a tab that closes while it runs cancels it, and its `ctx.on_close`
callbacks still run. A normal (sync) factory is unchanged. Two things to know: a click on a
control that is not on the skeleton does nothing until the real page arrives, and
`factory_timeout` and `factory_placeholder` apply to the built-in store, not to a `store=` you
pass. See `examples/async_start.py` and the "Async start" app in the Studio.

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

Try it live. Nothing downloads until you press **Run it**.

<indah-live page="live/topic"></indah-live>

<indah-live page="live/bounded"></indah-live>

### A refresh loop per tab: `ctx.every` and `ctx.spawn`

Work that should run while a tab is open, and stop when it closes, belongs on the context.

```python
def build(ctx):
    count = indah.Signal(0)

    async def refresh():  # a plain function works too
        count.set(await fetch_pending_count())

    ctx.every(5, refresh, immediately=True)  # now, then every 5 seconds
    ctx.spawn(watch_something(ctx))  # any coroutine, for the life of the session
```

Both are cancelled when the session ends: a closed tab, an eviction or an idle reaping. An
exception is logged once and the loop carries on (it logs again only after a successful call), so
one bad fetch does not stop the refresh. Call them from the session factory or a handler, where an
event loop is running; a plain function you pass to `every` runs on that loop, so keep it short.

Try it live. Nothing downloads until you press **Run it**.

<indah-live page="live/every"></indah-live>

### The tab's title and icon: `ctx.title` and `ctx.favicon`

A parked call should show in the browser tab, even when the viewer is on another tab. Set
`ctx.title` (the whole title) and `ctx.favicon` (the name of an icon you registered) from any
handler or `ctx.every` loop:

```python
app = indah.create_app(
    session_factory=build,
    title="semula",
    favicons={"alert": "static/red-dot.svg"},  # a PNG, SVG, ICO, JPEG or WebP, up to 64 KB each
)


def build(ctx):
    def refresh():
        n = parked.value
        ctx.title.set(f"({n}) semula" if n else None)  # None puts the app's own title back
        ctx.favicon.set("alert" if n else None)

    ctx.every(5, refresh, immediately=True)
    ...
```

The change reaches this session's tab only, with no reload, and a reload or a reconnect keeps it. A
new session starts with the app's own title and icon. Titles are cut at 200 characters. A favicon
name that is not registered is ignored with a warning. The icons are served by the app itself, so
this works under `csp="strict"`.

Try it live. Nothing downloads until you press **Run it**.

<indah-live page="live/tab-title"></indah-live>

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
- `Col(kind="cell", render=spec, sort_key="field")` draws a composite cell from the row's fields,
  with the same spec vocabulary as a `List` item (`text` and `bind` name row fields). It is
  display only, and it sorts and is searched by `sort_key`. Keep a cell to one line in a
  `virtual` table. `Col("prompt", truncate=True, max_width="30ch")` clips a long value with an
  ellipsis and shows the full text on hover; `wrap=True` lets it wrap instead (not with
  `virtual=True`). Both are off by default. The Studio page "Table: composite cells" shows them.
- `density="compact"` shrinks one table. Pass a `Signal[str]` to let the viewer toggle it.
- `on_open=fn` (or `keyboard=True`) makes the table drivable from the keyboard. Tab or click to
  focus it, then `j`/`k` or the arrows move the active row, `Home`/`End` jump, `PageUp`/`PageDown`
  move a screenful, Space ticks a row of a `checked=` table, and **Enter calls `fn(key)`** (sync or
  `async`; without `on_open`, Enter selects like a click). Moving never posts anything. The active
  row is held by key, so streamed rows, sorting and `follow=` do not move it (`End` resumes
  following), and at the edge of a paged or remote table the arrow turns the page. Escape or Tab
  leaves the table. Off by default, so an existing table is unchanged. See "Keys and focus" below.

<details>
<summary>Try these live (5 examples)</summary>

<indah-live page="data/table-rich"></indah-live>

<indah-live page="data/table-cells"></indah-live>

<indah-live page="data/table-actions"></indah-live>

<indah-live page="data/table-keyboard"></indah-live>

<indah-live page="data/table-follow"></indah-live>

</details>

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

Try it live. Nothing downloads until you press **Run it**.

<indah-live page="data/table-remote"></indah-live>

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

indah.Menu(
    "Actions",
    [
        indah.MenuItem("Rename", rename, shortcut="F2"),  # shortcut is display text only
        indah.MenuItem("Delete", delete, danger=True, confirm="Delete this entry?"),
    ],
)  # a menu button; items may also be a Signal, Computed or function returning the list

ctx.toast("Saved", kind="success")  # info, success, warn or error; ttl=0 sticks
ctx.toast("Approved", ttl=8, action=("Undo", undo))  # a button; runs undo once, then dismisses
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

A `Menu` opens on click, Enter, Space or the arrow keys and follows the usual menu keys: Up and Down move
(and wrap), Home and End jump, a letter moves to the next item that starts with it, Escape closes and
returns focus to the trigger, and Tab closes and moves on, so the keyboard is never trapped. Choosing
an item closes the menu and runs its handler. A `MenuItem(shortcut="F2")` only *shows* the key; bind it
with `Shortcuts`. Items are matched by `key=` (default: the label) against the current list, so a click
that lands as an item disappears does nothing. To leave an item out for someone who may not use it, build
the list with `ctx.only(perm, lambda: MenuItem(...))` and wrap the handler in `guard(perm)`: an omitted
item is never sent, and `guard` checks again at the click. A `Menu` goes in a row, a card or a rail;
a table cell is display only, so keep `RowAction` for per-row buttons.

<details>
<summary>Try these live (6 examples)</summary>

<indah-live page="overlays/modal-drawer"></indah-live>

<indah-live page="overlays/toasts"></indah-live>

<indah-live page="overlays/toast-action"></indah-live>

<indah-live page="overlays/confirm"></indah-live>

<indah-live page="overlays/menu"></indah-live>

<indah-live page="overlays/badges"></indah-live>

</details>

### A command palette

`CommandPalette(commands)` is the dashboard driven like a terminal: press `Ctrl+K` (`Cmd+K` on a Mac),
type, and press Enter. Arrows move, Escape closes and puts focus back where it was.

```python
palette = indah.CommandPalette(
    [
        indah.Command("Open the log", to="/log", group="Go to"),
        indah.Command("Pause intake", pause, group="Actions", keywords="stop halt"),
        indah.Command("Delete all", wipe, group="Actions", confirm="Delete every entry?"),
    ],
    ctx=ctx,  # needed only for a jump (`to=`): it moves this tab, like `ctx.navigate`
)
```

A command either runs a function (sync or `async`) or jumps to an in-app page. The filter runs in the
browser over the list it was sent, so typing costs no round trip. The match order is stable: a label
that starts with what you typed, then one with a *word* that does, then one that contains it, then one
that contains it as a subsequence (`gl` finds "Go to log"), then a match in the `keywords` or the
`group`; ties keep the order you gave. Put commands of one `group` next to each other, since the empty
palette shows a heading each time the group changes.

**Commands for a page.** `commands` can be a `Signal`, `Computed` or function, and the palette re-sends
its list when it changes. To add a page's own commands, return the app's list plus the current page's from
one function that reads `ctx.path` (or a signal): the commands appear when the page shows and leave with it.

```python
def commands():
    out = list(app_commands)
    if ctx.path.value.startswith("/log"):
        out.append(indah.Command("Clear the log", clear_log, group="This page"))
    return out


indah.CommandPalette(commands, ctx=ctx)
```

The shortcut opens it from anywhere that is not already in a dialog. A bare key such as `shortcut="/"` is
ignored while the viewer types in a field; a `mod+` combo is not. Do not map the same key in
`Shortcuts`. To leave a command out for someone who may not use it, build the list with
`ctx.only(perm, lambda: Command(...))` and wrap the handler in `guard(perm)`: an omitted command is never
sent, a forged run of it does nothing, and `guard` checks again when it runs. Like `Menu`, a run is
matched by `key=` (default: the label) against the current list.

`confirm=` is a UX guard only: the server still runs any click it receives, so check
authorization in your handler. A toast goes to the current tab only, never put a secret in
one. A toast's `action=` button runs its function once as that tab's user, so a `guard()` on it is
checked at the click, and a second click or a stale toast does nothing. Give an undo a longer `ttl`
than the default 4 seconds. `Shortcuts` bare keys are ignored while the viewer types or a dialog is open, and a map
is active only while it is in the rendered tree.

Try it live. Nothing downloads until you press **Run it**.

<indah-live page="overlays/command-palette"></indah-live>

### Keys and focus

A widget that owns keys while it has focus (the keyboard `Table`, and the command
palette) goes first. It acts only on keys aimed at itself, never on a key typed into an input
inside it or one with `ctrl`, `cmd` or `alt` held, and it marks the key as handled, which
`Shortcuts` respects. So with a keyboard `Table` focused, `j` moves its row; anywhere else the
same `j` runs your `Shortcuts` binding. `mod+k` is the command palette's default key; give it another
`shortcut=` if you want `mod+k` for something else. Tab and Escape always
leave. Use `mod+` or `alt+` combos for page-wide actions and bare keys for the focused widget.

Try it live. Nothing downloads until you press **Run it**.

<indah-live page="overlays/shortcuts"></indah-live>

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

In a rail, use `NavItem(ctx, "Pending", to="/pending", badge=count, icon="...")`: a `Link` with a live
count at its end that disappears when the count is zero or empty.

!!! warning "Hidden pages still run"
    Every page is built up front, so a page's reactive code runs even when its route is not
    showing, with no params. Read params with `ctx.params.value.get("project")`, never
    `ctx.params.value["project"]`, and keep expensive work behind a `computed`. Do not put
    anything role-restricted in a page: hidden pages are in the page snapshot.

`{id:int}` converts a segment to an integer. After a server restart an open tab reopens on the
page it is on now.

!!! note "One `Router` per session"
    The address bar holds one path per tab, so a session can have only one `Router`; a second
    raises `ValueError`. To show routing inside part of a page (a docs chapter, a card), use
    `Tabs`, or a `Signal` with a `computed`, for that switcher; or run the routed app on its own
    and link to it. Nested routers are not supported.

<details>
<summary>Try these live (3 examples)</summary>

<indah-live page="routing/links"></indah-live>

<indah-live page="routing/navitem"></indah-live>

<indah-live page="routing/navigate"></indah-live>

</details>

## Split panes and master-detail

```python
indah.SplitPane(left, right, direction="horizontal", initial=0.4, height="30rem")
indah.MasterDetail(table, detail, open=drawer_open)  # a drawer on a narrow screen
```

Try it live. Nothing downloads until you press **Run it**.

<indah-live page="layout/split"></indah-live>

<indah-live page="layout/master-detail"></indah-live>

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

Try it live. Nothing downloads until you press **Run it**.

<indah-live page="data/json-tree"></indah-live>

<indah-live page="data/diff"></indah-live>

## Forms that edit data

`TextArea(signal, label=, rows=)` is a multi-line input. Like every input, the browser owns
the text while the viewer is typing in it, so a late echo from the server never overwrites it.

Try it live. Nothing downloads until you press **Run it**.

<indah-live page="data/list"></indah-live>

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
that off so the keyboard can leave the editor. `{{name}}` placeholders (a template slot such
as `{{now}}`) are highlighted in every language, as a visual cue only: names are not completed
or checked. If the editor cannot load, a plain text area
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

In a row spec, `"text": "title"` shows the item's `title` field. For fixed text, such as a
button label, use `"literal"`: `{"tag": "button", "literal": "Remove", "on": {"click":
{"event": "remove"}}}` needs no field on the items.

Try it live. Nothing downloads until you press **Run it**.

<indah-live page="overlays/code-editor"></indah-live>

## Theme and density

`indah.Theme(light={...}, dark={...}, radius=, font=)` overrides the design tokens, and
`create_app(density="compact")` tightens tables. See [Design system](design-system.md) for the
token names and what each is for.

## Hosted use

indah keeps one session per open tab, in memory, on the server. To put a dashboard in front of real
users (login, per-user sessions, roles, limits, a CSP), read [Host an app for real users](hosting.md).
The ADRs under `docs/adr/` (0025 to 0038) describe the decisions behind each feature above.
