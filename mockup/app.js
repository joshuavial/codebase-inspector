// Concept map mockup. Data arrives through loadConcepts() from orchestra-concepts.js.
// Agent-written text is only ever set with textContent.

const TYPES = "uses types from";
const SVG = "http://www.w3.org/2000/svg";
const elk = new ELK();
const byId = {};    // concept or external id -> object
const parentOf = {}; // concept id -> parent id (null at top)
const symById = {}; // symbol id -> symbol (with .leaf)
let M = null;
let view = { focus: null, sel: null };

function loadConcepts(data) {
  M = data;
  const walk = (cs, parent) => cs.forEach((c) => {
    byId[c.id] = c;
    parentOf[c.id] = parent;
    if (c.children) walk(c.children, c.id);
    for (const s of c.symbols || []) symById[s.id] = Object.assign(s, { leaf: c });
  });
  walk(M.concepts, null);
  for (const x of M.externals) { byId[x.id] = Object.assign(x, { ext: true }); parentOf[x.id] = null; }
  initSearch();
  addEventListener("hashchange", route);
  route();
}

// ---------- navigation ----------

function go(focus, sel) {
  const h = new URLSearchParams();
  if (focus) h.set("c", focus);
  if (sel) h.set("s", sel);
  location.hash = h.toString();
}

function route() {
  const h = new URLSearchParams(location.hash.slice(1));
  view = { focus: byId[h.get("c")] ? h.get("c") : null, sel: h.get("s") };
  crumbs();
  const f = view.focus && byId[view.focus];
  if (f && !f.children) drawLeaf(f); else drawConcepts(f);
  drawer();
}

function ancestors(id) {
  const out = [];
  for (let x = id; x != null; x = parentOf[x]) out.unshift(x);
  return out;
}

function crumbs() {
  const nav = document.getElementById("crumbs");
  nav.replaceChildren();
  const trail = [null, ...ancestors(view.focus)];
  trail.forEach((id, i) => {
    if (i) nav.append(el("span", "sep", "›"));
    const last = i === trail.length - 1;
    const a = el(last ? "span" : "a", last ? "here" : "", id ? byId[id].name : M.workspace);
    if (!last) a.onclick = () => go(id);
    nav.append(a);
  });
}

// ---------- concept diagrams ----------

// Map any concept id onto the box that stands for it in the view focused on `focus`.
function project(id, focus) {
  const anc = new Set([null, ...ancestors(focus)]);
  if (id === focus) return null;
  let x = id;
  while (!anc.has(parentOf[x])) x = parentOf[x];
  return x;
}

function conceptEdges(focus, shown) {
  const pairs = new Map();
  for (const r of M.relationships) {
    if (r.minor || r.label === TYPES) continue; // listed in the drawer, kept out of the picture
    const a = project(r.from, focus), b = project(r.to, focus);
    if (!a || !b || a === b || (!shown.has(a) && !shown.has(b))) continue;
    const key = a + ">" + b;
    if (!pairs.has(key)) pairs.set(key, { a, b, exact: [], rolled: [] });
    pairs.get(key)[a === r.from && b === r.to ? "exact" : "rolled"].push(r.label);
  }
  return [...pairs.values()].map((p) => {
    const labels = [...new Set(p.exact.length ? p.exact : p.rolled)];
    return { a: p.a, b: p.b, text: labels[0] + (labels.length > 1 ? `  +${labels.length - 1}` : ""), all: labels };
  });
}

function drawConcepts(f) {
  const kids = f ? f.children : [...M.concepts, ...M.externals];
  const shown = new Set(kids.map((c) => c.id));
  const edges = conceptEdges(f ? f.id : null, shown);
  const ctx = new Set();
  for (const e of edges) for (const x of [e.a, e.b]) if (!shown.has(x)) ctx.add(x);

  const nodes = [
    ...kids.map((c) => box(c, c.ext ? "ext" : "")),
    ...[...ctx].map((id) => box(byId[id], "ctx")),
  ];
  layout(nodes, edges.map((e, i) => ({
    id: "e" + i, a: e.a, b: e.b, text: e.text, title: e.all.join("\n"),
  })), { dir: "DOWN", layer: 52, gap: 44 }, (id) => {
    const c = byId[id];
    if (c.ext) go(view.focus, id);
    else go(id);
  });
}

