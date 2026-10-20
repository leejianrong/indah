# ADR-0028: Editor and viewer family

- Status: Accepted for `TextArea` (IND-98), `JsonTree` (IND-108), `Diff` (IND-109); `CodeEditor` (IND-111) is on hold (Q4)
- Date: 2026-10-20
- Deciders: Jian (owner)
- Extends: ADR-0013 (focused inputs are client-owned)

## Context

semula's dashboard shows and edits JSON: a request and its cached response, a diff between an
incoming and a candidate entry, a free-text reply. indah had a single-line `TextInput` and no
viewer. The heavy answer (CodeMirror for syntax highlighting and folding) costs about 120 KB
compressed in the shell, so the cheaper pieces come first and the editor waits for evidence it
is needed (`docs/SEMULA-REQUESTS-PLAN.md`, Q4).

## Decision

- **`TextArea` is a native `<textarea>`**, zero bundle cost, two-way bound to a `Signal[str]`.
  It follows ADR-0013 (the DOM owns the value while focused) and adds what a long note needs:
  keystrokes are debounced into one POST per 150 ms pause, a blur flushes at once so a click
  right after typing never reads stale text, and `create_app(max_event_bytes=)` (default 1 MiB)
  rejects an oversize `/api/event` body with 413 before parsing it.
- **`JsonTree(value, expanded=, search=, label=)` is a read-only viewer** built in the shell, no
  dependency. `value` is an object, a list or JSON text. The server turns it into JSON-safe data
  (string keys, NaN/Infinity as strings, unknown objects as strings, nesting cut at 64) and
  sends one reactive prop `doc: {data, error}`; invalid text or a document over 8 MB becomes an
  `error` line, never an exception. The browser creates a node's children only when it is
  opened, in chunks of 100 ("show more" adds 200), so a megabyte document costs nothing until
  you look inside it. Search is time-sliced (8 ms slices, a newer query cancels the old one),
  finds keys and values case-insensitively up to 500 hits, and opens the path to each; a hit
  deep in a long list is rendered without rendering every sibling before it. Each node has a
  "copy path" button producing a JSONPath (`$.entries[3500].name`). Measured on a 1.1 MB
  document: no long task over 100 ms while rendering, searching, expanding and copying.
- **`Diff(a, b, mode=, normalise=, context=, labels=)` is computed in Python** (`indah.diff`) with
  stdlib `difflib`, so the browser only draws rows and the logic is testable in pytest. Inputs are
  objects, lists, JSON text or plain text; in `json` mode both sides are pretty-printed with sorted
  keys first, so key order and formatting never show up as changes (text that is not JSON is
  compared as written). Rows are `eq`/`del`/`add`/`chg`/`skip`; a `chg` row carries the character
  spans that differ on each side (skipped when the lines are too long or too unlike for marking to
  help), and runs of unchanged lines collapse to a `skip` row keeping `context` lines. A replaced
  block is paired by similarity (the `ndiff` idea), not by position, so a deleted line beside an
  edited one is not mistaken for an edit of it; a block of exactly one line for one line is always
  a changed line. The shell offers split and unified layouts and draws rows in chunks.
  **Bounds:** at most 5,000 lines per side are compared (flagged `truncated`), lines are clipped to
  2,000 characters, and because `difflib` is quadratic (8.7 s measured on a repetitive 5k-line
  pair) the common prefix and suffix are trimmed first and a remaining block above 1.5 million line
  pairs is diffed with `autojunk` on, which is fast but coarser (flagged `approximate`). A diff of
  line-oriented pretty JSON is a line diff: adding a last key also changes the previous line by its
  trailing comma, as in git.
- **`CodeEditor` is deferred.** If the entry-editor demo shows a plain `TextArea` is not
  enough, it will be a second static file loaded with `import()` on first use, so apps that
  never use it pay nothing (this will amend ADR-0004's "fetches nothing at runtime" to "nothing
  from a third party").
- All additive: new node types and props, no `protocol_version` bump.

## Alternatives considered

| Option | Why not |
|--------|---------|
| A JS JSON-tree library | A dependency for a 150-line component, and none of the ones surveyed render lazily in chunks. |
| Send the tree pre-flattened from the server | A megabyte becomes several, and every expand would be a round trip. The browser already holds the document. |
| Render everything, collapse with CSS | 60k nodes in the DOM at once is the long task this avoids. |

## Consequences

- A `JsonTree` document rides one prop, so it is limited by the SSE frame and the 8 MB cap, not by
  rendering. Larger inspection needs a remote viewer (out of scope).
- Search scans the document in the browser; it never sends the query to the server.
- `Diff` runs on the event loop inside a computed, so its worst case is bounded by the limits above
  (well under a second for exact diffs); anything larger is approximate rather than slow.
- Three-way merge and a structural (tree) JSON diff are out of scope.
