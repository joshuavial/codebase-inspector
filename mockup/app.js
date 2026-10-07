// Concept map mockup. Data arrives through loadConcepts() from orchestra-concepts.js.
// Agent-written text is only ever set with textContent.

const TYPES = "uses types from";
const SVG = "http://www.w3.org/2000/svg";
const ROLES = { ui: "Interface", app: "App or process", service: "Service", core: "Core logic", data: "Data and model" };
const KINDS = { platform: "Platform service", cli: "CLI tool", saas: "SaaS or API", terminal: "Terminal or OS" };
const GHOSTS_PER_GROUP = 5;
const elk = new ELK();
const byId = {};    // concept or external id -> object
const parentOf = {}; // concept id -> parent id (null at top)
const symById = {}; // symbol id -> symbol (with .leaf)
const ghostById = {}; // foreign symbol id -> { name, kind, concept }
let M = null;
let view = { focus: null, sel: null, mode: null, screen: null };
let last = null; // the previous view, null before the first render
let lateralHash = null; // where the last lateral jump landed, so Back can use browser history
let glow = false; // highlight where we jumped from, until the next click in the stage
let restore = null; // camera to reuse instead of fitting
const camByHash = {};
let camBeforeZoom = null; // the camera before a drill-in animation, which is what Back should restore

function loadConcepts(data) {
  M = data;
  const walk = (cs, parent) => cs.forEach((c) => {
    byId[c.id] = c;
    parentOf[c.id] = parent;
    if (c.children) walk(c.children, c.id);
    for (const s of c.symbols || []) symById[s.id] = Object.assign(s, { leaf: c });
    Object.assign(ghostById, c.ghosts || {});
  });
  walk(M.concepts, null);
  for (const x of M.externals) { byId[x.id] = Object.assign(x, { ext: true }); parentOf[x.id] = null; }
  initSearch();
  initCamera();
  addEventListener("hashchange", route);
  addEventListener("keydown", onKey);
  route();
}

// ---------- navigation ----------

function go(focus, sel, extra = {}) {
  const h = new URLSearchParams();
  if (focus) h.set("c", focus);
  if (sel) h.set("s", sel);
  // Keep the way back while moving around inside the concept a lateral jump landed on.
  if (view.from && (focus || null) === view.focus && !("from" in extra)) {
    h.set("from", view.from);
    h.set("bh", view.backHash);
  }
  for (const [k, v] of Object.entries(extra)) if (v) h.set(k, v);
  location.hash = h.toString();
}

// A jump that is neither into a child nor up to an ancestor.
function lateral(target) {
  if (target === view.focus || !view.focus || !target) return false;
  return !ancestors(target).includes(view.focus) && !ancestors(view.focus).includes(target);
}

// Every way into a view except drilling into a child or going up leaves a "Back to <origin>" chip.
// `force` marks entries that always count as a jump: search, drawer links, grey nodes, sketch regions.
// The origin's full hash rides along in the URL so Back restores its exact zoom and selection.
function jump(target, sel, { force = false, extra = {} } = {}) {
  target = target || null;
  if (target === view.focus || (!force && !lateral(target))) return go(target, sel, extra);
  glow = true;
  go(target, sel, { ...extra, from: view.focus || "~", bh: location.hash.slice(1) || "-" });
  lateralHash = location.hash;
}

function back() {
  if (!view.from) return;
  if (location.hash === lateralHash) history.back();
  else location.hash = view.backHash === "-" ? "" : view.backHash;
}

const originName = (id) => (id === "~" ? M.workspace : byId[id].name);

function route() {
  const h = new URLSearchParams(location.hash.slice(1));
  const first = !last;
  if (!first) camByHash[last.hash] = camBeforeZoom || { ...cam };
  camBeforeZoom = null;
  const prev = view;
  view = {
    focus: byId[h.get("c")] ? h.get("c") : null, sel: h.get("s"), mode: h.get("v"), screen: h.get("w"),
    from: byId[h.get("from")] || h.get("from") === "~" ? h.get("from") : null, backHash: h.get("bh") || "-",
  };
  if (first) glow = !!view.from;
  // Same diagram: keep the camera. A view seen before (Back): restore its camera.
  restore = !first && prev.focus === view.focus && prev.mode === view.mode ? { ...cam } : camByHash[location.hash] || null;
  crumbs();
  const f = view.focus && byId[view.focus];
  const from = first ? null : last.focus;
  last = { focus: view.focus, hash: location.hash };
  // Going up: start zoomed on the box we came out of. Going down: start from further away.
  const up = from && from !== view.focus && ancestors(from).includes(view.focus) || (from && !view.focus);
  const down = view.focus && view.focus !== from && (!from || ancestors(view.focus).includes(from));
  const enter = first ? null : up ? { from: project(from, view.focus) } : down ? { zoomIn: true } : null;
  if (f && !f.children && sketchable(f) && view.mode !== "code") drawSketch(f);
  else if (f && !f.children) drawLeaf(f, enter);
  else drawConcepts(f, enter);
  drawer();
}

function up() {
  if (view.focus) go(parentOf[view.focus]);
  else if (view.sel) go(null);
}

