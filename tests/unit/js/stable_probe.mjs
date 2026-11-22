// A stable layout (ADR-0053): each node's start comes from its own id, so a different group
// assignment or a different node order gives the same position for the same id.
import { createSimulation, run, hashString } from "../../../frontend/graph/layout.js";

const input = JSON.parse(await new Promise((resolve) => {
  let text = "";
  process.stdin.on("data", (c) => (text += c)).on("end", () => resolve(text));
}));
const ids = input.ids;
const edges = input.edges; // pairs of ids

function settle(order, groupOf) {
  const idx = new Map(order.map((id, i) => [id, i]));
  const sim = createSimulation({
    n: order.length,
    s: Int32Array.from(edges, ([a]) => idx.get(a)),
    t: Int32Array.from(edges, ([, b]) => idx.get(b)),
    group: Int32Array.from(order, groupOf),
    nGroups: 3,
    seed: 1,
    idSeeds: Uint32Array.from(order, hashString),
  });
  const start = Object.fromEntries(order.map((id, i) => [id, [sim.x[i], sim.y[i]]]));
  while (!sim.done) run(sim, 50);
  const end = Object.fromEntries(order.map((id, i) => [id, [sim.x[i], sim.y[i]]]));
  return { start, end };
}
const a = settle(ids, (_, i) => i % 3);
const b = settle(ids, (_, i) => (i + 1) % 3);
const c = settle([...ids].reverse(), () => 0);
const maxDiff = (p, q) => Math.max(...ids.flatMap((id) => [Math.abs(p[id][0] - q[id][0]), Math.abs(p[id][1] - q[id][1])]));
console.log(JSON.stringify({
  startGroup: maxDiff(a.start, b.start),
  startOrder: maxDiff(a.start, c.start),
  endGroup: maxDiff(a.end, b.end),
}));
