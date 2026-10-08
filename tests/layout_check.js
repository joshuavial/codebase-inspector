const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.resolve(__dirname, "..");

function load(rel, extras) {
  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    structuredClone,
    ELK: function () { this.layout = async () => ({}); },
    document: {
      createElement() {
        return { getContext() { return { measureText: (s) => ({ width: String(s).length * 7 }) }; } };
      },
      createElementNS() {
        return { setAttribute() {}, append() {}, classList: { add() {} } };
      },
      getElementById() { return null; },
      querySelectorAll() { return []; },
    },
    location: { href: "http://local/", hash: "", search: "" },
    history: { replaceState() {}, state: null },
    addEventListener() {},
  };
  Object.assign(sandbox, extras || {});
  sandbox.window = sandbox.window || {
    addEventListener() {},
    cbiLoad() {},
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(root, rel), "utf8"), sandbox, { filename: rel });
  return sandbox;
}

function hits(a, b) {
  return a.x < b.x + (b.w || b.width) + 3 && a.x + a.width + 3 > b.x
    && a.y < b.y + (b.h || b.height) + 3 && a.y + a.height + 3 > b.y;
}

async function main() {
  const app = load("src/cbi/viewer/app.js");
  assert.strictEqual(
    app.edgeLabelText(["reads snapshot over IPC", "opens the window for"]),
    "reads snapshot over IPC +1",
  );
  assert.strictEqual(app.edgeLabelText(["reads", "reads"]), "reads");
  assert.strictEqual(app.edgeLabelText(["reads", "writes", "watches"]), "reads +2");
  assert.strictEqual(app.statedClass(true, true), "stated quiet");
  assert.strictEqual(app.statedClass(true, false), "stated");
  assert.strictEqual(app.statedClass(false, true), "");
  const mixed = app.joinEdgeClass(
    { cls: "stated quiet", rels: [{ backing: "stated" }] },
    { cls: "", rels: [{ backing: "calls" }] },
  );
  assert.ok(!mixed.split(" ").includes("stated"));
  assert.ok(!mixed.split(" ").includes("quiet"));

  const shown = new Set(["desktop", "ui"]);
  const merged = app.mergePairEdges([
    {
      id: "e0", a: "ui", b: "desktop", text: "reads snapshot over IPC", via: "IPC",
      title: "reads snapshot over IPC", cls: "", rels: [{ kind: "relates" }],
    },
    {
      id: "e1", a: "desktop", b: "ui", text: "opens the window for",
      title: "opens the window for", cls: "", rels: [{ kind: "hosts" }],
    },
  ], shown);
  assert.strictEqual(merged.length, 1);
  assert.strictEqual(merged[0].a, "desktop");
  assert.strictEqual(merged[0].b, "ui");
  assert.strictEqual(merged[0].text, "reads snapshot over IPC +1");
  assert.strictEqual(merged[0].count, 2);
  assert.ok(merged[0].cls.split(" ").includes("both"));
  const quietPair = app.mergePairEdges([
    { id: "q0", a: "x", b: "y", text: "one", title: "one", cls: "stated quiet", rels: [{ backing: "stated" }] },
    { id: "q1", a: "y", b: "x", text: "two", title: "two", cls: "stated quiet", rels: [{ backing: "stated" }] },
  ], new Set(["x", "y"]));
  assert.strictEqual(quietPair.length, 1);
  assert.strictEqual(quietPair[0].count, 2);
  assert.ok(quietPair[0].cls.split(" ").includes("stated"));
  assert.ok(quietPair[0].cls.split(" ").includes("quiet"));

  const pts = [{ x: 90, y: 40 }, { x: 90, y: 400 }];
  const a = { x: 100, y: 100, width: 90, height: 24, pts: pts.slice() };
  const b = { x: 104, y: 108, width: 90, height: 24, pts: pts.slice() };
  const box = { x: 96, y: 96, w: 100, h: 50 };
  app.separateLabels([a, b], [box]);
  assert.ok(!hits(a, b), `labels still overlap ${JSON.stringify(a)} ${JSON.stringify(b)}`);
  assert.ok(!app.obstacleHits(a, box), `label hits box ${JSON.stringify(a)}`);
  assert.ok(!app.obstacleHits(b, box), `label hits box ${JSON.stringify(b)}`);

  const free = { x: 10, y: 10, width: 40, height: 16, pts: [{ x: 0, y: 0 }, { x: 200, y: 0 }] };
  app.separateLabels([free], []);
  assert.strictEqual(free.x, 10);
  assert.strictEqual(free.y, 10);

  const inner = { x: 40, y: 50, width: 80, height: 20, pts: [{ x: 30, y: 0 }, { x: 30, y: 280 }] };
  const boundary = { x: 0, y: 0, w: 400, h: 300, container: true };
  app.separateLabels([inner], [boundary]);
  assert.strictEqual(inner.x, 40);
  assert.strictEqual(inner.y, 50);

  const title = { x: 40, y: 4, width: 60, height: 20, pts: [{ x: 30, y: 0 }, { x: 30, y: 280 }] };
  app.separateLabels([title], [boundary]);
  assert.ok(title.y >= 32, `title-band label stayed at ${title.y}`);
  assert.ok(!app.obstacleHits(title, boundary));

  const host = {
    x: 0, y: 0, width: 120, height: 20, a: "desktop", b: "ui",
    text: "opens the window for", rels: [{ kind: "hosts" }],
    meta: { text: "opens the window for", rels: [{ kind: "hosts" }] },
  };
  const back = {
    x: 8, y: 0, width: 140, height: 20, a: "ui", b: "desktop",
    text: "reads snapshot over IPC", rels: [],
    meta: { text: "reads snapshot over IPC", rels: [] },
  };
  assert.strictEqual(app.collapseStackedPairs([host, back]), true);
  assert.strictEqual(host.text, "reads snapshot over IPC +1");
  assert.strictEqual(host.meta.text, host.text);
  assert.strictEqual(back.drop, true);

  const render = load("src/cbi/viewer/render.js");
  const frame = render.keyFrame({ x: 10, y: 20, width: 400, height: 300 }, 220, 26);
  const [vx, vy, vw, vh] = frame.viewBox.split(" ").map(Number);
  const key = frame.key;
  assert.ok(key.x >= vx + 16, "key left margin");
  assert.ok(key.y + key.height <= vy + vh - 16, "key bottom margin");
  assert.ok(key.x + key.width <= vx + vw - 16, "key right margin");
  assert.ok(key.y >= 20 + 300, "key is below the camera");
  const wide = render.keyFrame({ x: 0, y: 0, width: 40, height: 40 }, 300, 26);
  assert.ok(wide.key.x + wide.key.width <= wide.x + wide.width - 16);

  const ELK = require(path.join(root, "src/cbi/viewer/vendor/elk.bundled.js"));
  const elk = new ELK();
  const graph = await elk.layout({
    id: "root",
    layoutOptions: app.elkOptions({ dir: "RIGHT", layer: 30, gap: 24 }),
    children: [
      { id: "a", width: 120, height: 48 },
      { id: "b", width: 120, height: 48 },
      { id: "c", width: 120, height: 48 },
    ],
    edges: [
      { id: "e1", sources: ["a"], targets: ["b"], labels: [{ text: "reads snapshot over IPC", width: 140, height: 16 }] },
      { id: "e2", sources: ["a"], targets: ["c"], labels: [{ text: "fetches snapshot from", width: 120, height: 16 }] },
    ],
  });
  assert.strictEqual(graph.edges.length, 2);
  for (const edge of graph.edges) assert.ok(edge.labels && edge.labels[0], "ELK placed a label");

  assert.strictEqual(app.sideRanks({ x: 10, y: 100 }, 400, 300)[0].side, "left");
  assert.strictEqual(app.sideRanks({ x: 380, y: 100 }, 400, 300)[0].side, "right");
  assert.strictEqual(app.sideRanks({ x: 200, y: 10 }, 400, 300)[0].side, "above");
  assert.strictEqual(app.sideRanks({ x: 200, y: 280 }, 400, 300)[0].side, "below");
  assert.strictEqual(app.sideRanks({ x: 0, y: 0 }, 100, 100)[0].side, "above");

  const ids = ["a", "b", "c", "d", "e", "f"];
  const meta = {
    a: { kind: "cli", callers: ["core"] },
    b: { kind: "cli", callers: ["core"] },
    c: { kind: "storage", callers: ["core"] },
    d: { kind: "storage", callers: ["core"] },
    e: { kind: "saas", callers: ["core"] },
    f: { kind: "terminal", callers: ["core"] },
  };
  const grouped = app.groupExternals(ids, meta);
  assert.strictEqual(grouped.length, 4);
  assert.strictEqual(grouped[0].members.join(","), "a,b");
  assert.strictEqual(grouped[0].id, "xg:cli:core");
  assert.ok(grouped[0].grouped);
  assert.ok(app.groupExternals(ids.slice(0, 5), meta).every((g) => !g.grouped));
  const split = app.groupExternals(ids, {
    ...meta,
    b: { kind: "cli", callers: ["other"] },
  });
  assert.ok(!split.some((g) => g.grouped && g.members.includes("a") && g.members.includes("b")));
  const twoCallers = app.groupExternals(ids, {
    ...meta,
    a: { kind: "cli", callers: ["core", "service"] },
  });
  assert.ok(!twoCallers.some((g) => g.grouped && g.members.includes("a")));

  const inside = app.routeInside({ x: 0, y: 0, width: 40, height: 20 }, { x: 100, y: 80, width: 40, height: 20 });
  assert.strictEqual(inside[0].x, 40);
  assert.strictEqual(inside[0].y, 10);
  for (const p of inside) {
    assert.ok(p.x >= 0 && p.x <= 140 && p.y >= 0 && p.y <= 100, JSON.stringify(p));
  }
  assert.strictEqual(app.hugsFrame([{ x: 10, y: 10 }, { x: 10, y: 0 }, { x: 200, y: 0 }, { x: 200, y: 150 }], 200, 160), true);
  assert.strictEqual(app.hugsFrame([{ x: 20, y: 40 }, { x: 80, y: 40 }, { x: 80, y: 90 }], 200, 160), false);

  // A wide inner graph (MULTI_EDGE 0.8, 1137×861). A run longer than 48px
  // within 24px of the border is a frame route. An end that misses its box is redrawn.
  const iw = 1137, ih = 861;
  const obox = {
    contracts: { x: 255, y: 692, width: 200, height: 94 },
    desktop: { x: 255, y: 474, width: 307, height: 94 },
    tooling: { x: 286.5, y: 166, width: 244, height: 94 },
    core: { x: 805, y: 273, width: 244, height: 94 },
    mobile: { x: 277, y: 320, width: 263, height: 94 },
    service: { x: 255, y: 12, width: 307, height: 94 },
  };
  const olist = Object.values(obox);
  const gaps = app.columnGaps(olist);
  assert.strictEqual(gaps.length, 1);
  assert.ok(Math.abs(gaps[0] - 683.5) < 0.01, `gap ${gaps[0]}`);
  assert.strictEqual(app.frameRun([{ x: 12, y: 594 }, { x: 12, y: 802 }], iw, ih), true);
  assert.strictEqual(app.frameRun([{ x: 1115, y: 59 }, { x: 1115, y: 638 }], iw, ih), true);
  assert.strictEqual(app.frameRun([{ x: 12, y: 100 }, { x: 12, y: 140 }], iw, ih), false);
  assert.strictEqual(app.frameRun([{ x: 40, y: 100 }, { x: 40, y: 400 }], iw, ih), false);
  assert.strictEqual(app.frameRun([{ x: 1105, y: 320 }, { x: 1105, y: 627 }], iw, ih), false);
  const line = (pts) => pts.map(([x, y]) => ({ x, y }));
  const raw = {
    e1: ["core", "contracts", [[1049, 320], [1105, 320], [1105, 627], [42, 627], [42, 709], [219, 709], [219, 730], [255, 730]]],
    e7: ["mobile", "contracts", [[540, 383], [1079, 383]]],
    e8: ["mobile", "core", [[540, 351], [578, 351], [578, 339], [789, 339], [789, 320], [805, 320]]],
    e9: ["mobile", "desktop", [[277, 383], [219, 383], [219, 583], [598, 583], [598, 802], [12, 802], [12, 594], [757, 594], [757, 547], [598, 547], [598, 545], [562, 545]]],
    e10: ["mobile", "service", [[277, 351], [588, 351], [588, 676], [239, 676], [239, 649], [1125, 649], [1125, 36], [562, 36]]],
    e11: ["desktop", "contracts", [[562, 521], [598, 521], [598, 497], [789, 497], [789, 605], [22, 605], [22, 783], [229, 783], [229, 767], [255, 767]]],
    e12: ["service", "contracts", [[562, 59], [1115, 59], [1115, 638], [52, 638], [52, 665], [229, 665], [229, 711], [255, 711]]],
    e13: ["service", "core", [[562, 83], [578, 83], [578, 282], [789, 282], [789, 297], [805, 297]]],
    e16: ["desktop", "core", [[562, 498], [578, 498], [578, 440], [789, 440], [789, 344], [805, 344]]],
  };
  for (const [id, [sa, sb, pts]] of Object.entries(raw)) {
    const a = obox[sa], b = obox[sb];
    const settled = app.settleInnerEdge(line(pts), a, b, olist, iw, ih);
    assert.ok(app.innerEdgeOk(settled, a, b, iw, ih), `${id} ${JSON.stringify(settled)}`);
  }
  const kept = line(raw.e8[2]);
  assert.strictEqual(app.settleInnerEdge(kept, obox.mobile, obox.core, olist, iw, ih), kept);
  const rim = line(raw.e1[2]);
  assert.strictEqual(app.settleInnerEdge(rim, obox.core, obox.contracts, olist, iw, ih), rim);
  const stub = app.settleInnerEdge(line(raw.e7[2]), obox.mobile, obox.contracts, olist, iw, ih);
  assert.deepStrictEqual(stub, app.routeGap(obox.mobile, obox.contracts, gaps[0]));
  assert.strictEqual(stub[0].x, obox.mobile.x + obox.mobile.width);
  assert.strictEqual(stub[stub.length - 1].x, obox.contracts.x + obox.contracts.width);
  const direct = app.settleInnerEdge(line(raw.e9[2]), obox.mobile, obox.desktop, olist, iw, ih);
  assert.deepStrictEqual(direct, app.routeInside(obox.mobile, obox.desktop));
  const around = app.settleInnerEdge(line(raw.e12[2]), obox.service, obox.contracts, olist, iw, ih);
  assert.deepStrictEqual(around, app.routeGap(obox.service, obox.contracts, gaps[0]));
  assert.ok(!app.pathClear(app.routeInside(obox.mobile, obox.contracts), olist));

  const groups = { "xg:cli:core": { members: ["a", "b"] } };
  const edge = { a: "xg:cli:core", b: "core" };
  assert.strictEqual(app.edgeMatches(edge, "a", groups), true);
  assert.strictEqual(app.edgeMatches(edge, "core", groups), true);
  assert.strictEqual(app.edgeMatches(edge, "z", groups), false);

  // Relationships that end on a container attach to the child the code reaches, or to the
  // frame when the relationship is only stated. The top-level map does not gain those edges.
  app.clearIndex();
  const alpha = "local:repo:left.ts#alpha";
  const beta = "local:repo:right.ts#beta";
  // `let M` is lexical in the viewer script, so a property write does not reach conceptEdges.
  app.__fixture = {
    workspace: "fixture",
    concepts: [
      { id: "box", name: "Box", role: "core", children: [
        { id: "left", name: "Left", role: "core", files: ["left.ts"], symbols: [{ id: alpha, name: "alpha", kind: "class", file: "src/left.ts", line: 4 }] },
        { id: "right", name: "Right", role: "core", files: ["right.ts"], symbols: [{ id: beta, name: "beta", kind: "class", file: "src/right.ts", line: 8 }] },
      ] },
      { id: "caller", name: "Caller", role: "service", files: ["call.ts"], symbols: [] },
      { id: "neighbour", name: "Neighbour", role: "service", files: ["near.ts"], symbols: [] },
      { id: "sink", name: "Sink", role: "service", files: ["sink.ts"], symbols: [] },
      { id: "filer", name: "Filer", role: "service", files: ["filer.ts"], symbols: [] },
    ],
    externals: [],
    relationships: [
      { from: "caller", to: "box", label: "reads the model", backing: "calls", code: [{ kind: "calls", src: "local:repo:call.ts#go", dst: alpha, src_name: "go", dst_name: "alpha" }, { kind: "calls", src: "local:repo:call.ts#go", dst: beta, src_name: "go", dst_name: "beta" }] },
      { from: "caller", to: "box", label: "watches", backing: "calls", code: [{ kind: "calls", src: "local:repo:call.ts#go", dst: alpha, src_name: "go", dst_name: "alpha" }, { kind: "calls", src: "local:repo:call.ts#go", dst: beta, src_name: "go", dst_name: "beta" }] },
      { from: "neighbour", to: "box", label: "states a link", backing: "stated" },
      { from: "box", to: "sink", label: "publishes", backing: "stated" },
      { from: "left", to: "right", label: "hands off", backing: "imports", code: [{ kind: "imports", src: "local:repo:left.ts", dst: "local:repo:right.ts", src_name: "left.ts", dst_name: "right.ts" }] },
      { from: "filer", to: "box", label: "imports the schedule", backing: "imports", code: [{ kind: "imports", src: "local:repo:filer.ts", dst: "local:repo:right.ts", src_name: "filer.ts", dst_name: "right.ts" }] },
    ],
  };
  vm.runInContext("M = __fixture", app);
  app.indexModel(app.__fixture);
  const boxed = app.conceptEdges("box", new Set(["left", "right"]));
  const edgeTo = (a, b) => boxed.find((e) => e.a === a && e.b === b);
  const caller = edgeTo("caller", "left");
  assert.ok(caller, "code-backed container relationship attaches to the child");
  assert.strictEqual(caller.lane, "in");
  assert.strictEqual(caller.stated, false);
  assert.strictEqual(caller.count, 2);
  assert.strictEqual(caller.text, "reads the model +1");
  const callerRight = edgeTo("caller", "right");
  assert.ok(callerRight && callerRight.lane === "in" && callerRight.count === 2, "code that reaches a second child gets its own edge");
  const statedIn = edgeTo("neighbour", "boundary");
  assert.ok(statedIn, "stated relationship attaches to the frame");
  assert.strictEqual(statedIn.lane, "in");
  assert.strictEqual(statedIn.stated, true);
  assert.strictEqual(statedIn.text, "states a link");
  const statedOut = edgeTo("boundary", "sink");
  assert.ok(statedOut && statedOut.lane === "out" && statedOut.stated);
  assert.ok(edgeTo("left", "right") && !edgeTo("left", "right").lane, "child to child stays inside");
  const filed = edgeTo("filer", "right");
  assert.ok(filed && filed.lane === "in", "a file-level import rolls down to the owning child");
  const onLeaf = app.conceptEdges("left", new Set());
  assert.ok(onLeaf.some((e) => e.a === "caller" && e.b === alpha && e.lane === "in"), "ancestor code rolls down to the symbol");
  assert.ok(!onLeaf.some((e) => e.a === "neighbour" || e.b === "neighbour"), "a stated ancestor relationship does not enter a child");
  const top = app.conceptEdges(null, new Set(["box", "caller", "neighbour", "sink", "filer"]));
  assert.ok(top.every((e) => e.a !== "boundary" && e.b !== "boundary" && !e.lane), "top level is unchanged");
  assert.ok(top.some((e) => e.a === "caller" && e.b === "box"));

  const used = app.usageExplain("box", "caller", true);
  assert.deepStrictEqual([...used.labels], ["reads the model", "watches"]);
  assert.strictEqual(used.calls, 2);
  assert.strictEqual(used.stated, 0);
  assert.ok(used.edges.includes("go → alpha  left.ts:4"), [...used.edges].join(" | "));
  assert.ok(used.edges.includes("go → beta  right.ts:8"));
  const statedUse = app.usageExplain("box", "neighbour", true);
  assert.deepStrictEqual([...statedUse.labels], ["states a link"]);
  assert.strictEqual(statedUse.stated, 1);
  assert.deepStrictEqual([...statedUse.edges], []);
  const outUse = app.usageExplain("box", "sink", false);
  assert.deepStrictEqual([...outUse.labels], ["publishes"]);
  assert.strictEqual(outUse.stated, 1);
  const leafUse = app.usageExplain("left", "caller", true);
  assert.ok(leafUse.labels.includes("reads the model"));
  assert.strictEqual(leafUse.calls, 1);
  assert.deepStrictEqual([...leafUse.edges], ["go → alpha  left.ts:4"]);
  assert.deepStrictEqual([...app.usageExplain("left", "neighbour", true).labels], []);
  assert.deepStrictEqual([...app.usageExplain("box", "filer", true).edges], ["filer.ts → right.ts"]);
  app.__fixture.relationships.push({
    from: "caller", to: "box", label: "also imports", backing: "imports",
    code: [{ kind: "imports", src: "local:repo:call.ts", dst: "local:repo:left.ts", src_name: "call.ts", dst_name: "left.ts", weight: 9 }],
  });
  const ranked = app.usageExplain("box", "caller", true);
  assert.deepStrictEqual([...ranked.edges], [
    "go → alpha  left.ts:4",
    "go → beta  right.ts:8",
    "call.ts → left.ts",
  ]);

  console.log("layout checks passed");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
