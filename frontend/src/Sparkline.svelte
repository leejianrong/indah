<script>
  // Sparkline (IND-263): a tiny trend line with no axes, drawn as one SVG polyline. The colour
  // comes from a tone class or, for an explicit `color`, through the CSSOM (no style attribute,
  // so it holds under the strict CSP). `values` has null for a gap, which breaks the line.
  let { values = [], tone, color, fill = false, height = 24, label = "" } = $props();

  const W = 100;
  const nums = $derived(values.filter((v) => v != null));
  const lo = $derived(Math.min(...nums));
  const hi = $derived(Math.max(...nums));
  // Runs of consecutive points, each a list of "x,y" pairs; a lone point is drawn as a dot.
  const runs = $derived.by(() => {
    if (!nums.length) return [];
    const span = hi - lo || 1;
    const dx = values.length > 1 ? W / (values.length - 1) : 0;
    const out = [];
    let cur = [];
    values.forEach((v, i) => {
      if (v == null) {
        if (cur.length) out.push(cur);
        cur = [];
      } else cur.push([i * dx, 100 - ((v - lo) / span) * 92 - 4]);
    });
    if (cur.length) out.push(cur);
    return out;
  });
  const aria = $derived(
    nums.length
      ? `${label || "Trend"}: from ${nums[0]} to ${nums[nums.length - 1]}, lowest ${lo}, highest ${hi}`
      : `${label || "Trend"}: no data`,
  );

  function paint(el, c) {
    const set = (v) => (v ? el.style.setProperty("color", v) : el.style.removeProperty("color"));
    set(c);
    return { update: set };
  }
</script>

<svg
  class={`spark ${tone ? "tone-" + tone : ""}`}
  viewBox="0 0 100 100"
  preserveAspectRatio="none"
  role="img"
  aria-label={aria}
  height={height}
  use:paint={color}
>
  {#each runs as run}
    {#if fill && run.length > 1}
      <polygon class="spark-fill" points={`${run[0][0]},100 ${run.map((p) => p.join(",")).join(" ")} ${run[run.length - 1][0]},100`} />
    {/if}
    {#if run.length > 1}
      <polyline class="spark-line" points={run.map((p) => p.join(",")).join(" ")} />
    {:else}
      <line class="spark-line" x1={run[0][0] - 0.5} x2={run[0][0] + 0.5} y1={run[0][1]} y2={run[0][1]} />
    {/if}
  {/each}
</svg>
