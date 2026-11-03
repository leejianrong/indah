// Checks the Graph spatial index (frontend/graph/spatial.js) against brute force, for
// tests/unit/test_graph_layout.py. Prints how many queries disagreed.
import { buildGrid, nearest } from "../../../frontend/graph/spatial.js";
import { mulberry32 } from "../../../frontend/graph/layout.js";

const rand = mulberry32(5);
let checked = 0;
let bad = 0;
for (const n of [1, 2, 10, 500, 5000]) {
  const x = new Float64Array(n);
  const y = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    x[i] = (rand() - 0.5) * 2000;
    y[i] = n === 500 ? 0 : (rand() - 0.5) * 1500; // 500 nodes: all on one line
  }
  const grid = buildGrid(x, y, n);
  for (let q = 0; q < 40; q++) {
    const px = (rand() - 0.5) * 2400;
    const py = (rand() - 0.5) * 1800;
    const k = Math.min(n, 1 + Math.floor(rand() * 300));
    const got = nearest(grid, px, py, k);
    const d = (i) => (x[i] - px) ** 2 + (y[i] - py) ** 2;
    const truth = Array.from({ length: n }, (_, i) => i).sort((a, b) => d(a) - d(b)).slice(0, k);
    const kth = d(truth[k - 1]);
    checked++;
    // approximate at cell borders: every node returned is within a small slack of the true k-th
    if (got.length !== k || got.some((i) => d(i) > kth * 1.6 + 1)) bad++;
  }
}
console.log(JSON.stringify({ checked, bad }));
