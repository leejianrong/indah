# ADR-0049: Chart steps, log scales and annotations

- Status: **Accepted** 2026-11-12
- Date: 2026-11-12
- Deciders: Jian (owner)
- Builds on: ADR-0018 (chart), ADR-0046 (chart kinds, rules, playhead), ADR-0042 (size budget)
- Driven by: a progress dashboard for a separate project (a best-cost staircase, a threshold, a
  cost model across decades). The needs are general: every "best so far" line, every heavy-tailed
  metric and every annotated threshold.

## Decision

All additive, with no `protocol_version` bump (ADR-0005). Defaults leave an existing chart unchanged.

1. **`kind="step"`** series (uPlot `paths.stepped`). `align` is `"after"` (default: the value holds
   from its x until the next point) or `"before"`.
2. **`x_scale` / `y_scale`**, `"linear"` (default) or `"log"` (base 10, uPlot `distr: 3`). A log axis
   cannot place zero or below, so Python refuses a non-positive range, rule, band or marker, and the
   shell draws a non-positive data point as a gap.
3. **Annotations**, drawn in the existing overlay hook: `rules` take `x` (vertical) or `y`
   (horizontal), exactly one; new `bands` (`x0`/`x1` or `y0`/`y1`, `color`, `alpha`, `label`) and
   `markers` (`x`, `y`, `label`, `color`). Each list holds at most 12 items, colours go through
   `_color`, and labels are drawn as canvas text, never HTML.
4. **`indah.chart_rows({"name": [(x, y), ...], ...})`**, Python only: the sorted union of x, one
   column per series, `None` where a series has no point; NaN and infinity become `None`.

## Not in scope

Time and category axes, stacked bars and hover or click events (separate stories).

## Consequences

The shell grows by a small amount (see the PR for the measured delta). Markers use a ringed dot and
bands carry an optional label, so a region is not told apart by colour alone.
