// The Graph component's renderer (ADR-0048). Its own ES module, fetched lazily by the shell on
// the first `graph` render (ADR-0042), so an app without a graph does not download it. It draws a
// node-link graph to a <canvas>: a force layout in time slices, drag to pan, wheel and pinch to
// zoom. No dependency; the layout is in layout.js and runs under Node too. Output:
// dist-graph/graph.js (copied to src/indah/static/).
import { createSimulation, run, bounds, hashString, LAYOUT_LIMIT } from "./layout.js";
import { resolveColor, onThemeChange } from "../src/colors.js";

// Same vivid palette as Chart: it reads on both the light and dark Studio themes. Groups past
// the sixth get a hue from the golden angle, so any number of groups stays distinguishable.
const PALETTE = ["#b5296b", "#2e6d62", "#e0701a", "#3457d5", "#8a3ffc", "#c0362c"];
const SLICE_MS = 24; // layout time per animation frame while settling
const DRAW_EVERY_MS = 100; // while settling, redraw no more often than this, and no more than
const DRAW_SHARE = 4; // one draw per DRAW_SHARE times its own cost: drawing stays under a fifth of the time
const MIN_ZOOM = 0.02;
const MAX_ZOOM = 40;

export function groupColor(index) {
  return index < PALETTE.length ? PALETTE[index] : `hsl(${(index * 137.508) % 360} 55% 50%)`;
}

// Decode the columnar wire form (ADR-0048): nodes {id, label?, group?, size?, color?, x?, y?},
// edges {s, t}, where s and t are indexes into the node columns.
export function decode(data) {
  const cols = data.nodes ?? {};
  const ids = cols.id ?? [];
  const n = ids.length;
  const groups = [];
  const groupIndex = new Map();
  const group = new Int32Array(n);
  for (let i = 0; i < n; i++) {
    const name = cols.group?.[i] ?? "";
    if (!groupIndex.has(name)) {
      groupIndex.set(name, groups.length);
      groups.push(name);
    }
    group[i] = groupIndex.get(name);
  }
  const e = data.edges ?? {};
  const s = Int32Array.from(e.s ?? []);
  const t = Int32Array.from(e.t ?? []);
  const degree = new Int32Array(n);
  for (let k = 0; k < s.length; k++) {
    degree[s[k]]++;
    degree[t[k]]++;
  }
  const given = cols.x && cols.y ? { x: Float64Array.from(cols.x), y: Float64Array.from(cols.y) } : null;
  if (given) {
    given.gx = new Float64Array(Math.max(1, groups.length));
    given.gy = new Float64Array(Math.max(1, groups.length));
  }
  return { n, ids, labels: cols.label ?? null, size: cols.size ?? null, colors: cols.color ?? null, groups, group, s, t, degree, given };
}