function onKey(ev) {
  const typing = ev.target.closest && ev.target.closest("input, textarea");
  if (typing) return;
  if (ev.key === "Escape") up();
  else if (ev.key === "Backspace" && view.from) { back(); ev.preventDefault(); }
  else if (ev.key === "/") { document.getElementById("q").focus(); ev.preventDefault(); }
  else if (ev.key === "0" || ev.key === "f") fit(true);
  else if (ev.key === "+" || ev.key === "=") zoomBy(1 / 1.25);
  else if (ev.key === "-") zoomBy(1.25);
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
    const lastCrumb = i === trail.length - 1;
    const a = el(lastCrumb ? "span" : "a", lastCrumb ? "here" : "", id ? byId[id].name : M.workspace);
    if (!lastCrumb) a.onclick = () => go(id);
    nav.append(a);
  });
  if (view.from) {
    const b = el("button", "back", `← Back to ${originName(view.from)}`);
    b.title = "Back (Backspace)";
    b.onclick = back;
    nav.append(b);
  }
}

// ---------- concept diagrams ----------

// Map any concept id onto the box that stands for it in the view focused on `focus`.
function project(id, focus) {
  const anc = new Set([null, ...ancestors(focus)]);
  if (id === focus || !id) return null;
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
    if (!pairs.has(key)) pairs.set(key, { a, b, exact: [], rolled: [], via: [] });
    const p = pairs.get(key);
    p[a === r.from && b === r.to ? "exact" : "rolled"].push(r.label);
    if (r.via) p.via.push(r.via);
  }
  return [...pairs.values()].map((p) => {
    const labels = [...new Set(p.exact.length ? p.exact : p.rolled)];
    const via = [...new Set(p.via)];
    return {
      a: p.a, b: p.b, all: labels, via: via.length > 1 ? via[0] + " +" + (via.length - 1) : via[0],
      text: labels[0] + (labels.length > 1 ? `  +${labels.length - 1}` : ""),
    };
  });
}

function drawConcepts(f, enter) {
  const kids = f ? f.children : M.concepts;
  const shown = new Set(kids.map((c) => c.id));
  const edges = conceptEdges(f ? f.id : null, new Set([...shown, ...(f ? [] : M.externals.map((x) => x.id))]));
  const outside = new Set(f ? [] : M.externals.map((x) => x.id));
  for (const e of edges) for (const x of [e.a, e.b]) if (!shown.has(x)) outside.add(x);

  const boundary = {
    id: "boundary", cls: "boundary", label: f ? f.name : M.workspace, children: kids.map((c) => box(c, "")),
  };
  const nodes = [boundary, ...[...outside].map((id) => box(byId[id], f ? "ctx" : "ext"))];
  const kind = (e) => byId[e.a].ext || byId[e.b].ext ? "integration" : shown.has(e.a) && shown.has(e.b) ? "" : "port";
  layout(nodes, edges.map((e, i) => ({
    id: "e" + i, a: e.a, b: e.b, text: e.text, via: e.via, title: e.all.join("\n"), cls: kind(e),
  })), { dir: "DOWN", layer: 52, gap: 40 }, (id) => {
    const c = byId[id];
    if (!c) return;
    if (c.ext) go(view.focus, id);
    else if (lateral(id)) jump(id);
    else zoomInto(id, () => go(id));
  }, enter);
  legend([...kids, ...[...outside].map((id) => byId[id])], edges.some((e) => kind(e) === "integration"), false);
}

function box(c, cls) {
  const tone = c.ext ? "kind-" + c.kind : "role-" + c.role;
  if (cls === "ctx") return { id: c.id, cls: `node ctx ${c.ext ? "ext " : ""}${tone}`, w: textW(c.name, 500, 14) + 36, h: 38, name: c.name, lines: [] };
  const w = Math.max(cls === "ext" ? 190 : 230, textW(c.name, 600, 14) + 32);
  const lines = wrap(c.summary, w - 32, 12, 3);
  const env = envOf(c).length;
  return { id: c.id, cls: `node ${cls} ${tone}`, w: w + (env ? 44 : 0), h: 46 + lines.length * 16, name: c.name, lines, stack: !!c.children, env };
}

// ---------- leaf diagrams ----------

