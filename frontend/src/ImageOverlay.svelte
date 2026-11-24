<script>
  // Read-only overlay display (ADR-0020) plus zoom/pan (#77). Boxes/points/masks
  // are positioned as percentages relative to `.ov-content`, so a single CSS
  // scale+translate on that one layer zooms/pans everything in lockstep - no
  // coordinate math in the box/point rendering itself. `.overlay-wrap` stays a
  // fixed-size, overflow:hidden viewport; only `.ov-content` inside it transforms.
  import { postEvent } from "./api.js";
  let { props, id = "" } = $props();

  // Shapes in raster pixels (ADR-0052) live in one SVG whose viewBox is the raster, stretched over
  // the image, so they line up at any size and any zoom. `view` crops to a region of the raster.
  const size = $derived(props.size ?? null);
  const view = $derived(props.view ?? null);
  const cropStyle = $derived(
    view && size
      ? `aspect-ratio: ${view[2]} / ${view[3]}; display: block; width: 100%;`
      : "",
  );
  const contentStyle = $derived(
    view && size
      ? `position: absolute; width: ${(size[0] / view[2]) * 100}%; left: ${(-view[0] / view[2]) * 100}%; top: ${(-view[1] / view[3]) * 100}%;`
      : null,
  );
  const pick = (sh) => sh.pick && postEvent(id, "pick", { id: sh.id });
  const onShapeKey = (e, sh) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      pick(sh);
    }
  };

  // Drawing (ADR-0020 step 2): a drag makes a box, a click a point, both sent in raster pixels. The
  // pointer maps through `.ov-content`'s own rect, which already carries any zoom or crop.
  const draw = $derived(size ? (props.draw ?? null) : null);
  let contentEl = $state();
  let rubber = $state(null); // {x1, y1, x2, y2} while a box is being dragged
  const dotR = $derived(size ? Math.max(3, Math.max(size[0], size[1]) / 150) : 3);
  function rasterXY(e) {
    const r = contentEl.getBoundingClientRect();
    return [((e.clientX - r.left) / r.width) * size[0], ((e.clientY - r.top) / r.height) * size[1]];
  }
  function drawDown(e) {
    if (e.button !== 0) return;
    e.preventDefault(); // else the browser starts dragging the <img> and cancels the pointer
    const [x, y] = rasterXY(e);
    rubber = { x1: x, y1: y, x2: x, y2: y };
    wrapEl.setPointerCapture(e.pointerId);
  }
  function drawMove(e) {
    if (!rubber) return;
    const [x, y] = rasterXY(e);
    rubber = { ...rubber, x2: x, y2: y };
  }
  function drawUp(e) {
    if (!rubber) return;
    const r = rubber;
    rubber = null;
    if (wrapEl.hasPointerCapture(e.pointerId)) wrapEl.releasePointerCapture(e.pointerId);
    if (draw === "point") postEvent(id, "draw", { kind: "point", point: [r.x2, r.y2] });
    else if (draw === "box") postEvent(id, "draw", { kind: "box", box: [r.x1, r.y1, r.x2, r.y2] });
  }
  $effect(() => {
    if (!draw) rubber = null;
  });

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
    if (view) return; // a cropped view is fixed
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
    if (draw) return drawDown(e);
    if (scale <= 1 || view) return;
    dragging = true;
    dragStart = { x: e.clientX, y: e.clientY, panX, panY };
    wrapEl.setPointerCapture(e.pointerId);
  }

  function handlePointerMove(e) {
    if (draw) return drawMove(e);
    if (!dragging || !dragStart) return;
    const nx = dragStart.panX + (e.clientX - dragStart.x);
    const ny = dragStart.panY + (e.clientY - dragStart.y);
    const clamped = clampPan(scale, nx, ny);
    panX = clamped.x;
    panY = clamped.y;
  }

  function handlePointerUp(e) {
    if (draw) return drawUp(e);
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
  class:drawing={draw}
  data-draw={draw}
  style={cropStyle}
  bind:this={wrapEl}
  onwheel={handleWheel}
  onpointerdown={handlePointerDown}
  onpointermove={handlePointerMove}
  onpointerup={handlePointerUp}
  onpointercancel={() => (rubber = null)}
>
  <div
    class="ov-content"
    bind:this={contentEl}
    style={contentStyle ?? `transform: translate(${panX}px, ${panY}px) scale(${scale}); transform-origin: 0 0;`}
  >
    <img class="image" src={props.src ?? ""} alt={props.alt ?? ""} draggable="false" />
    {#if size && (props.shapes || draw)}
      <svg class="ov-shapes" viewBox="0 0 {size[0]} {size[1]}" preserveAspectRatio="none" aria-hidden={props.shapes?.some((x) => x.pick) ? null : "true"}>
        {#each props.shapes ?? [] as sh (sh.id)}
          {@const on = props.selected != null && props.selected === sh.id}
          {@const common = {
            fill: sh.fill ?? "none",
            "fill-opacity": sh.opacity ?? 0.25,
            stroke: sh.stroke ?? "var(--primary)",
            "stroke-width": (sh.width ?? 1.5) + (on ? 2 : 0),
            "stroke-dasharray": sh.dash ? sh.dash.join(" ") : null,
            "vector-effect": "non-scaling-stroke",
          }}
          {#if sh.box}
            <rect
              x={sh.box[0]} y={sh.box[1]} width={sh.box[2] - sh.box[0]} height={sh.box[3] - sh.box[1]}
              {...common} class:ov-pick={sh.pick} class:ov-on={on}
              role={sh.pick ? "button" : null} tabindex={sh.pick ? 0 : null} aria-label={sh.pick ? sh.label : null}
              onclick={() => pick(sh)} onkeydown={(e) => sh.pick && onShapeKey(e, sh)}
            >{#if sh.label}<title>{sh.label}</title>{/if}</rect>
          {:else if sh.point}
            <circle
              cx={sh.point[0]} cy={sh.point[1]} r={dotR}
              {...common} fill={sh.fill ?? sh.stroke ?? "var(--primary)"} fill-opacity={sh.opacity ?? 0.9}
              class:ov-pick={sh.pick} class:ov-on={on}
              role={sh.pick ? "button" : null} tabindex={sh.pick ? 0 : null} aria-label={sh.pick ? sh.label : null}
              onclick={() => pick(sh)} onkeydown={(e) => sh.pick && onShapeKey(e, sh)}
            >{#if sh.label}<title>{sh.label}</title>{/if}</circle>
          {:else if sh.points}
            <polygon
              points={sh.points.map((p) => p.join(",")).join(" ")}
              {...common} class:ov-pick={sh.pick} class:ov-on={on}
              role={sh.pick ? "button" : null} tabindex={sh.pick ? 0 : null} aria-label={sh.pick ? sh.label : null}
              onclick={() => pick(sh)} onkeydown={(e) => sh.pick && onShapeKey(e, sh)}
            >{#if sh.label}<title>{sh.label}</title>{/if}</polygon>
          {/if}
        {/each}
        {#if rubber && draw === "box"}
          <rect
            class="ov-rubber"
            x={Math.min(rubber.x1, rubber.x2)} y={Math.min(rubber.y1, rubber.y2)}
            width={Math.abs(rubber.x2 - rubber.x1)} height={Math.abs(rubber.y2 - rubber.y1)}
            fill="var(--primary)" fill-opacity="0.15" stroke="var(--primary)" stroke-width="1.5"
            stroke-dasharray="5 3" vector-effect="non-scaling-stroke"
          />
        {/if}
      </svg>
    {/if}
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
