<script>
  // Pie (ADR-0046): slices as shares of a total, one slice lit. The lit slice is pulled out and
  // glows while the others dim; the change eases over a short transition (CSS, so it stays
  // smooth however often the prop is patched). Colours may be var(--token) and so follow the
  // theme with no code.
  let { props } = $props();

  const C = 90;
  const R = 78;
  const FALLBACK = ["var(--primary)", "var(--secondary)", "var(--ok)", "var(--warn)", "var(--err)"];

  const slices = $derived(props.slices ?? []);
  const total = $derived(slices.reduce((sum, s) => sum + (s.value || 0), 0));
  const lit = $derived(props.active ?? null);

  function point(fraction) {
    const a = fraction * 2 * Math.PI - Math.PI / 2;
    return [C + R * Math.cos(a), C + R * Math.sin(a)];
  }

  function wedge(from, to) {
    if (to - from >= 0.9999) {
      return `M ${C - R} ${C} A ${R} ${R} 0 1 1 ${C + R} ${C} A ${R} ${R} 0 1 1 ${C - R} ${C} Z`;
    }
    const [x1, y1] = point(from);
    const [x2, y2] = point(to);
    return `M ${C} ${C} L ${x1.toFixed(2)} ${y1.toFixed(2)} A ${R} ${R} 0 ${to - from > 0.5 ? 1 : 0} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} Z`;
  }

  // Each slice with its path, colour and the offset that pulls it out when lit.
  const shapes = $derived.by(() => {
    let acc = 0;
    return slices
      .map((s, i) => {
        const share = total > 0 ? (s.value || 0) / total : 0;
        const from = acc;
        acc += share;
        const mid = ((from + acc) / 2) * 2 * Math.PI - Math.PI / 2;
        return {
          i,
          label: s.label,
          share,
          color: s.color || FALLBACK[i % FALLBACK.length],
          d: share > 0 ? wedge(from, acc) : "",
          dx: 6 * Math.cos(mid),
          dy: 6 * Math.sin(mid),
        };
      })
      .filter((s) => s.share > 0);
  });

  const pct = (v) => `${(v * 100).toFixed(1)}%`;
  const description = $derived(
    shapes.map((s) => `${s.label || "slice " + (s.i + 1)} ${pct(s.share)}`).join(", ") +
      (lit != null && slices[lit] ? `. ${slices[lit].label || "Slice " + (lit + 1)} is lit.` : "."),
  );
</script>

<div class="pie">
  <svg
    viewBox="0 0 180 180"
    style="height: {props.height ?? 180}px; width: {props.height ?? 180}px"
    role="img"
    aria-label={description}
  >
    <defs>
      <filter id="pie-glow" x="-30%" y="-30%" width="160%" height="160%">
        <feGaussianBlur stdDeviation="5" result="blur" />
        <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
    </defs>
    {#each shapes as s (s.i)}
      <path
        d={s.d}
        class="pie-slice"
        style="fill: {s.color}; opacity: {lit == null || lit === s.i ? 1 : 0.3}; transform: {lit === s.i
          ? `translate(${s.dx.toFixed(1)}px, ${s.dy.toFixed(1)}px)`
          : 'none'}; filter: {lit === s.i ? 'url(#pie-glow)' : 'none'};"
      />
    {/each}
  </svg>
  {#if props.showLabels !== false}
    <ul class="pie-legend">
      {#each shapes as s (s.i)}
        <li class:lit={lit === s.i} style="opacity: {lit == null || lit === s.i ? 1 : 0.5}">
          <span class="pie-swatch" style="background: {s.color}"></span>
          <span>{s.label || `slice ${s.i + 1}`}</span>
          <span class="pie-pct">{pct(s.share)}</span>
        </li>
      {/each}
    </ul>
  {/if}
</div>
