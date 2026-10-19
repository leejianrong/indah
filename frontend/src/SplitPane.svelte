<script>
  // Two panes and a draggable divider (IND-103). Entirely client-side: pointer drag, the
  // arrow keys on the focused divider and the ratio remembered in localStorage by `key`.
  import { onMount } from "svelte";

  let { id, direction = "horizontal", initial = 0.4, min = 0.2, storageKey, height = null, first, second } = $props();

  const horizontal = $derived(direction === "horizontal");
  const lsKey = $derived(`indah-split:${location.pathname}:${storageKey || id}`);
  const clamp = (v) => Math.min(1 - min, Math.max(min, v));

  let ratio = $state(initial);
  let box = $state();
  let dragging = false;

  onMount(() => {
    try {
      const saved = parseFloat(localStorage.getItem(lsKey));
      if (Number.isFinite(saved)) ratio = clamp(saved);
    } catch (e) {
      /* storage blocked: start from `initial` */
    }
  });

  function save() {
    try {
      localStorage.setItem(lsKey, String(ratio));
    } catch (e) {
      /* not remembered */
    }
  }
  function set(next) {
    ratio = clamp(next);
    save();
  }

  function onpointerdown(e) {
    dragging = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    e.preventDefault();
  }
  function onpointermove(e) {
    if (!dragging) return;
    const r = box.getBoundingClientRect();
    ratio = clamp(horizontal ? (e.clientX - r.left) / r.width : (e.clientY - r.top) / r.height);
  }
  function onpointerup() {
    if (!dragging) return;
    dragging = false;
    save();
  }
  function onkeydown(e) {
    const step = e.shiftKey ? 0.1 : 0.02;
    const [less, more] = horizontal ? ["ArrowLeft", "ArrowRight"] : ["ArrowUp", "ArrowDown"];
    if (e.key === less) set(ratio - step);
    else if (e.key === more) set(ratio + step);
    else if (e.key === "Home") set(min);
    else if (e.key === "End") set(1 - min);
    else if (e.key === "Enter") set(initial);
    else return;
    e.preventDefault();
  }
</script>

<div
  bind:this={box}
  class="split {direction}"
  style:height={!horizontal ? (height ?? "28rem") : null}
  style:--a="{ratio}fr"
  style:--b="{1 - ratio}fr"
>
  <div class="split-pane" id={`${id}-first`}>{@render first()}</div>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
  <div
    class="split-handle"
    role="separator"
    aria-label="Resize panes"
    aria-orientation={horizontal ? "vertical" : "horizontal"}
    aria-controls={`${id}-first`}
    aria-valuemin={Math.round(min * 100)}
    aria-valuemax={Math.round((1 - min) * 100)}
    aria-valuenow={Math.round(ratio * 100)}
    tabindex="0"
    {onpointerdown}
    {onpointermove}
    {onpointerup}
    {onkeydown}
    ondblclick={() => set(initial)}
  ></div>
  <div class="split-pane">{@render second()}</div>
</div>

<style>
  .split { display: grid; gap: 0; min-width: 0; }
  .split.horizontal { grid-template-columns: minmax(0, var(--a)) 10px minmax(0, var(--b)); }
  .split.vertical { grid-template-rows: minmax(0, var(--a)) 10px minmax(0, var(--b)); }
  .split-pane { min-width: 0; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 1rem; padding: 0.1rem; }
  .split-handle { background: var(--outline-soft); border-radius: 4px; touch-action: none; transition: background 0.15s; }
  .split.horizontal > .split-handle { cursor: col-resize; margin: 0 2px; }
  .split.vertical > .split-handle { cursor: row-resize; margin: 2px 0; }
  .split-handle:hover, .split-handle:focus-visible { background: var(--primary); outline: none; }
  @media (max-width: 560px) {
    .split.horizontal { grid-template-columns: minmax(0, 1fr); }
    .split.horizontal > .split-handle { display: none; }
  }
</style>
