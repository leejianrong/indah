<script>
  // Client-side chart (ADR-0018, KAN-1423). uPlot is bundled into the shell at
  // build time (a devDependency of frontend/, inlined by the singlefile build) --
  // it is NOT a Python runtime dep and adds no Node at install or runtime.
  //
  // Data and encoding ride ordinary reactive props: `data` is a list of rows
  // [[x, y0, y1, ...], ...] and `series` names the y columns. Streaming points
  // arrive via the `append` patch op (App.svelte concatenates arrays), so a live
  // curve grows at O(point) on the wire; uPlot redraws in the browser. Zoom (drag)
  // and hover run client-side.
  import uPlot from "uplot";
  import "uplot/dist/uPlot.min.css";
  import { untrack } from "svelte";

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
      ...ySeries().map((s, i) => ({
        label: (typeof s === "string" ? s : s.label) ?? `y${i + 1}`,
        stroke: (typeof s === "object" && s.stroke) || PALETTE[i % PALETTE.length],
        width: 2,
        points: { show: props.points ?? false },
      })),
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

  function options() {
    const axis = { stroke: AXIS, grid: { stroke: "rgba(140,133,144,0.18)" }, ticks: { stroke: AXIS } };
    return {
      width: (el && el.clientWidth) || 400,
      height: props.height ?? 240,
      title: props.title ?? "",
      scales: { x: { time: false } },
      series: seriesConfig(),
      axes: [{ ...axis, label: props.xLabel ?? "" }, { ...axis, label: props.yLabel ?? "" }],
      legend: { show: ySeries().length > 1 },
      cursor: { drag: { x: true, y: false } }, // drag-to-zoom on x
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

  // Rebuild only on structural changes (series/title/height/labels), reading the
  // data untracked so a point append does not tear down and recreate the plot.
  $effect(() => {
    void props.series;
    void props.title;
    void props.height;
    void props.xLabel;
    void props.yLabel;
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

  // Keep the plot the width of its container.
  $effect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0].contentRect.width);
      if (u && w && Math.abs(w - u.width) > 1) u.setSize({ width: w, height: props.height ?? 240 });
    });
    ro.observe(el);
    return () => ro.disconnect();
  });
</script>

<div class="chart" bind:this={el}></div>
