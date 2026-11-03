// Force layout for the Graph component (ADR-0048). Pure functions, no DOM, so it runs under Node
// for tests and for the settle-time measurement. The shape follows d3-force's defaults (charge,
// link and centring forces, a cooling alpha) with a Barnes-Hut quadtree for the charge, so a
// step is about O(n log n). Positions start clustered by group on a seeded spiral, so the same
// graph always lays out the same way.

export const LAYOUT_LIMIT = 8000; // above this many nodes the clustered start is used as is
const LINK_DISTANCE = 30;
const CHARGE = -30;
const THETA2 = 1.44; // Barnes-Hut opening angle 1.2, squared: coarse is fine for a picture
const VELOCITY_DECAY = 0.6;
const ALPHA_MIN = 0.001;
const MAX_DEPTH = 40;
// Steps to settle: 300 up to 1,000 nodes, fewer beyond that so a big graph settles in about the
// same wall time (the clustered start already puts nodes near their place).
export function stepsFor(n) {
  return n <= 1000 ? 300 : Math.max(100, Math.round(300 * Math.sqrt(1000 / n)));
}
// How far apart group centres sit, as a multiple of the base spacing. Tight enough that groups which
// are heavily linked to each other stay in one picture, wide enough that they stay distinct: measured
// over eight seeds on cross-linked graphs, 0.64 keeps the centres further apart than a group is wide
// (separation above 1), and 0.5 does not (IND-250).
const GROUP_SPACING = 0.64;
// Nodes with no or one edge feel only repulsion and the group pull, so they drift far out and shrink
// the picture. A stronger pull for them keeps the core readable (IND-250).
const PULL_ISOLATED = 8;
const PULL_LEAF = 3;
const GOLDEN = 2.399963229728653;

export function hashString(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Group-clustered start: each group gets a centre on a spiral and its nodes a disc around it.
// `group` is an Int32Array of group indexes (0 for an ungrouped graph).
export function initialPositions(n, group, nGroups, seed) {
  const rand = mulberry32(seed);
  const size = new Int32Array(nGroups);
  for (let i = 0; i < n; i++) size[group[i]]++;
  const gx = new Float64Array(nGroups);
  const gy = new Float64Array(nGroups);
  const base = LINK_DISTANCE * Math.sqrt(n / nGroups) * 1.2;
  for (let g = 0; g < nGroups && nGroups > 1; g++) {
    const r = base * Math.sqrt(g + 0.5) * GROUP_SPACING;
    gx[g] = r * Math.cos(g * GOLDEN);
    gy[g] = r * Math.sin(g * GOLDEN);
  }
  const x = new Float64Array(n);
  const y = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const g = group[i];
    const radius = LINK_DISTANCE * Math.sqrt(size[g]) * 0.7;
    const r = radius * Math.sqrt(rand());
    const a = rand() * Math.PI * 2;
    x[i] = gx[g] + r * Math.cos(a);
    y[i] = gy[g] + r * Math.sin(a);
  }
  return { x, y, gx, gy };
}