/** Mount a graph in `el`. Returns a small controller; the shell owns the lifecycle. */
export function createGraph(el) {
  const canvas = document.createElement("canvas");
  canvas.className = "graph-canvas";
  el.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  let g = null; // decoded data
  let sim = null;
  let view = { k: 1, tx: 0, ty: 0 };
  let w = 0;
  let h = 0;
  let dpr = 1;
  let raf = 0;
  let touched = false; // the viewer has panned or zoomed: stop auto-fitting
  let startedAt = 0;
  let lastDraw = 0;
  let drawMs = 0;
  let theme = null; // resolved colours
  let batches = []; // [{ color, nodes: Int32Array }]

  function resolveTheme() {
    theme = {
      edge: resolveColor(el, "var(--muted)"),
      text: resolveColor(el, "var(--text)"),
      halo: resolveColor(el, "var(--surface)"),
    };
  }

  function nodeColor(i) {
    const explicit = g.colors?.[i];
    if (explicit) return resolveColor(el, explicit);
    return groupColor(g.group[i]);
  }

  function buildBatches() {
    const byColor = new Map();
    for (let i = 0; i < g.n; i++) {
      const c = nodeColor(i);
      if (!byColor.has(c)) byColor.set(c, []);
      byColor.get(c).push(i);
    }
    batches = [...byColor].map(([color, nodes]) => ({ color, nodes: Int32Array.from(nodes) }));
  }

  function radius(i) {
    const explicit = g.size?.[i];
    return explicit != null ? explicit : 2.5 + Math.min(5, Math.sqrt(g.degree[i]) * 0.7);
  }

  function resize() {
    dpr = window.devicePixelRatio || 1;
    w = el.clientWidth;
    h = el.clientHeight || canvas.clientHeight;
    canvas.width = Math.max(1, Math.round(w * dpr));
    canvas.height = Math.max(1, Math.round(h * dpr));
    if (!touched) fit();
    draw();
  }

  function fit() {
    if (!g || !sim || !w || !h) return;
    const b = bounds(sim.x, sim.y, g.n);
    const pad = 24;
    const bw = Math.max(b.maxx - b.minx, 1);
    const bh = Math.max(b.maxy - b.miny, 1);
    const k = Math.min((w - 2 * pad) / bw, (h - 2 * pad) / bh, MAX_ZOOM);
    view = {
      k,
      tx: w / 2 - ((b.minx + b.maxx) / 2) * k,
      ty: h / 2 - ((b.miny + b.maxy) / 2) * k,
    };
  }

  function draw() {
    if (!ctx || !g || !w || !h) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const { x, y } = sim;
    const { k, tx, ty } = view;
    // Edges: one path, drawn faint.
    ctx.globalAlpha = g.n > 2000 ? 0.18 : 0.35;
    ctx.strokeStyle = theme.edge;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let e = 0; e < g.s.length; e++) {
      const a = g.s[e];
      const b = g.t[e];
      ctx.moveTo(x[a] * k + tx, y[a] * k + ty);
      ctx.lineTo(x[b] * k + tx, y[b] * k + ty);
    }
    ctx.stroke();
    ctx.globalAlpha = 1;
    // Nodes: one fill per colour. Tiny nodes are drawn as squares, which is much cheaper.
    let visible = 0;
    for (const { color, nodes } of batches) {
      ctx.fillStyle = color;
      ctx.beginPath();
      for (let j = 0; j < nodes.length; j++) {
        const i = nodes[j];
        const px = x[i] * k + tx;
        const py = y[i] * k + ty;
        if (px < -10 || py < -10 || px > w + 10 || py > h + 10) continue;
        visible++;
        const r = radius(i) * Math.min(1.6, Math.max(0.5, Math.sqrt(k)));
        if (r < 1.6) ctx.rect(px - 0.8, py - 0.8, 1.6, 1.6);
        else {
          ctx.moveTo(px + r, py);
          ctx.arc(px, py, r, 0, Math.PI * 2);
        }
      }
      ctx.fill();
    }
    // Labels, only when few nodes are in view and the view is zoomed in enough to read them.
    if (visible <= 150 && k >= 0.6) {
      ctx.font = '12px "IBM Plex Sans", system-ui, sans-serif';
      ctx.textBaseline = "middle";
      ctx.lineWidth = 3;
      ctx.strokeStyle = theme.halo;
      ctx.fillStyle = theme.text;
      for (let i = 0; i < g.n; i++) {
        const px = x[i] * k + tx;
        const py = y[i] * k + ty;
        if (px < 0 || py < 0 || px > w || py > h) continue;
        const text = String(g.labels?.[i] ?? g.ids[i]);
        const r = radius(i) + 4;
        ctx.strokeText(text, px + r, py);
        ctx.fillText(text, px + r, py);
      }
    }
  }

  function frame() {
    raf = 0;
    let due = true;
    if (sim && !sim.done) {
      run(sim, SLICE_MS);
      if (sim.done) finish();
      else due = performance.now() - lastDraw >= Math.max(DRAW_EVERY_MS, DRAW_SHARE * drawMs);
    }
    if (due) {
      const t0 = performance.now();
      if (!touched) fit();
      draw();
      lastDraw = performance.now();
      drawMs = lastDraw - t0;
      if (el.__graph) el.__graph.drawMs = Math.round(drawMs);
    }
    if (sim && !sim.done) raf = requestAnimationFrame(frame);
  }

  function finish() {
    el.dataset.settled = "true";
    el.dataset.settleMs = String(Math.round(performance.now() - startedAt));
    el.__graph.settled = true;
    el.__graph.settleMs = Math.round(performance.now() - startedAt);
    el.__graph.steps = sim.iterations;
  }

  function schedule() {
    if (!raf) raf = requestAnimationFrame(frame);
  }

  function setData(data) {
    g = decode(data);
    resolveTheme();
    buildBatches();
    const seed = hashString(`${g.n}:${g.s.length}:${g.ids[0] ?? ""}:${g.ids[g.n - 1] ?? ""}`);
    sim = createSimulation({ n: g.n, s: g.s, t: g.t, group: g.group, nGroups: Math.max(1, g.groups.length), seed, given: g.given });
    touched = false;
    startedAt = performance.now();
    el.dataset.settled = "false";
    el.__graph = { nodes: g.n, edges: g.s.length, groups: g.groups.length, settled: false, laidOut: !g.given && g.n <= LAYOUT_LIMIT };
    if (sim.done) finish();
    fit();
    schedule();
  }

  // Pan with a drag, zoom with the wheel or two fingers.
  const pointers = new Map();
  let pinch = 0;
  function zoomAt(px, py, factor) {
    const k = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.k * factor));
    const f = k / view.k;
    view = { k, tx: px - (px - view.tx) * f, ty: py - (py - view.ty) * f };
    touched = true;
    draw();
  }
  function local(ev) {
    const r = canvas.getBoundingClientRect();
    return [ev.clientX - r.left, ev.clientY - r.top];
  }
  canvas.addEventListener("pointerdown", (ev) => {
    canvas.setPointerCapture(ev.pointerId);
    pointers.set(ev.pointerId, local(ev));
    pinch = 0;
  });
  canvas.addEventListener("pointermove", (ev) => {
    if (!pointers.has(ev.pointerId)) return;
    const [px, py] = local(ev);
    const [ox, oy] = pointers.get(ev.pointerId);
    pointers.set(ev.pointerId, [px, py]);
    if (pointers.size === 1) {
      view = { ...view, tx: view.tx + px - ox, ty: view.ty + py - oy };
      touched = true;
      draw();
    } else if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (pinch) zoomAt((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, d / pinch);
      pinch = d;
    }
  });
  const release = (ev) => {
    pointers.delete(ev.pointerId);
    pinch = 0;
  };
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);
  canvas.addEventListener(
    "wheel",
    (ev) => {
      ev.preventDefault();
      const [px, py] = local(ev);
      zoomAt(px, py, Math.exp(-ev.deltaY * 0.0015));
    },
    { passive: false },
  );

  const offTheme = onThemeChange(() => {
    resolveTheme();
    if (g) buildBatches();
    draw();
  });

  return {
    setData,
    resize,
    fit() {
      touched = false;
      fit();
      draw();
    },
    legend() {
      if (!g || g.groups.length === 0 || (g.groups.length === 1 && g.groups[0] === "")) return [];
      return g.groups.map((name, i) => ({ group: name, color: groupColor(i) }));
    },
    destroy() {
      if (raf) cancelAnimationFrame(raf);
      offTheme();
      canvas.remove();
    },
  };
}
