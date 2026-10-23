<script>
  // InfoTip (IND-159): a small focusable info icon that shows a tip (ADR-0030's tip look). One tab
  // stop, a real <button> named by `label`; the tip is always in the DOM (hidden) so that
  // aria-describedby resolves for a screen reader, and role=tooltip. It opens on mouse hover and on
  // keyboard focus, a click or tap toggles it (and pins it open past a mouse leave), and it closes
  // on Escape (without letting a modal behind it see the key), on blur and on a tap outside.
  // The bubble is placed in viewport coordinates and clamped, so it stays on screen at 390px.
  let { text = "", label = "More information" } = $props();

  let btn = $state();
  let bubble = $state();
  let open = $state(false);
  let pinned = $state(false);
  let pos = $state({ x: 0, y: 0 });
  const tipId = `infotip-${Math.random().toString(36).slice(2, 8)}`;
  const GAP = 8;
  const MARGIN = 8;

  function close() {
    open = false;
    pinned = false;
  }

  // Measure the bubble once it is shown: below the icon, flipped above when it would run off the
  // bottom, and clamped inside the viewport on both sides.
  $effect(() => {
    if (!open || !bubble || !btn) return;
    void text;
    const r = btn.getBoundingClientRect();
    const w = bubble.offsetWidth;
    const h = bubble.offsetHeight;
    let x = Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - MARGIN);
    let y = r.bottom + GAP;
    if (y + h > window.innerHeight - MARGIN) y = Math.max(MARGIN, r.top - h - GAP);
    pos = { x: Math.max(MARGIN, x), y };
  });

  // While open: Escape closes it (capture, so a modal or drawer behind does not also close), and a
  // press outside closes it (the tap-away on a touch screen). The tip itself ignores the pointer.
  $effect(() => {
    if (!open) return;
    const key = (e) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      e.preventDefault();
      close();
    };
    const away = (e) => {
      if (!btn?.contains(e.target)) close();
    };
    window.addEventListener("keydown", key, true);
    window.addEventListener("pointerdown", away, true);
    return () => {
      window.removeEventListener("keydown", key, true);
      window.removeEventListener("pointerdown", away, true);
    };
  });

  function toggle() {
    if (open && pinned) close();
    else {
      open = true;
      pinned = true;
    }
  }
</script>

<span class="infotip">
  <button
    bind:this={btn}
    type="button"
    class="infotip-btn"
    aria-label={label}
    aria-describedby={tipId}
    aria-expanded={open}
    onclick={toggle}
    onpointerenter={(e) => {
      if (e.pointerType === "mouse") open = true;
    }}
    onpointerleave={(e) => {
      if (e.pointerType === "mouse" && !pinned) open = false;
    }}
    onfocus={(e) => {
      if (e.currentTarget.matches(":focus-visible")) open = true;
    }}
    onblur={close}
  >
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
      <circle class="i-ring" cx="8" cy="8" r="6.6" />
      <circle class="i-dot" cx="8" cy="4.9" r="0.95" />
      <path class="i-stem" d="M8 7.3v4.4" />
    </svg>
  </button>
  <span
    id={tipId}
    bind:this={bubble}
    role="tooltip"
    class="infotip-bubble"
    class:shown={open}
    style="left: {pos.x}px; top: {pos.y}px;">{text}</span
  >
</span>

<style>
  .infotip { display: inline-flex; vertical-align: middle; }
  .infotip-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.5rem;
    height: 1.5rem;
    padding: 0;
    color: var(--muted);
    background: transparent;
    border: 0;
    border-radius: var(--radius-pill);
    cursor: help;
  }
  .infotip-btn:hover { color: var(--text); }
  .infotip-btn:focus-visible { outline: 2px solid var(--primary); outline-offset: 1px; }
  .i-ring { fill: none; stroke: currentColor; stroke-width: 1.4; }
  .i-dot { fill: currentColor; }
  .i-stem { fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; }
  /* Hidden, not removed: aria-describedby still reads a display:none tooltip. */
  .infotip-bubble { display: none; }
  .infotip-bubble.shown {
    display: block;
    position: fixed;
    z-index: 70;
    max-width: min(20rem, calc(100vw - 16px));
    padding: 0.3rem 0.6rem;
    font-size: 0.8rem;
    line-height: 1.4;
    white-space: pre-line;
    overflow-wrap: anywhere;
    color: var(--text);
    background: var(--surface-3);
    border: 1px solid var(--outline);
    border-radius: var(--radius-sm);
    box-shadow: var(--shadow);
    pointer-events: none;
  }
</style>
