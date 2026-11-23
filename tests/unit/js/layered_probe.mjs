// layout="layered" (IND-264): a node sits one layer below its deepest parent, a cycle is broken
// instead of looping, and the result is deterministic.
import { layeredPositions } from "../../../frontend/graph/layout.js";

const input = JSON.parse(await new Promise((resolve) => {
  let text = "";
  process.stdin.on("data", (c) => (text += c)).on("end", () => resolve(text));
}));
const idx = new Map(input.ids.map((id, i) => [id, i]));
const s = Int32Array.from(input.edges, ([a]) => idx.get(a));
const t = Int32Array.from(input.edges, ([, b]) => idx.get(b));
const run = () => layeredPositions(input.ids.length, s, t);
const p = run();
const q = run();
const same = Array.from(p.x).every((v, i) => v === q.x[i]) && Array.from(p.y).every((v, i) => v === q.y[i]);
console.log(JSON.stringify({
  y: Object.fromEntries(input.ids.map((id, i) => [id, p.y[i]])),
  x: Object.fromEntries(input.ids.map((id, i) => [id, p.x[i]])),
  deterministic: same,
}));