function box(c, cls) {
  if (cls === "ctx") return { id: c.id, cls: "node ctx", w: textW(c.name, 500, 14) + 32, h: 38, name: c.name, lines: [] };
  const w = Math.max(cls === "ext" ? 190 : 230, textW(c.name, 600, 14) + 28);
  const lines = wrap(c.summary, w - 28, 12, 3);
  return { id: c.id, cls: "node " + cls, w, h: 46 + lines.length * 16, name: c.name, lines, stack: !!c.children };
}

// ---------- leaf diagrams ----------

function drawLeaf(c) {
  const nodes = c.symbols.map((s) => {
    const n = s.tests.length;
    const badge = n ? textW("✓ " + n, 600, 11) + 12 : 0;
    return { id: s.id, sym: s, cls: "sym", w: Math.max(textW(s.name, 500, 13, true) + 28 + (badge && badge + 8), 110), h: 44, name: s.name, badge };
  });
  const edges = c.calls.map(([a, b], i) => ({ id: "c" + i, a, b, cls: "call" }));
  if (!nodes.length) return empty("No classes or functions here, only types.");
  layout(nodes, edges, { dir: "RIGHT", layer: 48, gap: 14 }, (id) => go(view.focus, id));
}

// ---------- layout and render ----------

async function layout(nodes, edges, opt, onClick) {
  const graph = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": opt.dir,
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.layered.spacing.nodeNodeBetweenLayers": String(opt.layer),
      "elk.spacing.nodeNode": String(opt.gap),
      "elk.spacing.edgeLabel": "4",
      "elk.spacing.edgeNode": "16",
      "elk.layered.spacing.edgeNodeBetweenLayers": "16",
      "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
      "elk.spacing.componentComponent": String(opt.gap * 1.5),
      "elk.padding": "[top=12,left=12,bottom=12,right=12]",
    },
    children: nodes.map((n) => ({ id: n.id, width: n.w, height: n.h })),
    edges: edges.map((e) => ({
      id: e.id, sources: [e.a], targets: [e.b],
      labels: e.text ? [{ text: e.text, width: textW(e.text, 400, 11.5) + 6, height: 14 }] : [],
    })),
  };
  const out = await elk.layout(graph);
  render(out, nodes, edges, onClick);
}