function drawLeaf(c, enter) {
  const own = new Set(c.symbols.map((s) => s.id));
  const symNode = (s, cls) => {
    const n = s.tests ? s.tests.length : 0;
    const badge = n ? textW("✓ " + n, 600, 11) + 12 : 0;
    const env = s.env || [];
    const envText = env.length ? envName(env[0]) + (env.length > 1 ? ` +${env.length - 1}` : "") : "";
    const envW = envText ? textW(s.kind, 400, 11) + textW(envText, 600, 10.5, true) + 52 : 0;
    return { id: s.id, sym: s, cls: `sym ${cls}`, w: Math.max(textW(s.name, 500, 13, true) + 28 + (badge && badge + 8), envW, 110), h: 46, name: s.name, badge, envText };
  };
  if (!c.symbols.length) { empty("No classes or functions here, only types."); legend([], false, false); return; }

  // Foreign symbols, grouped by owning concept, capped per group.
  const groups = {};
  for (const [id, g] of Object.entries(c.ghosts)) (groups[g.concept] ||= []).push(id);
  const alias = {};
  const groupNodes = Object.entries(groups).map(([cid, ids]) => {
    ids.sort((a, b) => ghostById[a].name.localeCompare(ghostById[b].name));
    const shown = ids.slice(0, GHOSTS_PER_GROUP), hidden = ids.slice(GHOSTS_PER_GROUP);
    const kids = shown.map((id) => symNode(Object.assign({ id }, ghostById[id]), "ghost"));
    if (hidden.length) {
      const more = "more:" + cid;
      kids.push({ id: more, cls: "sym ghost more", w: 90, h: 32, name: `+${hidden.length} more`, more: cid });
      for (const id of hidden) alias[id] = more;
    }
    return { id: "group:" + cid, cls: `group role-${byId[cid].role}`, label: byId[cid].name, concept: cid, children: kids };
  });

  const seen = new Set();
  const edges = [];
  for (const [a0, b0, verb] of c.calls) {
    const a = alias[a0] || a0, b = alias[b0] || b0, key = a + ">" + b;
    if (seen.has(key)) continue;
    seen.add(key);
    edges.push({ id: "c" + edges.length, a, b, cls: (own.has(a) && own.has(b) ? "call" : "call ghosted") + (verb === "renders" ? " renders" : "") });
  }
  // Integration points of this leaf, drawn to the external from the function named in the code.
  const ext = [];
  for (const r of M.relationships) {
    const mine = r.from === c.id ? r.to : r.to === c.id ? r.from : null;
    if (!mine || !byId[mine].ext) continue;
    if (!ext.includes(mine)) ext.push(mine);
    const fn = r.at && r.at.split(":")[1];
    const s = c.symbols.find((x) => x.name === fn);
    const inner = s ? s.id : "boundary";
    edges.push({ id: "x" + edges.length, a: r.from === c.id ? inner : mine, b: r.from === c.id ? mine : inner, text: r.label, via: r.via, cls: "integration" });
  }

  const boundary = { id: "boundary", cls: `boundary role-${c.role}`, label: c.name, children: c.symbols.map((s) => symNode(s, "")) };
  const nodes = [boundary, ...groupNodes, ...ext.map((id) => box(byId[id], "ctx"))];
  layout(nodes, edges, { dir: "RIGHT", layer: 56, gap: 14 }, (id) => {
    if (own.has(id)) return go(view.focus, id, { v: view.mode });
    if (ghostById[id]) return go(view.focus, id, { v: view.mode }); // select; double-click jumps
    if (id.startsWith("more:")) return jump(id.slice(5), null, { force: true });
    if (id.startsWith("group:")) return jump(id.slice(6), null, { force: true });
    if (byId[id] && byId[id].ext) return go(view.focus, id, { v: view.mode });
  }, enter, (id) => { if (ghostById[id] && !own.has(id)) jump(ghostById[id].concept, id, { force: true }); });
  legend([c, ...ext.map((id) => byId[id])], ext.length > 0, groupNodes.length > 0, c.symbols.some((s) => s.env));
}

// ---------- UI sketch view ----------

function componentIds(c) { return new Set(c.symbols.filter((s) => s.kind === "component").map((s) => s.id)); }

function regionsWith(region, ids, out = []) {
  if (ids.has(region.component)) out.push(region);
  for (const k of region.children || []) regionsWith(k, ids, out);
  return out;
}

function sketchable(c) {
  const ids = componentIds(c);
  return ids.size > 0 && (M.screens || []).some((s) => regionsWith(s.root, ids).length);
}

function drawSketch(c) {
  setStage("sketch");
  legend([], false, false);
  const pane = document.getElementById("sketch");
  pane.replaceChildren();
  const ids = componentIds(c);
  const sel = symById[view.sel] && ids.has(view.sel) ? view.sel : null;
  const screens = M.screens.filter((s) => regionsWith(s.root, sel ? new Set([sel]) : ids).length);
  const screen = screens.find((s) => s.id === view.screen) || screens[0];

  // The component the panel describes: the selected one, else the outermost one of this concept on screen.
  // The screen root is the whole frame, so highlighting starts one level in.
  const outer = [];
  const size = (r) => 1 + (r.children || []).reduce((n, k) => n + size(k), 0);
  (function walk(r, inside) {
    const mine = ids.has(r.component) && r !== screen.root;
    if (mine && !inside) outer.push(r);
    for (const k of r.children || []) walk(k, inside || mine);
  })(screen.root, false);
  outer.sort((a, b) => size(b) - size(a));
  if (!outer.length && ids.has(screen.root.component)) outer.push(screen.root);
  const focusComp = sel || (outer[0] && outer[0].component);
  const hl = new Set(sel ? [sel] : outer.map((r) => r.component));

  const picker = el("div", "screens");
  for (const s of screens) {
    const b = el("button", s.id === screen.id ? "on" : "", s.name);
    b.onclick = () => go(view.focus, view.sel, { w: s.id });
    picker.append(b);
  }
  const frame = el("div", "frame " + screen.device);
  frame.append(region(screen.root, hl, false));
  const left = el("div", "sketch-main");
  left.append(picker, frame);
  pane.append(left, componentPanel(symById[focusComp]));
  const target = frame.querySelector(".hl");
  if (target) requestAnimationFrame(() => target.scrollIntoView({ block: "center", inline: "nearest" }));
}

