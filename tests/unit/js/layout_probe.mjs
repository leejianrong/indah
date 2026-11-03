// Runs the Graph layout (frontend/graph/layout.js) on a graph read from stdin and prints measurements
// as JSON, for tests/unit/test_graph_layout.py. No DOM, so it runs under plain Node.
import { createSimulation, run, bounds, stepsFor, hashString } from "../../../frontend/graph/layout.js";

const input = JSON.parse(await new Promise((resolve) => {
  let text = "";
  process.stdin.on("data", (c) => (text += c)).on("end", () => resolve(text));
}));
const n = input.n;
const group = Int32Array.from(input.group);
const make = () =>
  createSimulation({
    n,
    s: Int32Array.from(input.s),
    t: Int32Array.from(input.t),
    group,
    nGroups: Math.max(...input.group) + 1,
    seed: hashString(input.seed ?? "probe"),
  });
const settle = () => {
  const sim = make();
  while (!sim.done) run(sim, 50);
  return sim;
};
const sim = settle();
const { x, y } = sim;
const quantile = (a, p) => Float64Array.from(a).sort()[Math.floor(p * (n - 1))];
const fit = bounds(x, y, n);
const fitW = fit.maxx - fit.minx;
const fitH = fit.maxy - fit.miny;
const coreW = quantile(x, 0.85) - quantile(x, 0.15);
const coreH = quantile(y, 0.85) - quantile(y, 0.15);
const G = Math.max(...input.group) + 1;
const cx = new Float64Array(G);
const cy = new Float64Array(G);
const count = new Float64Array(G);
for (let i = 0; i < n; i++) {
  cx[group[i]] += x[i];
  cy[group[i]] += y[i];
  count[group[i]]++;
}
for (let g = 0; g < G; g++) {
  cx[g] /= count[g];
  cy[g] /= count[g];
}
let spread = 0;
for (let i = 0; i < n; i++) spread += Math.hypot(x[i] - cx[group[i]], y[i] - cy[group[i]]);
spread /= n;
let apart = 0;
let pairs = 0;
for (let a = 0; a < G; a++)
  for (let b = a + 1; b < G; b++) {
    apart += Math.hypot(cx[a] - cx[b], cy[a] - cy[b]);
    pairs++;
  }
apart /= pairs;
const again = settle();
console.log(
  JSON.stringify({
    steps: sim.iterations,
    expectedSteps: stepsFor(n),
    finite: Array.from(x).every(Number.isFinite) && Array.from(y).every(Number.isFinite),
    coreFill: (coreW * coreH) / (fitW * fitH),
    groupSeparation: apart / spread,
    deterministic: Array.from(x.slice(0, 20)).join() === Array.from(again.x.slice(0, 20)).join(),
  }),
);
