# ADR-0027: Table v2: keyed rows, typed columns and streamed rows

- Status: Accepted (core built in IND-91; client filter, row actions and remote mode follow)
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
- Not yet built (later cards in the same epic): client-side search and column toggle,
  follow-tail, row actions and multi-select, server-driven (remote) queries and virtual
  scroll for thousands of rows.
