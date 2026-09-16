# ADR-0019: Client-side heatmap / 2-D field renderer

- Status: Accepted
- Date: 2026-09-16 (accepted + built same day, KAN-1461)
- Deciders: Jian (owner)

## Context

Slice E shipped the client `Chart` as a line / time-series chart (uPlot, ADR-0018).
Raster output — heatmaps, spectrograms, attention/confusion maps — stayed on the
server-PNG `Plot` (Matplotlib `imshow`), the zero-JS static path. That is fine for a
one-off figure, but the Phase 2 demo push leans on **real-time, interactive** 2-D
fields: a streaming audio spectrogram, a live attention map, a segmentation heat
overlay. A whole PNG per frame is exactly the weight ADR-0018 went hybrid to avoid,
and it loses hover/zoom. The owner prioritised a client-side heatmap (2026-09-16).

## Decision

Add a **client-side 2-D field component** built into the shell, mirroring the
`Chart` pattern (ADR-0018): its data and encoding ride ordinary reactive props, so
there is **no `protocol_version` bump**, and a streaming field pushes new rows/columns
via the existing `append` op at O(row) rather than resending the grid.

- **Data shape:** a 2-D array of values (`z[y][x]`) plus optional `x`/`y` coordinate
  vectors; a `colormap` name and `zmin`/`zmax` for the scale. A spectrogram streams by
  appending a new time-column (or row) as it arrives — the same append-of-rows path
  `Chart` uses for points, so a live spectrogram grows at O(column).
- **Renderer:** draw to a `<canvas>` in a small Svelte component (like `Chart.svelte`).
  A hand-rolled canvas fill is enough for a heatmap/spectrogram and adds no dependency;
  if a richer library is wanted later it is bundled at build time like uPlot (no Node
  at install/runtime, ADR-0004). Hover-to-read and zoom run client-side.
- **Keep server-PNG `Plot`** for static raster and for anything Matplotlib does that a
  simple field renderer does not (contours, complex colorbars). Hybrid, as ADR-0018.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Keep heatmaps on server-PNG `Plot` only | A PNG per frame is heavy for streaming spectrograms and loses interactivity — the ADR-0018 problem, restated |
| Extend uPlot with a heatmap paths plugin | uPlot is line/time-series first; a heatmap needs a custom draw hook that is as much work as a small purpose-built canvas renderer, with an awkward data model |
| A generic WebGL field renderer / bundle a heavy viz lib | Overkill for the demo push; a canvas fill covers heatmaps and spectrograms at a fraction of the size, matching indah's light-wheel value |

## Consequences

- Real-time/interactive heatmaps and spectrograms become practical (unblocks the
  audio-analysis demo and the spectrogram half of image/attention demos); static
  raster keeps working on `Plot`.
- The shell grows by a small canvas renderer (and a bundled lib only if we later
  decide we need one); the Python package stays pure-Python.
- Streaming uses the existing append op (now array-aware after Slice E), so no wire
  change and it composes with the KAN-1395 flush coalescing.
- A new `heatmap` (or `field`) component type + its prop schema get documented in
  `docs/protocol.md`, additive within `protocol_version` 1.

## As built (KAN-1461, 2026-09-16)

- **`Heatmap` component** (`components.py`): a column-major field `z` (`z[x][y]`) on
  ordinary reactive props — no `protocol_version` bump. Reactive mode (`z=` a
  Signal/callable/list, replaced on change) and streaming mode (`push_column` /
  `extend` / `clear` append time slices via the append op at O(column), the Chart
  path). Snapshot carries the full field for a resume.
- **Renderer** (`Heatmap.svelte`): a hand-rolled canvas fill — an offscreen
  `ImageData` at data resolution drawn scaled (nearest-neighbour) to the canvas, so a
  redraw is O(cells) with no dependency. Built-in colormaps `magma` / `viridis` /
  `gray` (anchor-stop interpolation); `y = 0` at the bottom (spectrogram convention);
  auto colour-scale when `zmin`/`zmax` are omitted.
- **Server-PNG `Plot` stays** for static raster and Matplotlib-only cases (hybrid,
  ADR-0018). Streaming rides the array-aware append op (Slice E) and composes with the
  KAN-1395 flush coalescing.
- Documented in `docs/protocol.md`; guarded by unit tests + a browser e2e (canvas
  mounts, streamed columns grow the field).
