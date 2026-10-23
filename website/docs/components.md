# Components

Every component is a Python object you place in a tree and bind to a signal. The
sections below walk through the common ones with runnable snippets; this is the full
set shipped so far.

### Text and display

| Component | Use |
|-----------|-----|
| `Text` | a label bound to a signal, computed, or string |
| `Marked` | text with shaded spans (the part that is ignored or flagged): `Marked(text, marks=[(start, end, tone)])` |
| `Steps` | a timeline of steps, vertical or horizontal: `Steps(items, orientation=)`; each step is `done`, `current`, `skipped`, `off` or `pending` |
| `Image` | a URL, `data:` URI, or raw PNG bytes |
| `ImageOverlay` | an image with read-only vector overlays (boxes, masks, keypoints) |
| `Audio` | a URL, `data:` URI, or raw audio bytes, played with native browser controls |

### Inputs (two-way bound to a signal)

| Component | Use |
|-----------|-----|
| `Slider` | a numeric input on a track |
| `Number` | a plain numeric input with optional bounds |
| `TextInput` | a single-line text box |
| `TextArea` | a multi-line text box |
| `CodeEditor` | a JSON / YAML / text editor: highlighting, auto-indent, auto-closing brackets and quotes, folding, search, JSON lint |
| `Switch` | an on/off toggle bound to a `Signal[bool]` |
| `Select` | a single-choice dropdown |
| `MultiSelect` | a list of checkboxes; the value is the list of checked options |
| `Radio` | a radio group |
| `Chips` | filter chips, single (`Signal[str]`) or `multi=True` (`Signal[list]`); an option may carry a `count` and a `tone` |
| `Segmented` | a joined row of options, one selected; `tones={value: tone}` tints a segment |
| `Checkbox` | a boolean checkbox |
| `Date` | a date picker (ISO `YYYY-MM-DD`) |

### Actions

| Component | Use |
|-----------|-----|
| `Button` | an `on_click` handler (sync or `async def`); `confirm=` asks first |
| `Shortcuts` | keyboard shortcuts for the page, with a `?` help overlay |

### Layout

| Component | Use |
|-----------|-----|
| `Column` | a vertical stack; `gap=` sets the spacing |
| `Row` | a horizontal flex row that wraps; children share the width, unless `align=` is set to anything but `"stretch"` (buttons and badges size to their content) or `justify=` (`"start"`, `"center"`, `"end"`, `"between"`, `"around"`) is set (every child sizes to its content) |
| `Spacer` | free space that grows to fill a `Row`, pushing what follows to the far end; `Spacer(size="2rem")` is a fixed gap |
| `Divider` | a thin rule; `Divider(vertical=True)` between the children of a `Row` |
| `Grid` | an N-column grid that collapses to one column on phones |
| `Card` | a titled surface panel; `variant="flat"` drops the frame, `"tonal"` tints it, `padding=` sets the inner space |
| `Tabs` | a tabbed container, one panel at a time |
| `Sidebar` | a persistent side region plus a main region |
| `AppShell` | the app frame: a rail that stays put while the page scrolls, an optional top bar and the main region (`rail=`, `main=`, `top=`, `rail_width=`); a drawer behind a menu button on a narrow screen |
| `Expander` | a collapsible labelled section |
| `SplitPane` | two panels with a draggable divider |
| `MasterDetail` | a list beside its detail, a drawer on a narrow screen |
| `Router` / `Link` | pages chosen by the URL, and links between them |
| `NavItem` | a `Link` for a rail with an `icon=` and a live count `badge=` that hides at zero |
| `Modal` / `Drawer` | a dialog and a side panel, opened from a signal |
| `CommandPalette` / `Command` | a keyboard palette opened with Ctrl/Cmd+K: fuzzy filter, run a function or jump to a page, `confirm=`, per-page commands |
| `Menu` / `MenuItem` | a menu button of actions with arrow keys, `confirm=`, `danger=` and `disabled=` items |

### Charts and data

| Component | Use |
|-----------|-----|
| `Plot` | a Matplotlib figure rasterised to a PNG on the Python side |
| `Chart` | an interactive client-side chart (zoom, hover, live points) |
| `Heatmap` | a client-side heatmap / 2-D field |
| `Map` | an interactive client-side map (Leaflet): pan/zoom, markers, polygons, polylines |
| `DataFrame` | a pandas frame, a `{columns, rows}` dict, or record dicts |
| `Table` | an interactive table: sort, page, and select |
| `Stat` | a metric / KPI card: a big value with a label and optional delta |
| `BarStrip` | a small activity strip: one bar per interval (calls per minute), optionally stacked, with a tooltip per bar |
| `JsonTree` | a collapsible, searchable JSON viewer |
| `Diff` | a split or unified diff of two texts or JSON values |