function region(r, hl, inside) {
  const d = el("div", `wf ${r.layout}` + (r.style ? " " + r.style.map((s) => "s-" + s).join(" ") : ""));
  if (r.cols) d.style.gridTemplateColumns = `repeat(${Number(r.cols)}, auto)`;
  const on = hl.has(r.component);
  if (on) d.classList.add("hl");
  else if (inside && r.component) d.classList.add("ol");
  if (r.component && symById[r.component]) {
    const s = symById[r.component];
    d.title = s.name;
    d.onclick = (ev) => { ev.stopPropagation(); jump(s.leaf.id, s.id, { force: true, extra: { w: view.screen } }); };
    if (on && r.layout === "column") d.append(el("span", "tag", s.name));
  }
  if (r.text != null) {
    if (r.style && r.style.includes("bar")) d.append(el("span", "barfill"));
    for (const part of r.text.split(/(\{[^}]*\})/)) {
      if (!part) continue;
      d.append(part.startsWith("{") ? el("span", "ph", part.slice(1, -1)) : document.createTextNode(part));
    }
  }
  for (const k of r.children || []) d.append(region(k, hl, inside || on));
  return d;
}

function componentPanel(s) {
  const p = el("div", "comp-panel");
  if (!s) return p;
  p.append(el("h4", "", s.name));
  const chips = (title, items, cls, onClick) => {
    if (!items.length) return;
    p.append(el("h5", "", title));
    const row = el("div", "chips");
    for (const it of items) {
      const c = el("span", "chip " + cls, onClick ? it.name : it);
      if (onClick) c.onclick = () => onClick(it);
      row.append(c);
    }
    p.append(row);
  };
  chips("Props", s.props || [], "mono");
  const renders = s.leaf.calls.filter(([a, , v]) => a === s.id && v === "renders").map(([, b]) => symById[b]).filter(Boolean);
  chips("Renders", renders, "link", (x) => jump(x.leaf.id, x.id, { force: true }));
  chips("Reads", s.reads || [], "mono");
  const n = s.tests.length;
  p.append(el("p", "tests", n ? `✓ ${n} linked test case${n > 1 ? "s" : ""}` : "No test links found"));
  return p;
}

// ---------- layout and render ----------

async function layout(nodes, edges, opt, onClick, enter, onDbl) {
  const toElk = (n) => ({
    id: n.id,
    ...(n.children ? {}: { width: n.w, height: n.h }),
    ...(n.children ? {
      children: n.children.map(toElk),
      layoutOptions: { "elk.padding": "[top=40,left=20,bottom=20,right=20]" },
    } : {}),
  });
  const graph = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": opt.dir,
      "elk.hierarchyHandling": "INCLUDE_CHILDREN",
      "org.eclipse.elk.json.edgeCoords": "ROOT",
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
    children: nodes.map(toElk),
    edges: edges.map((e) => ({
      id: e.id, sources: [e.a], targets: [e.b],
      labels: e.text ? [{ text: e.text, width: labelW(e) , height: 16 }] : [],
    })),
  };
  let out;
  try { out = await elk.layout(graph); } catch (err) { return empty("Layout failed: " + err.message); }
  render(out, nodes, edges, onClick, enter, onDbl);
}

const labelW = (e) => textW(e.text, 400, 11.5) + 6 + (e.via ? textW(e.via, 600, 10.5, true) + 18 : 0);

