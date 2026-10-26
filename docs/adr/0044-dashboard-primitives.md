# ADR-0044: Dashboard primitives: a fixed frame, track grids, fill heights

- Status: **Accepted** 2026-10-26 (built on `agent/dashboard-primitives`)
- Date: 2026-10-26
- Deciders: Jian (owner)
- Builds on: ADR-0015 (layout components), ADR-0018 and ADR-0019 (chart, heatmap), ADR-0014 (tokens)
- Driven by: the Tower of Hanoi replay dashboard (github.com/leejianrong/tower-of-hanoi, ADR-0006
  there), the first indah app meant to be screen-recorded on one screen.

## Context

A recorded dashboard must fit one screen with no scrolling, whatever the window. indah's layout
flows and wraps: `Grid` collapses to one column on a phone, `Card` and `Chart` take their content's
height, and the page scrolls. Fitting a layout to a window with those pieces means guessing sizes in
CSS indah does not expose.

## Decision

1. **`Frame`**, a container with a fixed design size (default 1920 by 1080). Its children are laid
   out once inside that box, which the shell scales uniformly (CSS `transform`) and centres, so the
   layout is identical at any window size. `fit="contain"` (default) fits the width its parent gives
   and the height left in the window; `"shrink"` never scales up; `"width"` fits the width only, for a
   compact frame in a card. `kiosk=True` covers the whole window for recording. Children fill a CSS
   grid given as track lists (`columns="1fr"`, `rows="56px 1fr 196px"`).
2. **`Grid(columns=..., rows=...)`** also takes a track list (`"760px 1fr"`), and a new **`Cell`**
   spans columns or rows. Track lists are checked token by token (px, rem, em, %, fr, auto,
   minmax, at most 24), so nothing else can ride in on the style attribute. Inside a frame a grid
   never collapses to one column, because a frame has a fixed design size.
3. **`Chart` and `Heatmap` accept `height="fill"`**: the plot takes the height its container gives it
   (the title and legend are measured and subtracted), so a card in a frame is filled rather than
   padded.

All three are additive: a new component type or prop, with no `protocol_version` bump (ADR-0005).

## Alternatives considered

| Option | Why not |
|--------|---------|
| Tell apps to use `vh` units and CSS they write themselves | Every dashboard would reinvent it, and indah has no way to carry arbitrary CSS |
| A viewport-sized layout with no scaling | Text and charts keep a fixed pixel size, so a layout designed for 1920 wide breaks at 1280 |
| `position: fixed` for every frame | It would cover indah's own header and app shell; only kiosk mode should |

## Consequences

- A dashboard designed once at 1920 by 1080 renders the same at 1280 by 720 and 3840 by 2160, with
  no scrollbar. Text scales with the box, so very small windows give small text; that is the trade.
- With the default fit the page's own footer (the "live" badge) is hidden, because there is no room
  for it.
- `Frame` measures its own top edge and the page's bottom padding, so it assumes it is laid out
  once in the page flow; two stacked frames each fit the whole remaining height.
