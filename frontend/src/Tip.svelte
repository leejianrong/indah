<script>
  // Generic tooltip (ADR-0030): wraps any node without adding a box (display: contents).
  // Shows on hover or keyboard focus, hides on Esc or leave, and is linked to the
  // wrapped element with aria-describedby so a screen reader reads it too.
  let { text, children } = $props();

  let wrap = $state();
  let shown = $state(false);
  let pos = $state({ x: 0, y: 0 });
  const tipId = `tip-${Math.random().toString(36).slice(2, 8)}`;

  $effect(() => {
    const el = wrap?.firstElementChild;
    if (el) el.setAttribute("aria-describedby", tipId);
  });

  function show() {
    const el = wrap?.firstElementChild;
    if (!el) return;
    const r = el.getBoundingClientRect();
    pos = { x: r.left + r.width / 2, y: r.bottom + 6 };
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
  onmouseover={show}
  onfocusin={show}
  onmouseout={leave}
  onfocusout={leave}
>
  {@render children?.()}
  {#if shown}
    <span id={tipId} role="tooltip" class="tip-bubble" style="left: {pos.x}px; top: {pos.y}px;">{text}</span>
  {/if}
</span>

<style>
  .tip { display: contents; }
  .tip-bubble {
    position: fixed;
    z-index: 70;
    transform: translateX(-50%);
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