function render(out, nodes, edges, onClick, enter, onDbl) {
  setStage("diagram");
  const svg = document.getElementById("diagram");
  svg.replaceChildren(defs());
  const meta = {};
  (function index(ns) { for (const n of ns) { meta[n.id] = n; if (n.children) index(n.children); } })(nodes);
  const em = Object.fromEntries(edges.map((e) => [e.id, e]));
  const world = svgEl("g"), boxG = svgEl("g"), edgeG = svgEl("g"), nodeG = svgEl("g");
  world.append(boxG, edgeG, nodeG);
  svg.append(world);
  rects = {};

  const sel = view.sel;
  const placed = [];
  (function place(ns, ox, oy) {
    for (const n of ns) {
      const x = ox + n.x, y = oy + n.y;
      rects[n.id] = { x, y, w: n.width, h: n.height };
      placed.push({ n, x, y });
      if (n.children) place(n.children, x, y);
    }
  })(out.children, 0, 0);

  const edgeEls = [];
  for (const e of out.edges) {
    const m = em[e.id];
    const g = svgEl("g", { class: "edge " + (m.cls || "") });
    for (const s of e.sections || []) {
      const pts = [s.startPoint, ...(s.bendPoints || []), s.endPoint];
      g.append(svgEl("path", { d: rounded(pts), "marker-end": `url(#${m.cls && m.cls.includes("integration") ? "arrow-int" : "arrow"})` }));
    }
    for (const l of e.labels || []) {
      const t = svgEl("text", { x: l.x + 3, y: l.y + 12 });
      t.textContent = l.text;
      g.append(t);
      if (m.via) {
        const x = l.x + textW(l.text, 400, 11.5) + 10, w = textW(m.via, 600, 10.5, true) + 12;
        const pill = svgEl("g", { class: "via", transform: `translate(${x},${l.y})` });
        const vt = svgEl("text", { x: 6, y: 12 });
        vt.textContent = m.via;
        pill.append(svgEl("rect", { width: w, height: 16, rx: 8 }), vt);
        g.append(pill);
      }
    }
    if (m.title) { const t = svgEl("title"); t.textContent = m.title; g.append(t); }
    edgeG.append(g);
    edgeEls.push({ g, a: m.a, b: m.b });
  }

  // Where a lateral jump came from: its box, or its ghost group and ghosts.
  const glowing = new Set();
  if (glow && view.from && view.from !== "~") {
    const box = project(view.from, view.focus);
    for (const { n } of placed) {
      const m = meta[n.id];
      if (n.id === view.from || n.id === box || m.concept === view.from || m.more === view.from || (m.sym && m.sym.concept === view.from)) glowing.add(n.id);
    }
    for (const x of edgeEls) if (glowing.has(x.a) || glowing.has(x.b)) x.g.classList.add("glow");
  }

  const near = new Set();
  if (sel && symById[sel]) for (const x of edgeEls) if (x.a === sel || x.b === sel) near.add(x.a).add(x.b);

  for (const { n, x, y } of placed) {
    const m = meta[n.id];
    if (m.children) {
      const g = svgEl("g", { class: m.cls + (glowing.has(n.id) ? " glow" : ""), transform: `translate(${x},${y})` });
      g.append(svgEl("rect", { class: "frame", width: n.width, height: n.height, rx: 14 }));
      const t = svgEl("text", { class: "label", x: 16, y: 25 });
      t.textContent = m.label;
      g.append(t);
      if (m.concept) { g.classList.add("clickable"); t.onclick = (ev) => { ev.stopPropagation(); if (!moved) onClick(n.id); }; }
      boxG.append(g);
      continue;
    }
    const g = svgEl("g", { class: m.cls + (n.id === sel ? " sel" : "") + (glowing.has(n.id) ? " glow" : ""), transform: `translate(${x},${y})`, tabindex: 0 });
    if (m.stack) g.append(svgEl("rect", { class: "stack", x: 4, y: 4, width: n.width, height: n.height, rx: 10 }));
    g.append(svgEl("rect", { class: "body", width: n.width, height: n.height, rx: m.sym ? 8 : 10 }));
    if (!m.sym && !m.cls.includes("ctx") && !m.cls.includes("ext")) g.append(svgEl("rect", { class: "stripe", width: 4, height: n.height - 16, x: 0, y: 8, rx: 2 }));
    if (m.sym || m.more) drawSym(g, m, n);
    else {
      const ctx = m.cls.includes("ctx");
      if (ctx) g.append(svgEl("circle", { class: "dot", cx: 14, cy: 19, r: 4 }));
      const name = svgEl("text", { class: "name", x: ctx ? 24 : 16, y: ctx ? 24 : 26 });
      name.textContent = m.name;
      g.append(name);
      if (m.env) g.append(envPill(`env ${m.env}`, n.width - textW(`env ${m.env}`, 600, 10.5, true) - 22, 9, `${m.env} environment variable${m.env > 1 ? "s" : ""} read here`));
      m.lines.forEach((line, i) => {
        const t = svgEl("text", { class: "sum", x: 16, y: 46 + i * 16 });
        t.textContent = line;
        g.append(t);
      });
    }
    if (sel && rects[sel] && symById[sel] && !near.has(n.id) && n.id !== sel) g.classList.add("dim");
    g.onclick = (ev) => { ev.stopPropagation(); if (!moved) onClick(n.id); };
    g.ondblclick = (ev) => { ev.stopPropagation(); if (onDbl) onDbl(n.id); };
    g.onkeydown = (ev) => { if (ev.key === "Enter") onClick(n.id); };
    g.onmouseenter = () => hot(edgeEls, n.id, true);
    g.onmouseleave = () => hot(edgeEls, n.id, false);
    nodeG.append(g);
  }
  if (sel && symById[sel]) hot(edgeEls, sel, true);
  svg.onclick = () => { if (!moved && view.sel) go(view.focus, null, { v: view.mode }); };

  content = { w: out.width, h: out.height };
  fit(false);
  const z = Number(new URLSearchParams(location.search).get("zoom")); // ?zoom=2 opens zoomed in, for screenshots
  if (z && !enter) zoomBy(1 / z);
  if (restore) setCam(restore);
  else if (enter && enter.from && rects[enter.from]) {
    const target = { ...cam };
    setCam(around(rects[enter.from], 1.6));
    animate(target, 320);
  } else if (enter && enter.zoomIn) {
    const target = { ...cam };
    setCam({ x: cam.x + cam.w * 0.2, y: cam.y + cam.h * 0.2, w: cam.w * 0.6, h: cam.h * 0.6 });
    animate(target, 300);
  }
}

function envPill(text, x, y, title) {
  const w = textW(text, 600, 10.5, true) + 12;
  const p = svgEl("g", { class: "env", transform: `translate(${x},${y})` });
  const t = svgEl("text", { x: 6, y: 12 });
  t.textContent = text;
  const tt = svgEl("title");
  tt.textContent = title;
  p.append(svgEl("rect", { width: w, height: 17, rx: 4 }), t, tt);
  return p;
}

