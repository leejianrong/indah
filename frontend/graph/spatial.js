// A uniform grid over node positions, for the Graph focus window (ADR-0048): "the N nodes
// nearest this point" without scanning every node, and a hit test for a click. Pure, no DOM, so it
// runs under Node for tests. Built once per layout in O(n) by a counting sort.

export function buildGrid(x, y, n) {
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
  if (n === 0) minx = miny = maxx = maxy = 0;
  const bw = Math.max(maxx - minx, 1e-6);
  const bh = Math.max(maxy - miny, 1e-6);
  // About four nodes per cell; a thin graph (all on a line) still gets a sane cell size.
  let cell = Math.max(Math.sqrt((bw * bh) / Math.max(1, n)) * 2, Math.max(bw, bh) / (2 * Math.sqrt(Math.max(1, n))));
  let gw = Math.floor(bw / cell) + 1;
  let gh = Math.floor(bh / cell) + 1;
  while (gw * gh > 4 * n + 64) {
    cell *= 1.5;
    gw = Math.floor(bw / cell) + 1;
    gh = Math.floor(bh / cell) + 1;
  }
  const cells = gw * gh;
  const start = new Int32Array(cells + 1);
  const of = new Int32Array(n);
  for (let i = 0; i < n; i++) {
    const c = Math.floor((y[i] - miny) / cell) * gw + Math.floor((x[i] - minx) / cell);
    of[i] = c;
    start[c + 1]++;
  }
  for (let c = 0; c < cells; c++) start[c + 1] += start[c];
  const fill = start.slice(0, cells);
  const items = new Int32Array(n);
  for (let i = 0; i < n; i++) items[fill[of[i]]++] = i;
  return { x, y, n, minx, miny, cell, gw, gh, start, items };
}

// The k nodes nearest (px, py), nearest first. Rings of cells are added until k candidates are
// found, plus one more ring so a node just across a cell border is not missed.
export function nearest(grid, px, py, k) {
  const { x, y, n, minx, miny, cell, gw, gh, start, items } = grid;
  if (n === 0 || k <= 0) return new Int32Array(0);
  const cx = Math.min(gw - 1, Math.max(0, Math.floor((px - minx) / cell)));
  const cy = Math.min(gh - 1, Math.max(0, Math.floor((py - miny) / cell)));
  const want = Math.min(k, n);
  const found = [];
  let stop = -1;
  const reach = Math.max(gw, gh);
  for (let r = 0; r <= reach; r++) {
    for (let yy = Math.max(0, cy - r); yy <= Math.min(gh - 1, cy + r); yy++) {
      const edgeRow = yy === cy - r || yy === cy + r;
      const step = edgeRow || r === 0 ? 1 : 2 * r;
      for (let xx = cx - r; xx <= cx + r; xx += step) {
        if (xx < 0 || xx >= gw) continue;
        const c = yy * gw + xx;
        for (let j = start[c]; j < start[c + 1]; j++) found.push(items[j]);
      }
    }
    if (found.length >= want && stop < 0) stop = r + 1;
    if (stop >= 0 && r >= stop) break;
  }
  const d2 = (i) => (x[i] - px) * (x[i] - px) + (y[i] - py) * (y[i] - py);
  found.sort((a, b) => d2(a) - d2(b));
  return Int32Array.from(found.slice(0, want));
}
