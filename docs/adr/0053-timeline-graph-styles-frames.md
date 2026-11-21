# ADR-0053: Timeline, Graph element styles and Graph frames

- Status: **Proposed** 2026-11-21 (for owner review)
- Date: 2026-11-21
- Deciders: Jian (owner)
- Builds on: ADR-0048 (Graph), ADR-0013 (focus-owned inputs), ADR-0050 (Slider), ADR-0005 (additive changes)
- Driven by: `docs/design/indah-requests.md` in the graph-rag-demo repo (GRA-193), requests 2, 3 and 5. Requests
  1, 4 and 6 (reactive `Slider`, `ChoiceCards`, `Text` display) are built already. Cards IND-277, 278, 280.

## Context

The graph-rag Studio steps a changing graph through years. Today it builds a slider, four buttons and a text
readout by hand, paints "ended" and "not yet" states as colour only (lost on a node outside the focus window),
lets `group` move the nodes, and sends one whole graph per step, so play speed is capped by the shared
`/api/event` bucket (5 events/s). Stepping a changing thing through irregular moments is a general pattern
(a log, a run's history), so the pieces belong in indah.

## Decision

All additive and off by default (no `protocol_version` bump, ADR-0005). Three parts, built in this order.

### 1. `Timeline` (IND-277)

`Timeline(value, points, *, labels=None, density=None, unit=None, playing=None, speed=1.0)`.

- `points` is the ordered list of moments that exist (numbers or strings, unique, at most 2,000). `value` is a
  `Signal` holding one of them. Stepping goes to the next *point*, so irregular dates are stepped exactly.
- `labels` is a list the same length as `points`, or a callable `point -> str` that Python calls once per point;
  `density` is an optional list of non-negative numbers, one per point, drawn as small bars behind the track
  (where the busy moments are). `unit` ("year") is only for the screen reader: "year 2003, step 4 of 11".
- Controls: previous and next point, previous and next *event* (a point with density above 0), play and pause
  with a speed, arrow keys, Home and End, space to play. The track is a native range input over the point
  index, so keyboard and assistive technology work without custom roles.
- The wire carries the **index**, not the value: `input {index}`. Python maps it to `points[index]` and refuses
  an index out of range. This keeps duplicate-looking labels and mixed types out of the protocol.
- Playing is a browser timer that posts one `input` per step. The speed is capped at 4 steps a second so a
  hosted app on `Rate(per_second=5)` keeps working controls. `playing` is an optional `Signal[bool]`, two way.
  Reaching the last point stops playback, and pressing play at the last point starts again from the first. A step the server refuses with 429 is dropped without a message, as for Graph hover.
- Node type `timeline`; props `points` (the labels), `index`, `density`, `unit`, `playing`, `speed`.

### 2. Graph element styles and stable layout (IND-278)

- Node: `ring` (a colour or `True`), `opacity` (0 to 1), `label_style` (`"strike"` or `"bold"`). Edge: `dash`
  (`True` or `[dash, gap]`), `opacity`, `width`. Each is an optional key of the existing node and edge dicts.
- Styles are drawn identically inside and outside the focus window, so a dashed edge and a ringed dot are
  still visible far from the centre (the dot keeps its ring and opacity; the label style needs a label and is
  drawn only where labels are).
- **Layout is seeded from ids and edges only**, never from `group`, `color` or any style, so changing a style or
  a group never moves a node. This is a documented guarantee, with a test that reads positions before and after.
  Today's clustering by group changes: with `layout="auto"` the start is a deterministic function of the ids and
  edges. `group` still picks the colour and the legend.
- `Graph(update="keep")`: when `nodes` and `edges` are replaced, every id already on screen keeps its position
  and only new ids are placed (near their neighbours). The default stays today's behaviour (`"relayout"`).
- `transition_ms` (0 to 2,000, default 0) eases colour, opacity and position changes between updates. It is off
  under `prefers-reduced-motion`.

### 3. Graph frames (IND-280)

- `Graph(nodes, edges, frames=[...], frame=Signal[int])`: a base graph plus, per frame, a list of patches:
  `{"nodes": {id: style}, "edges": {id: style}, "hide": [ids]}`. Each style is the same dict as in part 2.
  Frame 0 is the base graph with its patches; a frame is the base plus *only its own* patches (no accumulation),
  so any frame can be shown directly.
- The browser applies a frame locally and reports only the frame number (`frame {index}`) when it settles.
  `Timeline(..., link=graph)` couples the two in the browser: while playing, the timeline steps the linked
  graph's frame locally and posts nothing; it reports the index once on pause, on reaching the end, and on any
  manual step. Playing 20 frames at 4 a second sends no events while it plays.
- Limits: at most 400 frames, and the patches of all frames together at most 60,000 entries (the same ceiling as
  edges). Unknown ids raise `ValueError` in Python, as `highlight` does.
- `frames` and `frame` are optional; a graph without them is unchanged.

## Not in scope

Range selection on the timeline, a calendar axis (use a time `Chart`), editing the graph from the viewer, and a
generic "linked components" mechanism: `link=` is only Timeline to Graph.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Build the timeline from `Slider` plus `Button` in the app | What the Studio does today; no density, no event stepping, no keyboard model, and each app repeats it. |
| Send the value, not the index | Duplicate or mixed-type points would be ambiguous on the wire, and the server has to look it up anyway. |
| A server timer for play | Costs a round trip per step against the same bucket as clicks; the browser timer costs the same events but is smoother and stops when the tab hides. |
| Whole graphs per frame | What is sent today; frames patch styles only, so a frame is a few hundred bytes. |
| Keep group-seeded layout, add `update="keep"` only | Fixes position drift between updates but not between two different frames of the same data. |

## Consequences

- The auto layout of existing graphs changes (no more group clustering). It is still deterministic. Graphs that
  need the old look can pass `x` and `y` with `layout="given"`. Listed under Changed in the CHANGELOG.
- The Python-source size budget needs raising for the three parts (about 4 KB left today); each PR says so.
- Three PRs, one per part, in the order above; part 3 needs part 2's style vocabulary.

## Open questions for the owner

1. Is capping play at 4 steps a second right, or should a hosted app be able to raise it with its own `Rate`?
2. Is changing the default layout acceptable (the guarantee needs it), or should stable layout be opt-in
   (`layout="stable"`) with the old clustering kept as the default until 1.0?
3. `Timeline(link=graph)` couples two components in the browser. Is that acceptable, or should frames play
   from the Graph's own control strip instead?
