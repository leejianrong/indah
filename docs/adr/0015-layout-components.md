# ADR-0015: Layout components

- Status: Accepted
- Date: 2026-09-15
- Deciders: Jian (owner)

## Context

The only container today is `Column` (ADR-0003). Almost every real app needs more
arrangement than a single vertical stack: inputs-left / outputs-right (the classic
Gradio shape), dashboards, tabbed sections, a sidebar, collapsible detail. This is
the shared foundation the post-MVP round put first (Slice A), and it serves both the
ML-demo and data-viz halves.

The UI tree already carries `children` on the wire (ADR-0005), so *arrangement of
existing children* needs no new protocol capability — it is a rendering concern.

## Decision

Add a set of first-class container components the pre-built shell renders, styled
through the design tokens (ADR-0014):

- `Row` — horizontal flex with wrap/gap.
- `Grid` — N columns, responsive collapse to one column at phone width.
- `Tabs` — shows one active child; the active index rides an ordinary reactive prop.
- `Sidebar` — a persistent side region + main region (collapses on narrow screens).
- `Expander` — a collapsible section; open/closed is a reactive prop.

All of them arrange existing child nodes, so there is **no protocol change**: the
tree still serialises as nodes with `children`, and show/hide/active state travels
as normal reactive props merged by the existing `patch` op. Layout is CSS in the
shell driven by static props (columns, gap, orientation).

## Alternatives considered

| Option | Why not |
|--------|---------|
| A CSS-grammar prop (arbitrary fl/grid strings) | Pushes layout logic onto the app author and widens the surface; a small set of named containers covers the real cases |
| Raw HTML/CSS injection | Against the data-only, inert-shell ethos (ADR-0012, Q-sec) |
| Defer layout | Blocks dashboards, multi-panel demos, and nearly every non-trivial app |

## Consequences

- Unblocks the dashboard/app-structure use cases and the standard inputs/outputs
  split; every later component slots into these containers.
- No `protocol_version` bump — arrangement rides existing `children` + props.
- `Tabs`/`Expander` need the shell to render only the active/expanded region; the
  layout model (naming, nesting, responsive rules) is documented alongside.
- Multi-page/routing is a separate, larger concern (needs a nav model and, for
  runtime-added pages, the structural op deferred in ADR-0016); `Tabs` covers the
  common "sections" case in the interim.
