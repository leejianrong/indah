# ADR-0048: Graph, an interactive node-link graph with a focus window

- Status: **Accepted 2026-11-04** (IND-244, design only; nothing here is built)
- Date: 2026-11-04
- Deciders: Jian (owner); reviewed by the indah session against the code (changes applied below)
- Relates to: ADR-0004 (pre-built shell, no Node), ADR-0019 (hand-rolled canvas heatmap), ADR-0037 (limits),
  ADR-0038 (CSP), ADR-0042 (lazy modules and the size budget), ADR-0027 (Table selection events),
  ADR-0044 (Map v2)

## Context

indah draws charts, heatmaps, maps and tables, but not a graph of nodes and edges. The first user is the
graph-rag synthetic data generator, which needs to show a generated knowledge graph (up to a few thousand
entities, with typed relations), let a person pan around it, click an entity for detail, and highlight a
multi-hop path. Knowledge graphs, dependency graphs, call graphs and org charts all want the same thing.

Two facts shape the design:

1. **Big graphs are unreadable and slow if everything is drawn in full.** Past a few hundred labelled nodes a
   picture is a hairball, and thousands of DOM elements make pan and zoom stutter. The useful view is local:
   the neighbourhood you are looking at in detail, with the rest of the graph visible only as context.
2. **A server-PNG `Plot` (networkx plus Matplotlib) is already possible and is not enough.** It has no hover,
   no click, no pan, and a fresh PNG per interaction.

## Decision

Add a **`Graph` component**: a hand-rolled canvas renderer (as `Heatmap`, ADR-0019) in a **lazy module**
(ADR-0042). Data and encoding ride ordinary reactive props, so there is **no `protocol_version` bump**.

### Python API

```python
Graph(
    nodes,                      # Source: list of {id, label?, group?, size?, color?, x?, y?} or ids
    edges,                      # Source: list of {source, target, id?, label?, color?} or (source, target)
    *,
    selected: Signal[str | None] | None = None,   # two-way: click a node to select, set it to select
    focus: Source = None,                          # node id to centre on (Python -> viewer)
    focus_size: Source = 300,                      # how many nodes are drawn in detail
    highlight: Source = None,                      # {"nodes": [ids], "edges": [ids]}
    height: int | Literal["fill"] = 480,           # pixels or "fill", as Heatmap and Chart
    layout: Literal["auto", "given"] = "auto",
    legend: bool = True,
    max_nodes: int = 10_000,                       # raise up to the hard ceiling below
    label: str = "",                               # aria-label
)
```

- **Groups and colour.** `group` picks a colour from the Studio palette tokens (light and dark aware), shown in
  a legend; an explicit `color` wins. `size` scales the node radius (default by degree).
- **Edges** may carry an `id` so a caller can highlight them. A tuple `(source, target)` is accepted.
- **Errors at build time.** An edge naming an unknown node, a duplicate node id, or more than `max_nodes` nodes
  raises `ValueError` in Python, before anything is sent.
- **Hover is not in the first cut.** A hovered node shows a client-side tooltip (its label), with no event sent
  to Python. See "Events" for why, and the follow-up.

### The focus window (level of detail by proximity)

The viewer keeps a **focus point** (the viewport centre, or a selected or `focus`-ed node). The **`focus_size`
nodes nearest to it in layout space** are the *detailed* set: drawn as full circles with labels, and edges are
drawn between them. Every other node is a **dot**: a one-to-two pixel square in its group colour, no label, no
edges. Panning moves the focus point, so detail follows the viewer across the canvas; clicking a node or a dot
selects it, centres the focus on it and promotes it. Zoom scales the canvas and never changes which nodes are
detailed. Proximity is found with a uniform grid index built once per layout, so choosing the window is
O(window), not O(nodes).

Two rules keep the window from hiding what matters:

- **Highlighted nodes and edges are always drawn in full**, whether or not they are inside the window, so a path
  that runs outside it is never reduced to dots.
- **A selected node draws every edge incident to it and promotes its neighbours** into the detailed set, so it
  never looks isolated because its neighbours are dots. The window grows by those neighbours (they count toward
  a draw budget of `focus_size` plus a fixed allowance, so a hub cannot make the frame unbounded; beyond the
  allowance the nearest neighbours win).

Dots are batched into one path per colour, so a graph at the node ceiling stays interactive; detail is bounded by
`focus_size` whatever the graph size.

### Layout

- `layout="auto"` (default): positions are computed in the browser. Nodes start on a seeded, group-clustered
  spiral; up to **8,000 nodes** are then relaxed with a Barnes-Hut force simulation (repulsion, spring along
  edges, weak pull to the group centre) that cools and stops. Above 8,000 nodes the group-clustered placement is
  used as is. The seed comes from the data, so the same graph always lays out the same way.
