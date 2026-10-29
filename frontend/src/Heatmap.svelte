<script>
  // Client-side heatmap / 2-D field (ADR-0019, KAN-1461; ADR-0046). Draws a column-major field
  // z (z[x][y]) to a canvas through a colormap - spectrograms, heatmaps, attention
  // maps. Streaming appends a column (a time slice) via the append op (App.svelte
  // concatenates arrays), so a live spectrogram grows at O(column). No dependency:
  // the render is a small ImageData fill scaled to the canvas.
  //
  // ADR-0046 adds, all optional: a `colormap` given as a list of colour stops (hex or
  // var(--token), so the scale follows the theme); `nullColor` for cells with no value (a masked
  // cell, rather than the lowest colour); `origin="top"` to put row 0 at the top; `rowLabels` in a
  // left gutter; `colGroups` as labelled brackets over runs of columns; and a spotlight (`markX`)
  // with a ringed cell (`markY`), both reactive.
  import { resolveColor, onThemeChange } from "./colors.js";

  let { props } = $props();
  let el = $state();
  let canvas = $state();
  let titleEl = $state();
  let ctx = null;
  const off = typeof document !== "undefined" ? document.createElement("canvas") : null;
  const offctx = off ? off.getContext("2d", { willReadFrequently: true }) : null;
  let cache = { z: null, key: null, ncols: 0, nrows: 0 }; // what the cell image on `off` was built from

  const GUTTER = 52; // px reserved for row labels
  const BAND = 30; // px reserved for column-group brackets
  const MONO = '"IBM Plex Mono", ui-monospace, monospace';

  // A few colormaps as anchor stops (approximating matplotlib), linearly interpolated.
  const MAPS = {
    magma: [[0, 0, 4], [81, 18, 124], [183, 55, 121], [252, 137, 97], [252, 253, 191]],
    viridis: [[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]],
    gray: [[0, 0, 0], [255, 255, 255]],
  };

  // Any CSS colour (or var(--token)) to [r, g, b], by letting a 1x1 canvas parse it.
  const probe = typeof document !== "undefined" ? document.createElement("canvas") : null;
  function rgb(value) {
    const c = resolveColor(el, value);
    const p = probe.getContext("2d", { willReadFrequently: true });
    probe.width = probe.height = 1;
    p.clearRect(0, 0, 1, 1);
    p.fillStyle = "#000";
    p.fillStyle = c;
    p.fillRect(0, 0, 1, 1);
    const d = p.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2]];
  }

  function stopsFor(map) {
    if (Array.isArray(map)) return map.map(rgb);
    return MAPS[map] || MAPS.magma;
  }

  function color(stops, t) {
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

  // Build the cell image (one pixel per cell) into the off-screen canvas.
  function buildImage(cols, ncols, nrows) {
    const stops = stopsFor(props.colormap || "magma");
    const [lo, hi] = bounds(cols);
    const empty = props.nullColor ? rgb(props.nullColor) : null;
    const top = props.origin === "top";
    off.width = ncols;
    off.height = nrows;
    const img = offctx.createImageData(ncols, nrows);
    for (let x = 0; x < ncols; x++) {
      const col = cols[x] || [];
      for (let y = 0; y < nrows; y++) {
        const v = col[y];
        const [r, g, b] =
          v == null && empty ? empty : color(stops, v == null ? 0 : (v - lo) / (hi - lo));
        // Row 0 is at the bottom (like a spectrogram's low frequencies) unless origin="top".
        const idx = ((top ? y : nrows - 1 - y) * ncols + x) * 4;
        img.data[idx] = r;
        img.data[idx + 1] = g;
        img.data[idx + 2] = b;
        img.data[idx + 3] = 255;
      }
    }
    offctx.putImageData(img, 0, 0);
  }

  function draw() {
    const cols = props.z ?? [];
    if (!canvas || !ctx || !offctx) return;
    const dpr = window.devicePixelRatio || 1;
    const w = el?.clientWidth || 400;
    // height="fill" (ADR-0046): the container's height, less the title row above the canvas.
    const h =
      props.height === "fill"
        ? Math.max(40, Math.floor((el?.clientHeight || 0) - (titleEl ? titleEl.offsetHeight + 5 : 0)))
        : (props.height ?? 240);
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.height = `${h}px`;
    el.__heatmap = { ncols: cols.length, nrows: 0 }; // for debugging / e2e
    if (!cols.length) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      return;
    }
    const ncols = cols.length;
    let nrows = 0;
    for (const c of cols) nrows = Math.max(nrows, c.length);
    if (!nrows) return;
    el.__heatmap.nrows = nrows;

    // The cell image only changes with the field or how it is coloured; a moving mark reuses it.
    const key = JSON.stringify([props.colormap, props.zmin, props.zmax, props.nullColor, props.origin]);
    if (cache.z !== cols || cache.key !== key || cache.ncols !== ncols || cache.nrows !== nrows) {
      buildImage(cols, ncols, nrows);
      cache = { z: cols, key, ncols, nrows };
    }

    const left = (props.rowLabels?.length ? GUTTER : 0) * dpr;
    const topPad = (props.colGroups?.length ? BAND : 0) * dpr;
    const pw = canvas.width - left;
    const ph = canvas.height - topPad;
    ctx.imageSmoothingEnabled = false; // crisp cells, nearest-neighbour scale
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(off, 0, 0, ncols, nrows, left, topPad, pw, ph);
    overlays(ncols, nrows, { left, topPad, pw, ph, dpr });
  }

  function overlays(ncols, nrows, g) {
    const { left, topPad, pw, ph, dpr } = g;
    const muted = resolveColor(el, "var(--muted)");
    ctx.font = `${11 * dpr}px ${MONO}`;
    ctx.fillStyle = muted;
    const cellW = pw / ncols;
    const cellH = ph / nrows;
    const rowY = (y) => topPad + (props.origin === "top" ? y : nrows - 1 - y) * cellH;

    if (props.rowLabels?.length) {
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      props.rowLabels.slice(0, nrows).forEach((label, y) => {
        ctx.fillText(label, left - 8 * dpr, rowY(y) + cellH / 2);
      });
    }

    if (props.colGroups?.length) {
      ctx.textAlign = "center";
      ctx.textBaseline = "alphabetic";
      ctx.strokeStyle = resolveColor(el, "var(--outline)");
      ctx.lineWidth = 2 * dpr;
      ctx.lineCap = "round";
      ctx.font = `${12 * dpr}px ${getComputedStyle(el).fontFamily || "sans-serif"}`;
      for (const grp of props.colGroups) {
        const x1 = left + (grp.start / ncols) * pw + 2 * dpr;
        const x2 = left + ((grp.end + 1) / ncols) * pw - 2 * dpr;
        ctx.beginPath();
        ctx.moveTo(x1, topPad - 8 * dpr);
        ctx.lineTo(x2, topPad - 8 * dpr);
        ctx.stroke();
        ctx.fillText(grp.label, (x1 + x2) / 2, topPad - 14 * dpr);
      }
    }

    if (props.markX != null && props.markX >= 0 && props.markX < ncols) {
      const x = left + props.markX * cellW;
      ctx.fillStyle = resolveColor(el, "var(--text)");
      ctx.globalAlpha = 0.14;
      ctx.fillRect(x - 1.5 * dpr, topPad, cellW + 3 * dpr, ph);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = resolveColor(el, "var(--text)");
      ctx.lineWidth = 1.2 * dpr;
      ctx.strokeRect(x - 1.5 * dpr, topPad, cellW + 3 * dpr, ph);
      if (props.markY != null && props.markY >= 0 && props.markY < nrows) {
        ctx.strokeStyle = resolveColor(el, props.markColor || "var(--x-gold, #d9a300)");
        ctx.lineWidth = 2 * dpr;
        ctx.strokeRect(x - 2.5 * dpr, rowY(props.markY) - 1 * dpr, cellW + 5 * dpr, cellH + 2 * dpr);
      }
    }
  }

  $effect(() => {
    if (canvas) ctx = canvas.getContext("2d");
  });

  // Redraw on any prop change (data, colormap, bounds, height, labels, marks).
  $effect(() => {
    void props.z;
    void props.colormap;
    void props.zmin;
    void props.zmax;
    void props.height;
    void props.nullColor;
    void props.origin;
    void props.rowLabels;
    void props.colGroups;
    void props.markX;
    void props.markY;
    void props.markColor;
    draw();
  });

  // Colours written as var(--token) are resolved when drawing: draw again on a theme switch.
  $effect(() =>
    onThemeChange(() => {
      cache = { z: null, key: null, ncols: 0, nrows: 0 };
      draw();
    }),
  );

  $effect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(el);
    return () => ro.disconnect();
  });
</script>

<div class="heatmap" bind:this={el}>
  {#if props.title}<span class="heatmap-title" bind:this={titleEl}>{props.title}</span>{/if}
  <canvas bind:this={canvas}></canvas>
</div>
