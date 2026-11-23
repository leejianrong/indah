// update="keep" (ADR-0053): ids already placed keep their exact position; a new id lands near
// the mean of its placed neighbours, and a new id with none lands at the centre of the old ones.
import { keepPositions } from "../../../frontend/graph/layout.js";

const input = JSON.parse(await new Promise((resolve) => {
  let text = "";
  process.stdin.on("data", (c) => (text += c)).on("end", () => resolve(text));
}));
const idx = new Map(input.ids.map((id, i) => [id, i]));
const prev = new Map(input.prev.map(([id, x, y]) => [id, [x, y]]));
const p = keepPositions(prev, input.ids, Int32Array.from(input.edges, ([a]) => idx.get(a)), Int32Array.from(input.edges, ([, b]) => idx.get(b)));
const at = (id) => [p.x[idx.get(id)], p.y[idx.get(id)]];
console.log(JSON.stringify({ pos: Object.fromEntries(input.ids.map((id) => [id, at(id)])), isNew: Array.from(p.fresh) }));