### Streaming and data-driven lists

| Component | Use |
|-----------|-----|
| `StreamText` | a string that grows token by token over SSE |
| `List` | a data-driven list bound to a `Signal[list]`; `key=` and `on_item=` make rows editable |
| `Chat` | a chat transcript of role bubbles bound to a `Signal[list]` |
| `Gallery` | an image grid bound to a `Signal[list]` |

### Files and feedback

| Component | Use |
|-----------|-----|
| `Upload` | a file input (image / audio / any file) |
| `Download` | a link that hands the user a file back |
| `Progress` | a progress bar bound to a source |
| `Spinner` | an indeterminate busy indicator |
| `Skeleton` | grey placeholder bars for content that has not arrived (`lines=`, `height=`); an `async` session factory that is still running shows one |
| `Badge` | a small status pill |
| `Empty` | what to show where there is nothing yet: `Empty(title, body, action=, children=)` |
| `Code` | a read-only block of code or a command with a Copy button: `Code(text, language=, copy=True)` |
| `SecretReveal` | shows a secret (a new API token) once, with Copy and dismiss; never replayed on reconnect (see [Host an app](hosting.md#showing-a-secret-once)) |

Every component also takes `tooltip="..."`, and `ctx.toast(message)` shows a transient message in the
current tab. For the live-data, table, overlay and routing features, see
[Build a dashboard](dashboards.md).

## Display

```python
from indah import Text, Image, DataFrame, Column, Signal, computed

name = Signal("Ada")
page = Column(
    children=[
        Text("a static label"),
        Text(computed(lambda: f"hello, {name.value}")),  # reactive
        Image("https://example.com/logo.png", alt="logo"),
        DataFrame({"columns": ["n", "n^2"], "rows": [[k, k * k] for k in range(1, 6)]}),
    ]
)
```

`Text` accepts a string, a `Signal`, a `computed`, or a plain `lambda` - anything
that reads signals reactively.

Plain `Text` is body text: normal size and weight, with line breaks kept. Pick a role with
`variant=`:

| `variant` | Use |
|-----------|-----|
| `"body"` (default) | paragraphs, status lines, notes |
| `"title"` | a heading for a block that is not Markdown |
| `"label"` | the name of a field or group (muted) |
| `"caption"` | help text, timestamps, fine print (muted) |
| `"mono"` | ids, paths, numbers that must line up |
| `"readout"` | a counter or a figure: large, semi-bold, tabular numbers |

Plain text never interprets markup, so backticks stay literal; use `Text(..., markdown=True)`
for code, emphasis, links and headings (a Markdown text takes no `variant`). `size="body"` and
`size="readout"` from 0.4.0 still work and mean `variant="body"` and `variant="readout"`.

### Marked text

`Marked(text, marks)` shows a text with some spans shaded, such as the part of a request that was ignored
when matching or the words a check flagged:

```python
from indah import Marked

Marked(
    "Summarise the report. Ignore the template header.",
    [(0, 9, "info", "the task"), (22, 49, "warn", "ignored")],
)
```

A mark is `(start, end, tone)` or `(start, end, tone, label)`. `text` and `marks` can each be a string or
list, a `Signal`, a `Computed` or a function, so the shading follows the data. The tones are the theme's:
`ok`, `warn`, `err`, `info`, and `neutral` for a plain highlight. A tone is never colour alone, since each
has its own underline (solid, dashed, wavy, dotted), and the optional `label` is the span's hover text. The
spans are real inline elements that add no characters, so selecting and copying gives back the plain text,
and newlines are kept. `label=` on `Marked` names the block for a screen reader.

Offsets count characters as Python does (Unicode code points, `end` exclusive), so `"a\U0001f600b"` has the
emoji at offset 1. The rules are fixed so the same input always gives the same result: a range is clamped to
the text, an empty or reversed range is dropped, marks are taken in order of start (then end), and a mark that
overlaps an earlier one is cut to begin where the earlier one ends (and dropped if nothing is left). A tone
that is not one of the five, or an offset that is not an integer, raises an error.

To show it in a `List` item or a table cell, compute the runs with `marked_runs(text, marks)`, keep them in a
field, and name the component in the render spec:

```python
from indah import Col, List, Table, marked_runs

rows = [{"id": "a", "runs": marked_runs("GET /v1/models 200", [(4, 14, "ok")])}]
cell = {"component": "marked", "bind": {"runs": "runs"}}

List(rows, key="id", item=cell)
Table(
    columns=[Col("id"), Col("runs", title="Request", kind="cell", render=cell)], rows=rows, key="id"
)
```

A `Diff` draws its own changed characters; to show shaded text beside one, put a `Marked` in the other pane
of a `Row` or `SplitPane`. `marked_runs` returns a list that a List item or a table row carries as it is
(other lists and dicts in an item field are shown as text).

### Steps

`Steps(items)` draws a timeline: a pipeline, a checklist, the tiers a request went through.

```python
from indah import Steps

Steps(
    [
        {"label": "Plan", "state": "done", "detail": "2 min"},
        ("Build", "current"),
        ("Test", "pending"),
        "Ship",
    ],
    orientation="vertical",
)
```

An item is a dict (`label`, `state`, `detail`), a tuple `(label, state)` or `(label, state, detail)`, or a bare
label. The `state` is `done`, `current`, `skipped`, `off` or `pending` (the default), and anything else raises
an error. `items` can be a list, a `Signal`, a `Computed` or a function, so the timeline follows the data and
updates in place. At most 100 steps are drawn.

A state is never colour alone. Each has its own drawing (a check, a ring with a dot, a barred ring, a dashed
ring, an empty ring), a skipped label is struck through, and a screen reader hears "Build, step 2 of 4,
current" followed by the `detail`. The current step has `aria-current="step"`. The steps are display only, so
they are not a tab stop. `label=` names the timeline for assistive technology.

`orientation` is `"vertical"` (the default) or `"horizontal"`. `size="compact"` is for tight places: one line,
smaller, and the `detail` moves into the hover text (a screen reader still reads it); at the normal size the
`detail` is shown under its label.

To show it in a `List` item or a table cell, build the field with `steps_items` and name the component in the
render spec. There it is horizontal and compact, unless you bind `orientation` or `size` to fields as well:

```python
from indah import Col, Table, steps_items

tiers = steps_items([("exact", "done", "hit"), ("fuzzy", "skipped"), ("llm", "current")])
cell = {"component": "steps", "bind": {"items": "tiers"}}

Table(
    columns=[Col("id"), Col("tiers", kind="cell", render=cell)],
    rows=[{"id": 1, "tiers": tiers}],
    key="id",
)
```

### Empty states and code blocks

`Empty` is for the place a list, log or table would be when there is nothing in it yet. Say what is
missing and what to do about it; `children` (between the text and the action) is a good home for the one
command that fills it, and `action` is usually a `Button`:

```python
from indah import Button, Code, Empty

Empty(
    "No requests yet",
    "Start the proxy and every request appears here.",
    children=[Code("semula log --follow", language="bash")],
    action=Button("Send a test request", send),
)
```

`Code(text, language=, copy=True)` shows a block of text in a monospace face with its newlines and
indentation kept. `text` can be a string, a `Signal` or a callable. `language` is only a label in the
header (there is no colouring; use `CodeEditor(read_only=True)` for that). The Copy button puts the plain
text on the clipboard and shows a "Copied" toast in that tab, with no round trip to the server. A page that
is not a secure context (plain `http` away from `localhost`) cannot use the clipboard API; then the text
is selected and the toast asks for Ctrl+C. The Copy button and a long block that scrolls are both reachable
with the keyboard. `copy=False` hides the button.

### Activity strips

`BarStrip` is a compact strip with one bar per interval, for "calls per minute" next to a number, not
a chart to read values from. `series` is a list (or a `Signal`, `Computed` or function returning one) with
a number per bar, or a tuple of numbers for a stacked bar, first segment at the bottom:

```python
from indah import BarStrip, Signal

calls = Signal([(3, 1), (5, 0), (2, 2)])  # (hits, misses) per minute
BarStrip(
    calls,
    tones=["ok", "err"],  # theme tones: neutral, ok, warn, err, info
    names=["hit", "miss"],
    labels=lambda: [f"{m}m ago" for m in range(len(calls.value), 0, -1)],
    label="Calls per minute",  # the name a screen reader hears
    height=40,  # pixels, 8 to 240 (default 32)
)
```

The strip updates in place when the source changes, so appending a bar from `ctx.every` or a `Stream`
callback is cheap; only the latest 1440 bars are sent. The scale is the tallest bar unless you fix it with
`max=`. Negative, non-finite or non-numeric values draw as zero. Tones are the theme's colours, so they
follow light and dark and `Theme(...)`. The default tone is `info`, and a segment with no tone in the list
is `neutral`.

Colour is never the only cue. Hover a bar, or focus the strip (it is one tab stop) and use the arrow keys,
Home and End, and a tooltip reads `12:03: 4 (hit 3, miss 1)`; a screen reader gets the same text from a
live region. Escape hides the tooltip and Tab moves on, so the keyboard is never trapped. Give stacked bars
`names=` and the bars `labels=` so the tooltip says what each part is. Animation is off when the reader
asks for reduced motion.

`DataFrame` duck-types its input: a pandas frame
(via `to_dict(orient="split")`), a `{columns, rows}` dict, or a list of record
dicts. Neither pandas nor Matplotlib is a hard dependency; each is only touched if
you pass it.

`Plot` takes anything with a `savefig` method (a Matplotlib figure) and serialises
to an image, so the browser needs nothing extra to show it.

## Inputs

Inputs are two-way bound: the UI reflects the signal, and a user change writes back
to the signal.

```python
from indah import Slider, TextInput, Select, Signal, Column

n = Signal(3)
who = Signal("world")
choice = Signal("squares")

page = Column(
    children=[
        Slider(n, min=0, max=10, step=1, label="n"),
        TextInput(who, placeholder="your name", label="Name"),
        Select(choice, options=[("squares", "Squares"), ("primes", "Primes")], label="Dataset"),
    ]
)
```

`Select` options are `(value, label)` pairs, or plain strings when the value and
label are the same. Read the current value anywhere with `.value`; it stays in
sync with what the user picked.

Options may change while the page is open. Pass a `Signal`, a `computed` or a function
instead of a list (to `Select`, `Radio`, `MultiSelect`, `Chips` or `Segmented`) and the
control follows it with no reload. A selection whose value is still offered is kept. A
multi-value control (`MultiSelect`, `Chips(multi=True)`) drops values that are no longer
offered; a single-value control leaves its signal alone, so your code decides what a
removed project should fall back to.

```python
projects = Signal(["alpha", "beta"])
current = Signal("beta")
Select(current, options=projects, label="Project")
projects.set([*projects.value, "gamma"])  # "gamma" appears; "beta" stays selected
```

`Chips` (filter chips, single or `multi=True`) and `Segmented` (a joined row, one
selected) take the same options plus an optional count and tone per option:
`{"value": "err", "label": "Errors", "count": 2, "tone": "err"}`, or
`Segmented(mode, options=[...], tones={"record": "err"})`.

Try them here. The example runs in your browser; nothing is downloaded until you press **Run it**.

<indah-live page="start/choices"></indah-live>

`TextInput(value, password=True)` masks the field (an `<input type="password">`) for
secrets like an API key. It is only display masking - the value still round-trips like
any input, so keep it in per-session state and never log it.

## Buttons and async handlers

```python
from indah import Button, Signal, Text, Column

count = Signal(0)


def bump():
    count.set(count.value + 1)


page = Column(
    children=[
        Button("Add one", on_click=bump),
        Text(lambda: f"count = {count.value}"),
    ]
)
```

An `on_click` handler may be `async def`. It runs in the background, so a handler that
*awaits* (an async HTTP call, `asyncio.sleep`) never holds up other viewers, and the rest of
the UI stays responsive while it runs.

A plain `def` handler runs **on the event loop**, and so does any blocking call inside an
`async def` one. While it runs, every tab on that server waits. Move blocking work (a
database query, `requests`, a model forward pass) off the loop with `await
asyncio.to_thread(...)`; see [Slow handlers](dashboards.md#slow-handlers-keep-the-loop-free).

## Streaming

`StreamText` holds an accumulating string. `feed(token)` appends a delta over SSE
- only the new text crosses the wire, not the whole string - and `reset()` clears
it.

```python
from indah import StreamText

out = StreamText(label="Response")
out.feed("Hello ")
out.feed("world")  # the shell appends, token by token
out.reset()  # start over
```

Pair it with an async button handler (see [Quickstart](quickstart.md)) to stream a
model's output into the page.

## Beyond the starter set

If the set does not cover what you need, register a custom component against the
public protocol - no framework fork, no Node build. See
[Custom components](custom-components.md).
