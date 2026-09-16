# Components

Every component is a Python object you place in a tree and bind to a signal. The
sections below walk through the common ones with runnable snippets; this is the full
set shipped in 0.2.0.

### Text and display

| Component | Use |
|-----------|-----|
| `Text` | a label bound to a signal, computed, or string |
| `Image` | a URL, `data:` URI, or raw PNG bytes |
| `ImageOverlay` | an image with read-only vector overlays (boxes, masks, keypoints) |

### Inputs (two-way bound to a signal)

| Component | Use |
|-----------|-----|
| `Slider` | a numeric input on a track |
| `Number` | a plain numeric input with optional bounds |
| `TextInput` | a single-line text box |
| `Select` | a single-choice dropdown |
| `MultiSelect` | a multi-choice select |
| `Radio` | a radio group |
| `Checkbox` | a boolean checkbox |
| `Date` | a date picker (ISO `YYYY-MM-DD`) |

### Actions

| Component | Use |
|-----------|-----|
| `Button` | an `on_click` handler (sync or `async def`) |

### Layout

| Component | Use |
|-----------|-----|
| `Column` | a vertical stack |
| `Row` | a horizontal flex row that wraps |
| `Grid` | an N-column grid that collapses to one column on phones |
| `Card` | a titled surface panel |
| `Tabs` | a tabbed container, one panel at a time |
| `Sidebar` | a persistent side region plus a main region |
| `Expander` | a collapsible labelled section |

### Charts and data

| Component | Use |
|-----------|-----|
| `Plot` | a Matplotlib figure rasterised to a PNG on the Python side |
| `Chart` | an interactive client-side chart (zoom, hover, live points) |
| `Heatmap` | a client-side heatmap / 2-D field |
| `DataFrame` | a pandas frame, a `{columns, rows}` dict, or record dicts |
| `Table` | an interactive table: sort, page, and select |
| `Stat` | a metric / KPI card: a big value with a label and optional delta |

### Streaming and data-driven lists

| Component | Use |
|-----------|-----|
| `StreamText` | a string that grows token by token over SSE |
| `List` | a data-driven list bound to a `Signal[list]` |
| `Chat` | a chat transcript of role bubbles bound to a `Signal[list]` |
| `Gallery` | an image grid bound to a `Signal[list]` |

### Files and feedback

| Component | Use |
|-----------|-----|
| `Upload` | a file input (image / audio / any file) |
| `Download` | a link that hands the user a file back |
| `Progress` | a progress bar bound to a source |
| `Spinner` | an indeterminate busy indicator |

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
that reads signals reactively. `DataFrame` duck-types its input: a pandas frame
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

An `on_click` handler may be `async def`. It runs in the background, so a slow
handler (a model call, an HTTP request) never blocks the event loop or other
viewers, and the rest of the UI stays responsive while it runs.

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
