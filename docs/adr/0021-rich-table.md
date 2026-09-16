# ADR-0021: Rich Table (sort / page / filter / select)

- Status: Accepted
- Date: 2026-09-16 (accepted + built same day, KAN-1462/1463)
- Deciders: Jian (owner)

## Context

`DataFrame` renders a static HTML table from a `{columns, rows}` prop (duck-typed
from pandas). That is right for showing a result, but the Phase 2 standalone demos —
the stock/peer dashboard, the DataFrame explorer — need an interactive table: sort by
a column, page through many rows, filter, and select a row to drive the rest of the
app. This is the top of cluster A ("Dashboards & tables") in `PLAN.md`, and it is what
Streamlit (`st.dataframe`), Dash (DataTable), Shiny, and Panel (Tabulator) all lead
their dashboards with.

## Decision

Add a **`Table`** component whose data and view-state ride ordinary reactive props, so
there is **no `protocol_version` bump** (same principle as the list family, ADR-0016,
and charts, ADR-0018). It is a superset of `DataFrame`'s display, adding interaction:

- **Data:** the existing `{columns, rows}` shape (pandas duck-typed), unchanged.
- **Sort / page:** column headers sort; a page size pages large data. Where the data
  is small the shell can sort/page client-side (no round-trip); for large or
  server-owned data these are events (`sort`/`page`) the app handles, so the same
  component scales from a fixed frame to a backend query.
- **Select:** clicking a row emits a `select` event with the row id/index and binds a
  `Signal`, so a selection drives other components (the dashboard pattern:
  select a ticker → charts update).
- **Edit (later):** cell edit round-trips as an event; gated behind demand, not in the
  first cut.

`DataFrame` stays as the zero-interaction display (a `Table` with everything off is
equivalent); keep it for the simple case rather than forcing every table to be rich.

Also fold in **metric / KPI cards** (gap G4) alongside this slice — a small `Stat`
display component (value, label, optional delta) that dashboards pair with a table.
It carries only static/reactive props and needs no ADR of its own; recorded here so
the dashboard demo has both halves.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Extend `DataFrame` in place with all the interaction | Muddies the simple display case; a separate `Table` keeps `DataFrame` a clean zero-JS-logic display and lets `Table` own the interaction props |
| Bundle a heavy grid library (AG Grid, Tabulator) | Large addition to the shell for the notebook audience; a purpose-built sortable/pageable table covers the demos at a fraction of the size, matching indah's light-wheel value. Revisit only if a demo needs spreadsheet-grade editing |
| Client-only, never server-side sort/page | Breaks for large or backend-owned datasets; emitting sort/page as events lets the same component front a query |

## Consequences

- The stock/peer dashboard and the DataFrame explorer become practical; a selected row
  can drive charts/metrics reactively (the classic dashboard loop).
- Small-data tables stay a pure prop change (client-side sort/page); large-data tables
  use events, so the component scales without a wire change.
- `DataFrame` is unchanged; a new `table` (and `stat`) component type + prop/event
  schema are documented in `docs/protocol.md`, additive within `protocol_version` 1.

## As built (KAN-1462/1463, 2026-09-16)

- **`Table`** (`components.py`): same source as `DataFrame` (pandas / dict / records
  via `_to_table`), plus `page_size` and a `selected` `Signal[int]` (or `None`). A row
  click emits `select {index}` which sets the signal and patches back `value`, so a
  selection drives other components. `DataFrame` stays the zero-interaction display.
- **Sort + paging are client-side** (`Table.svelte`): header click sorts (numeric or
  locale string), `pageSize` pages, and the shell tracks each row's original index so
  a click/highlight refers to the source row, not the sorted/paged position. The
  planned server-side sort/page events are **not** built — client-side covers the
  demo data sizes; add them later if a backend-owned dataset needs them.
- **`Stat`** metric card: `value` + `label` + optional `delta` (shell colours by sign)
  + `help`. No new protocol capability.
- Documented in `docs/protocol.md`; guarded by unit tests + a browser e2e (sort, then
  select a row that drives a bound `Stat`).
