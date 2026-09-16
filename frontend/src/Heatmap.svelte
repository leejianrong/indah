<script>
  // Client-side heatmap / 2-D field (ADR-0019, KAN-1461). Draws a column-major field
  // z (z[x][y]) to a canvas through a colormap - spectrograms, heatmaps, attention
  // maps. Streaming appends a column (a time slice) via the append op (App.svelte
  // concatenates arrays), so a live spectrogram grows at O(column). No dependency:
  // the render is a small ImageData fill scaled to the canvas.
  let { props } = $props();
  let el = $state();
  let canvas = $state();
  let ctx = null;
  const off = typeof document !== "undefined" ? document.createElement("canvas") : null;
  const offctx = off ? off.getContext("2d") : null;

  // A few colormaps as anchor stops (approximating matplotlib), linearly interpolated.
  const MAPS = {
    magma: [[0, 0, 4], [81, 18, 124], [183, 55, 121], [252, 137, 97], [252, 253, 191]],
    viridis: [[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]],
    gray: [[0, 0, 0], [255, 255, 255]],
  };

  function color(map, t) {
    const stops = MAPS[map] || MAPS.magma;
    const clamped = t < 0 ? 0 : t > 1 ? 1 : t;
    const seg = clamped * (stops.length - 1);
    const i = Math.min(stops.length - 2, Math.floor(seg));
    const f = seg - i;
    const a = stops[i];
    const b = stops[i + 1];
    return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
  }

  function bounds(cols) {
    let lo = props.zmin;
    let hi = props.zmax;
    if (lo == null || hi == null) {
      let mn = Infinity;
      let mx = -Infinity;
      for (const c of cols)
        for (const v of c) {
          if (v == null || Number.isNaN(v)) continue;
          if (v < mn) mn = v;
          if (v > mx) mx = v;
        }
      if (lo == null) lo = mn === Infinity ? 0 : mn;
      if (hi == null) hi = mx === -Infinity ? 1 : mx;
    }
    if (hi === lo) hi = lo + 1; // avoid divide-by-zero on a flat field
    return [lo, hi];
  }

  function draw() {
    const cols = props.z ?? [];
    if (!canvas || !ctx || !offctx) return;
    const w = el?.clientWidth || 400;
    const h = props.height ?? 240;
    canvas.width = w;
    canvas.height = h;
    el.__heatmap = { ncols: cols.length, nrows: 0 }; // for debugging / e2e
    if (!cols.length) {
      ctx.clearRect(0, 0, w, h);
      return;
    }
    const ncols = cols.length;
    let nrows = 0;
    for (const c of cols) nrows = Math.max(nrows, c.length);
    if (!nrows) return;
    el.__heatmap.nrows = nrows;

    const map = props.colormap || "magma";
    const [lo, hi] = bounds(cols);
    off.width = ncols;
    off.height = nrows;
    const img = offctx.createImageData(ncols, nrows);
    for (let x = 0; x < ncols; x++) {
      const col = cols[x] || [];
      for (let y = 0; y < nrows; y++) {
        const v = col[y];
        const t = v == null ? 0 : (v - lo) / (hi - lo);
        const [r, g, b] = color(map, t);
        // y=0 at the bottom (like a spectrogram's low frequencies).
        const idx = ((nrows - 1 - y) * ncols + x) * 4;
        img.data[idx] = r;
        img.data[idx + 1] = g;
        img.data[idx + 2] = b;
        img.data[idx + 3] = 255;
      }
    }
    offctx.putImageData(img, 0, 0);
    ctx.imageSmoothingEnabled = false; // crisp cells, nearest-neighbour scale
    ctx.clearRect(0, 0, w, h);
    ctx.drawImage(off, 0, 0, ncols, nrows, 0, 0, w, h);
  }

  $effect(() => {
    if (canvas) ctx = canvas.getContext("2d");
  });

  // Redraw on any prop change (data, colormap, bounds, height).
  $effect(() => {
    void props.z;
    void props.colormap;
    void props.zmin;
    void props.zmax;
    void props.height;
    draw();
  });

  $effect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(el);
    return () => ro.disconnect();
  });
</script>

<div class="heatmap" bind:this={el}>
  {#if props.title}<span class="heatmap-title">{props.title}</span>{/if}
  <canvas bind:this={canvas}></canvas>
</div>
