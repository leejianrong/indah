<script>
  // Read-only overlay display (ADR-0020) plus zoom/pan (#77). Boxes/points/masks
  // are positioned as percentages relative to `.ov-content`, so a single CSS
  // scale+translate on that one layer zooms/pans everything in lockstep - no
  // coordinate math in the box/point rendering itself. `.overlay-wrap` stays a
  // fixed-size, overflow:hidden viewport; only `.ov-content` inside it transforms.
  let { props } = $props();

  let wrapEl = $state();
  let scale = $state(1);
  let panX = $state(0);
  let panY = $state(0);
  let dragging = $state(false);
  let dragStart = null; // plain object, not reactive - read only inside the drag

  const MIN_SCALE = 1;
  const MAX_SCALE = 6;

  function boxLabel(b) {
    if (b.label == null) return null;
    return b.score != null ? `${b.label} ${(b.score * 100).toFixed(0)}%` : b.label;
  }

  // `.ov-content`'s untransformed size equals the viewport's size at rest (it
  // shrink-to-fits the image, same as the viewport does). Clamp so a zoomed-in
  // drag/zoom-to-cursor can't expose empty space past the content's edge.
  function clampPan(nextScale, x, y) {
    if (!wrapEl) return { x, y };
    const w = wrapEl.clientWidth;
    const h = wrapEl.clientHeight;
    const minX = Math.min(0, w - w * nextScale);
    const minY = Math.min(0, h - h * nextScale);
    return { x: Math.min(0, Math.max(minX, x)), y: Math.min(0, Math.max(minY, y)) };
  }

  function resetView() {
    scale = 1;
    panX = 0;
    panY = 0;
  }

  // A new image shouldn't inherit the previous one's zoom/pan state.
  $effect(() => {
    void props.src;
    resetView();
  });

  function handleWheel(e) {
    e.preventDefault();
    if (!wrapEl) return;
    const rect = wrapEl.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    const factor = Math.exp(-e.deltaY * 0.0015);
    const nextScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale * factor));
    if (nextScale === scale) return;
    // Zoom-to-cursor: keep the content point under the cursor fixed on screen.
    const nx = cx - (nextScale / scale) * (cx - panX);
    const ny = cy - (nextScale / scale) * (cy - panY);
    const clamped = clampPan(nextScale, nx, ny);
    scale = nextScale;
    panX = clamped.x;
    panY = clamped.y;
  }

  function handlePointerDown(e) {
    // Don't hijack a click on the reset button: pointer capture retargets its
    // mouseup/click to the wrap too, so the button's own handler never fires.
    if (e.target.closest(".ov-reset-btn")) return;
    if (scale <= 1) return;
    dragging = true;
    dragStart = { x: e.clientX, y: e.clientY, panX, panY };
    wrapEl.setPointerCapture(e.pointerId);
  }

  function handlePointerMove(e) {
    if (!dragging || !dragStart) return;
    const nx = dragStart.panX + (e.clientX - dragStart.x);
    const ny = dragStart.panY + (e.clientY - dragStart.y);
    const clamped = clampPan(scale, nx, ny);
    panX = clamped.x;
    panY = clamped.y;
  }

  function handlePointerUp(e) {
    if (dragging) wrapEl.releasePointerCapture(e.pointerId);
    dragging = false;
    dragStart = null;
  }
</script>

<!-- A pan/zoom viewport, not a semantic control - the wheel/drag interaction is
     supplementary (the overlay is fully usable unscrolled) and the reset button
     is the keyboard-reachable way to undo it. -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="overlay-wrap"
  class:zoomed={scale > 1}
  class:dragging
  bind:this={wrapEl}
  onwheel={handleWheel}
  onpointerdown={handlePointerDown}
  onpointermove={handlePointerMove}
  onpointerup={handlePointerUp}
  onpointercancel={handlePointerUp}
>
  <div
    class="ov-content"
    style="transform: translate({panX}px, {panY}px) scale({scale}); transform-origin: 0 0;"
  >
    <img class="image" src={props.src ?? ""} alt={props.alt ?? ""} />
    {#each props.masks ?? [] as m (m.src)}
      <img class="ov-mask" src={m.src} alt="" style="opacity: {m.opacity ?? 0.5};" />
    {/each}
    {#each props.boxes ?? [] as b, i (i)}
      <div
        class="ov-box"
        class:ov-box--hover={props.labelMode === "hover"}
        style="left: {(b.x ?? 0) * 100}%; top: {(b.y ?? 0) * 100}%; width: {(b.w ?? 0) *
          100}%; height: {(b.h ?? 0) * 100}%; border-color: {b.color ?? 'var(--primary)'};"
        title={props.labelMode === "hover" ? boxLabel(b) : null}
      >
        {#if b.label != null && props.labelMode !== "hover"}
          <span class="ov-label" style="background: {b.color ?? 'var(--primary)'};"
            >{b.label}{#if b.score != null}&nbsp;{(b.score * 100).toFixed(0)}%{/if}</span
          >
        {/if}
      </div>
    {/each}
    {#each props.points ?? [] as p, i (i)}
      <div
        class="ov-point"
        style="left: {(p.x ?? 0) * 100}%; top: {(p.y ?? 0) * 100}%; background: {p.color ??
          'var(--primary)'};"
        title={p.label ?? ""}
      ></div>
    {/each}
  </div>
  {#if scale !== 1}
    <button type="button" class="ov-reset-btn" onclick={resetView}>Reset view</button>
  {/if}
</div>
