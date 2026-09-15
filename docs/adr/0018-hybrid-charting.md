# ADR-0018: Hybrid charting

- Status: Proposed
- Date: 2026-09-15
- Deciders: Jian (owner)

## Context

`Plot` today rasterises a Matplotlib figure to a PNG `data:` URI on the Python side
and reuses the `image` renderer (ADR-0005, V4). That is fine for a static or one-off
plot, but it is a whole PNG per frame: for interactive charts (zoom, hover) and
real-time/streaming data (live loss curves, spectrograms, sensor streams) it is
heavy, and each frame also pays the ~8 KB proxy-flush pad (KAN-1395). The data-viz
half of the roadmap (Slice E) needs better.

## Decision

Go **hybrid**.

- **Keep server-PNG `Plot`** (Matplotlib, duck-typed, no hard dependency) for static
  and one-off figures — it stays the zero-JS path and needs nothing in the browser.
- **Add one client-side chart component** built into the shell at build time. Its
  data and encoding ride ordinary reactive props; streaming series use the existing
  `append` op to push points at O(point) cost. Interactive behaviours (zoom, hover,
  live update) run in the browser.

Recommended library: **uPlot** (~40 KB, built for real-time time-series; aligns with
the future live-detection direction and keeps the wheel light). Chart.js and
Vega-Lite were considered for richer defaults at higher weight; the final pick is
made in this ADR when the slice is built. The library is bundled into the pre-built
shell — it is **not** a Python runtime dependency, and no Node is added at install or
runtime (ADR-0004).

Because chart data travels as props, there is **no `protocol_version` bump**.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Server-PNG only, forever | Real-time/interactive charts stay weak, and every frame pays the per-frame pad (KAN-1395) |
| Vega-Lite / Plotly as the primary | Rich, but a heavy addition to the wheel/shell for the notebook audience; uPlot covers the real-time need at a fraction of the size |
| Client-only charts (drop Matplotlib) | Loses the familiar, zero-JS static path researchers already reach for |
| A generic chart via the render spec (ADR-0012) | The spec is deliberately loop/condition-free and cannot express a chart; heavy UI is a first-class shell component by design |

## Consequences

- Interactive and real-time charts (live curves, heatmaps, spectrograms) become
  practical; static Matplotlib plots keep working unchanged.
- The shell/wheel grows by the bundled chart library (single, pinned, build-time).
- Couples with KAN-1395: streaming chart points amplify the same per-frame proxy pad
  as streaming tokens, so that transport fix should land before or with this slice.
- No wire-format change; a new `chart` component type and its prop schema are
  documented in `docs/protocol.md`.
- Picks a charting library as a build-time dependency of `frontend/` only; the
  Python package stays pure-Python.