function drawSym(g, m, n) {
  const name = svgEl("text", { class: "name", x: 12, y: m.more ? 20 : 19 });
  name.textContent = m.name;
  g.append(name);
  if (m.more) return;
  const kind = svgEl("text", { class: "kind", x: 12, y: 36 });
  kind.textContent = m.sym.kind;
  g.append(kind);
  if (m.envText) g.append(envPill(m.envText, 12 + textW(m.sym.kind, 400, 11) + 8, 24, (m.sym.env || []).map(envName).join(", ")));
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
  for (const x of edgeEls) if (x.a === id || x.b === id) x.g.classList.toggle("hot", on);
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
  for (const id of ["arrow", "arrow-int"]) {
    const m = svgEl("marker", { id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
    m.append(svgEl("path", { d: "M0,1 L9,5 L0,9 z", fill: "context-stroke" }));
    d.append(m);
  }
  return d;
}

function empty(msg) {
  setStage("diagram");
  const svg = document.getElementById("diagram");
  svg.replaceChildren();
  const t = svgEl("text", { class: "empty", x: 200, y: 24, "text-anchor": "middle" });
  t.textContent = msg;
  svg.append(t);
  content = { w: 400, h: 40 };
  fit(false);
}

function setStage(mode) {
  const stage = document.getElementById("stage");
  stage.dataset.mode = mode;
  const f = view.focus && byId[view.focus];
  const toggle = document.getElementById("toggle");
  toggle.hidden = !(f && !f.children && sketchable(f));
  toggle.replaceChildren();
  if (!toggle.hidden) for (const [v, label] of [[null, "Sketch"], ["code", "Code"]]) {
    const b = el("button", (view.mode === "code") === (v === "code") ? "on" : "", label);
    b.onclick = () => go(view.focus, view.sel, { v, w: view.screen });
    toggle.append(b);
  }
}

// ---------- legend ----------

function legend(items, integration, ghosts, env) {
  const lg = document.getElementById("legend");
  lg.replaceChildren();
  const roles = new Set(items.filter((c) => !c.ext).map((c) => c.role));
  const kinds = new Set(items.filter((c) => c.ext).map((c) => c.kind));
  for (const [k, label] of Object.entries(ROLES)) if (roles.has(k)) lg.append(swatch("role-" + k, label));
  for (const [k, label] of Object.entries(KINDS)) if (kinds.has(k)) lg.append(swatch("ext kind-" + k, label));
  if (integration) lg.append(lineKey("integration", "Integration point"));
  if (ghosts) lg.append(swatch("ghost", "In another concept"));
  if (env || items.some((c) => envOf(c).length)) { const k = el("div", "key"); k.append(el("span", "envkey", "env"), el("span", "", "Env vars read")); lg.append(k); }
  lg.hidden = !lg.childElementCount;
}

function swatch(cls, label) {
  const li = el("div", "key");
  li.append(el("span", "sw " + cls), el("span", "", label));
  return li;
}

function lineKey(cls, label) {
  const li = el("div", "key");
  li.append(el("span", "ln " + cls), el("span", "", label));
  return li;
}

// ---------- camera: zoom and pan by moving the SVG viewBox, so text stays vector-crisp ----------

let cam = { x: 0, y: 0, w: 100, h: 100 };
let content = { w: 100, h: 100 };
let rects = {};
let moved = false;
let anim = null;

function setCam(c) {
  cam = c;
  document.getElementById("diagram").setAttribute("viewBox", `${c.x} ${c.y} ${c.w} ${c.h}`);
}

function stageSize() {
  const s = document.getElementById("diagram").getBoundingClientRect();
  return { w: s.width || 800, h: s.height || 600 };
}

// Fit the content into the stage, keeping clear of the legend on the left.
function fitCam() {
  const s = stageSize(), pad = 48;
  const lg = document.getElementById("legend");
  const left = lg.hidden ? 0 : lg.offsetWidth + 16;
  const k = Math.min(1.4, (s.w - left - pad) / content.w, (s.h - pad) / content.h);
  const w = s.w / k, h = s.h / k;
  return { x: content.w / 2 - w / 2 - left / 2 / k, y: content.h / 2 - h / 2, w, h };
}

function fit(animated) { animated ? animate(fitCam(), 250) : setCam(fitCam()); }

// A camera that frames rect r with some margin, at the stage's aspect ratio.
function around(r, margin) {
  const s = stageSize();
  const k = Math.min(s.w / (r.w * margin), s.h / (r.h * margin));
  const w = s.w / k, h = s.h / k;
  return { x: r.x + r.w / 2 - w / 2, y: r.y + r.h / 2 - h / 2, w, h };
}

function zoomBy(f, px, py) {
  const s = stageSize();
  const cx = px == null ? cam.x + cam.w / 2 : cam.x + (px / s.w) * cam.w;
  const cy = py == null ? cam.y + cam.h / 2 : cam.y + (py / s.h) * cam.h;
  const w = Math.min(Math.max(cam.w * f, 120), content.w * 8);
  const k = w / cam.w;
  setCam({ x: cx - (cx - cam.x) * k, y: cy - (cy - cam.y) * k, w, h: cam.h * k });
}

function animate(to, ms, done) {
  cancelAnimationFrame(anim);
  const from = { ...cam }, t0 = performance.now();
  const ease = (t) => 1 - Math.pow(1 - t, 3);
  const step = (now) => {
    const t = Math.min(1, (now - t0) / ms), e = ease(t);
    setCam({ x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e, w: from.w + (to.w - from.w) * e, h: from.h + (to.h - from.h) * e });
    if (t < 1) anim = requestAnimationFrame(step);
    else if (done) done();
  };
  anim = requestAnimationFrame(step);
}

function zoomInto(id, done) {
  if (!rects[id]) return done();
  camBeforeZoom = { ...cam };
  animate(around(rects[id], 1.3), 220, done);
}

function initCamera() {
  const svg = document.getElementById("diagram");
  svg.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    const r = svg.getBoundingClientRect();
    // Figma convention: scroll pans both axes; pinch (arrives as ctrl+wheel) or Cmd/Ctrl+wheel zooms at the cursor.
    if (ev.ctrlKey || ev.metaKey) return zoomBy(Math.exp(ev.deltaY * 0.01), ev.clientX - r.left, ev.clientY - r.top);
    const line = ev.deltaMode === 1 ? 16 : 1; // some mice report lines, not pixels
    const s = stageSize();
    setCam({ ...cam, x: cam.x + ev.deltaX * line * cam.w / s.w, y: cam.y + ev.deltaY * line * cam.h / s.h });
  }, { passive: false });
  let start = null;
  svg.addEventListener("pointerdown", (ev) => {
    start = { x: ev.clientX, y: ev.clientY, cam: { ...cam } };
    moved = false;
  });
  svg.addEventListener("pointermove", (ev) => {
    if (!start) return;
    const dx = ev.clientX - start.x, dy = ev.clientY - start.y;
    if (!moved && Math.hypot(dx, dy) < 4) return;
    if (!moved) { moved = true; svg.setPointerCapture(ev.pointerId); svg.classList.add("panning"); }
    const s = stageSize();
    setCam({ ...start.cam, x: start.cam.x - dx * start.cam.w / s.w, y: start.cam.y - dy * start.cam.h / s.h });
  });
  const end = () => { start = null; svg.classList.remove("panning"); setTimeout(() => (moved = false), 0); };
  svg.addEventListener("pointerup", end);
  svg.addEventListener("pointercancel", end);
  svg.addEventListener("dblclick", (ev) => { if (ev.target === svg || ev.target.closest(".boundary, .group")) fit(true); });
  document.getElementById("stage").addEventListener("click", () => {
    glow = false;
    for (const x of document.querySelectorAll("#diagram .glow")) x.classList.remove("glow");
  }, true);
  document.getElementById("zin").onclick = () => zoomBy(1 / 1.25);
  document.getElementById("zout").onclick = () => zoomBy(1.25);
  document.getElementById("zfit").onclick = () => fit(true);
  addEventListener("resize", () => { if (!location.search.includes("zoom")) fit(false); });
}

