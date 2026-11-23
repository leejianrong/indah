<script>
  // Spans (IND-268): nested labelled intervals as a flame chart, an icicle chart or a timeline.
  // Each span is a real <button> placed by percentage, so the keyboard and a screen reader reach
  // it and no canvas hit-testing is needed. Positions and colours are set through the CSSOM, not
  // a style attribute, so the strict CSP holds. Python decides each span's row; this places them.
  import { postEvent } from "./api.js";

  let { props, nodeId } = $props();

  const cols = $derived(props.spans ?? { id: [], label: [], start: [], end: [], row: [], rows: 0 });
  const n = $derived(cols.id.length);
  const unit = $derived(props.unit ? ` ${props.unit}` : "");
  const range = $derived.by(() => {
    if (props.view) return props.view;
    if (!n) return [0, 1];
    const lo = Math.min(...cols.start);
    const hi = Math.max(...cols.end);
    return [lo, hi > lo ? hi : lo + 1];
  });
  const ROW = 24;
  const rows = $derived(Math.max(cols.rows, 1));
  let sel = $state(null); // the selected id; follows Python, and runs ahead of its echo
  let seen;
  $effect(() => {
    const s = props.selected ?? null;
    if (s !== seen) [seen, sel] = [s, s];
  });

  const fmt = (v) => `${Math.round(v * 1000) / 1000}`;
  const shown = $derived.by(() => {
    const [r0, r1] = range;
    const out = [];
    for (let i = 0; i < n; i++) {
      if (cols.end[i] <= r0 || cols.start[i] >= r1) continue;
      const l = Math.max(cols.start[i], r0);
      const r = Math.min(cols.end[i], r1);
      const top = (props.layout === "flame" ? rows - 1 - cols.row[i] : cols.row[i]) * ROW;
      out.push({
        i, id: cols.id[i], text: cols.label[i], left: ((l - r0) / (r1 - r0)) * 100,
        width: Math.max(((r - l) / (r1 - r0)) * 100, 0.15), top,
        name: `${cols.label[i]}, ${fmt(cols.end[i] - cols.start[i])}${unit}, from ${fmt(cols.start[i])} to ${fmt(cols.end[i])}`,
        color: cols.color?.[i] ?? null, hue: cols.row[i] % 6,
      });
    }
    return out;
  });
  const ticks = $derived([0, 0.25, 0.5, 0.75, 1].map((f) => ({ f, v: range[0] + f * (range[1] - range[0]) })));

  function pick(id) {
    if (!props.selectable) return;
    sel = sel === id ? null : id;
    postEvent(nodeId, "select", { id: sel });
  }
  function place(el, s) {
    const set = (s) => {
      el.style.setProperty("left", `${s.left}%`);
      el.style.setProperty("width", `${s.width}%`);
      el.style.setProperty("top", `${s.top}px`);
      if (s.color) el.style.setProperty("background", s.color);
      else el.style.removeProperty("background");
    };
    set(s);
    return { update: set };
  }
  function height(el, h) {
    const set = (h) => el.style.setProperty("height", `${h}px`);
    set(h);
    return { update: set };
  }
</script>

<div class="spans" role="group" aria-label={props.label || "Spans"}>
  <div class="spans-plot" use:height={rows * ROW}>
    {#each shown as s (s.id)}
      <button
        type="button"
        class={`span span-c${s.hue}`}
        class:picked={sel === s.id}
        class:inert={!props.selectable}
        title={s.name}
        aria-label={s.name}
        aria-pressed={props.selectable ? sel === s.id : undefined}
        use:place={s}
        onclick={() => pick(s.id)}><span class="span-text">{s.text}</span></button
      >
    {/each}
  </div>
  <div class="spans-axis" aria-hidden="true">
    {#each ticks as t}<span>{fmt(t.v)}{t.f === 1 ? unit : ""}</span>{/each}
  </div>
</div>
