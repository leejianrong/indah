<script>
  // BarStrip (IND-162): a compact activity strip, one bar per interval, optionally stacked. Plain
  // divs, no chart library. Heights are percentages of the strip, so a patch moves the existing
  // bars (keyed by position) instead of remounting them. The strip is one tab stop: arrow keys,
  // Home and End read each bar through a tooltip and a polite live region, Escape hides the
  // tooltip and Tab leaves (no keyboard trap). Colour is never the only cue: the tooltip names
  // every segment ("12:03: 4 (hit 3, miss 1)"). Tones are the theme's own variables.
  let { node, props } = $props();

  let bars = $derived(props.series ?? []);
  let tones = $derived(props.tones ?? ["info"]);
  let names = $derived(props.names ?? []);
  let labels = $derived(props.labels ?? []);
  let height = $derived(props.height ?? 32);
  let totals = $derived(bars.map((b) => b.reduce((a, v) => a + v, 0)));
  let scale = $derived(props.max ?? Math.max(0, ...totals));

  let active = $state(null);
  let tipOn = $state(false);
  let focused = $state(false);

  function fmt(n) {
    return Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100);
  }

  // "12:03: 4 (hit 3, miss 1)"; a bar of one segment, or of nothing, has no breakdown.
  function textFor(i) {
    const b = bars[i];
    if (!b) return "";
    const head = `${labels[i] ?? `Bar ${i + 1}`}: ${fmt(totals[i])}`;
    if (b.length < 2 || totals[i] === 0) return head;
    return `${head} (${b.map((v, k) => `${names[k] ?? `series ${k + 1}`} ${fmt(v)}`).join(", ")})`;
  }

  // A segment's height as a share of the strip. A bar taller than a fixed `max` is squeezed to fit.
  function pct(v, i) {
    const top = Math.max(scale, totals[i]);
    return top > 0 ? (v / top) * 100 : 0;
  }

  function show(i) {
    active = i;
    tipOn = true;
  }

  function onkey(e) {
    if (e.ctrlKey || e.metaKey || e.altKey || !bars.length) return;
    const last = bars.length - 1;
    const at = active ?? last;
    let to = null;
    if (e.key === "ArrowLeft") to = Math.max(0, at - 1);
    else if (e.key === "ArrowRight") to = Math.min(last, at + 1);
    else if (e.key === "Home") to = 0;
    else if (e.key === "End") to = last;
    else if (e.key === "Escape" && tipOn) {
      tipOn = false;
      e.preventDefault();
      return;
    }
    if (to === null) return;
    e.preventDefault();
    show(to);
  }

  // Where the tooltip sits: it hangs from the bar's position, aligned so it stays inside the strip.
  let frac = $derived(active === null || !bars.length ? 0 : (active + 0.5) / bars.length);
</script>

<div class="field">
  <div
    class="barstrip"
    role="group"
    tabindex="0"
    aria-label={`${props.label || "Activity"}: ${bars.length} bars`}
    aria-describedby={tipOn ? `${node.id}-tip` : undefined}
    style:max-width={`${Math.max(bars.length, 1) * 16}px`}
    onkeydown={onkey}
    onfocus={() => {
      focused = true;
      show(active !== null && active < bars.length ? active : bars.length - 1);
    }}
    onblur={() => {
      focused = false;
      tipOn = false;
      active = null;
    }}
    onpointerleave={() => {
      if (!focused) tipOn = false;
    }}
  >
    <div class="barstrip-bars" style:height={`${height}px`}>
      {#each bars as b, i (i)}
        <div
          class="barstrip-bar"
          class:on={tipOn && active === i}
          aria-hidden="true"
          onpointerenter={() => show(i)}
        >
          {#each b as v, k (k)}
            <div
              class="barstrip-seg tone-{tones[k] ?? 'neutral'}"
              style:height={`${pct(v, i)}%`}
            ></div>
          {/each}
        </div>
      {/each}
    </div>
    {#if tipOn && active !== null && bars[active]}
      <div
        class="barstrip-tip"
        role="tooltip"
        id="{node.id}-tip"
        style:left={`${frac * 100}%`}
        style:transform={`translateX(-${frac * 100}%)`}
      >{textFor(active)}</div>
    {/if}
    <div class="sr-only barstrip-status" role="status" aria-live="polite">
      {tipOn && active !== null ? textFor(active) : ""}
    </div>
  </div>
</div>
