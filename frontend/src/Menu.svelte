<script>
  // Menu (IND-161): the ARIA menu button pattern. A trigger button opens a list of actions;
  // arrow keys, Home and End move between items, a letter jumps to the next item that starts
  // with it, Escape closes and gives focus back to the trigger, Tab closes and moves on (no
  // keyboard trap, WCAG 2.1.2). Choosing an item closes the menu and posts `select {item}`;
  // an item with `confirm` asks first, like Button. Keys follow the routing rule in ADR-0030:
  // only events whose target is the trigger or an item, never ctrl/meta/alt combos, and every
  // key it handles is defaulted so `Shortcuts` skips it.
  import { tick } from "svelte";
  import { postEvent } from "./api.js";
  import Overlay from "./Overlay.svelte";

  let { node, props } = $props();

  let items = $derived(props.items ?? []);
  let open = $state(false);
  let confirming = $state(null);
  let trigger = $state();
  let pop = $state();
  let pos = $state({ x: 0, y: 0 });
  const menuId = `menu-${Math.random().toString(36).slice(2, 8)}`;
  const GAP = 4;
  const MARGIN = 8;

  // The popup is moved to <body>: it is fixed to the viewport, and an ancestor with a transform
  // (the AppShell drawer) or an overflow would otherwise move or clip it.
  function portal(el) {
    document.body.appendChild(el);
    return { destroy: () => el.remove() };
  }

  function buttons() {
    return pop ? Array.from(pop.querySelectorAll('[role="menuitem"]')) : [];
  }

  function focusItem(i) {
    const list = buttons();
    if (list.length) list[(i + list.length) % list.length].focus();
  }

  async function show(at) {
    if (!items.length) return;
    open = true;
    // Wait for the popup to exist, place it, then focus where the key or click asked.
    await tick();
    place();
    focusItem(at === "last" ? -1 : 0);
  }

  function place() {
    if (!pop || !trigger) return;
    const r = trigger.getBoundingClientRect();
    const w = pop.offsetWidth;
    const h = pop.offsetHeight;
    let x = props.align === "end" ? r.right - w : r.left;
    x = Math.max(MARGIN, Math.min(x, window.innerWidth - w - MARGIN));
    let y = r.bottom + GAP;
    if (y + h > window.innerHeight - MARGIN) y = Math.max(MARGIN, r.top - h - GAP);
    pos = { x, y };
  }

  function close(refocus = true) {
    if (!open) return;
    open = false;
    typed = "";
    if (refocus) trigger?.focus();
  }

  function toggle() {
    if (open) close();
    else show("first");
  }

  function choose(item) {
    if (item.disabled) return;
    close();
    if (item.confirm) confirming = item;
    else postEvent(node.id, "select", { item: item.id });
  }

  function onTriggerKey(e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      show("first");
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      show("last");
    }
  }

  let typed = "";
  let typedAt = 0;

  function onItemKey(e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const list = buttons();
    const at = list.indexOf(document.activeElement);
    if (e.key === "ArrowDown") focusItem(at + 1);
    else if (e.key === "ArrowUp") focusItem(at - 1);
    else if (e.key === "Home") focusItem(0);
    else if (e.key === "End") focusItem(-1);
    else if (e.key === "Escape") close();
    else if (e.key === "Tab") {
      // Leave the menu: put focus on the trigger and let the browser's Tab move on from there.
      close();
      return;
    } else if (e.key.length === 1 && e.key !== " ") {
      const now = Date.now();
      const key = e.key.toLowerCase();
      const order = [...list.slice(at + 1), ...list.slice(0, at + 1)];
      const find = (prefix) => order.find((b) => b.textContent.trim().toLowerCase().startsWith(prefix));
      // A prefix typed quickly narrows the search (from the current item); a repeated letter
      // cycles through the items that start with it; a letter that fits neither starts over.
      const prefix = now - typedAt > 600 ? key : typed + key;
      const repeat = prefix.length > 1 && prefix.split("").every((c) => c === key);
      const hit = (repeat ? find(key) : find(prefix)) ?? find(key);
      typed = hit && !repeat && find(prefix) ? prefix : key;
      typedAt = now;
      if (hit) hit.focus();
    } else return;
    e.preventDefault();
  }

  // A click outside, a scroll or a resize closes it: the popup is placed once, in viewport
  // coordinates, so it would otherwise drift away from its trigger.
  function outside(e) {
    if (!open) return;
    if (pop?.contains(e.target) || trigger?.contains(e.target)) return;
    close(false);
  }
  function drift(e) {
    if (open && !pop?.contains(e.target)) close(false);
  }
