# ADR-0048: Graph, an interactive node-link graph with a focus window

- Status: **Proposed** (IND-244, design only; nothing here is built)
- Date: 2026-11-04
- Deciders: Jian (owner)
- Relates to: ADR-0004 (pre-built shell, no Node), ADR-0019 (hand-rolled canvas heatmap), ADR-0038 (CSP),
  ADR-0042 (lazy modules and the size budget), ADR-0027 (Table selection events), ADR-0044 (Map v2)

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
    hovered: Signal[str | None] | None = None,    # one-way from the viewer, debounced
    focus: Source = None,                          # node id to centre on (Python -> viewer)
    focus_size: Source = 300,                      # how many nodes are drawn in detail
    highlight: Source = None,                      # {"nodes": [ids], "edges": [ids]}
    height: int = 480,
    layout: Literal["auto", "given"] = "auto",
    legend: bool = True,
    label: str = "",                               # aria-label
)
```

- **Groups and colour.** `group` picks a colour from the Studio palette tokens (light and dark aware), shown in
  a legend; an explicit `color` wins. `size` scales the node radius (default by degree).
- **Edges** may carry an `id` so a caller can highlight them. A tuple `(source, target)` is accepted.
- **`highlight`** is its own small reactive prop, separate from `nodes` and `edges`, so showing a path does not
  resend the graph. Highlighted nodes and edges are drawn emphasised and everything else is dimmed.
- **Limits.** At most **20,000 nodes and 60,000 edges**; more raises `ValueError` pointing the caller at
  sampling. An edge naming an unknown node is an error, not a silent drop.

### The focus window (level of detail by proximity)

The viewer keeps a **focus point** (the viewport centre, or a selected or `focus`-ed node). The **`focus_size`
nodes nearest to it in layout space** are the *detailed* set: drawn as full circles with labels, and edges are
drawn between them. Every other node is a **dot**: a one-to-two pixel square in its group colour, no label, no
edges. Panning moves the focus point, so detail follows the viewer across the canvas; clicking a node or a dot
selects it, centres the focus on it and promotes it. Zoom scales the canvas and never changes which nodes are
detailed. Proximity is found with a uniform grid index built once per layout, so choosing the window is
O(window), not O(nodes).

Dots are batched into one path per colour, so a graph of 20,000 nodes stays interactive; detail is bounded by
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

Wire events use the existing `POST /api/event` (ADR-0027 pattern, no new transport):

| Event | Payload | Effect |
|-------|---------|--------|
| `select` | `{"id": "E001"}` or `{"id": null}` | sets `selected` |
| `hover` | `{"id": "E001"}` or `{"id": null}` | sets `hovered`; throttled to one per 100 ms |

The viewer's own pan and zoom are **not** reported to Python, as with `Map` and `ImageOverlay`. A `Signal` is
bound only when given, so a display-only graph sends no events. Setting `selected` or `focus` from Python
re-centres the viewer.

### Wire shape

`nodes` and `edges` ship **columnar** (`{"id": [...], "label": [...], "group": [...]}`), which is roughly a third
the size of a list of objects for a large graph. The Python API stays list-of-dicts. The full graph is resent
only when `nodes` or `edges` change; `highlight`, `focus`, `focus_size` and `selected` are separate props.

### Accessibility and theme

The canvas has a role and `aria-label`; it is keyboard-focusable: arrow keys pan, `+` and `-` zoom, `Esc`
clears the selection. Colours and label text read the Studio tokens, so light and dark work and the contrast
is checked against them. A graph is not a text equivalent: apps should pair it with a detail panel for the
selected node, which is what `selected` is for.

### Size

The module is lazy, loaded on first `Graph` mount (ADR-0042). Target: **at most 30 KB raw / 10 KB gzip**, with
a new `graph_raw_bytes` and `graph_gzip_bytes` budget in `docs/size-budget.json`. No new runtime dependency.

## Alternatives considered

| Option | Why not |
|--------|---------|
| **SVG** nodes and edges | One DOM element per node and edge: 5,000 nodes and 12,000 edges is about 17,000 elements, which makes pan and zoom janky and style recalculation costly. Fine to a few hundred, wrong for this. |
| **A graph library** (Cytoscape.js about 360 KB min, Sigma.js plus graphology about 150 KB, vis-network about 500 KB) | Several times the size of the whole `Map` module for features we do not need, and they bring their own event, style and theming models to fight the Studio tokens. The shell's value is a light wheel (ADR-0042). |
| **d3-force for layout only** | A reasonable fallback (about 12 KB min, battle-tested). Not first choice because a seeded, group-clustered start and a time-sliced loop are small, and owning them keeps layouts reproducible. If a hand-rolled simulation proves poor in practice this is the swap, behind the same props. |
| **WebGL** (regl or raw) | Needed past roughly 50,000 nodes. At the 20,000-node cap batched 2D canvas dots are fast enough, and WebGL adds context-loss handling, a larger module and harder testing. Revisit if the cap is raised. |
| **Layout on the server** (networkx, igraph) | Adds a Python dependency to a pure-Python package (ADR-0042 counts direct dependencies) and ships positions in every payload. Callers who want it can use `layout="given"`. |
| **A Web Worker for layout** | Needs `worker-src blob:` under strict CSP and a message protocol; main-thread time slicing at 8,000 nodes is enough. Revisit if profiling shows jank. |
| **Draw everything, no focus window** | Unreadable and slow above a few hundred nodes; the user-facing requirement is a local, readable view with context. |

## Why canvas holds at 5,000 nodes

Per frame the work is bounded by the focus window, not the graph: up to `focus_size` circles with labels and
the edges among them, plus one batched fill per group colour for the dots (5,000 dots is 5,000 `rect` calls in
a single path per colour, well under a millisecond to a few milliseconds). Layout is the only O(graph) cost and
is paid once, in time slices, on data change. This is verified before the component is accepted: the
implementation card (IND-245) must show a 5,000-node, 12,000-edge graph panning at 60 fps and settling in under
three seconds on the CI browser, or the layout limit above is lowered.

## Consequences

- indah can draw interactive node-link graphs with no dependency and no Node at runtime; `Plot` stays for static
  networkx figures.
- The shell grows only by a lazy module (budget set in the same diff as the implementation).
- `docs/protocol.md` gains the `graph` component type and its props, additive within `protocol_version` 1.
- Python gets two-way `selected` and one-way `hovered`, following the `Table` pattern.
- The 20,000-node cap means very large worlds (for example 50,000 entities) must be sampled by the caller; that is
  a deliberate limit, not a bug.

## Implementation plan

1. IND-245 renders a pannable, zoomable force-directed `Graph` (layout and canvas).
2. IND-246 adds the focus window and the dot rendering.
3. IND-247 adds `selected`, `hovered`, `highlight` and `focus` events.
4. IND-248 adds docs, a Studio page and an end-to-end test under `csp="strict"`.
