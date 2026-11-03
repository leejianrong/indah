// The Graph component's renderer (ADR-0048). Its own ES module, fetched lazily by the shell on
// the first `graph` render (ADR-0042), so an app without a graph does not download it. It draws a
// node-link graph to a <canvas>: a force layout in time slices, drag to pan, wheel and pinch to
// zoom. The focus window (ADR-0048): only the `focusSize` nodes nearest the viewport centre are
// drawn in full (labels, edges); the rest are batched dots. No dependency; the layout is in layout.js
// and the spatial index in spatial.js, and both run under Node too. Output:
// dist-graph/graph.js (copied to src/indah/static/).
import { createSimulation, run, bounds, hashString, LAYOUT_LIMIT } from "./layout.js";
import { buildGrid, nearest } from "./spatial.js";
import { resolveColor, onThemeChange } from "../src/colors.js";

// Same vivid palette as Chart: it reads on both the light and dark Studio themes. Groups past
// the sixth get a hue from the golden angle, so any number of groups stays distinguishable.
const PALETTE = ["#b5296b", "#2e6d62", "#e0701a", "#3457d5", "#8a3ffc", "#c0362c"];
const SLICE_MS = 24; // layout time per animation frame while settling
const DRAW_EVERY_MS = 100; // while settling, redraw no more often than this, and no more than
const DRAW_SHARE = 4; // one draw per DRAW_SHARE times its own cost: drawing stays under a fifth of the time
const MIN_ZOOM = 0.02;
const MAX_ZOOM = 40;
const NEIGHBOUR_ALLOWANCE = 100; // most neighbours a selected node promotes into the window
const MAX_LABELS = 150;

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
  const idIndex = new Map();
  for (let i = 0; i < n; i++) idIndex.set(ids[i], i);
  const adjStart = new Int32Array(n + 1);
  for (let i = 0; i < n; i++) adjStart[i + 1] = adjStart[i] + degree[i];
  const adjEdge = new Int32Array(2 * s.length);
  const fillAt = adjStart.slice(0, n);
  for (let k = 0; k < s.length; k++) {
    adjEdge[fillAt[s[k]]++] = k;
    adjEdge[fillAt[t[k]]++] = k;
  }
  const given = cols.x && cols.y ? { x: Float64Array.from(cols.x), y: Float64Array.from(cols.y) } : null;
  if (given) {
    given.gx = new Float64Array(Math.max(1, groups.length));
    given.gy = new Float64Array(Math.max(1, groups.length));
  }
  return { n, ids, idIndex, adjStart, adjEdge, edgeIds: e.id ?? null, labels: cols.label ?? null, size: cols.size ?? null, colors: cols.color ?? null, groups, group, s, t, degree, given };
}