</script>

<svelte:window onpointerdown={outside} onresize={() => close(false)} onscrollcapture={drift} />

<span class="menu">
  <button
    bind:this={trigger}
    type="button"
    class="menu-trigger"
    class:ghost={(props.variant ?? "ghost") === "ghost"}
    class:tonal={props.variant === "tonal"}
    aria-haspopup="menu"
    aria-expanded={open}
    aria-controls={open ? menuId : undefined}
    aria-label={props.label || undefined}
    disabled={!items.length}
    onclick={toggle}
    onkeydown={onTriggerKey}
  >
    <span>{props.trigger}</span><span class="menu-caret" aria-hidden="true">▾</span>
  </button>
</span>

{#if open}
  <div
    use:portal
    bind:this={pop}
    id={menuId}
    class="menu-pop"
    role="menu"
    aria-label={props.label || props.trigger}
    tabindex="-1"
    style="left: {pos.x}px; top: {pos.y}px;"
    onkeydown={onItemKey}
  >
    {#each items as item (item.id)}
      <button
        type="button"
        role="menuitem"
        tabindex="-1"
        class="menu-item"
        class:danger={item.danger}
        aria-disabled={item.disabled ? "true" : undefined}
        onclick={() => choose(item)}
      >
        <span class="menu-label">{item.label}</span>
        {#if item.shortcut}<span class="menu-shortcut" aria-hidden="true">{item.shortcut}</span>{/if}
      </button>
    {/each}
  </div>
{/if}

{#if confirming}
  <Overlay kind="modal" size="sm" title={confirming.confirm} onclose={() => (confirming = null)} initialFocus=".confirm-no">
    <div class="confirm-actions">
      <button type="button" class="ghost confirm-no" onclick={() => (confirming = null)}>Cancel</button>
      <button
        type="button"
        class="confirm-yes"
        onclick={() => {
          const item = confirming;
          confirming = null;
          postEvent(node.id, "select", { item: item.id });
        }}>{confirming.label}</button
      >
    </div>
  </Overlay>
{/if}

<style>
  .menu { display: inline-flex; align-self: flex-start; }
  .menu-trigger { display: inline-flex; align-items: center; gap: 0.45rem; }
  .menu-caret { font-size: 0.75em; opacity: 0.7; }
  .menu-pop {
    position: fixed;
    z-index: 60;
    min-width: 11rem;
    max-width: min(24rem, 92vw);
    display: flex;
    flex-direction: column;
    padding: 0.3rem;
    background: var(--surface);
    color: var(--text);
    border: 1px solid var(--outline);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    outline: none;
  }
  .menu-pop .menu-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1.5rem;
    width: 100%;
    align-self: stretch;
    padding: 0.45rem 0.7rem;
    font-weight: 500;
    text-align: left;
    color: var(--text);
    background: transparent;
    border: 0;
    border-radius: var(--radius-sm);
    filter: none;
    transform: none;
  }
  .menu-pop .menu-item:hover,
  .menu-pop .menu-item:focus-visible {
    background: var(--surface-2);
    filter: none;
    outline: none;
  }
  .menu-pop .menu-item:focus-visible { box-shadow: inset 0 0 0 2px var(--primary); }
  .menu-pop .menu-item.danger { color: var(--err); }
  .menu-pop .menu-item[aria-disabled="true"] { color: var(--muted); cursor: not-allowed; opacity: 0.6; }
  .menu-pop .menu-item[aria-disabled="true"]:hover { background: transparent; }
  .menu-shortcut { font-family: var(--font-mono); font-size: 0.78rem; color: var(--muted); }
</style>