// ---------- drawer ----------

function integrationPoints(c) {
  const inside = (id) => !c || id === c.id || ancestors(id).includes(c.id);
  return M.relationships.filter((r) => r.at && (c && c.ext ? r.from === c.id || r.to === c.id : inside(r.from.startsWith("x.") ? r.to : r.from)));
}

function integrationList(d, points) {
  if (!points.length) return;
  d.append(el("h3", "", "Integration points"));
  const ul = el("ul", "ints");
  for (const r of points) {
    const li = el("li");
    const head = el("div", "rel");
    const a = byId[r.from], b = byId[r.to];
    const nav = (x) => link(x.name, () => (x.ext ? go(view.focus, x.id) : jump(x.id, null, { force: true })));
    head.append(nav(a), " → ", nav(b));
    const [file, fn] = r.at.split(":");
    const foot = el("div", "where");
    foot.append(el("span", "pill", r.via), el("span", "path", `${file.split("/").pop()} · ${fn}`));
    foot.title = r.at;
    li.append(head, foot);
    ul.append(li);
  }
  d.append(ul);
}

function envList(d, c) {
  const env = c ? envOf(c) : M.concepts.flatMap(envOf);
  if (!env.length) return;
  d.append(el("h3", "", "Environment"));
  const ul = el("ul", "ints");
  for (const e of env.sort((a, b) => a.name.localeCompare(b.name))) {
    const li = el("li");
    const head = el("div", "envrow");
    head.append(el("span", "envname", envName(e.name)));
    if (e.default != null) head.append(el("span", "path", `default ${e.default || '""'}`));
    const who = el("div", "rel");
    const syms = [...new Set(e.symbols)].map((id) => symById[id]);
    if (syms.length) syms.forEach((x, i) => { if (i) who.append(", "); who.append(link(x.name, () => jump(x.leaf.id, x.id, { force: true }))); });
    else who.append("read at module level in ", link(e.leaf.name, () => jump(e.leaf.id, null, { force: true })));
    li.append(head, who);
    ul.append(li);
  }
  d.append(ul);
}

