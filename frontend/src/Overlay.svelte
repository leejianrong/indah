<script>
  // Modal / Drawer / confirm dialog (ADR-0030). Rendered only while open, so mounting
  // is "opening": remember what had focus, move focus in, trap Tab, close on Esc or a
  // backdrop click, and give focus back on teardown.
  import { onMount } from "svelte";

  let { kind = "modal", side = "right", size = "md", title = "", onclose, children, initialFocus } =
    $props();

  let panel = $state();
  const titleId = `ov-${Math.random().toString(36).slice(2, 8)}`;

  const FOCUSABLE =
    'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

  onMount(() => {
    const opener = document.activeElement;
    const target = (initialFocus && panel.querySelector(initialFocus)) || panel.querySelector(FOCUSABLE) || panel;
    target.focus();
    return () => {
      if (opener && opener.isConnected && typeof opener.focus === "function") opener.focus();
    };
  });

  function onkeydown(e) {
    if (e.key === "Escape") {
      e.stopPropagation();
      onclose?.();
      return;
    }
    if (e.key !== "Tab") return;
    const items = Array.from(panel.querySelectorAll(FOCUSABLE));
    if (items.length === 0) {
      e.preventDefault();
      panel.focus();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || active === panel)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class="ov-backdrop" class:drawer={kind === "drawer"} onclick={(e) => { if (e.target === e.currentTarget) onclose?.(); }}>
  <div
    bind:this={panel}
    class="ov-panel {kind === 'drawer' ? `drawer-${side}` : `size-${size}`}"
    role="dialog"
    aria-modal="true"
    aria-labelledby={title ? titleId : undefined}
    tabindex="-1"
    {onkeydown}
  >
    <div class="ov-head">
      <h2 id={titleId}>{title}</h2>
      <button type="button" class="ghost ov-close" aria-label="Close" onclick={() => onclose?.()}>×</button>
    </div>
    <div class="ov-body">{@render children?.()}</div>
  </div>
</div>

<style>
  .ov-backdrop {
    position: fixed;
    inset: 0;
    z-index: 50;
    display: flex;
    align-items: center;
    justify-content: center;
    background: color-mix(in srgb, #000 45%, transparent);
  }
  .ov-backdrop.drawer { align-items: stretch; justify-content: flex-end; }
  .ov-panel {
    display: flex;
    flex-direction: column;
    max-height: 90vh;
    background: var(--surface);
    color: var(--text);
    border: 1px solid var(--outline);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    outline: none;
  }
  .size-sm { width: min(24rem, 92vw); }
  .size-md { width: min(34rem, 92vw); }
  .size-lg { width: min(52rem, 94vw); }
  .drawer-left, .drawer-right {
    width: min(30rem, 94vw);
    max-height: none;
    border-radius: 0;
  }
  .drawer-left { margin-right: auto; }
  .ov-head { display: flex; align-items: center; justify-content: space-between; padding: 0.8rem 1rem 0.4rem; }
  .ov-head h2 { margin: 0; font-size: 1.05rem; }
  .ov-close { padding: 0.1rem 0.6rem; font-size: 1.2rem; align-self: auto; }
  .ov-body { display: flex; flex-direction: column; gap: 1rem; padding: 0.6rem 1rem 1rem; overflow: auto; }
</style>
