# Table

`Table` shows rows you can sort, filter, select and act on. It has three forms that share one set
of options: **classic** (a frame or a list), **rich** (typed columns and a stable key) and
**remote** (a loader that returns one window of rows at a time). For a walk-through, see
[Your first dashboard](dashboard-tutorial.md); for patterns, see
[Dashboard recipes](dashboards.md#show-and-act-on-rows-with-table).

## `Table(source=None, *, rows=None, columns=None, key=None, ...)`

| Form | Call | Use it for |
|------|------|-----------|
| Classic | `Table(source)` | A pandas frame, a `{"columns", "rows"}` dict or a list of row dicts. Sorting and paging happen in the browser. `selected` holds the row index. |
| Rich | `Table(rows=..., columns=[Col(...)], key="id")` | Typed columns and a stable key per row. `selected` holds the key, so it survives sorting and new rows. `rows` may be a list, a signal or a `Stream`. `columns` may be left out when `rows` is a non-empty static list. |
| Remote | `Table(columns=[...], key="id", remote=loader)` | More rows than one prop should carry. The loader is asked for a window at a time. |

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | frame, dict or list | `None` | Classic form data. |
| `rows` | list, signal or `Stream` | `None` | Rich form data. A `Stream` sends new rows as small `append` patches; the browser keeps the newest `stream.limit`. |
| `columns` | `list[Col]` | `None` | The columns. |
| `key` | `str` | `None` | The field that identifies a row. Required for `actions`, `checked`, `remote` and keyboard use. |
| `selected` | `Signal` | `None` | The clicked row: its key (rich) or its index (classic). `None` when nothing is selected. |
| `page_size` | `int` | `0` | Rows per page; `0` shows all. In the remote form it is the window size (50 when unset). |
| `label` | `str` | `""` | The table's label, sent as its `label` prop. |
| `height` | CSS length | `None` | Makes the body scroll under a sticky header. Needed by `follow` and `virtual`. |
| `search` | `bool` | `False` | A filter box. Case-insensitive over every column and run in the browser, so streamed rows are filtered too. In the remote form the loader does it. |
| `column_toggle` | `bool` | `False` | Lets the viewer hide columns, remembered in the browser. |
| `follow` | `bool` | `False` | Keeps the newest row in view while rows arrive, and pauses when the viewer scrolls up. Needs `height`. Raises `ValueError` with `remote`. |
| `actions` | `list[RowAction]` | `None` | A button per row. Needs `key`. |
| `checked` | `Signal[list]` | `None` | A checkbox column plus select-all, holding the ticked keys. Needs `key`. |
| `remote` | `Callable[[TableQuery], (rows, total)]` | `None` | The loader. A sync loader runs in a worker thread. |
| `reload_on` | `list[Signal]` | `None` | Re-runs the last query when one of these changes. |
| `query` | `Signal[TableQuery \| None]` | `None` | Mirrors the latest query. |
| `virtual` | `bool` | `False` | Renders only the rows in view, for tens of thousands of rows. Needs `height`. Rows have one fixed height. |
| `density` | `str` or `Signal[str]` | `None` | `"compact"` shrinks this table. A signal lets the viewer toggle it. The app-wide default is `create_app(density=)`. |
| `on_open` | `Callable[[key], Any]` | `None` | Called on Enter for the active row. Turns on keyboard use. |
| `keyboard` | `bool` | `False` | Turns on keyboard use without `on_open`. Enter then selects, if `selected` is bound. |

**Keyboard.** Focus the table with Tab or a click. `j`/`k` or the arrows move the active row,
`Home`/`End` jump, `PageUp`/`PageDown` move a screenful, Space ticks a row of a `checked` table,
and Escape or Tab leaves. Moving posts nothing; only Enter does.

**Remote tables.** The browser debounces search, sort and paging into a query. A newer query
supersedes an older one, whose late answer is dropped, and an offset past the end is pulled back to
the last window. With `checked`, the header checkbox ticks only the rows shown, and a "Select all
M" button gathers every match, up to 10,000 keys.

## `Col(field, title=None, kind="text", ...)`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `field` | `str` | required | The row field this column shows. |
| `title` | `str` | `None` | The header; defaults to the field. |
| `kind` | `str` | `"text"` | The cell renderer, below. |
| `width` | CSS length | `None` | Column width, such as `"9ch"`. |
| `sortable` | `bool` | `True` | Whether a click on the header sorts. |
| `tones` | `dict[str, str]` | `None` | For `badge`: maps a cell value to `ok`, `warn`, `err`, `info` or `neutral`. |
| `time_format` | `str` | `"relative"` | For `time`: `"relative"` ("3s ago", refreshed live), `"clock"` (`09:14:22.318`) or `"datetime"` (`2026-10-21 09:14:22`), both in the viewer's local time. The tooltip always carries the full UTC value. |
| `render` | spec | `None` | For `cell`: a render spec in the vocabulary of a `List` item. |
| `sort_key` | `str` | `None` | For `cell`: the row field to sort and search by. Defaults to `field`. |
| `truncate` | `bool` | `False` | Clips a long value with an ellipsis at `max_width` and shows the full text on hover. |
| `max_width` | CSS length | `None` | The clip width for `truncate` (`32ch` when unset). |
| `wrap` | `bool` | `False` | Lets a long value wrap instead. Refused with `virtual=True`. |

| `kind` | Cell |
|--------|------|
| `text` | Plain text. |
| `mono` | Monospace, truncated, with the full value on hover. |
| `badge` | A pill toned by `tones`. |
| `time` | An ISO string or epoch seconds or milliseconds, shown by `time_format`. |
| `number` | Right-aligned, with grouped digits. |
| `cell` | A composite cell drawn from the row's fields. Display only: an `on` in the spec is refused. The spec travels once, in the column. |

No cell interprets HTML.

## `RowAction(label, on_click, confirm=None, variant="ghost", when=True)`

A per-row button on a rich `Table`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `label` | `str` or `Callable[[row], str]` | required | The button text. A function gets the row dict, so one column can say "Make editor" on one row and "Make viewer" on another. |
| `on_click` | `Callable[[key], Any]` | required | Runs with the row's key. Sync or `async`. |
| `confirm` | `str` | `None` | The shell asks this first. A UX guard, not authorization. |
| `variant` | `str` | `"ghost"` | The button style. |
| `when` | `bool` or `Callable[[row], bool]` | `True` | Where it is false, the row has no button. |

A row can be stale by the time a click lands, so the handler must tolerate a key that no longer
exists. `when` only hides the button: the click is still dispatched, so keep the real check in
`on_click` or your authorization layer. A label or `when` function that raises hides the button on
that row and does not fail the page. The resolved label and visibility are sent with each row, so a
plain string label sends nothing extra.

## `TableQuery`

What a remote table passes to its loader.

| Field | Type | Meaning |
|-------|------|---------|
| `search` | `str` | The filter text. |
| `filters` | `dict` | A dict of filters that arrives with the query (empty unless the page sends some). |
| `sort` | `(field, "asc" \| "desc")` or `None` | The order. |
| `offset` | `int` | The first row wanted. |
| `limit` | `int` | How many rows. |
| `seq` | `int` | Numbers the viewer's queries so an old answer is never shown over a new one. |

The loader returns `(rows, total)`, where `total` is the count of rows matching the search.
Sorting and search are the loader's job: a loader that ignores them is a bug in your app.
