<script>
  // Client-side chart (ADR-0018, KAN-1423; ADR-0046). uPlot is bundled into the shell at
  // build time (a devDependency of frontend/, inlined by the singlefile build) --
  // it is NOT a Python runtime dep and adds no Node at install or runtime.
  //
  // Data and encoding ride ordinary reactive props: `data` is a list of rows
  // [[x, y0, y1, ...], ...] and `series` names the y columns. Streaming points
  // arrive via the `append` patch op (App.svelte concatenates arrays), so a live
  // curve grows at O(point) on the wire; uPlot redraws in the browser. Zoom (drag)
  // and hover run client-side.
  //
  // ADR-0046 adds, all optional: a series `kind` (line, scatter, bars), `dash`, `width`,
  // `alpha`; fixed `xRange` / `yRange`; a `playhead` (a vertical line, with the region after it
  // shaded when `shadeAfter`); horizontal `rules`; a `highlight` bar; and colours written as
  // var(--token) that follow the light/dark switch.
  import uPlot from "uplot";
  import "uplot/dist/uPlot.min.css";
  import { untrack } from "svelte";
  import { resolveColor, onThemeChange } from "./colors.js";

  let { props } = $props();
  let el = $state();
  let u = null;

  // A vivid palette that reads on both the light and dark Studio themes.
  const PALETTE = ["#b5296b", "#2e6d62", "#e0701a", "#3457d5", "#8a3ffc", "#c0362c"];
  const AXIS = "#8a8590"; // neutral so axes/labels stay legible in either theme

  function ySeries() {
    return props.series ?? [];
  }

  function seriesConfig() {
    return [
      {}, // x
      ...ySeries().map((s, i) => {
        const o = typeof s === "string" ? { label: s } : s;
        const stroke = resolveColor(el, o.stroke || PALETTE[i % PALETTE.length]);
        const base = { label: o.label ?? `y${i + 1}`, stroke, width: o.width ?? 2 };
        if (o.dash) base.dash = o.dash;
        if (o.alpha != null) base.alpha = o.alpha;
        if (o.kind === "scatter") {
          const size = o.size ?? 5;
          return { ...base, paths: () => null, points: { show: true, size, fill: stroke, stroke, width: 0 } };
        }
        if (o.kind === "bars") {
          return {
            ...base,
            width: 0,
            fill: stroke,
            paths: uPlot.paths.bars({ size: [0.55, 60] }),
            points: { show: false },
          };
        }
        return { ...base, points: { show: props.points ?? false } };
      }),
    ];
  }

  // Rows [[x, y0, y1], ...] -> uPlot's columnar [[x...], [y0...], [y1...]].
  function columnar() {
    const n = ySeries().length;
    const cols = Array.from({ length: n + 1 }, () => []);
    for (const row of props.data ?? []) {
      for (let i = 0; i <= n; i++) cols[i].push(row?.[i] ?? null);
    }
    return cols;
  }

  // height="fill" (ADR-0046): the plot takes the height its container gives it, less the title
  // and legend uPlot adds around the plot area (measured once the plot exists).
  function plotHeight() {
    if (props.height !== "fill") return props.height ?? 240;
    const chrome = u
      ? u.root.offsetHeight - u.height
      : (props.title ? 32 : 0) + (ySeries().length > 1 ? 28 : 0);
    return Math.max(60, Math.floor(((el && el.clientHeight) || 300) - chrome));
  }

  // ---- drawing on top of the plot (device pixels) ----------------------------------------

  function drawOverlays(self) {
    const { left, top, width, height } = self.bbox;
    const ctx = self.ctx;
    const dpr = uPlot.pxRatio;
    ctx.save();
    ctx.beginPath();
    ctx.rect(left, top, width, height);
    ctx.clip();
    if (props.shadeAfter && props.playhead != null) {
      // Dim everything after the playhead (the part of the run not played yet).
      const edge = Math.min(Math.max(self.valToPos(props.playhead, "x", true), left), left + width);
      ctx.globalAlpha = 0.62;
      ctx.fillStyle = resolveColor(el, "var(--surface)");
      ctx.fillRect(edge, top, left + width - edge, height);
      ctx.globalAlpha = 1;
    }
    for (const rule of props.rules ?? []) {
      const y = self.valToPos(rule.y, "y", true);
      ctx.strokeStyle = resolveColor(el, rule.color || "var(--x-gold, #d9a300)");
      ctx.lineWidth = 1.4 * dpr;
      ctx.setLineDash(rule.dash === false ? [] : [5 * dpr, 4 * dpr]);
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(left + width, y);
      ctx.stroke();
      if (rule.label) {
        ctx.setLineDash([]);
        ctx.fillStyle = ctx.strokeStyle;
        ctx.textAlign = "right";
        ctx.font = `${11 * dpr}px ${getComputedStyle(el).getPropertyValue("--font-mono") || "monospace"}`;
        ctx.fillText(rule.label, left + width - 4 * dpr, y - 5 * dpr);
      }
    }
    ctx.setLineDash([]);
    if (props.playhead != null) {
      const x = self.valToPos(props.playhead, "x", true);
      ctx.strokeStyle = resolveColor(el, "var(--text)");
      ctx.lineWidth = 1.2 * dpr;
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, top + height);
      ctx.stroke();
    }
    if (props.highlight != null) drawHighlight(self, ctx, dpr); // above the playhead line
    ctx.restore();
  }

  // Redraw the bar at x in the highlight colour, on every bars series.
  function drawHighlight(self, ctx, dpr) {
    const xs = self.data[0];
    const at = xs.indexOf(props.highlight);
    if (at < 0) return;
    const next = xs[at + 1] ?? xs[at - 1];
    const pitch = next == null ? 6 * dpr : Math.abs(self.valToPos(next, "x", true) - self.valToPos(xs[at], "x", true));
    const w = Math.max(4 * dpr, pitch * 0.95);
    ctx.fillStyle = resolveColor(el, props.highlightColor || "var(--x-gold, #d9a300)");
    ySeries().forEach((s, i) => {
      if (typeof s !== "object" || s.kind !== "bars") return;
      const y = self.data[i + 1][at];
      if (y == null) return;
      const x = self.valToPos(xs[at], "x", true);
      const top = self.valToPos(y, "y", true);
      const base = self.valToPos(Math.max(0, self.scales.y.min ?? 0), "y", true);
      ctx.fillRect(x - w / 2, top, w, base - top);
    });
  }

  // legend: "auto" (shown for more than one series, with live values on hover), "labels" (the
  // series names and swatches only) or "off".
  function legendOptions() {
    const mode = props.legend ?? "auto";
    if (mode === "off") return { show: false };
    if (mode === "labels") return { show: true, live: false };
    return { show: ySeries().length > 1 };
  }

  function options() {
    const axis = { stroke: AXIS, grid: { stroke: "rgba(140,133,144,0.18)" }, ticks: { stroke: AXIS } };
    const x = { time: false };
    if (props.xRange) x.range = () => [props.xRange[0], props.xRange[1]];
    const scales = { x };
    if (props.yRange) scales.y = { range: () => [props.yRange[0], props.yRange[1]] };
    return {
      width: (el && el.clientWidth) || 400,
      height: plotHeight(),
      title: props.title ?? "",
      scales,
      series: seriesConfig(),
      // An axis with no label needs no room for one: a compact x axis keeps the plot tall.
      axes: [
        { ...axis, ...(props.xLabel ? { label: props.xLabel } : { size: 30 }) },
        { ...axis, ...(props.yLabel ? { label: props.yLabel } : {}) },
      ],
      padding: [8, 8, 0, 0],
      legend: legendOptions(),
      cursor: { drag: { x: true, y: false } }, // drag-to-zoom on x
      hooks: {
        draw: [drawOverlays],
        // Until the pointer is over the plot the legend would read "Value: --"; hide the
        // placeholders and show values only while hovering (IND-227).
        setCursor: [(self) => el && el.classList.toggle("hovering", self.cursor.idx != null)],
      },
    };
  }

  function build() {
    destroy();
    if (!el) return;
    u = new uPlot(options(), columnar(), el);
    el.__uplot = u; // expose the instance for debugging / e2e introspection
  }

  function destroy() {
    if (u) {
      u.destroy();
      u = null;
    }
    if (el) el.__uplot = null;
  }

  // Rebuild only on structural changes (series/title/height/labels/ranges/rules), reading the
  // data untracked so a point append does not tear down and recreate the plot.
  $effect(() => {
    void props.series;
    void props.title;
    void props.height;
    void props.xLabel;
    void props.yLabel;
    void props.xRange;
    void props.yRange;
    void props.rules;
    void props.shadeAfter;
    void props.highlightColor;
    void props.legend;
    void el;
    untrack(build);
    return destroy;
  });

  // Data-only updates: push the new columnar data into the existing plot (O(redraw),
  // and O(point) on the wire because the delta arrived as an append).
  $effect(() => {
    const cols = columnar(); // tracks props.data
    if (u) untrack(() => u.setData(cols));
  });

  // The playhead and the highlighted bar move without a rebuild: just draw again. `props` is
  // replaced on every patch, so remember the marks and redraw only when one really changed (a
  // redraw straight after the data was cleared would draw axes that have no scale yet).
  let lastMarks;
  $effect(() => {
    const marks = `${props.playhead}|${props.highlight}`;
    const changed = marks !== lastMarks;
    lastMarks = marks;
    if (u && changed && u.data[0]?.length) untrack(() => u.redraw(false));
  });

  // A colour written as var(--token) is resolved when the plot is built, so rebuild when the
  // light/dark switch changes the tokens.
  $effect(() => onThemeChange(() => untrack(build)));

  // Keep the plot the width of its container.
  $effect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0].contentRect.width);
      if (!u || !w) return;
      const h = plotHeight();
      if (Math.abs(w - u.width) > 1 || (props.height === "fill" && Math.abs(h - u.height) > 1))
        u.setSize({ width: w, height: h });
    });
    ro.observe(el);
    return () => ro.disconnect();
  });
</script>

<div class="chart" class:legend-labels={props.legend === "labels"} bind:this={el}></div>
