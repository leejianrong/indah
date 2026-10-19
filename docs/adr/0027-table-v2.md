# ADR-0027: Table v2: keyed rows, typed columns and streamed rows

- Status: Accepted (core in IND-91, client search/column toggle/follow in IND-92; row actions and remote mode follow)
- Date: 2026-10-19
- Deciders: Jian (owner)
- Amends: ADR-0021

## Context

ADR-0021's `Table` serves a fixed frame: rows are lists, selection is a row *index*,
every row renders, and a grown table must re-send the whole `data` prop. The semula
dashboard (`docs/SEMULA-REQUESTS-PLAN.md`, E2) needs a live log (rows keyed by ULID,
badges, monospace ids, relative times), where an index is unusable as an identity
because rows are sorted, filtered and appended while the user is looking at one.

## Decision

One `Table` component, two forms, chosen by the arguments:

- **Classic**, `Table(source, page_size=, selected=)`: exactly ADR-0021. Untouched; its
  tests pass unchanged.
- **Rich**, `Table(rows=, columns=[Col(...)], key=, selected=, height=)`: rows are dicts,
  `key` names the field that identifies a row, and `selected` holds that key. `columns`
  may be omitted for a non-empty static list. `rows` may be a `Stream` (ADR-0026): new
  rows arrive as `append` patches on `rows` and the shell keeps the newest `limit`.

`Col(field, title, kind, width, sortable, tones)` types a column. The renderers are a
closed set implemented in the shell and none interprets HTML (`text`, `mono`, `badge`,
`time`, `number`), so cell content cannot inject markup. A `time` cell is shown relative
("3s ago") and every such cell on the page shares one 1 s timer.

I extended `Table` rather than add a `DataTable`: the sorting, paging and select code is
shared, and the classic contract is preserved by the argument-based split. The wire is
additive (new props `columns`, `rows`, `rowKey`, `height`; a `select` event carrying
`key`), so no `protocol_version` bump.

## Alternatives considered

| Option | Why not |
|--------|---------|
| A separate `DataTable` | Duplicates the shell's sort/page/select code; two tables to document |
| Keep index selection | An index changes meaning on sort, filter and append |
| A grid library (AG Grid, Tabulator) | Rejected in ADR-0021 and still too heavy for the shell |

## Consequences

- A selection can survive sorting and new rows, so a detail panel stays on the row the
  user clicked while the log scrolls.
- Rows must carry their key; a row without it is rejected when the prop is built.
- Search, column toggle and follow-tail (IND-92) are client-only state: the filter text is
  not sent to the server, hidden columns are remembered in `localStorage` per page and
  table, and follow pauses on scroll-up or an active sort. Filtering a streaming table
  therefore only sees the rows the browser holds (the stream's `limit`).
- Row actions and multi-select (IND-99): `Table(actions=[RowAction(label, fn(key), confirm=)],
  checked=Signal[list])`, rich form with `key=` only. An action posts `action {action, key}`;
  checking posts the whole new key set as `check {keys}`, so a lost event cannot leave the
  sides disagreeing. Clicking an action or a checkbox never selects the row. A handler must
  tolerate a stale key.
- Remote mode (IND-101): `Table(columns=, key=, remote=loader(TableQuery) -> (rows, total),
  reload_on=[...], query=)`. The shell debounces search/sort/paging into `query {..., seq}`; the
  server runs the loader (a sync loader in a worker thread, so a blocking database call does not
  stall the loop), drops a superseded query, re-clamps an offset past `total`, and answers with a
  single `window` prop so rows, total and seq are atomic. The shell shows a window only if its seq
  is current. Paging is Prev/Next here; virtual scroll over the same protocol is IND-102. One
  loader is the only place that honours search and sort, so a loader that ignores them is a bug
  in the app, not the table. `TableQuery.parse` clamps limit, truncates search and ignores a sort
  on a non-sortable column, so a client cannot ask for an arbitrary field or unbounded window.
- Virtual scroll (IND-102): `Table(virtual=True, height=)`, any rich form. The shell renders the
  visible rows plus 8 of overscan between two spacer rows, so the scrollbar is the real
  `total x --row-h` and the header stays sticky (no absolute positioning). Row height is fixed
  (cells do not wrap; density tokens are IND-103). Remote windows are block-aligned so nearby
  scroll positions share a request, the last 8 are cached to avoid flicker, and a search or sort
  change drops the cache and invalidates in-flight answers by bumping the seq. Select-all on a
  remote table covers only the rows the browser holds. Measured: 20k remote rows, under 200 DOM
  rows, worst frame under 100 ms while scrolling the whole table.
