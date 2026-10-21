<script>
  // Generic tooltip (ADR-0030): wraps any node without adding a box (display: contents).
  // Shows on hover or keyboard focus, hides on Esc or leave, and is linked to the
  // wrapped element with aria-describedby so a screen reader reads it too.
  let { text, children } = $props();

  let wrap = $state();
  let bubble = $state();
  let shown = $state(false);
  // Where the tip wants to be: the pointer on hover, the element's start on keyboard focus.
  let anchor = $state({ x: 0, y: 0, h: 0 });
  let pos = $state({ x: 0, y: 0 });
  const tipId = `tip-${Math.random().toString(36).slice(2, 8)}`;
  const GAP = 14;
  const MARGIN = 8;

  $effect(() => {
    const el = wrap?.firstElementChild;
    if (el) el.setAttribute("aria-describedby", tipId);
  });

  // Once the bubble is in the DOM, measure it, flip above the anchor when it would run off
  // the bottom, and clamp it inside the viewport.
  $effect(() => {
    if (!shown || !bubble) return;
    const w = bubble.offsetWidth;
    const h = bubble.offsetHeight;
    let x = Math.min(anchor.x, window.innerWidth - w - MARGIN);
    let y = anchor.y + anchor.h + GAP;
    if (y + h > window.innerHeight - MARGIN) y = Math.max(MARGIN, anchor.y - h - GAP);
    pos = { x: Math.max(MARGIN, x), y };
  });

  function point(e) {
    anchor = { x: e.clientX, y: e.clientY, h: 0 };
    shown = true;
  }
  function focus() {
    const el = wrap?.firstElementChild;
    if (!el) return;
    const r = el.getBoundingClientRect();
    anchor = { x: r.left, y: r.top, h: r.height - GAP + 6 };
    shown = true;
  }
  function leave(e) {
    if (!wrap.contains(e.relatedTarget)) shown = false;
  }
</script>

<svelte:window onkeydown={(e) => { if (shown && e.key === "Escape") shown = false; }} />

<!-- svelte-ignore a11y_no_static_element_interactions -->
<span
  bind:this={wrap}
  class="tip"
  onmouseover={point}
  onmousemove={(e) => shown && point(e)}
  onfocusin={focus}
  onmouseout={leave}
  onfocusout={leave}
>
  {@render children?.()}
  {#if shown}
    <span
      id={tipId}
      bind:this={bubble}
      role="tooltip"
      class="tip-bubble"
      style="left: {pos.x}px; top: {pos.y}px;">{text}</span
    >
  {/if}
</span>

<style>
  .tip { display: contents; }
  .tip-bubble {
    position: fixed;
    z-index: 70;
    max-width: min(20rem, 90vw);
    padding: 0.3rem 0.6rem;
    font-size: 0.8rem;
    color: var(--text);
    background: var(--surface-3);
    border: 1px solid var(--outline);
    border-radius: var(--radius-sm);
    box-shadow: var(--shadow);
    pointer-events: none;
  }
</style>