function render(out, nodes, edges, onClick) {
  const svg = document.getElementById("diagram");
  svg.replaceChildren(defs());
  const stage = document.getElementById("stage");
  const fit = Math.min(1.4, (stage.clientWidth - 48) / out.width, (stage.clientHeight - 48) / out.height);
  const scale = Math.max(fit, 0.55);
  svg.setAttribute("viewBox", `0 0 ${out.width} ${out.height}`);
  svg.setAttribute("width", out.width * scale);
  svg.setAttribute("height", out.height * scale);

  const meta = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const em = Object.fromEntries(edges.map((e) => [e.id, e]));
  const edgeG = svgEl("g"), nodeG = svgEl("g");
  svg.append(edgeG, nodeG);

  const edgeEls = [];
  for (const e of out.edges) {
    const m = em[e.id];
    const g = svgEl("g", { class: "edge " + (m.cls || "") });
    for (const s of e.sections || []) {
      const pts = [s.startPoint, ...(s.bendPoints || []), s.endPoint];
      g.append(svgEl("path", { d: rounded(pts), "marker-end": "url(#arrow)" }));
    }
    for (const l of e.labels || []) {
      const t = svgEl("text", { x: l.x + 3, y: l.y + 11 });
      t.textContent = l.text;
      g.append(t);
    }
    if (m.title) { const t = svgEl("title"); t.textContent = m.title; g.append(t); }
    edgeG.append(g);
    edgeEls.push({ g, a: m.a, b: m.b });
  }

  const sel = view.sel;
  const near = new Set();
  if (sel && symById[sel]) for (const x of edgeEls) if (x.a === sel || x.b === sel) near.add(x.a).add(x.b);

  for (const n of out.children) {
    const m = meta[n.id];
    const g = svgEl("g", { class: m.cls + (n.id === sel ? " sel" : ""), transform: `translate(${n.x},${n.y})`, tabindex: 0 });
    if (m.stack) g.append(svgEl("rect", { class: "stack", x: 4, y: 4, width: n.width, height: n.height, rx: 10 }));
    g.append(svgEl("rect", { class: "body", width: n.width, height: n.height, rx: m.sym ? 8 : 10 }));
    if (m.sym) drawSym(g, m, n);
    else {
      const ctx = m.cls.includes("ctx");
      const name = svgEl("text", { class: "name", x: 14, y: ctx ? 24 : 26 });
      name.textContent = m.name;
      g.append(name);
      m.lines.forEach((line, i) => {
        const t = svgEl("text", { class: "sum", x: 14, y: 46 + i * 16 });
        t.textContent = line;
        g.append(t);
      });
    }
    if (sel && symById[sel] && !near.has(n.id) && n.id !== sel) g.classList.add("dim");
    g.onclick = (ev) => { ev.stopPropagation(); onClick(n.id); };
    g.onkeydown = (ev) => { if (ev.key === "Enter") onClick(n.id); };
    g.onmouseenter = () => hot(edgeEls, n.id, true);
    g.onmouseleave = () => hot(edgeEls, n.id, false);
    nodeG.append(g);
  }
  if (sel && symById[sel]) hot(edgeEls, sel, true);
  svg.onclick = () => { if (view.sel) go(view.focus); };
}

function drawSym(g, m, n) {
  const name = svgEl("text", { class: "name", x: 12, y: 19 });
  name.textContent = m.name;
  const kind = svgEl("text", { class: "kind", x: 12, y: 35 });
  kind.textContent = m.sym.kind;
  g.append(name, kind);
  if (m.badge) {
    const b = svgEl("g", { class: "badge", transform: `translate(${n.width - m.badge - 8},8)` });
    const t = svgEl("text", { x: 6, y: 13 });
    t.textContent = "✓ " + m.sym.tests.length;
    const title = svgEl("title");
    title.textContent = `${m.sym.tests.length} linked test case${m.sym.tests.length > 1 ? "s" : ""}`;
    b.append(svgEl("rect", { width: m.badge, height: 18, rx: 9 }), t, title);
    g.append(b);
  }
}

function hot(edgeEls, id, on) {
  for (const x of edgeEls) if (x.a === id || x.b === id) {
    x.g.classList.toggle("hot", on);
    for (const p of x.g.querySelectorAll("path")) p.setAttribute("marker-end", on ? "url(#arrow-hot)" : "url(#arrow)");
  }
}