// A Barnes-Hut quadtree in typed arrays, rebuilt every step without allocating objects.
class Tree {
  constructor(n) {
    this.cap = Math.max(32, 4 * n + 8);
    this.alloc(this.cap);
    this.cnt = 0;
  }
  alloc(cap) {
    const grow = (Old, len, mult = 1) => {
      const next = new Old.constructor(len * mult);
      if (this.cx) next.set(Old.subarray(0, Math.min(Old.length, next.length)));
      return next;
    };
    const first = !this.cx;
    const seed = (Type, mult = 1) => new Type(cap * mult);
    this.cx = first ? seed(Float64Array) : grow(this.cx, cap);
    this.cy = first ? seed(Float64Array) : grow(this.cy, cap);
    this.hs = first ? seed(Float64Array) : grow(this.hs, cap);
    this.sx = first ? seed(Float64Array) : grow(this.sx, cap);
    this.sy = first ? seed(Float64Array) : grow(this.sy, cap);
    this.mass = first ? seed(Int32Array) : grow(this.mass, cap);
    this.leaf = first ? seed(Int32Array) : grow(this.leaf, cap);
    this.kids = first ? seed(Uint8Array) : grow(this.kids, cap);
    this.ch = first ? seed(Int32Array, 4) : grow(this.ch, cap, 4);
    this.cap = cap;
  }
  init(c, cx, cy, hs) {
    this.cx[c] = cx;
    this.cy[c] = cy;
    this.hs[c] = hs;
    this.mass[c] = 0;
    this.sx[c] = 0;
    this.sy[c] = 0;
    this.leaf[c] = -1;
    this.kids[c] = 0;
    this.ch.fill(-1, 4 * c, 4 * c + 4);
  }
  child(c, q) {
    if (this.cnt >= this.cap) this.alloc(this.cap * 2);
    const d = this.cnt++;
    const h = this.hs[c] / 2;
    this.init(d, this.cx[c] + (q & 1 ? h : -h), this.cy[c] + (q & 2 ? h : -h), h);
    this.ch[4 * c + q] = d;
    this.kids[c]++;
    return d;
  }
  build(X, Y, n) {
    let minx = Infinity;
    let miny = Infinity;
    let maxx = -Infinity;
    let maxy = -Infinity;
    for (let i = 0; i < n; i++) {
      if (X[i] < minx) minx = X[i];
      if (X[i] > maxx) maxx = X[i];
      if (Y[i] < miny) miny = Y[i];
      if (Y[i] > maxy) maxy = Y[i];
    }
    const size = Math.max(maxx - minx, maxy - miny, 1);
    this.cnt = 1;
    this.init(0, (minx + maxx) / 2, (miny + maxy) / 2, size / 2 + 1e-6);
    for (let i = 0; i < n; i++) this.insert(i, X, Y);
    for (let c = 0; c < this.cnt; c++) {
      const w = this.mass[c];
      this.sx[c] = w ? this.sx[c] / w : 0; // from here on sx, sy hold the centre of mass
      this.sy[c] = w ? this.sy[c] / w : 0;
    }
  }
  insert(i, X, Y) {
    const { cx, cy, mass, sx, sy, leaf, kids, ch } = this;
    let c = 0;
    let depth = 0;
    for (;;) {
      mass[c]++;
      sx[c] += X[i];
      sy[c] += Y[i];
      if (kids[c] === 0) {
        const j = leaf[c];
        if (j < 0) {
          leaf[c] = i;
          return;
        }
        // Coincident or too deep: the cell stays an aggregate leaf.
        if (depth >= MAX_DEPTH || (X[j] === X[i] && Y[j] === Y[i])) return;
        leaf[c] = -1;
        const d = this.child(c, (X[j] >= cx[c] ? 1 : 0) + (Y[j] >= cy[c] ? 2 : 0));
        this.mass[d] = 1;
        this.sx[d] = X[j];
        this.sy[d] = Y[j];
        this.leaf[d] = j;
      }
      const q = (X[i] >= this.cx[c] ? 1 : 0) + (Y[i] >= this.cy[c] ? 2 : 0);
      let d = this.ch[4 * c + q];
      if (d < 0) {
        d = this.child(c, q);
        this.mass[d] = 1;
        this.sx[d] = X[i];
        this.sy[d] = Y[i];
        this.leaf[d] = i;
        return;
      }
      c = d;
      depth++;
    }
  }
}