/** Mount a graph in `el`. Returns a small controller; the shell owns the lifecycle. */
export function createGraph(el, { onSelect } = {}) {
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
  let grid = null;
  let gridStamp = -1;
  let inWin = new Uint8Array(0); // 1 for a node drawn in full
  let focusSize = 300;
  let selected = -1; // index of the selected node, or -1
  let hlNodes = new Int32Array(0);
  let hlNodeFlag = new Uint8Array(0);
  let hlEdges = new Int32Array(0);
  let appliedSelected; // the last `selected` / `focus` from Python, so only a change acts
  let appliedFocus;

  function resolveTheme() {
    theme = {
      edge: resolveColor(el, "var(--muted)"),
      text: resolveColor(el, "var(--text)"),
      halo: resolveColor(el, "var(--surface)"),
      primary: resolveColor(el, "var(--primary, #b5296b)"),
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

  function ensureGrid() {
    // Positions move while the layout settles, so rebuild the index whenever a step has happened.
    if (!grid || gridStamp !== sim.iterations) {
      grid = buildGrid(sim.x, sim.y, g.n);
      gridStamp = sim.iterations;
    }
  }

  // The nodes drawn in full: the `focusSize` nearest the viewport centre, every highlighted node
  // whatever its distance, and a selected node with its nearest neighbours (up to an allowance, so
  // a hub cannot make a frame unbounded). Sets `inWin`; returns the list.
  function computeWindow() {
    const { n } = g;
    if (inWin.length !== n) inWin = new Uint8Array(n);
    if (n <= focusSize) {
      inWin.fill(1);
      return null; // everything is detailed; there are no dots
    }
    inWin.fill(0);
    ensureGrid();
    const fx = (w / 2 - view.tx) / view.k;
    const fy = (h / 2 - view.ty) / view.k;
    const near = nearest(grid, fx, fy, focusSize);
    for (let j = 0; j < near.length; j++) inWin[near[j]] = 1;
    for (let j = 0; j < hlNodes.length; j++) inWin[hlNodes[j]] = 1;
    if (selected >= 0) {
      inWin[selected] = 1;
      const x = sim.x;
      const y = sim.y;
      const around = [];
      for (let j = g.adjStart[selected]; j < g.adjStart[selected + 1]; j++) {
        const e = g.adjEdge[j];
        around.push(g.s[e] === selected ? g.t[e] : g.s[e]);
      }
      const d2 = (i) => (x[i] - x[selected]) ** 2 + (y[i] - y[selected]) ** 2;
      around.sort((p, q) => d2(p) - d2(q));
      for (let j = 0; j < Math.min(around.length, NEIGHBOUR_ALLOWANCE); j++) inWin[around[j]] = 1;
    }
    return near;
  }

  function publish(count) {
    if (!el.__graph) return;
    el.__graph.windowSize = count;
    el.__graph.selected = selected >= 0 ? g.ids[selected] : null;
  }

  function draw() {
    const t0 = performance.now();
    paint();
    if (el.__graph) el.__graph.lastDrawMs = Math.round((performance.now() - t0) * 10) / 10;
  }

  function paint() {
    if (!ctx || !g || !w || !h) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const { x, y } = sim;
    const { k, tx, ty } = view;
    const everything = g.n <= focusSize;
    computeWindow();
    let count = 0;
    for (let i = 0; i < g.n; i++) count += inWin[i];
    publish(count);
    const dim = hlNodes.length > 0 || hlEdges.length > 0;

    // Dots: every node outside the window, as a batched fill per colour.
    if (!everything) {
      ctx.globalAlpha = dim ? 0.22 : 0.6;
      for (const { color, nodes } of batches) {
        ctx.fillStyle = color;
        ctx.beginPath();
        for (let j = 0; j < nodes.length; j++) {
          const i = nodes[j];
          if (inWin[i]) continue;
          const px = x[i] * k + tx;
          const py = y[i] * k + ty;
          if (px < -4 || py < -4 || px > w + 4 || py > h + 4) continue;
          ctx.rect(px - 0.8, py - 0.8, 1.6, 1.6);
        }
        ctx.fill();
      }
    }

    // Edges between detailed nodes, faint.
    ctx.globalAlpha = dim ? 0.1 : 0.35;
    ctx.strokeStyle = theme.edge;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let e = 0; e < g.s.length; e++) {
      const a = g.s[e];
      const b = g.t[e];
      if (!inWin[a] || !inWin[b]) continue;
      ctx.moveTo(x[a] * k + tx, y[a] * k + ty);
      ctx.lineTo(x[b] * k + tx, y[b] * k + ty);
    }
    ctx.stroke();

    // A selected node draws every edge it has, so it never looks isolated.
    const strokeEdges = (list, color, width) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.beginPath();
      for (const e of list) {
        const a = g.s[e];
        const b = g.t[e];
        ctx.moveTo(x[a] * k + tx, y[a] * k + ty);
        ctx.lineTo(x[b] * k + tx, y[b] * k + ty);
      }
      ctx.stroke();
    };
    if (selected >= 0) {
      ctx.globalAlpha = 0.8;
      strokeEdges(Array.from(g.adjEdge.subarray(g.adjStart[selected], g.adjStart[selected + 1])), theme.text, 1.5);
    }
    // Highlighted edges are always drawn in full, however far outside the window.
    ctx.globalAlpha = 1;
    if (hlEdges.length) strokeEdges(hlEdges, theme.primary, 2.5);

    // Detailed nodes: circles, one fill per colour.
    let labelled = 0;
    for (const { color, nodes } of batches) {
      ctx.fillStyle = color;
      ctx.beginPath();
      for (let j = 0; j < nodes.length; j++) {
        const i = nodes[j];
        if (!inWin[i]) continue;
        const px = x[i] * k + tx;
        const py = y[i] * k + ty;
        if (px < -10 || py < -10 || px > w + 10 || py > h + 10) continue;
        const r = radius(i) * Math.min(1.6, Math.max(0.5, Math.sqrt(k)));
        ctx.moveTo(px + r, py);
        ctx.arc(px, py, r, 0, Math.PI * 2);
      }
      ctx.globalAlpha = dim ? 0.4 : 1;
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    // Rings: highlighted nodes in the accent colour, the selected node in the text colour.
    const ring = (i, color, width) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.beginPath();
      ctx.arc(x[i] * k + tx, y[i] * k + ty, radius(i) + 3, 0, Math.PI * 2);
      ctx.stroke();
    };
    for (let j = 0; j < hlNodes.length; j++) ring(hlNodes[j], theme.primary, 2.5);
    if (selected >= 0) ring(selected, theme.text, 2);

    // Labels: detailed nodes in view while the view is zoomed in enough to read them, plus the
    // selected and highlighted nodes always.
    ctx.font = '12px "IBM Plex Sans", system-ui, sans-serif';
    ctx.textBaseline = "middle";
    ctx.lineWidth = 3;
    const label = (i, force) => {
      const px = x[i] * k + tx;
      const py = y[i] * k + ty;
      if (px < 0 || py < 0 || px > w || py > h) return;
      if (!force && (k < 0.5 || labelled >= MAX_LABELS)) return;
      labelled++;
      const text = String(g.labels?.[i] ?? g.ids[i]);
      const r = radius(i) + 4;
      ctx.strokeStyle = theme.halo;
      ctx.fillStyle = theme.text;
      ctx.strokeText(text, px + r, py);
      ctx.fillText(text, px + r, py);
    };
    for (let i = 0; i < g.n; i++) if (inWin[i] && !hlNodeFlag[i] && i !== selected) label(i, false);
    for (let j = 0; j < hlNodes.length; j++) label(hlNodes[j], true);
    if (selected >= 0) label(selected, true);
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
    selected = -1;
    appliedSelected = undefined;
    appliedFocus = undefined;
    grid = null;
    inWin = new Uint8Array(g.n);
    hlNodes = new Int32Array(0);
    hlNodeFlag = new Uint8Array(g.n);
    hlEdges = new Int32Array(0);
    el.__graph = {
      nodes: g.n,
      edges: g.s.length,
      groups: g.groups.length,
      settled: false,
      laidOut: !g.given && g.n <= LAYOUT_LIMIT,
      // For tests and debugging: is this node drawn in full right now?
      isDetailed: (id) => inWin[g.idIndex.get(id)] === 1,
      neighbours: (id) => {
        const i = g.idIndex.get(id);
        const out = [];
        for (let j = g.adjStart[i]; j < g.adjStart[i + 1]; j++) {
          const e = g.adjEdge[j];
          out.push(g.ids[g.s[e] === i ? g.t[e] : g.s[e]]);
        }
        return out;
      },
      view: () => ({ ...view, w, h }),
      screenOf: (id) => {
        const i = g.idIndex.get(id);
        return [sim.x[i] * view.k + view.tx, sim.y[i] * view.k + view.ty];
      },
    };
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
  let downAt = null; // where a single-pointer press began, to tell a click from a drag
  let travelled = 0;
  canvas.addEventListener("pointerdown", (ev) => {
    canvas.setPointerCapture(ev.pointerId);
    pointers.set(ev.pointerId, local(ev));
    pinch = 0;
    downAt = pointers.size === 1 ? local(ev) : null;
    travelled = 0;
  });
  canvas.addEventListener("pointermove", (ev) => {
    if (!pointers.has(ev.pointerId)) return;
    const [px, py] = local(ev);
    const [ox, oy] = pointers.get(ev.pointerId);
    pointers.set(ev.pointerId, [px, py]);
    if (downAt) travelled = Math.max(travelled, Math.hypot(px - downAt[0], py - downAt[1]));
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
  canvas.addEventListener("pointerup", (ev) => {
    const click = downAt && travelled < 4 && pointers.size === 1;
    const at = local(ev);
    release(ev);
    if (click) clickAt(at[0], at[1]);
    downAt = null;
  });
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

  // A click picks the nearest node (a dot too) within a few pixels, selects it and centres the
  // view on it, which also moves the focus there; a click on empty canvas clears the selection.
  function clickAt(px, py) {
    if (!g || !sim || g.n === 0) return;
    ensureGrid();
    const wx = (px - view.tx) / view.k;
    const wy = (py - view.ty) / view.k;
    const i = nearest(grid, wx, wy, 1)[0];
    const near = Math.hypot(sim.x[i] * view.k + view.tx - px, sim.y[i] * view.k + view.ty - py);
    if (near <= Math.max(10, radius(i) + 4)) {
      select(i);
      centreOn(i);
      if (onSelect) onSelect(g.ids[i]);
    } else if (selected >= 0) {
      select(-1);
      if (onSelect) onSelect(null);
    }
    draw();
  }

  function select(i) {
    selected = i;
  }

  // Pan so node i is in the middle of the canvas, which also moves the focus window there.
  function centreOn(i) {
    view = { ...view, tx: w / 2 - sim.x[i] * view.k, ty: h / 2 - sim.y[i] * view.k };
    touched = true;
  }

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
    // Options from Python: how many nodes are drawn in full, and a path to emphasise.
    setOptions({ focusSize: size, highlight, selected: want, focus }) {
      if (size != null && size !== focusSize) focusSize = size;
      // Python set `selected` (a node id, or null to clear): select it and centre on it. Only a
      // change acts, so an unrelated update does not recentre the viewer, and the echo of the
      // viewer's own click is a no-op.
      if (want !== undefined && g && want !== appliedSelected) {
        appliedSelected = want;
        const i = want == null ? -1 : g.idIndex.get(want);
        if (i !== undefined && i !== selected) {
          select(i);
          if (i >= 0) centreOn(i);
        }
      }
      if (focus !== undefined && g && focus !== appliedFocus) {
        appliedFocus = focus;
        const i = focus == null ? undefined : g.idIndex.get(focus);
        if (i !== undefined) centreOn(i);
      }
      if (highlight !== undefined && g) {
        const nodes = [];
        for (const id of highlight?.nodes ?? []) if (g.idIndex.has(id)) nodes.push(g.idIndex.get(id));
        let edges = [];
        if (g.edgeIds && (highlight?.edges ?? []).length) {
          const want = new Set(highlight.edges);
          for (let e = 0; e < g.edgeIds.length; e++) if (want.has(g.edgeIds[e])) edges.push(e);
        }
        hlNodes = Int32Array.from(nodes);
        hlNodeFlag = new Uint8Array(g.n);
        for (const i of nodes) hlNodeFlag[i] = 1;
        hlEdges = Int32Array.from(edges);
      }
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
