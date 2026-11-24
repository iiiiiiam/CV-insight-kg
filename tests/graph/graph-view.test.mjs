import fs from "node:fs";
import assert from "node:assert/strict";
const code = fs.readFileSync("src/graph_query/graph-view.js");
const { selectVisible, layout, expansion, loadExpansion, latestExpansion } =
  await import("data:text/javascript;base64," + code.toString("base64"));
const data = {
  nodes: Array.from({ length: 100 }, (_, i) => ({
    id: String(i),
    kind: i % 2 ? "author" : "paper",
  })),
  edges: Array.from({ length: 99 }, (_, i) => ({
    source: "0",
    target: String(i + 1),
    kind: "has_author",
  })),
};
const v = selectVisible(data, "99");
assert.equal(v.nodes.length, 60);
assert.ok(v.nodes.some((n) => n.id === "99"));
assert.equal(v.limited, true);
assert.ok(
  v.edges.every(
    (e) =>
      v.nodes.some((n) => n.id === e.source) &&
      v.nodes.some((n) => n.id === e.target),
  ),
);
const filtered = selectVisible(data, "0", new Set(["author"]));
assert.ok(filtered.nodes.every((n) => n.kind === "paper"));
assert.equal(filtered.edges.length, 49);
const pos = layout(v.nodes, v.edges);
assert.equal(pos.size, 60);
assert.ok(
  [...pos.values()].every((p) => Number.isFinite(p.x) && Number.isFinite(p.y)),
);
assert.deepEqual(selectVisible({ nodes: [], edges: [] }, "x").nodes, []);
assert.equal(layout([{ id: "solo" }], []).size, 1);
console.log("graph-view: 7 layout/filter/limit/empty checks passed");

const one = {
  batch_id: "b",
  nodes: [
    { id: "a", kind: "paper" },
    { id: "b", kind: "author" },
  ],
  edges: [{ id: "ab", source: "a", target: "b", kind: "has_author" }],
  truncated: false,
};
const two = {
  ...one,
  nodes: [...one.nodes, { id: "c", kind: "institution" }],
  edges: [
    ...one.edges,
    { id: "bc", source: "b", target: "c", kind: "affiliated_with" },
  ],
};
const ex = expansion(one, two, "a");
assert.deepEqual(ex.addedNodes, ["c"]);
assert.deepEqual(ex.addedEdges, ["bc"]);
assert.equal(ex.nodes.find((n) => n.id === "c").hop, 2);
assert.equal(ex.edges.find((e) => e.id === "bc").source, "b");
const none = expansion(one, one, "a");
assert.equal(none.addedNodes.length, 0);
assert.equal(none.addedEdges.length, 0);
const calls = [];
const load = async (p) => {
  calls.push(p);
  return p.hops === 1 ? one : two;
};
const twice = await loadExpansion(load, {
  seed: "a",
  batch_id: "b",
  hops: 2,
  limit: 60,
});
const again = await loadExpansion(load, {
  seed: "a",
  batch_id: "b",
  hops: 2,
  limit: 60,
});
assert.equal(twice.nodes.length, 3);
assert.equal(again.nodes.length, 3);
assert.deepEqual(
  calls.map((p) => p.hops),
  [1, 2, 1, 2],
);
const capped = selectVisible(ex, "a", new Set(), 2);
assert.equal(capped.nodes.length, 2);
assert.equal(capped.limited, true);
assert.ok(capped.nodes.every((n) => n.hop !== 2));
await assert.rejects(
  loadExpansion(
    async (p) => (p.hops === 1 ? one : { ...two, batch_id: "wrong" }),
    { hops: 2, seed: "a" },
  ),
);
console.log(
  "hop regression: extension, no addition, identity/direction, cap, repeated requests and batch mismatch passed",
);

const pending = [];
const latest = latestExpansion(
  (p) => new Promise((resolve) => pending.push(resolve)),
);
const older = latest.run({ hops: 1, seed: "a" }),
  newer = latest.run({ hops: 1, seed: "a" });
pending[1](one);
assert.ok(await newer);
pending[0](two);
assert.equal(await older, null);
console.log("repeated-click race: older response cannot replace latest graph");