// A simulation over `n` nodes. `s` and `t` are edge endpoint indexes (Int32Array), `group` the
// per-node group index. Call step() until `done`. With more than LAYOUT_LIMIT nodes it is done
// at once and the clustered start is the layout.
export function createSimulation({ n, s, t, group, nGroups, seed, given }) {
  const start = given ?? initialPositions(n, group, nGroups, seed);
  const x = start.x;
  const y = start.y;
  const vx = new Float64Array(n);
  const vy = new Float64Array(n);
  const m = s.length;
  const deg = new Int32Array(n);
  for (let e = 0; e < m; e++) {
    deg[s[e]]++;
    deg[t[e]]++;
  }
  const strength = new Float64Array(m);
  const bias = new Float64Array(m);
  for (let e = 0; e < m; e++) {
    strength[e] = 1 / Math.max(1, Math.min(deg[s[e]], deg[t[e]]));
    bias[e] = deg[s[e]] / Math.max(1, deg[s[e]] + deg[t[e]]);
  }
  const maxSteps = stepsFor(n);
  const alphaDecay = 1 - Math.pow(ALPHA_MIN, 1 / maxSteps);
  const tree = new Tree(n);
  const stack = new Int32Array(4 * MAX_DEPTH + 16);
  const sim = {
    x,
    y,
    n,
    alpha: 1,
    iterations: 0,
    done: given != null || n > LAYOUT_LIMIT || n < 2,
    gx: start.gx,
    gy: start.gy,
    step() {
      if (sim.done) return;
      sim.alpha += (0 - sim.alpha) * alphaDecay;
      const a = sim.alpha;
      // Charge: every node is pushed away from the Barnes-Hut aggregate of the others.
      tree.build(x, y, n);
      const { sx, sy, mass, leaf, kids, ch, hs } = tree;
      for (let i = 0; i < n; i++) {
        const xi = x[i];
        const yi = y[i];
        let sp = 0;
        stack[sp++] = 0;
        while (sp > 0) {
          const c = stack[--sp];
          const w = mass[c];
          if (w === 0) continue;
          const dx = sx[c] - xi;
          const dy = sy[c] - yi;
          let d2 = dx * dx + dy * dy;
          if (kids[c] === 0) {
            if (w === 1 && leaf[c] === i) continue;
          } else if (4 * hs[c] * hs[c] >= THETA2 * d2) {
            for (let q = 0; q < 4; q++) if (ch[4 * c + q] >= 0) stack[sp++] = ch[4 * c + q];
            continue;
          }
          if (d2 < 1) d2 = 1;
          const k = (CHARGE * a * w) / d2;
          vx[i] += dx * k;
          vy[i] += dy * k;
        }
      }
      // Links: springs along edges, biased toward the less connected end.
      for (let e = 0; e < m; e++) {
        const si = s[e];
        const ti = t[e];
        let dx = x[ti] + vx[ti] - x[si] - vx[si];
        let dy = y[ti] + vy[ti] - y[si] - vy[si];
        let l = Math.sqrt(dx * dx + dy * dy) || 1;
        l = ((l - LINK_DISTANCE) / l) * a * strength[e];
        dx *= l;
        dy *= l;
        vx[ti] -= dx * bias[e];
        vy[ti] -= dy * bias[e];
        vx[si] += dx * (1 - bias[e]);
        vy[si] += dy * (1 - bias[e]);
      }
      // A weak pull to each node's group centre keeps groups together and the graph centred.
      const pull = nGroups > 1 ? 0.05 : 0.03;
      for (let i = 0; i < n; i++) {
        const k = pull * (deg[i] === 0 ? PULL_ISOLATED : deg[i] === 1 ? PULL_LEAF : 1) * a;
        vx[i] += (sim.gx[group[i]] - x[i]) * k;
        vy[i] += (sim.gy[group[i]] - y[i]) * k;
      }
      for (let i = 0; i < n; i++) {
        x[i] += vx[i] *= VELOCITY_DECAY;
        y[i] += vy[i] *= VELOCITY_DECAY;
      }
      sim.iterations++;
      if (sim.alpha < ALPHA_MIN || sim.iterations >= maxSteps) sim.done = true;
    },
  };
  return sim;
}

// Step until the time budget is used or the simulation is done; always at least one step.
export function run(sim, budgetMs, now = () => performance.now()) {
  const t0 = now();
  let steps = 0;
  do {
    if (sim.done) break;
    sim.step();
    steps++;
  } while (now() - t0 < budgetMs);
  return steps;
}

// The box to fit the view to. With 100 or more nodes it trims the outermost 1% on each side, so a
// few stray nodes (an isolated one drifts far from the rest) do not shrink the picture; they stay
// reachable by panning.
export function bounds(x, y, n) {
  if (n === 0) return { minx: 0, miny: 0, maxx: 1, maxy: 1 };
  if (n < 100) return extent(x, y, n);
  const xs = Float64Array.from(x.subarray(0, n)).sort();
  const ys = Float64Array.from(y.subarray(0, n)).sort();
  const lo = Math.floor(n * 0.01);
  const hi = n - 1 - lo;
  return { minx: xs[lo], miny: ys[lo], maxx: xs[hi], maxy: ys[hi] };
}

function extent(x, y, n) {
  let minx = Infinity;
  let miny = Infinity;
  let maxx = -Infinity;
  let maxy = -Infinity;
  for (let i = 0; i < n; i++) {
    if (x[i] < minx) minx = x[i];
    if (x[i] > maxx) maxx = x[i];
    if (y[i] < miny) miny = y[i];
    if (y[i] > maxy) maxy = y[i];
  }
  return { minx, miny, maxx, maxy };
}