- `layout="given"`: every node carries `x` and `y` and nothing is simulated (for callers with their own layout).
- The simulation runs **on the main thread in time slices** (about 8 ms per frame), not in a Web Worker, so no
  CSP `worker-src` is needed (ADR-0038) and the page stays responsive while it settles.

### Events

Wire events use the existing `POST /api/event` (the `Table` `select` pattern, no new transport):

| Event | Payload | Effect |
|-------|---------|--------|
| `select` | `{"id": "E001"}` or `{"id": null}` | sets `selected` |

The payload key is `id` on purpose: `Table` sends `{key}` or `{index}` because rows may lack ids, but graph nodes
always have one. `Graph.handle` returns `True` for `select`, `False` otherwise, and **checks that the id is a
known node id or `None`**; any other string is refused, so a viewer cannot set `selected` to an arbitrary value.
The viewer's own pan and zoom are not reported to Python, as with `Map` and `ImageOverlay`. A `Signal` is bound
only when given, so a display-only graph sends no events. Setting `selected` or `focus` from Python re-centres
the viewer.

**Why no `hovered` yet.** No component posts on pointer move today. The hosting guide recommends
`Rate(per_second=5, burst=30)` for `/api/event`, and rate buckets are per address and per route, so hover would
share one bucket with every click and slider. Even throttled to 100 ms, moving over nodes can spend a burst of 30
in about six seconds and then a hosted app returns 429 on hover *and* on real events, which looks like dead
controls. The graph-rag detail panel works from `selected`. A follow-up card may add `hovered` once it is
needed, with these rules: post only when the hovered id **changes**, with a trailing debounce of about 250 ms,
nothing when unbound, and a 429 dropped silently on the client; the rate budget is documented with it.

### Wire shape

`nodes` and `edges` ship **columnar**, and edges refer to nodes by **integer index**, not id:

```json
{"nodes": {"id": ["E000", ...], "label": [...], "group": [...], "size": [...]},
 "edges": {"s": [0, 4, ...], "t": [3, 9, ...], "id": ["F000", ...]}}
```

Ids live only in the node columns. Index encoding roughly halves the edge payload against id strings, needs no
id-to-index map in the browser, and turns an unknown-node edge into a Python error at build time. The Python API
stays list-of-dicts. The props are **computed once** (a `computed`, not rebuilt inside a props lambda), so an
unrelated signal change does not re-columnarise the graph. `highlight`, `focus`, `focus_size` and `selected` are
separate props, so showing a path does not resend the graph.

**Message size.** The graph rides one SSE event, again in every `init` and on every reconnect, and the stream is
not compressed (only the shell is), and some proxies buffer SSE. Estimates, to be measured in IND-245: 10,000
nodes and 30,000 edges is about 0.7 MB; the hard ceiling of **20,000 nodes and 60,000 edges** is about 1.5 MB.
The default `max_nodes` is therefore 10,000 (edges are capped at three times the node limit), raisable to the
ceiling by the caller who accepts the message size. Props merge shallowly in a patch (`docs/protocol.md`), so a
changed graph replaces `nodes` and `edges` whole; `Heatmap` already ships column-major data the same way.

### Rendering, input and theme

- **Theme.** Reuse what `Heatmap.svelte` does: resolve any CSS colour or `var(--token)` through a 1x1 canvas,
  read the muted and text tokens, and redraw on a theme change. Colours and label text come from the Studio
  tokens, so light and dark work and contrast is checked against them.
- **Pointer.** Drag to pan follows `ImageOverlay`'s pointer capture; wheel and pinch zoom. Hit-testing and the
  grid index use CSS pixels and account for `devicePixelRatio`; the canvas resizes with its container (a
  `ResizeObserver`) and the backing store is rescaled so hit-testing stays correct on high-DPI screens.
- **Keyboard.** The canvas is focusable (`tabindex`, a role and `aria-label`). Arrow keys pan, `+` and `-` zoom,
  `Esc` clears the selection. There is no keyboard precedent in `Heatmap` or `ImageOverlay`; `Table.svelte`
  (`j`/`k`, arrows, `Esc`) is the closest model. A graph is not a text equivalent: apps should pair it with a
  detail panel for the selected node, which is what `selected` is for.
- **CSP.** Canvas needs no CSP change, and a lazy same-origin module import is what `Map` already does. The whole
  e2e suite already runs under `csp="strict"` (`tests/e2e/conftest.py`) and fails on any violation.

### Lazy module and size

`Graph` is a lazy module (ADR-0042). `Map` shows the five touch points, and `Graph` needs the same five:

1. `frontend/graph/graph.js`, the module source.
2. The `build:indah` script in `frontend/package.json` builds it to `dist-graph/` and copies it to
   `src/indah/static/graph.js`.
3. A content hash (`__GRAPH_HASH__`) in `frontend/vite.config.js`.
4. A `Route("/api/graph.js", ...)` with `_lazy_module("graph.js")` in `src/indah/app.py`.
5. A `Graph.svelte` loader that `import()`s `api/graph.js?v=<hash>` on first mount.

**Budget.** Add `graph_raw_bytes` and `graph_gzip_bytes` to `docs/size-budget.json` **and** measure them in
`scripts/size_report.py` in the same diff, because a budgeted key with no measurement fails the size gate. Per
that file's convention the limits sit about 15 percent above the measured number, so IND-245 sets them from the
measurement, not from a target. The estimate is about 30 KB raw and 10 KB gzip, which is unmeasured.
`wheel_bytes` (630,000) and `sdist_bytes` will need headroom for the new module; the PR says so and updates the
CHANGELOG. No new runtime dependency.

## Alternatives considered

| Option | Why not |
|--------|---------|
| **SVG** nodes and edges | One DOM element per node and edge: 5,000 nodes and 12,000 edges is about 17,000 elements, which makes pan and zoom janky and style recalculation costly. Fine to a few hundred, wrong for this. |
| **A graph library** (Cytoscape.js about 360 KB min, Sigma.js plus graphology about 150 KB, vis-network about 500 KB) | Several times the size of the whole `Map` module for features we do not need, and they bring their own event, style and theming models to fight the Studio tokens. The shell's value is a light wheel (ADR-0042). |
| **d3-force for layout only** | A reasonable fallback (about 12 KB min, battle-tested). Not first choice because a seeded, group-clustered start and a time-sliced loop are small, and owning them keeps layouts reproducible. If a hand-rolled simulation proves poor in practice this is the swap, behind the same props. |
| **WebGL** (regl or raw) | Needed past roughly 50,000 nodes. At the ceiling batched 2D canvas dots are fast enough, and WebGL adds context-loss handling, a larger module and harder testing. Revisit if the ceiling is raised. |
| **Layout on the server** (networkx, igraph) | Adds a Python dependency to a pure-Python package (ADR-0042 counts direct dependencies) and ships positions in every payload. Callers who want it can use `layout="given"`. |
| **A Web Worker for layout** | Needs `worker-src blob:` under strict CSP and a message protocol; main-thread time slicing at 8,000 nodes is enough. Revisit if profiling shows jank. |
| **Draw everything, no focus window** | Unreadable and slow above a few hundred nodes; the user-facing requirement is a local, readable view with context. |
| **Ship `hovered` in the first cut** | No precedent, and it competes with real events for the same rate bucket (see Events). Deferred, not rejected. |

## Why canvas holds at 5,000 nodes

Per frame the work is bounded by the focus window, not the graph: up to `focus_size` circles with labels and
the edges among them, plus one batched fill per group colour for the dots (5,000 dots is 5,000 `rect` calls in
a single path per colour, well under a millisecond to a few milliseconds). Layout is the only O(graph) cost and
is paid once, in time slices, on data change. IND-245 must demonstrate a 5,000-node, 12,000-edge graph before the
component is accepted. **The gate is settle time: the layout settles in under three seconds.** Frame rate (target
60 fps while panning) is recorded and **informational only**, because headless CI Chromium is software-rendered
and its frame rate says little about a real browser. If the gate fails, the layout limit above is lowered.

## Consequences

- indah can draw interactive node-link graphs with no dependency and no Node at runtime; `Plot` stays for static
  networkx figures.
- The shell grows only by a lazy module (budget set from measurement in the same diff as the implementation).
- `docs/protocol.md` gains the `graph` component type and its props, additive within `protocol_version` 1.
- Python gets a two-way `selected`, following the `Table` pattern. `hovered` is a follow-up.
- Very large worlds (for example 50,000 entities) must be sampled by the caller; the ceiling is deliberate, not
  a bug.

## Implementation plan

1. **IND-245** renders a pannable, zoomable force-directed `Graph` (layout, canvas, the lazy-module touch points,
   the size budget and `size_report.py`, and the 5,000-node measurement).
2. **IND-246** adds the focus window and the dot rendering, with the highlight and selected-neighbour rules.
3. **IND-247** adds `selected`, `highlight` and `focus`, with id validation in `Graph.handle`.
4. **IND-248** adds docs, the `docs/protocol.md` row, a Studio page (`tests/unit/test_studio_coverage.py` fails on
   any new public name without one) and an end-to-end test that covers pan, focus, click **and keyboard and
   focus handling** under `csp="strict"`.
5. A later card adds `hovered` if it is wanted.