function rounded(pts, r = 8) {
  let d = `M${pts[0].x},${pts[0].y}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const p = pts[i], a = pts[i - 1], b = pts[i + 1];
    const k1 = Math.min(r, dist(a, p) / 2), k2 = Math.min(r, dist(p, b) / 2);
    const s = toward(p, a, k1), e = toward(p, b, k2);
    d += ` L${s.x},${s.y} Q${p.x},${p.y} ${e.x},${e.y}`;
  }
  const z = pts[pts.length - 1];
  return d + ` L${z.x},${z.y}`;
}
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const toward = (p, q, k) => { const l = dist(p, q) || 1; return { x: p.x + (q.x - p.x) * k / l, y: p.y + (q.y - p.y) * k / l }; };

function defs() {
  const d = svgEl("defs");
  for (const id of ["arrow", "arrow-hot"]) {
    const m = svgEl("marker", { id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
    m.append(svgEl("path", { d: "M0,1 L9,5 L0,9 z" }));
    d.append(m);
  }
  return d;
}

function empty(msg) {
  const svg = document.getElementById("diagram");
  svg.replaceChildren();
  svg.setAttribute("viewBox", "0 0 400 40");
  svg.setAttribute("width", 400);
  svg.setAttribute("height", 40);
  const t = svgEl("text", { class: "empty", x: 200, y: 24, "text-anchor": "middle" });
  t.textContent = msg;
  svg.append(t);
}

// ---------- drawer ----------

function drawer() {
  const d = document.getElementById("drawer");
  d.replaceChildren();
  const s = view.sel && symById[view.sel];
  if (s) return symbolDrawer(d, s);
  const c = byId[view.sel] || byId[view.focus];
  if (!c) {
    d.append(el("h2", "", M.workspace), el("p", "", M.summary));
    d.append(el("h3", "", "Reading this map"));
    d.append(el("p", "", "Boxes are the parts of the system. Dashed boxes are things outside it. Click a box to open it."));
    return;
  }
  d.append(el("h2", "", c.name), el("p", "", c.summary));
  if (c.children) list(d, "Parts", c.children.map((k) => link(k.name, () => go(k.id))));

  const rels = M.relationships.filter((r) => (r.from === c.id || r.to === c.id) && r.label !== TYPES);
  if (rels.length) list(d, "Relationships", rels.map((r) => {
    const li = el("span", "rel");
    const other = byId[r.from === c.id ? r.to : r.from];
    const b = link(other.name, () => go(other.ext ? view.focus : other.id, other.ext ? other.id : null));
    if (r.from === c.id) li.append(r.label + " ", b);
    else li.append(b, " " + r.label);
    return li;
  }));
  if (c.ext) return;

  const leaves = leafList(c);
  const files = leaves.flatMap((l) => l.files);
  const tests = leaves.flatMap((l) => l.tests);
  if (!c.children) {
    const counts = {};
    for (const x of c.symbols) counts[x.kind] = (counts[x.kind] || 0) + 1;
    const tested = c.symbols.filter((x) => x.tests.length).length;
    const line = Object.entries(counts).map(([k, n]) => `${n} ${k}${n > 1 ? (k === "class" ? "es" : "s") : ""}`).join(", ");
    if (line) list(d, "Code", [el("span", "", line), el("span", "", `${tested} of ${c.symbols.length} linked to a test`)]);
  }
  fold(d, `Files (${files.length})`, files.map((f) => el("span", "path", f)), !c.children);
  fold(d, `Tests (${tests.length})`, tests.map((t) => {
    const li = el("span", "path", t.file);
    li.append(el("span", "n", t.cases + (t.cases === 1 ? " case" : " cases")));
    return li;
  }), !c.children);
}

function symbolDrawer(d, s) {
  d.append(el("h2", "", s.name), el("p", "", `${s.kind} in ${s.leaf.name}`));
  if (s.sig) d.append(el("div", "sig", s.sig));
  d.append(el("h3", "", "Where"), el("div", "path", `${s.file}:${s.line}`));
  const calls = s.leaf.calls.filter(([a]) => a === s.id).map(([, b]) => symById[b]);
  const by = s.leaf.calls.filter(([, b]) => b === s.id).map(([a]) => symById[a]);
  if (calls.length) list(d, "Calls", calls.map((x) => link(x.name, () => go(view.focus, x.id))));
  if (by.length) list(d, "Called by", by.map((x) => link(x.name, () => go(view.focus, x.id))));
  list(d, `Tests (${s.tests.length})`, s.tests.length ? s.tests.slice(0, 12).map((t) => el("span", "", t)) : [el("span", "rel", "No test links found by static analysis.")]);
  if (s.tests.length > 12) d.append(el("p", "", `and ${s.tests.length - 12} more`));
}

function leafList(c) { return c.children ? c.children.flatMap(leafList) : [c]; }

function list(d, title, items) {
  d.append(el("h3", "", title));
  const ul = el("ul");
  for (const it of items) { const li = el("li"); li.append(it); ul.append(li); }
  d.append(ul);
}

function fold(d, title, items, open) {
  if (!items.length) return;
  const det = el("details");
  det.open = open;
  const sum = el("summary", "", "");
  sum.append(el("h3", "", title));
  sum.style.listStyle = "none";
  sum.style.cursor = "pointer";
  det.append(sum);
  const ul = el("ul");
  for (const it of items) { const li = el("li"); li.append(it); ul.append(li); }
  det.append(ul);
  d.append(det);
}

function link(text, fn) { const b = el("b", "", text); b.onclick = fn; return b; }

// ---------- search ----------

let entries = [];
function initSearch() {
  for (const c of Object.values(byId)) entries.push({ name: c.name, text: (c.name + " " + c.summary).toLowerCase(), kind: c.ext ? "outside" : "concept", c });
  for (const s of Object.values(symById)) entries.push({ name: s.name, text: s.name.toLowerCase(), kind: `${s.kind} · ${s.leaf.name}`, s });
  const q = document.getElementById("q"), hits = document.getElementById("hits");
  let shown = [], on = 0;
  const pick = (h) => {
    hits.hidden = true;
    q.value = "";
    if (h.s) go(h.s.leaf.id, h.s.id);
    else if (h.c.ext) go(null, h.c.id);
    else go(h.c.id);
  };
  const paint = () => {
    hits.replaceChildren(...shown.map((h, i) => {
      const li = el("li", i === on ? "on" : "");
      li.append(el("span", "", h.name), el("span", "k", h.kind));
      li.onmousedown = () => pick(h);
      return li;
    }));
    hits.hidden = !shown.length;
  };
  q.oninput = () => {
    const t = q.value.trim().toLowerCase();
    shown = t ? entries
      .map((e) => ({ e, r: e.name.toLowerCase().startsWith(t) ? 0 : e.name.toLowerCase().includes(t) ? 1 : e.text.includes(t) ? 2 : 9 }))
      .filter((x) => x.r < 9)
      .sort((x, y) => x.r - y.r || (x.e.c ? 0 : 1) - (y.e.c ? 0 : 1) || x.e.name.length - y.e.name.length)
      .slice(0, 12).map((x) => x.e) : [];
    on = 0;
    paint();
  };
  q.onkeydown = (ev) => {
    if (ev.key === "ArrowDown") { on = Math.min(on + 1, shown.length - 1); paint(); ev.preventDefault(); }
    if (ev.key === "ArrowUp") { on = Math.max(on - 1, 0); paint(); ev.preventDefault(); }
    if (ev.key === "Enter" && shown[on]) pick(shown[on]);
    if (ev.key === "Escape") { q.value = ""; shown = []; paint(); }
  };
  q.onblur = () => setTimeout(() => (hits.hidden = true), 100);
  addEventListener("keydown", (ev) => { if (ev.key === "/" && document.activeElement !== q) { q.focus(); ev.preventDefault(); } });
}

// ---------- helpers ----------

function el(tag, cls = "", text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function svgEl(tag, attrs = {}) {
  const e = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

const measure = document.createElement("canvas").getContext("2d");
const SANS = '-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif';
const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";
function textW(s, weight, size, mono) {
  measure.font = `${weight} ${size}px ${mono ? MONO : SANS}`;
  return Math.ceil(measure.measureText(s).width);
}

function wrap(s, width, size, max) {
  const words = s.split(/\s+/), lines = [];
  let cur = "";
  for (const w of words) {
    const next = cur ? cur + " " + w : w;
    if (textW(next, 400, size) <= width) cur = next;
    else { lines.push(cur); cur = w; }
  }
  if (cur) lines.push(cur);
  if (lines.length > max) {
    let last = lines[max - 1];
    while (textW(last + "…", 400, size) > width) last = last.replace(/\s*\S+$/, "");
    lines.splice(max - 1, Infinity, last + "…");
  }
  return lines;
}