function drawer() {
  const d = document.getElementById("drawer");
  d.replaceChildren();
  const s = view.sel && symById[view.sel];
  const here = view.focus && byId[view.focus];
  if (s && here && !here.children && s.leaf !== here) return linkDrawer(d, here, s);
  if (s) return symbolDrawer(d, s);
  const g = view.sel && ghostById[view.sel];
  const c = byId[view.sel] || byId[view.focus];
  if (!c) {
    d.append(el("h2", "", M.workspace), el("p", "", M.summary));
    d.append(el("h3", "", "Reading this map"));
    d.append(el("p", "", "Coloured boxes are parts of the system, inside its boundary. Dashed boxes are outside it. Click to open. Scroll or drag to pan, pinch or Cmd+scroll to zoom. Esc goes up."));
    integrationList(d, integrationPoints(null));
    envList(d, null);
    return;
  }
  d.append(el("h2", "", c.name), el("p", "", c.summary));
  if (c.children) list(d, "Parts", c.children.map((k) => link(k.name, () => go(k.id))));
  integrationList(d, integrationPoints(c));
  if (!c.ext) envList(d, c);

  const rels = M.relationships.filter((r) => (r.from === c.id || r.to === c.id) && r.label !== TYPES && !r.at);
  if (rels.length) list(d, "Relationships", rels.map((r) => {
    const li = el("span", "rel");
    const other = byId[r.from === c.id ? r.to : r.from];
    const b = link(other.name, () => (other.ext ? go(view.focus, other.id) : jump(other.id, null, { force: true })));
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

// A ghost is selected: show every call between its concept and this one, both ways.
function linkDrawer(d, here, s) {
  const there = s.leaf;
  d.append(el("h2", "", s.name), el("p", "", `${s.kind} in ${there.name}`));
  const go2 = el("button", "action", `Go to ${there.name}`);
  go2.onclick = () => jump(there.id, s.id, { force: true });
  d.append(go2);
  const name = (id) => link(`${symById[id].name} (${symById[id].leaf.name})`, () => go(view.focus, id, { v: view.mode }));
  for (const [a, b] of [[there, here], [here, there]]) {
    const rows = here.calls.filter(([x, y]) => symById[x] && symById[y] && symById[x].leaf === a && symById[y].leaf === b);
    if (!rows.length) continue;
    list(d, `${a.name} → ${b.name}`, rows.map(([x, y, verb]) => {
      const li = el("span", "rel" + (x === s.id || y === s.id ? " on" : ""));
      li.append(name(x), ` ${verb} `, name(y));
      return li;
    }));
  }
}

// Functions with their owning concept and module, grouped by concept (own concept first) when several appear.
function callList(d, title, ids, home) {
  const syms = [...new Set(ids)].map((id) => symById[id]).filter(Boolean);
  if (!syms.length) return;
  const groups = new Map([[home, []]]);
  for (const x of syms) (groups.get(x.leaf) || groups.set(x.leaf, []).get(x.leaf)).push(x);
  const used = [...groups].filter(([, xs]) => xs.length);
  const conceptLink = (c) => link(c.name, () => jump(c.id, null, { force: true }));
  const item = (x, withConcept) => {
    const li = el("span", "callrow");
    li.append(link(x.name, () => jump(x.leaf.id, x.id, { force: true })));
    if (withConcept) li.append(el("span", "dot", " · "), x.leaf === home ? el("span", "here", x.leaf.name) : conceptLink(x.leaf));
    li.append(el("span", "module", ` · ${x.file.split("/").pop()}`));
    return li;
  };
  d.append(el("h3", "", `${title} (${syms.length})`));
  const ul = el("ul", "calls");
  for (const [c, xs] of used) {
    if (used.length > 1) {
      const head = el("li", "group");
      head.append(c === home ? el("span", "", `${c.name} (here)`) : conceptLink(c));
      ul.append(head);
    }
    for (const x of xs) { const li = el("li", used.length > 1 ? "indent" : ""); li.append(item(x, used.length === 1)); ul.append(li); }
  }
  d.append(ul);
}

function symbolDrawer(d, s) {
  d.append(el("h2", "", s.name), el("p", "", `${s.kind} in ${s.leaf.name}`));
  if (s.sig) d.append(el("div", "sig", s.sig));
  if (s.env) list(d, "Environment", s.env.map((n) => el("span", "envname", envName(n))));
  d.append(el("h3", "", "Where"), el("div", "path", `${s.file}:${s.line}`));
  const out = s.leaf.calls.filter(([a]) => a === s.id), into = s.leaf.calls.filter(([, b]) => b === s.id);
  const pick = (rows, verb, end) => rows.filter((r) => r[2] === verb).map((r) => r[end]);
  callList(d, "Calls", pick(out, "calls", 1), s.leaf);
  callList(d, "Renders", pick(out, "renders", 1), s.leaf);
  callList(d, "Called by", pick(into, "calls", 0), s.leaf);
  callList(d, "Rendered by", pick(into, "renders", 0), s.leaf);
  list(d, `Tests (${s.tests.length})`, s.tests.length ? s.tests.slice(0, 12).map((t) => el("span", "", t)) : [el("span", "rel", "No test links found by static analysis.")]);
  if (s.tests.length > 12) d.append(el("p", "", `and ${s.tests.length - 12} more`));
}

function leafList(c) { return c.children ? c.children.flatMap(leafList) : [c]; }

// Env vars read anywhere under a concept, merged by name. "*" is the whole environment passed on.
function envOf(c) {
  if (c.ext) return [];
  const out = {};
  for (const l of leafList(c)) for (const e of l.env || []) {
    const x = (out[e.name] ||= { name: e.name, default: e.default, symbols: [], leaf: l });
    x.symbols.push(...e.symbols);
  }
  return Object.values(out);
}
const envName = (n) => (n === "*" ? "whole env" : n);

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
  for (const l of Object.values(byId).filter((c) => c.env)) for (const e of l.env) {
    if (e.name !== "*") entries.push({ name: e.name, text: e.name.toLowerCase(), kind: `env var · ${l.name}`, c: l });
  }
  const q = document.getElementById("q"), hits = document.getElementById("hits");
  let shown = [], on = 0;
  const pick = (h) => {
    hits.hidden = true;
    q.value = "";
    q.blur();
    if (h.s) jump(h.s.leaf.id, h.s.id, { force: true });
    else if (h.c.ext) jump(null, h.c.id, { force: true });
    else jump(h.c.id, null, { force: true });
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
    if (ev.key === "Escape") { q.value = ""; shown = []; paint(); q.blur(); }
  };
  q.onblur = () => setTimeout(() => (hits.hidden = true), 100);
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
    let lastLine = lines[max - 1];
    while (textW(lastLine + "…", 400, size) > width) lastLine = lastLine.replace(/\s*\S+$/, "");
    lines.splice(max - 1, Infinity, lastLine + "…");
  }
  return lines;
}
