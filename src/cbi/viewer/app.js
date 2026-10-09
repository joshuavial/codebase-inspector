// Concept map. Data arrives through cbiLoad() from data/diff.js, data/concepts.js,
// data/context.js, data/editor.js and data/tree.js.
// Agent-written text is only ever set with textContent.

const TYPES = "uses types from";
const SVG = "http://www.w3.org/2000/svg";
const ROLES = { ui: "Interface", app: "App or process", service: "Service", core: "Core logic", data: "Data and model" };
const KINDS = { platform: "Platform service", cli: "CLI tool", saas: "SaaS or API", terminal: "Terminal or OS", storage: "Storage" };
const GHOSTS_PER_GROUP = 5;
const elk = new ELK();
const byId = {};    // concept or external id -> object
const parentOf = {}; // concept id -> parent id (null at top)
const symById = {}; // symbol id -> symbol (with .leaf)
const ghostById = {}; // foreign symbol id -> { name, kind, concept }
let fileOwner = null; // repo path -> leaf concept id, for code edges that name a file
let M = null;
let AGENT = { workspace: "", blocks: {} };
let toastTimer = 0;
let view = { focus: null, sel: null, mode: null, screen: null, overlay: null };
let last = null; // the previous view, null before the first render
let treeNodes = null;
let treeAdded = false;
let lateralHash = null; // where the last lateral jump landed
let glow = false; // highlight where we jumped from, until the next click in the stage
let restore = null; // camera to reuse instead of fitting
let glowTimer = null;
let refit = false; // the same view changed shape (a group opened or closed): fit again instead of keeping the camera
const camByHash = {};
let depth = 0; // history entries this page has pushed; Backspace will not step past the start
let layoutGen = 0; // a newer diagram cancels an in-flight layout
let writing = false; // ignore the hashchange that a pushState echoes in some browsers
let HEAD = null; // the head payload, kept intact so the base toggle can derive another model
let DIFF = null;
let shownSide = null;
let searchReady = false;
let CONCEPT_MARK = new Map();
let PROVISIONAL = new Set();
let ADDED = new Set();
let HEAD_ONLY = new Set();
let SYMBOL_MARK = new Map();
let REMOVED_SYMS = [];
let REL_MARK = new Map();
let HISTORY = null;
let historyIndex = -1;
let historyCompare = false;

function cbiLoad(name, value) {
  if (name === "context") {
    AGENT = value || AGENT;
    return;
  }
  if (name === "diff") {
    DIFF = value || null;
    if (DIFF) indexDiff(DIFF);
    return;
  }
  if (name === "history") {
    HISTORY = value && Array.isArray(value.entries) && value.entries.length ? value : null;
    return;
  }
  if (name === "tree") {
    treeNodes = value.nodes || [];
    addTreeHits();
    document.documentElement.dataset.cbiTree = "1";
    return;
  }
  if (name === "editor") {
    if (typeof cbiSetEditor === "function") cbiSetEditor(value);
    return;
  }
  if (name === "concepts") loadConcepts(value);
}

// One file the editor can open. A grey node is one of these, drawn in another concept.
const OPEN_KINDS = new Set(["file", "source file", "test file", "class", "function", "method", "component", "interface", "test case"]);

function openTargetFor(id) {
  const s = symById[id];
  if (!s || !s.file) return null;
  if (ghostById[id] || OPEN_KINDS.has(s.kind)) return { file: s.file, line: s.line || 1 };
  return null;
}

function loadConcepts(data) {
  HEAD = data;
  const first = !searchReady;
  if (first) {
    history.replaceState({ cbi: 0 }, "", location.href);
    // popstate and hashchange both fire for one browser back. The second one is the same view.
    const onHistory = () => {
      if (writing) return;
      const next = (history.state && history.state.cbi) || 0;
      if (last && last.hash === location.hash && depth === next) return;
      depth = next;
      route();
    };
    addEventListener("hashchange", onHistory);
    addEventListener("popstate", onHistory);
    addEventListener("keydown", onKey);
    initCamera();
    initOverlay();
    initCompare();
    initHistory();
  }
  route();
  if (first || shownSide) initSearch();
  searchReady = true;
}

// ---------- comparison ----------

function indexDiff(diff) {
  CONCEPT_MARK = new Map();
  PROVISIONAL = new Set(diff.provisional || []);
  ADDED = new Set();
  HEAD_ONLY = new Set();
  SYMBOL_MARK = new Map();
  REMOVED_SYMS = [];
  REL_MARK = new Map();
  const rank = { changed: 1, provisional: 2, added: 3, removed: 4 };
  const setConcept = (id, mark) => {
    if (!id) return;
    const prev = CONCEPT_MARK.get(id);
    if (!prev || rank[mark] >= rank[prev]) CONCEPT_MARK.set(id, mark);
  };
  const markRel = (rec, mark) => {
    if (!rec || !rec.from) return;
    const key = rec.from + "\0" + rec.to + "\0" + (rec.label || "");
    const set = REL_MARK.get(key) || new Set();
    set.add(mark);
    REL_MARK.set(key, set);
  };
  for (const g of (diff.changes && diff.changes.groups) || []) {
    // A deployable or package stands in for a concept when the model has no concept map.
    if (g.id && (g.kind === "concept" || g.kind === "deployable" || g.kind === "package" || g.kind === "folder"))
      setConcept(g.id, "changed");
    for (const ch of g.changes) {
      if (ch.kind === "concept-added") { setConcept(ch.after.id, "added"); ADDED.add(ch.after.id); }
      else if (ch.kind === "concept-removed") setConcept(ch.before.id, "removed");
      else if (ch.kind === "concept-renamed") {
        setConcept(ch.after.id, "changed");
        if (ch.before.id !== ch.after.id) { setConcept(ch.before.id, "removed"); HEAD_ONLY.add(ch.after.id); }
      } else if (ch.kind === "concept-split") {
        setConcept(ch.before.id, "removed");
        for (const part of ch.after || []) { setConcept(part.id, "added"); ADDED.add(part.id); }
      } else if (ch.kind === "concept-merged") {
        setConcept(ch.after.id, "changed");
        HEAD_ONLY.add(ch.after.id);
        for (const part of ch.before || []) setConcept(part.id, "removed");
      } else if ((ch.kind === "deployable-added" || ch.kind === "package-added") && ch.after) {
        setConcept(ch.after.id, "added"); ADDED.add(ch.after.id);
      } else if ((ch.kind === "deployable-removed" || ch.kind === "package-removed") && ch.before) {
        setConcept(ch.before.id, "removed");
      } else if (ch.kind === "symbol-added" && ch.after) SYMBOL_MARK.set(ch.after.id, "added");
      else if (ch.kind === "symbol-removed" && ch.before) {
        SYMBOL_MARK.set(ch.before.id, "removed");
        if (g.kind === "concept") REMOVED_SYMS.push({
          id: ch.before.id, name: ch.before.name, kind: ch.before.display_kind || "function",
          file: ch.before.path || "", line: 0, concept: g.id, tests: [],
        });
      } else if ((ch.kind === "symbol-changed" || ch.kind === "symbol-moved") && ch.code && ch.code[0]) {
        SYMBOL_MARK.set(ch.code[0].id, "changed");
        if (ch.after && ch.after.id) SYMBOL_MARK.set(ch.after.id, "changed");
      } else if (ch.kind === "render-added" || ch.kind === "render-removed") {
        const rec = ch.after || ch.before;
        if (rec && rec.from && !SYMBOL_MARK.has(rec.from)) SYMBOL_MARK.set(rec.from, "changed");
      }
      const rec = ch.after || ch.before;
      if (ch.kind === "relationship-added" || ch.kind === "integration-added") markRel(rec, "new");
      else if (ch.kind === "relationship-removed" || ch.kind === "integration-removed") markRel(rec, "removed");
      else if (ch.kind === "relationship-volume") markRel(ch.after || rec, "volume");
      else if (ch.kind === "integration-changed") markRel(ch.after, "mechanism");
    }
  }
}

function relChangeClass(rels) {
  if (!DIFF) return "";
  const marks = new Set();
  for (const r of rels || []) {
    const hit = REL_MARK.get(r.from + "\0" + r.to + "\0" + (r.label || ""));
    if (hit) for (const m of hit) marks.add("chg-" + m);
  }
  return [...marks].join(" ");
}

const MARK_LABEL = { new: "new", removed: "removed", volume: "volume changed", mechanism: "mechanism changed" };

function conceptTag(id) {
  if (!DIFF || !byId[id] || byId[id].ext) return null;
  if (PROVISIONAL.has(id)) return "provisional";
  return CONCEPT_MARK.get(id) || null;
}

function conceptClass(id) {
  if (!DIFF) return "";
  const marks = [];
  const own = CONCEPT_MARK.get(id);
  if (own) marks.push("chg-" + own);
  if (PROVISIONAL.has(id)) marks.push("chg-provisional");
  return marks.length ? " " + marks.join(" ") : "";
}

function symbolMark(id) {
  return SYMBOL_MARK.get(id) || null;
}

function clearIndex() {
  fileOwner = null;
  for (const obj of [byId, parentOf, symById, ghostById]) {
    for (const key of Object.keys(obj)) delete obj[key];
  }
}

function indexModel(data) {
  fileOwner = null;
  const walk = (cs, parent) => cs.forEach((c) => {
    byId[c.id] = c;
    parentOf[c.id] = parent;
    if (c.children) walk(c.children, c.id);
    for (const s of c.symbols || []) symById[s.id] = Object.assign(s, { leaf: c });
    Object.assign(ghostById, c.ghosts || {});
  });
  walk(data.concepts || [], null);
  for (const x of data.externals || []) { byId[x.id] = Object.assign(x, { ext: true }); parentOf[x.id] = null; }
}

function rollupMarks() {
  if (!DIFF) return;
  for (const id of Object.keys(byId)) {
    if (byId[id].ext || CONCEPT_MARK.has(id)) continue;
    const leaves = leafList(byId[id]);
    if (leaves.some((leaf) => leaf.id !== id && (CONCEPT_MARK.has(leaf.id) || PROVISIONAL.has(leaf.id))))
      CONCEPT_MARK.set(id, "changed");
  }
}

function derive(side) {
  const data = structuredClone(HEAD);
  const hide = side === "base" ? new Set([...ADDED, ...HEAD_ONLY]) : null;
  if (hide && hide.size) data.concepts = filterConcepts(data.concepts, hide);
  graft(data, (DIFF.removed && DIFF.removed.concepts) || []);
  const drop = side === "base" ? "new" : null;
  if (drop) data.relationships = (data.relationships || []).filter((r) => !relChangeClass([r]).split(" ").includes("chg-" + drop));
  const have = new Set((data.relationships || []).map((r) => r.from + "\0" + r.to + "\0" + (r.label || "")));
  for (const rel of (DIFF.removed && DIFF.removed.relationships) || []) {
    const key = rel.from + "\0" + rel.to + "\0" + (rel.label || "");
    if (!have.has(key)) { data.relationships.push(structuredClone(rel)); have.add(key); }
  }
  const ext = new Set((data.externals || []).map((e) => e.id));
  for (const external of (DIFF.removed && DIFF.removed.externals) || []) {
    if (!ext.has(external.id)) data.externals.push(structuredClone(external));
  }
  if (side === "base") {
    for (const g of DIFF.changes.groups) for (const ch of g.changes) {
      if (ch.kind === "integration-changed" && ch.before) {
        const rel = data.relationships.find((r) => r.from === ch.before.from && r.to === ch.before.to && (r.label || "") === (ch.before.label || ""));
        if (!rel) continue;
        if (ch.before.mechanism) rel.via = ch.before.mechanism;
        else delete rel.via;
        if (ch.before.at) rel.at = ch.before.at;
        else delete rel.at;
      } else if (ch.kind === "concept-renamed" && ch.before.id === ch.after.id) {
        const node = findConcept(data.concepts, ch.before.id);
        if (node) node.name = ch.before.name;
      }
    }
    const ends = new Set();
    for (const rel of data.relationships) { ends.add(rel.from); ends.add(rel.to); }
    data.externals = data.externals.filter((e) => ends.has(e.id));
  }
  injectSymbols(data, side);
  return data;
}

function filterConcepts(nodes, hide) {
  const out = [];
  for (const node of nodes || []) {
    if (hide.has(node.id)) { out.push(...filterConcepts(node.children, hide)); continue; }
    if (node.children) node.children = filterConcepts(node.children, hide);
    out.push(node);
  }
  return out;
}

function findConcept(nodes, id) {
  for (const node of nodes || []) {
    if (node.id === id) return node;
    const kid = findConcept(node.children, id);
    if (kid) return kid;
  }
  return null;
}

function graft(data, roots) {
  const map = new Map();
  (function walk(nodes) { for (const node of nodes || []) { map.set(node.id, node); walk(node.children); } })(data.concepts);
  for (const node of roots) {
    if (map.has(node.id)) continue;
    const copy = structuredClone(node);
    const parentId = copy.parent;
    delete copy.parent;
    const parent = parentId && map.get(parentId);
    if (parent) { parent.children = parent.children || []; parent.children.push(copy); }
    else data.concepts.push(copy);
    (function walk(nodes) { for (const n of nodes || []) { map.set(n.id, n); walk(n.children); } })([copy]);
  }
}

function injectSymbols(data, side) {
  const leaves = new Map();
  (function walk(nodes) {
    for (const node of nodes || []) {
      if (node.children && node.children.length) walk(node.children);
      else leaves.set(node.id, node);
    }
  })(data.concepts);
  for (const rec of REMOVED_SYMS) {
    const leaf = leaves.get(rec.concept);
    if (!leaf) continue;
    leaf.symbols = leaf.symbols || [];
    if (!leaf.symbols.some((s) => s.id === rec.id)) leaf.symbols.push({ ...rec });
  }
  if (side === "base") {
    for (const leaf of leaves.values()) {
      if (leaf.symbols) leaf.symbols = leaf.symbols.filter((s) => SYMBOL_MARK.get(s.id) !== "added");
    }
  }
}

function showModel(side) {
  clearIndex();
  // Capture already holds this side's model. derive() rebuilds base from the head model.
  const data = DIFF && !window.cbiRender ? derive(side) : HEAD;
  M = data;
  indexModel(M);
  rollupMarks();
  document.title = (M.workspace || "codebase") + " · concept map";
}

function ensureModel() {
  if (!HEAD) return false;
  const side = new URLSearchParams(location.hash.slice(1)).get("side") === "base" ? "base" : "head";
  if (M && side === shownSide) return false;
  shownSide = side;
  showModel(side);
  if (searchReady) initSearch();
  return true;
}

function initCompare() {
  const bar = document.getElementById("compare");
  bar.onclick = (ev) => {
    const button = ev.target.closest("button");
    if (!button) return;
    go(view.focus, view.sel, { side: button.dataset.side, v: view.mode, w: view.screen });
  };
  document.getElementById("chg-toggle").onclick = () => document.body.classList.toggle("changes-open");
}

function paintCompare() {
  const on = !!DIFF && (!HISTORY || historyCompare);
  document.getElementById("compare").hidden = !on;
  document.getElementById("chg-toggle").hidden = !on;
  if (!on) return;
  for (const button of document.querySelectorAll("#compare button")) {
    button.classList.toggle("on", (button.dataset.side || "head") === (shownSide || "head"));
  }
}

function initHistory() {
  const bar = document.getElementById("timeline");
  if (!bar) return;
  if (!HISTORY) { bar.hidden = true; return; }
  bar.hidden = false;
  const entries = HISTORY.entries;
  const ticks = document.getElementById("history-ticks");
  const largest = Math.max(...entries.map((entry) => entry.change_count || 1), 1);
  entries.forEach((entry, index) => {
    const tick = el("button");
    tick.style.height = `${7 + Math.round(21 * Math.sqrt((entry.change_count || 1) / largest))}px`;
    tick.title = `${entry.date.slice(0, 10)} · ${entry.change_count} changes`;
    tick.onclick = () => showHistoryEntry(index, true);
    ticks.append(tick);
  });
  const scrub = document.getElementById("history-scrub");
  scrub.max = String(entries.length - 1);
  scrub.value = String(entries.length - 1);
  scrub.oninput = () => showHistoryEntry(Number(scrub.value), false);
  document.getElementById("history-back").onclick = () => showHistoryEntry(historyIndex, false);
  showHistoryEntry(entries.length - 1, false);
}

function showHistoryEntry(index, compare) {
  if (!HISTORY || !HISTORY.entries[index]) return;
  const entry = HISTORY.entries[index];
  historyIndex = index;
  historyCompare = !!compare;
  document.body.classList.toggle("history-compare", historyCompare);
  document.getElementById("history-back").hidden = !historyCompare;
  document.getElementById("history-scrub").value = String(index);
  for (const [at, tick] of [...document.querySelectorAll("#history-ticks button")].entries())
    tick.classList.toggle("on", at === index);
  DIFF = entry.diff;
  indexDiff(DIFF);
  HEAD = entry.model;
  shownSide = null;
  M = null;
  const detail = document.getElementById("history-entry");
  detail.replaceChildren();
  const pr = entry.pr ? ` · PR #${entry.pr}` : "";
  detail.append(el("span", "summary", `${entry.date.slice(0, 10)} · ${entry.sha.slice(0, 12)}${pr} · ${entry.author} · ${entry.change_count} changes`));
  const copy = el("button", "", "Copy for agent");
  copy.onclick = () => copyHistoryEntry(entry);
  detail.append(copy);
  if (!historyCompare) {
    const open = el("button", "", "Open comparison");
    open.onclick = () => showHistoryEntry(index, true);
    detail.append(open);
  }
  route();
}

function copyHistoryEntry(entry) {
  const day = entry.date.slice(0, 10);
  const text = `${entry.text.trim()}\n\nReproduce:\ncbi history --since ${day} --until ${day}\ncbi diff ${entry.base} ${entry.sha}\n`;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => showToast("Copied"), () => fallbackCopy(text));
  } else fallbackCopy(text);
}

function fallbackCopy(text) {
  const area = document.createElement("textarea");
  area.value = text;
  document.body.append(area);
  area.select();
  document.execCommand("copy");
  area.remove();
  showToast("Copied");
}

function groupFocus(g) {
  if (!g || !g.id) return null;
  if (g.kind !== "concept" && g.kind !== "deployable" && g.kind !== "package" && g.kind !== "folder") return null;
  const node = byId[g.id];
  return node && !node.ext ? g.id : null;
}

function changesPanel() {
  const panel = document.getElementById("changes");
  panel.hidden = !DIFF || (!!HISTORY && !historyCompare);
  if (panel.hidden) return;
  panel.replaceChildren();
  panel.append(el("h2", "", "Changes"));
  const base = DIFF.base ? String(DIFF.base).slice(0, 12) : "base";
  const head = DIFF.head ? String(DIFF.head).slice(0, 12) : "head";
  panel.append(el("p", "hint", `${base} → ${head}`));
  const groups = (DIFF.changes && DIFF.changes.groups) || [];
  if (!groups.length) { panel.append(el("p", "", "No architectural changes.")); return; }
  for (const g of groups) {
    const headEl = el("h3");
    const focus = groupFocus(g);
    if (focus) headEl.append(link(g.name, () => jump(focus, null, { force: true })));
    else headEl.append(document.createTextNode(g.name));
    panel.append(headEl);
    const ul = el("ul");
    for (const ch of g.changes) {
      const li = el("li");
      const target = changeTarget(ch, g);
      const text = ch.summary;
      if (target) li.append(link(text, () => jump(target.focus, target.sel, { force: true, extra: target.side ? { side: target.side } : {} })));
      else li.append(el("span", "", text));
      li.append(el("div", "kind", ch.kind));
      ul.append(li);
    }
    panel.append(ul);
  }
}

function changeTarget(ch, g) {
  const concept = groupFocus(g);
  const sideFor = (id) => (id && !byId[id] && (ADDED.has(id) || HEAD_ONLY.has(id)) && shownSide === "base" ? "head" : null);
  if (ch.kind.startsWith("symbol-") || ch.kind === "untested") {
    const id = (ch.after && ch.after.id) || (ch.before && ch.before.id) || (ch.code && ch.code[0] && ch.code[0].id);
    const shown = id && (symById[id] ? id : ownerShown(id));
    const sym = shown && symById[shown];
    if (sym) return { focus: sym.leaf.id, sel: shown, side: sideFor(sym.leaf.id) };
    if (concept) return { focus: concept, sel: null, side: null };
  }
  if (ch.kind.startsWith("concept-")) {
    const after = ch.after && !Array.isArray(ch.after) ? ch.after.id : null;
    const before = ch.before && !Array.isArray(ch.before) ? ch.before.id : null;
    const id = (after && byId[after] && after) || (before && byId[before] && before) || concept;
    if (id && byId[id] && !byId[id].ext) return { focus: id, sel: null, side: null };
    if (after && sideFor(after)) return { focus: after, sel: null, side: "head" };
  }
  const rec = ch.after || ch.before;
  if (rec && rec.from && byId[rec.from] && !byId[rec.from].ext) return { focus: rec.from, sel: null, side: null };
  if (concept) return { focus: concept, sel: null, side: null };
  return null;
}

function ownerShown(id) {
  if (symById[id]) return id;
  if (!treeNodes) return null;
  const by = new Map(treeNodes.map((n) => [n.id, n]));
  let node = by.get(id);
  const seen = new Set();
  while (node && !seen.has(node.id)) {
    seen.add(node.id);
    if (symById[node.id]) return node.id;
    node = node.parent_id ? by.get(node.parent_id) : null;
  }
  return null;
}

function unified(before, after) {
  const a = String(before == null ? "" : before).split("\n");
  const b = String(after == null ? "" : after).split("\n");
  if (a.length * b.length > 40000) {
    return [...a.map((text) => ({ kind: "del", text })), ...b.map((text) => ({ kind: "add", text }))];
  }
  const n = a.length, m = b.length;
  const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  }
  const out = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ kind: "eq", text: a[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ kind: "del", text: a[i] }); i++; }
    else { out.push({ kind: "add", text: b[j] }); j++; }
  }
  while (i < n) out.push({ kind: "del", text: a[i++] });
  while (j < m) out.push({ kind: "add", text: b[j++] });
  return out;
}

function codeDiff(d, ids) {
  if (!DIFF || !DIFF.sources) return;
  const rows = ids.filter((id) => DIFF.sources[id]);
  if (!rows.length) return;
  d.append(el("h3", "", "Code diff"));
  for (const id of rows) {
    if (rows.length > 1) d.append(el("p", "hint", (symById[id] && symById[id].name) || id.split("#").pop()));
    const box = el("div", "diff");
    const src = DIFF.sources[id];
    for (const line of unified(src.base || "", src.head || "")) {
      const prefix = line.kind === "add" ? "+ " : line.kind === "del" ? "- " : "  ";
      box.append(el("div", "diff-" + line.kind, prefix + line.text));
    }
    d.append(box);
  }
}

function diffIds(s) {
  if (!DIFF || !DIFF.sources) return [];
  const ids = [];
  if (DIFF.sources[s.id]) ids.push(s.id);
  for (const id of Object.keys(DIFF.sources)) {
    if (id !== s.id && ownerShown(id) === s.id) ids.push(id);
  }
  return ids;
}

// ---------- navigation ----------

// Push a view, or replace the current one while a jump's return path is still in effect.
// Replacing keeps browser back and Backspace on the same step: the view we jumped from.
function writeHash(hash, { replace = false } = {}) {
  const cur = location.hash.replace(/^#/, "");
  if (cur === hash) return;
  const base = location.href.split("#")[0];
  const url = hash ? `${base}#${hash}` : base;
  writing = true;
  if (replace) history.replaceState({ cbi: depth }, "", url);
  else {
    depth += 1;
    history.pushState({ cbi: depth }, "", url);
  }
  writing = false;
  route();
}

// The concept a jump came from. "~" is the workspace, whose focus is null.
function originFocus() { return view.from === "~" ? null : view.from; }

function go(focus, sel, extra = {}) {
  // Landing back on the origin restores its zoom and selection, same as the chip.
  const home = view.from && !("from" in extra) && (focus || null) === originFocus()
    && !sel && !extra.v && !extra.w && !("t" in extra);
  if (home) { back(); return; }
  const h = new URLSearchParams();
  if (focus) h.set("c", focus);
  if (sel) h.set("s", sel);
  // The chip stays on until the origin itself: drills, selections and going up all keep it.
  const keep = view.from && (focus || null) !== originFocus() && !("from" in extra);
  if (keep) {
    h.set("from", view.from);
    h.set("bh", view.backHash);
  }
  for (const [k, v] of Object.entries(extra)) if (k !== "t" && k !== "side" && v) h.set(k, v);
  const cur = new URLSearchParams(location.hash.slice(1));
  const t = "t" in extra ? extra.t : cur.get("t");
  if (t) h.set("t", t);
  // side=base is the only value written; head is the bare URL, so a toggle back clears it.
  const side = "side" in extra ? extra.side : cur.get("side");
  if (side === "base") h.set("side", "base");
  writeHash(h.toString(), { replace: keep });
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
  // One step, the same step browser back takes. A shared link has no step behind it, so use the saved hash.
  if (depth > 0) history.back();
  else writeHash(view.backHash === "-" ? "" : view.backHash, { replace: true });
}

const originName = (id) => (id === "~" ? M.workspace : byId[id].name);

function route() {
  const rebuilt = ensureModel();
  if (rebuilt) refit = true;
  const h = new URLSearchParams(location.hash.slice(1));
  const first = !last;
  if (!first) camByHash[last.hash] = { ...cam };
  haltAnim();
  const prev = view;
  view = {
    focus: byId[h.get("c")] ? h.get("c") : null, sel: h.get("s"), mode: h.get("v"), screen: h.get("w"),
    from: byId[h.get("from")] || h.get("from") === "~" ? h.get("from") : null, backHash: h.get("bh") || "-",
    overlay: h.get("t"),
  };
  // A flat box has nothing to open. Select it on its parent's diagram (the top diagram, for a deployable).
  if (view.focus && byId[view.focus].flat) {
    const id = view.focus;
    view.sel = view.sel || id;
    view.focus = parentOf[id] || null;
  }
  paintOverlay();
  paintCompare();
  changesPanel();
  if (first) glow = !!view.from;
  if (/(^|[#&])debug\b/.test(location.hash) && !debug) { debug = true; const b = document.getElementById("debug"); b.hidden = false; b.textContent = "wheel readout on: scroll or swipe over the map"; }
  // Same diagram: keep the camera. A view seen before (Back): restore its camera.
  restore = refit ? null : !first && prev.focus === view.focus && prev.mode === view.mode ? { ...cam } : camByHash[location.hash] || null;
  refit = false;
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
  if ((ev.metaKey || ev.ctrlKey) && !ev.altKey && (ev.key === "c" || ev.key === "C")) {
    // Shift+C always copies the agent block. Plain Cmd/Ctrl+C does too, unless the
    // user is copying selected text or typing in a field.
    if (ev.shiftKey) {
      if (inField(ev.target)) return;
      ev.preventDefault();
      copyAgent();
      return;
    }
    if (wantsBrowserCopy(ev.target)) return;
    ev.preventDefault();
    copyAgent();
    return;
  }
  if (inField(ev.target)) return;
  if (ev.key === "Escape") up();
  else if (ev.key === "Backspace") {
    ev.preventDefault();
    if (view.from) back();
    else if (depth > 0) history.back();
  }
  else if (ev.key === "/") { document.getElementById("q").focus(); ev.preventDefault(); }
  else if (ev.key === "0" || ev.key === "f") fit(true, true);
  else if (ev.key === "+" || ev.key === "=") zoomBy(1 / 1.25);
  else if (ev.key === "-") zoomBy(1.25);
  else if (ev.key === "?") { debug = !debug; const b = document.getElementById("debug"); b.hidden = !debug; b.textContent = "wheel readout on: scroll or swipe over the map"; }
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
    const name = id ? byId[id].name : M.workspace;
    nav.append(lastCrumb ? el("span", "here", name) : link(name, () => go(id)));
  });
  if (view.from) {
    const b = el("button", "back", `← Back to ${originName(view.from)}`);
    b.title = "Back (Backspace)";
    b.onclick = back;
    nav.append(b);
  }
}

// Who uses the concept in view and what it uses, at the most specific level known.
function usage(c) {
  const within = (id) => id === c.id || ancestors(id).includes(c.id);
  const level = (id) => project(id, parentOf[c.id]) || id; // the sibling-level box for an outside concept
  const usedBy = new Set(), uses = new Set();
  for (const r of M.relationships) {
    if (r.label === TYPES) continue;
    if (within(r.to) && !within(r.from)) usedBy.add(level(r.from));
    if (within(r.from) && !within(r.to)) uses.add(level(r.to));
  }
  for (const l of leafList(c)) {
    for (const [a, b] of l.calls || []) {
      const x = symById[a], y = symById[b];
      if (x && y && !within(x.leaf.id) && within(y.leaf.id)) usedBy.add(x.leaf.id);
      if (x && y && within(x.leaf.id) && !within(y.leaf.id)) uses.add(y.leaf.id);
    }
    for (const i of l.importsIn || []) if (!within(i.concept)) usedBy.add(i.concept);
    for (const r of l.reexports || []) if (!within(r.concept)) uses.add(r.concept);
  }
  // Prefer the most specific name: drop a concept when one of its descendants is listed.
  const tidy = (set) => [...set].filter((id) => ![...set].some((o) => o !== id && ancestors(o).includes(id)));
  return { by: tidy(usedBy), to: tidy(uses) };
}

// Two concepts match for hover linking when one contains the other.
const related = (a, b) => a === b || ancestors(a).includes(b) || ancestors(b).includes(a);

function linkHover(concept, on) {
  for (const x of document.querySelectorAll("#diagram [data-concept], #drawer [data-concept]")) {
    if (related(x.dataset.concept, concept)) x.classList.toggle("linked", on);
  }
}

// Relationships between the concept in view and one Used by / Uses entry, including an
// ancestor relationship whose code reaches this view.
function usageRels(focus, other, incoming) {
  if (!focus || !other || !M) return [];
  const within = (id, root) => id === root || ancestors(id).includes(root);
  return M.relationships.filter((r) => {
    if (r.label === TYPES) return false;
    const side = incoming ? r.from : r.to, end = incoming ? r.to : r.from;
    if (!within(side, other)) return false;
    if (within(end, focus) || end === focus) return true;
    return ancestors(focus).includes(end) && codeTargets(focus, r, incoming).length > 0;
  });
}

// A symbol's own line, or the same fact from the file tree. A bare file has no line, so it adds nothing.
function codeWhere(id) {
  const sym = id && symById[id];
  if (sym && sym.file && sym.line) return `${sym.file.split("/").pop()}:${sym.line}`;
  if (id && treeNodes) {
    const n = treeNodes.find((x) => x.id === id);
    if (n && n.path && n.start_line) return `${n.path.split("/").pop()}:${n.start_line}`;
  }
  return "";
}

function codeTouches(focus, c, incoming) {
  const owner = conceptOf(incoming ? c.dst : c.src);
  if (!owner) return true;
  return owner === focus || ancestors(owner).includes(focus);
}

function codeEdgeText(c) {
  const where = codeWhere(c.src) || codeWhere(c.dst);
  const names = `${c.src_name} → ${c.dst_name}`;
  return where ? `${names}  ${where}` : names;
}

// Calls and imports that put a concept on the list when no relationship records them.
function usageCode(focus, other, incoming) {
  const within = (id, root) => id === root || ancestors(id).includes(root);
  const node = byId[focus];
  if (!node) return [];
  const out = [];
  for (const l of leafList(node)) {
    for (const [a, b] of l.calls || []) {
      const x = symById[a], y = symById[b];
      if (!x || !y) continue;
      if (incoming && within(x.leaf.id, other) && within(y.leaf.id, focus))
        out.push({ kind: "calls", src: a, dst: b, src_name: x.name, dst_name: y.name, weight: 1 });
      if (!incoming && within(x.leaf.id, focus) && within(y.leaf.id, other))
        out.push({ kind: "calls", src: a, dst: b, src_name: x.name, dst_name: y.name, weight: 1 });
    }
    const side = incoming ? l.importsIn : l.importsOut;
    for (const i of side || []) if (within(i.concept, other)) {
      const name = (byId[i.concept] && byId[i.concept].name) || i.concept;
      for (const f of i.files || []) {
        const file = String(f).split("/").pop();
        out.push(incoming
          ? { kind: "imports", src: "", dst: "", src_name: name, dst_name: file, weight: 1 }
          : { kind: "imports", src: "", dst: "", src_name: file, dst_name: name, weight: 1 });
      }
    }
  }
  return out;
}

function usageExplain(focus, other, incoming) {
  const rels = usageRels(focus, other, incoming);
  const labels = [...new Set(rels.map((r) => (r.label || "").trim()).filter(Boolean))];
  const vias = [...new Set(rels.map((r) => r.via).filter(Boolean))];
  let calls = 0, imports = 0, injection = 0, stated = 0, hosts = 0;
  const seen = new Set(), edges = [];
  const take = (c) => {
    const key = `${c.kind}\0${c.src || c.src_name}\0${c.dst || c.dst_name}`;
    if (seen.has(key)) return;
    seen.add(key);
    if (c.kind === "calls") calls += 1;
    else if (c.kind === "imports") imports += 1;
    edges.push(c);
  };
  for (const r of rels) {
    for (const c of r.code || []) if (codeTouches(focus, c, incoming)) take(c);
    for (const e of r.evidence || []) if (e.kind === "injected") injection += 1;
    if (r.backing === "stated") stated += 1;
    if (r.backing === "hosts" || r.kind === "hosts") hosts += 1;
  }
  if (!rels.length) for (const c of usageCode(focus, other, incoming)) take(c);
  // A located call (file:line) explains more than a heavier file import, so it sorts first.
  const located = (c) => (codeWhere(c.src) || codeWhere(c.dst)) ? 1 : 0;
  edges.sort((a, b) => located(b) - located(a) || (b.weight || 0) - (a.weight || 0) || String(a.src_name).localeCompare(String(b.src_name)));
  return { labels, vias, calls, imports, injection, stated, hosts, edges: edges.slice(0, 3).map(codeEdgeText) };
}

let usagePop = null;
function hideUsagePop() {
  if (!usagePop) return;
  usagePop.hidden = true;
  for (const b of document.querySelectorAll("[aria-describedby='usage-pop']")) b.removeAttribute("aria-describedby");
}

function showUsagePop(anchor, id, incoming) {
  const info = view.focus && usageExplain(view.focus, id, incoming);
  if (!info) return;
  const pop = usagePop || (usagePop = el("div", "usage-pop"));
  pop.id = "usage-pop";
  pop.setAttribute("role", "tooltip");
  if (!pop.isConnected) document.body.append(pop);
  pop.replaceChildren();
  if (info.labels.length) pop.append(el("p", "lab", info.labels.join(" · ")));
  if (info.vias.length) pop.append(el("p", "via", `via ${info.vias.join(", ")}`));
  const backs = [
    info.calls && `${info.calls} resolved ${info.calls === 1 ? "call" : "calls"}`,
    info.imports && `${info.imports} ${info.imports === 1 ? "import" : "imports"}`,
    info.injection && `${info.injection} ${info.injection === 1 ? "injection" : "injections"}`,
    info.stated && (info.stated === 1 ? "stated by the concept map" : `${info.stated} stated by the concept map`),
    info.hosts && (info.hosts === 1 ? "hosts" : `${info.hosts} hosts`),
  ].filter(Boolean);
  if (backs.length) pop.append(el("p", "back", backs.join(" · ")));
  if (info.edges.length) {
    const ul = el("ul");
    for (const text of info.edges) ul.append(el("li", "", text));
    pop.append(ul);
  }
  if (!pop.childNodes.length) pop.append(el("p", "back", "No resolved link"));
  pop.hidden = false;
  const btn = anchor.querySelector("button");
  if (btn) btn.setAttribute("aria-describedby", "usage-pop");
  const r = anchor.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
  let left = r.left - w - 8;
  if (left < 8) left = Math.min(r.right + 8, window.innerWidth - w - 8);
  let top = r.top;
  if (top + h > window.innerHeight - 8) top = Math.max(8, window.innerHeight - h - 8);
  pop.style.left = `${left}px`;
  pop.style.top = `${top}px`;
}

function usageList(d, title, ids, incoming) {
  if (!ids.length) return;
  d.append(el("h3", "", `${title} (${ids.length})`));
  const ul = el("ul", "usage");
  const add = (list) => list.forEach((id) => {
    const x = byId[id];
    if (!x) return;
    const li = el("li");
    li.dataset.concept = id;
    li.append(el("span", "dot " + (x.ext ? `ext kind-${x.kind}` : `role-${x.role}`)));
    li.append(link(x.name, () => (x.ext ? go(view.focus, id) : jump(id, null, { force: true }))));
    if (x.ext) li.append(el("span", "tag", "external"));
    const show = () => { linkHover(id, true); showUsagePop(li, id, incoming); };
    const hide = () => {
      if (li.contains(document.activeElement) || li.matches(":hover")) return;
      linkHover(id, false);
      hideUsagePop();
    };
    li.onmouseenter = show;
    li.onmouseleave = hide;
    li.addEventListener("focusin", show);
    li.addEventListener("focusout", (ev) => { if (!li.contains(ev.relatedTarget)) hide(); });
    ul.insertBefore(li, moreLi.isConnected ? moreLi : null);
  });
  const moreLi = el("li");
  const more = link(`+${ids.length - 5} more`, () => {
    moreLi.remove();
    add(ids.slice(5));
    legendFromDiagram(lastDiagram);
  });
  more.classList.add("more");
  d.append(ul);
  add(ids.slice(0, 5));
  if (ids.length > 5) { moreLi.append(more); ul.append(moreLi); }
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

// Relationships between one pair share an edge. The first label stays; the rest are a count.
function edgeLabelText(labels) {
  const parts = [];
  for (const label of labels) {
    const text = String(label || "").trim();
    if (text && !parts.includes(text)) parts.push(text);
  }
  if (parts.length <= 1) return parts[0] || "";
  return `${parts[0]} +${parts.length - 1}`;
}

function labelList(e) {
  if (e.labels && e.labels.length) return e.labels.filter(Boolean);
  return e.text ? [e.text] : [];
}

function relCount(e) {
  return e.count || (e.rels && e.rels.length) || 1;
}

function relsStated(e) {
  const rels = e.rels || [];
  if (rels.length) return rels.every((r) => r.backing === "stated");
  return (e.cls || "").split(" ").includes("stated");
}

// Keep the edge kind and change marks. Stated (and its quiet fade) survives only when every
// relationship on the edge is stated, so a resolved call stays full strength.
function joinEdgeClass(a, b, extra) {
  const words = new Set(`${a.cls || ""} ${b.cls || ""}`.split(" ").filter((c) => c && c !== "stated" && c !== "quiet" && c !== "both" && !c.startsWith("chg-")));
  const marks = [...new Set(`${a.cls || ""} ${b.cls || ""}`.split(" ").filter((c) => c.startsWith("chg-")))];
  const stated = relsStated(a) && relsStated(b);
  const quiet = stated && (a.cls || "").split(" ").includes("quiet") && (b.cls || "").split(" ").includes("quiet");
  return [...words, stated ? "stated" : "", quiet ? "quiet" : "", ...(extra || []), ...marks].filter(Boolean).join(" ");
}

// Opposite edges between one pair become one line. The hosting direction leads the arrow.
// The other label is written first, so a host reads "reads snapshot over IPC +1".
function mergePairEdges(edges, shown) {
  const hosts = (x) => (x.rels || []).some((r) => r.kind === "hosts");
  let out = edges.slice();
  for (const e of [...out]) {
    const twin = out.find((x) => x !== e && x.a === e.b && x.b === e.a);
    if (!twin || !out.includes(e)) continue;
    const [first, second] = hosts(e) ? [e, twin] : hosts(twin) ? [twin, e] : shown.has(e.b) && !shown.has(e.a) ? [e, twin] : [twin, e];
    out = out.filter((x) => x !== twin && x !== e);
    const lead = hosts(first) && !hosts(second) ? [second, first] : [first, second];
    const labels = [...labelList(lead[0]), ...labelList(lead[1])];
    const rels = [...(first.rels || []), ...(second.rels || [])];
    out.push({
      ...first,
      cls: joinEdgeClass(first, second, ["both"]),
      rels, labels,
      count: relCount(first) + relCount(second),
      text: edgeLabelText(labels),
      via: [...new Set([first.via, second.via].filter(Boolean).join(" · ").split(" · ").filter(Boolean))].join(" · ") || undefined,
      title: `${first.title}\n${second.title}`,
      lines: null,
    });
  }
  return out;
}

// "stated" is faint on the top-level map until an endpoint is hovered or selected.
function statedClass(stated, top) {
  return [stated ? "stated" : "", stated && top ? "quiet" : ""].filter(Boolean).join(" ");
}

// Code records name a symbol or a file. The leaf that owns it is the box the arrow can aim at.
function conceptOf(nodeId) {
  if (!nodeId) return null;
  const sym = symById[nodeId];
  if (sym && sym.leaf) return sym.leaf.id;
  const ghost = ghostById[nodeId];
  if (ghost && ghost.concept) return ghost.concept;
  const base = String(nodeId).split("#")[0];
  if (!fileOwner) {
    fileOwner = {};
    const walk = (cs) => {
      for (const c of cs || []) {
        for (const f of c.files || []) fileOwner[f] = c.id;
        if (c.children) walk(c.children);
      }
    };
    walk(M && M.concepts);
  }
  if (fileOwner[base]) return fileOwner[base];
  const paths = Object.keys(fileOwner).sort((a, b) => b.length - a.length);
  for (const path of paths) if (base.endsWith(":" + path)) return fileOwner[path];
  return null;
}

// Where a relationship's code actually lands inside `focus`: a child box, a symbol on a leaf, or nothing.
function codeTargets(focus, r, incoming) {
  const node = byId[focus];
  if (!node) return [];
  const leaf = !node.children;
  const found = [];
  const add = (id) => { if (id && !found.includes(id)) found.push(id); };
  for (const c of r.code || []) {
    const id = incoming ? c.dst : c.src;
    const owner = conceptOf(id);
    if (!owner || (owner !== focus && !ancestors(owner).includes(focus))) continue;
    if (leaf) {
      if (owner !== focus) continue;
      if (symById[id] && symById[id].leaf && symById[id].leaf.id === focus) add(id);
      else add("boundary");
    } else if (owner === focus) add("boundary");
    else {
      const child = project(owner, focus);
      if (child) add(child);
    }
  }
  const kids = found.filter((id) => id !== "boundary");
  return kids.length ? kids : found;
}

// A relationship whose stored end is this concept, or an ancestor whose code reaches into this view.
// `boundary` means the frame: nothing in the code names a child or a symbol in this view.
function frameEnds(focus, r) {
  const inTree = (id) => id === focus || ancestors(id).includes(focus);
  const isAnc = (id) => !!id && id !== focus && ancestors(focus).includes(id);
  let incoming, inside, other;
  if (inTree(r.to) !== inTree(r.from)) {
    incoming = inTree(r.to);
    inside = incoming ? r.to : r.from;
    other = incoming ? r.from : r.to;
  } else if (!inTree(r.to) && isAnc(r.to) !== isAnc(r.from)) {
    incoming = isAnc(r.to);
    inside = incoming ? r.to : r.from;
    other = incoming ? r.from : r.to;
  } else return [];
  // The other end is outside this view. A descendant end is already drawn by project().
  if (!other || !byId[other] || inTree(other) || isAnc(other)) return [];
  if (inside !== focus && !isAnc(inside)) return [];
  let targets = codeTargets(focus, r, incoming);
  if (!targets.length) {
    if (inside !== focus) return []; // a stated ancestor stays on the ancestor's own frame
    targets = ["boundary"];
  }
  const lane = incoming ? "in" : "out";
  return targets.map((target) => ({ a: incoming ? other : target, b: incoming ? target : other, lane }));
}

function conceptEdges(focus, shown) {
  const pairs = new Map();
  const add = (a, b, r, lane) => {
    const key = a + ">" + b;
    if (!pairs.has(key)) pairs.set(key, { a, b, exact: [], rolled: [], via: [], code: [], rels: [], lane: undefined });
    const p = pairs.get(key);
    p.rels.push(r);
    p[a === r.from && b === r.to ? "exact" : "rolled"].push(r.label);
    if (r.via) p.via.push(r.via);
    if (r.code) p.code.push(...r.code);
    if (lane) p.lane = p.lane && p.lane !== lane ? undefined : (p.lane || lane);
  };
  for (const r of M.relationships) {
    if (r.label === TYPES) continue; // type-only links stay out of both the drawer and the picture
    const a = project(r.from, focus), b = project(r.to, focus);
    if (a && b && a !== b && (shown.has(a) || shown.has(b))) {
      add(a, b, r);
      continue;
    }
    // Ends on the concept in view never project onto a child. Draw them anyway.
    if (focus) for (const end of frameEnds(focus, r)) add(end.a, end.b, r, end.lane);
  }
  return [...pairs.values()].map((p) => {
    const labels = [...new Set(p.exact.length ? p.exact : p.rolled)];
    const via = [...new Set(p.via)];
    const behind = [...new Set(p.code.map((c) => c.src_name + " → " + c.dst_name))].slice(0, 12);
    return {
      a: p.a, b: p.b, all: labels, labels, via: via.length ? via.join(" · ") : undefined,
      text: edgeLabelText(labels), lane: p.lane,
      title: [...labels, ...behind].join("\n"),
      rels: p.rels, count: p.rels.length, stated: p.rels.every((r) => r.backing === "stated"),
    };
  });
}

function drawConcepts(f, enter) {
  const kids = f ? f.children : M.concepts;
  const shown = new Set(kids.map((c) => c.id));
  const edges = conceptEdges(f ? f.id : null, new Set([...shown, ...(f ? [] : M.externals.map((x) => x.id))]));
  const outside = new Set(f ? [] : M.externals.map((x) => x.id));
  for (const e of edges) for (const x of [e.a, e.b]) if (x !== "boundary" && !shown.has(x)) outside.add(x);

  // Entry concepts form the first tier and carry the start marker, unless a sibling in view hosts
  // them; calls back up to an entry then route as return edges.
  const hostedHere = (id) => M.relationships.some((r) => r.kind === "hosts" && r.to === id && shown.has(project(r.from, f ? f.id : null)));
  const startsHere = (c) => !!c.entry && !hostedHere(c.id);
  const boundary = {
    id: "boundary", cls: "boundary" + (f ? ` role-${f.role}` : ""), label: f ? f.name : M.workspace,
    children: kids.map((c) => Object.assign(box(c, "", startsHere(c)), { pinned: startsHere(c) })),
  };
  const outsideNodes = [...outside].map((id) => box(byId[id], f ? "ctx" : "ext"));
  const nodes = [boundary, ...outsideNodes];
  const endExt = (id) => !!(byId[id] && byId[id].ext);
  const kind = (e) => endExt(e.a) || endExt(e.b) ? "integration" : shown.has(e.a) && shown.has(e.b) ? "" : "port";
  const bareCls = (cls) => (cls || "").split(" ").filter((c) => c && !c.startsWith("chg-")).join(" ");
  const top = !f;
  const innerEnd = (id) => id === "boundary" || shown.has(id);
  let elkEdges = mergePairEdges(edges.map((e, i) => ({
    id: "e" + i, a: e.a, b: e.b, text: e.text, labels: e.labels, via: e.via, title: e.title || e.all.join("\n"),
    cls: [kind(e), statedClass(e.stated, top), relChangeClass(e.rels)].filter(Boolean).join(" "),
    rels: e.rels, count: e.count, lane: e.lane,
  })), shown);
  {
    // An outside concept or system linked to several inner boxes the same way gets one line, with its
    // labels on its own box so each label stays attached; hovering the box lights up the inner boxes.
    // A line that stops on the frame (stated, no child) keeps its own label.
    const bundles = {};
    for (const e of elkEdges) {
      if (bareCls(e.cls) !== "port" && bareCls(e.cls) !== "integration") continue; // stated links keep their own line
      const aIn = innerEnd(e.a), bIn = innerEnd(e.b);
      if (aIn === bIn) continue;
      const incoming = bIn, other = incoming ? e.a : e.b;
      if (!byId[other]) continue;
      (bundles[other + (incoming ? ">in" : ">out")] ||= []).push(e);
    }
    for (const [key, es] of Object.entries(bundles)) {
      if (es.length < 2) continue;
      const incoming = key.endsWith(">in"), other = key.slice(0, incoming ? -3 : -4);
      const childEs = es.filter((e) => (incoming ? e.b : e.a) !== "boundary");
      if (childEs.length < 2) continue;
      const node = outsideNodes.find((n) => n.id === other);
      const integration = bareCls(childEs[0].cls) === "integration";
      const labels = [...new Set(childEs.flatMap((e) => e.title.split("\n")))];
      const vias = [...new Set(childEs.flatMap((e) => (e.via || "").split(" · ")).filter(Boolean))];
      const text = labels.slice(0, 3).join(", ") + (labels.length > 3 ? ` +${labels.length - 3}` : "") + (vias.length ? ` (${vias.join(", ")})` : "");
      const ctx = node.cls.includes("ctx");
      node.w = Math.max(node.w, 232);
      const summary = ctx ? [] : wrap(byId[other].summary || "", node.w - 32, 12, 1);
      node.lines = [...summary, ...wrap(text, node.w - 32, 12, 3)];
      node.h = (ctx ? 40 : 46) + node.lines.length * 16;
      const inner = childEs.map((e) => (incoming ? e.b : e.a));
      node.touches = [...(node.touches || []), ...inner];
      node.cls = node.cls.replace(ctx ? "ctx" : "node", ctx ? "ctx bundled" : "node bundled");
      elkEdges = elkEdges.filter((e) => !childEs.includes(e));
      const bundleMarks = [...new Set(childEs.flatMap((e) => e.cls.split(" ").filter((c) => c.startsWith("chg-"))))];
      const lane = childEs.every((e) => e.lane === childEs[0].lane) ? childEs[0].lane : undefined;
      elkEdges.push({ id: "b" + key, a: incoming ? other : inner[0], b: incoming ? inner[0] : other, cls: [(integration ? "integration" : "port"), "bundle", ...bundleMarks].join(" "), bundle: inner, title: labels.join("\n"), lane });
    }
  }
  for (const e of elkEdges) {
    if (e.lane !== "in" && e.lane !== "out") continue;
    const other = e.lane === "in" ? e.a : e.b;
    const node = outsideNodes.find((n) => n.id === other);
    if (!node) continue;
    if (node.lane && node.lane !== e.lane) node.lane = "";
    else if (!node.lane) node.lane = e.lane;
  }
  const onClick = (id) => {
    if (externalGroups[id]) return go(view.focus, id);
    const c = byId[id];
    if (!c) return;
    if (c.ext || c.flat) go(view.focus, id);
    else if (lateral(id)) jump(id);
    else go(id); // the child view animates in; a zoom before go() held the drill past 200 ms
  };
  // Every level reads left to right: callers on the left, callees on the right.
  layoutBridged(boundary, nodes.slice(1), elkEdges, onClick, enter);
  legendInside = f;
}

const START = "▶ start"; // marks a concept that owns a deployable entry point

function box(c, cls, startsHere = !!c.entry) {
  const tone = c.ext ? "kind-" + c.kind : "role-" + c.role;
  const mark = conceptClass(c.id);
  const tag = conceptTag(c.id);
  if (cls === "ctx") return { id: c.id, cls: `node ctx ${c.ext ? "ext " : ""}${tone}${mark}`, w: textW(c.name, 500, 14) + 36, h: 38, name: c.name, lines: [], tag };
  const w = Math.max(cls === "ext" ? 170 : 200, textW(c.name, 600, 14) + 32);
  const lines = wrap(c.summary || "", w - 32, 12, 3);
  const env = envOf(c).length, entry = !c.ext && startsHere;
  const tagW = tag ? textW(tag, 600, 10.5, true) + 18 : 0;
  const extra = (env ? 44 : 0) + (entry ? textW(START, 600, 10.5, true) + 18 : 0) + tagW;
  return { id: c.id, cls: `node ${cls} ${tone}${mark}`, w: w + extra, h: 46 + lines.length * 16, name: c.name, lines, stack: !!c.children, env, entry, tag };
}

// ---------- leaf diagrams ----------

function drawLeaf(c, enter) {
  c.symbols = c.symbols || [];
  c.calls = c.calls || [];
  c.importsIn = c.importsIn || [];
  c.reexports = c.reexports || [];
  c.ghosts = c.ghosts || {};
  const own = new Set(c.symbols.map((s) => s.id));
  const symNode = (s, cls) => {
    const n = s.tests ? s.tests.length : 0;
    const badge = n ? textW("✓ " + n, 600, 11) + 12 : 0;
    const env = s.env || [];
    const envText = env.length ? envName(env[0]) + (env.length > 1 ? ` +${env.length - 1}` : "") : "";
    const mark = symbolMark(s.id);
    const kindShown = (s.kind || "") + (mark ? ` · ${mark}` : "");
    const envW = envText ? textW(kindShown, 400, 11) + textW(envText, 600, 10.5, true) + 52 : 0;
    return {
      id: s.id, sym: s, mark, cls: ["sym", cls, mark && "chg-" + mark].filter(Boolean).join(" "),
      w: Math.max(textW(s.name, 500, 13, true) + 28 + (badge && badge + 8), envW, textW(kindShown, 400, 11) + 28, 110),
      h: 46, name: s.name, badge, envText,
    };
  };
  const typesOnly = !c.symbols.length;
  if (typesOnly && !c.importsIn.length && !c.reexports.length) { empty("No classes or functions here, only types."); clearKey(); return; }
  const pseudo = (id, name, cls = "") => ({ id, cls: `sym ghost more ${cls}`, w: textW(name, 400, 12) + 28, h: 32, name, more: id.split(":").slice(1).join(":") });
  const edges = [];
  const edge = (a, b, cls, text) => edges.push({ id: "e" + edges.length, a, b, cls, text });

  // Foreign symbols, grouped by owning concept, capped per group. Callers end up left, callees right.
  const groups = {};
  const group = (cid) => (groups[cid] ||= { ids: [], extra: [] });
  for (const [id, g] of Object.entries(c.ghosts)) group(g.concept).ids.push(id);

  // Concepts that only import this one (re-exports hide the calls): an "imports" node on the left.
  const fileSyms = (files) => c.symbols.filter((x) => files.includes(x.file)).map((x) => x.id);
  for (const imp of c.importsIn) {
    if (groups[imp.concept] && groups[imp.concept].ids.some((id) => c.calls.some(([x]) => x === id))) continue;
    const node = "imp:" + imp.concept;
    group(imp.concept).extra.push(pseudo(node, "imports"));
    const targets = fileSyms(imp.files);
    if (!targets.length || targets.length > 4) edge(node, "boundary", "call ghosted", "imports");
    else targets.forEach((t, i) => edge(node, t, "call ghosted", i ? null : "imports"));
  }

  // Re-exports: each passed-through name, bridged to the function that defines it.
  const rx = [];
  const many = c.reexports.length > 12;
  const byTarget = {};
  for (const r of c.reexports) (byTarget[r.concept] ||= []).push(r);
  for (const [cid, rs] of Object.entries(byTarget)) {
    if (cid === c.id) continue;
    const all = "all:" + cid;
    const needAll = many || rs.some((r) => !r.def);
    if (needAll) group(cid).extra.push(pseudo(all, "all exports"));
    const list = many ? [{ name: `${rs.length} re-exports`, def: null }] : rs;
    for (const r of list) {
      const id = `rx:${cid}:${r.name}`;
      const label = r.name === "*" ? `all of ${byId[cid].name}` : r.name;
      rx.push({ id, cls: "sym reexport", w: Math.max(textW(label, 500, 13, true) + 28, 110), h: 46, name: label, sym: { kind: "re-export", tests: [] } });
      edge(id, r.def && !own.has(r.def) ? r.def : all, "call ghosted reexport");
    }
  }

  const alias = {};
  const groupNodes = Object.entries(groups).map(([cid, g]) => {
    g.ids.sort((a, b) => ghostById[a].name.localeCompare(ghostById[b].name));
    const shown = g.ids.slice(0, GHOSTS_PER_GROUP), hidden = g.ids.slice(GHOSTS_PER_GROUP);
    const kids = shown.map((id) => symNode(Object.assign({ id }, ghostById[id]), "ghost"));
    if (hidden.length) {
      kids.push(pseudo("more:" + cid, `+${hidden.length} more`));
      for (const id of hidden) alias[id] = "more:" + cid;
    }
    kids.push(...g.extra);
    return { id: "group:" + cid, cls: `group role-${byId[cid].role}`, label: byId[cid].name, concept: cid, children: kids };
  });

  const seen = new Set();
  for (const [a0, b0, verb] of c.calls) {
    const a = alias[a0] || a0, b = alias[b0] || b0, key = a + ">" + b;
    if (seen.has(key)) continue;
    seen.add(key);
    edge(a, b, (own.has(a) && own.has(b) ? "call" : "call ghosted") + (verb === "renders" ? " renders" : ""));
  }
  for (const e of edges) if (alias[e.b]) e.b = alias[e.b];

  // Relationships that end here, and ancestor relationships whose code reaches this leaf.
  // A resolved symbol gets the arrow; a stated relationship stops on the frame. A concept that
  // already has a group keeps the label on that group instead of a second stub.
  const framed = conceptEdges(c.id, new Set());
  const ext = [], stubs = [], laneOf = {};
  const noteLane = (id, lane) => {
    if (!lane) return;
    if (laneOf[id] && laneOf[id] !== lane) laneOf[id] = "";
    else if (!laneOf[id]) laneOf[id] = lane;
  };
  for (const e of framed) {
    const incoming = e.lane !== "out";
    const other = incoming ? e.a : e.b;
    const target = incoming ? e.b : e.a;
    if (!byId[other]) continue;
    noteLane(other, e.lane);
    const mark = relChangeClass(e.rels);
    if (byId[other].ext) {
      if (!ext.includes(other)) ext.push(other);
      const targets = [];
      if (own.has(target)) targets.push(target);
      else for (const r of e.rels || []) {
        const fn = r.at && String(r.at).split(":")[1];
        const s = fn && c.symbols.find((x) => x.name === fn);
        const inner = s ? s.id : "boundary";
        if (!targets.includes(inner)) targets.push(inner);
      }
      if (!targets.length) targets.push("boundary");
      for (const inner of targets) edges.push({
        id: "f" + edges.length, a: incoming ? other : inner, b: incoming ? inner : other,
        text: e.text, via: e.via, title: e.title, rels: e.rels, count: e.count, labels: e.labels,
        cls: ["integration", e.stated ? "stated" : "", mark].filter(Boolean).join(" "),
      });
      continue;
    }
    const g = groupNodes.find((n) => n.concept === other);
    if (g) {
      for (const label of e.labels || []) {
        if (!label || (g._relLabels || []).includes(label)) continue;
        g._relLabels = g._relLabels || [];
        g._relLabels.push(label);
        g.label += (g.labels ? ", " : " · ") + label;
        g.labels = true;
      }
      if (e.lane) g.lane = g.lane && g.lane !== e.lane ? "" : (g.lane || e.lane);
      continue;
    }
    if (!stubs.includes(other)) stubs.push(other);
    edges.push({
      id: "f" + edges.length, a: e.a, b: e.b, text: e.text, via: e.via, title: e.title,
      rels: e.rels, count: e.count, labels: e.labels,
      cls: ["port", e.stated ? "stated" : "", mark].filter(Boolean).join(" "),
    });
  }

  // Big leaves open on their responsibilities rather than every helper (see clusterLeaf).
  let inside = c.symbols.map((s) => symNode(s, ""));
  const cl = clusterLeaf(c);
  if (cl) {
    const opened = (openClusters[c.id] ||= new Set());
    const sel = view.sel && own.has(view.sel) ? view.sel : null;
    const bucketOf = {};
    for (const [b, v] of Object.entries(cl.buckets)) for (const id of v.members) bucketOf[id] = b;
    const entryOf = {};
    for (const [e, hs] of Object.entries(cl.helpers)) for (const h of hs) entryOf[h] = e;
    // Whatever holds the selection opens, so a search hit or Back always lands on a visible node.
    if (sel) {
      const e = cl.entries.includes(sel) ? sel : entryOf[sel];
      if (e && bucketOf[e]) opened.add(bucketOf[e]);
      if (cl.shared.includes(sel)) opened.add("cluster:shared");
      if (cl.lone.includes(sel)) opened.add("cluster:lone");
    }
    const repOf = {}, loose = [], boxes = {};
    const put = (id, where) => (where ? (boxes[where] ||= []).push(id) : loose.push(id));
    for (const e of cl.entries) {
      const b = bucketOf[e];
      if (b && !opened.has(b)) { repOf[e] = b; for (const h of cl.helpers[e] || []) repOf[h] = b; continue; }
      put(e, b && "open:" + b);
      const hs = cl.helpers[e] || [];
      const show = sel === e || hs.includes(sel) || opened.has(e);
      for (const h of hs) show ? put(h, b && "open:" + b) : (repOf[h] = e);
    }
    for (const id of Object.keys(repOf)) if (repOf[repOf[id]]) repOf[id] = repOf[repOf[id]];
    for (const [key, ids, label] of [["cluster:shared", cl.shared, "shared helpers"], ["cluster:lone", cl.lone, "standalone"]]) {
      if (!ids.length) continue;
      if (opened.has(key)) ids.forEach((id) => put(id, "open:" + key));
      else ids.forEach((id) => (repOf[id] = key));
    }
    const node = (id) => {
      const s0 = symById[id], n = symNode(s0, "");
      const k = (cl.helpers[id] || []).filter((h) => repOf[h] === id).length;
      if (k) {
        n.kindText = `${s0.kind} · +${k} helper${k > 1 ? "s" : ""}`;
        n.w = Math.max(n.w, textW(n.kindText + (n.mark ? ` · ${n.mark}` : ""), 400, 11) + 28);
      }
      return n;
    };
    const membersOf = (key) => {
      if (key.startsWith("bucket:")) {
        const ids = new Set(cl.buckets[key] ? cl.buckets[key].members : []);
        for (const [id, rep] of Object.entries(repOf)) if (rep === key) ids.add(id);
        return ids;
      }
      if (key === "cluster:shared") return new Set(cl.shared);
      if (key === "cluster:lone") return new Set(cl.lone);
      return new Set();
    };
    const closed = (id, label, count) => {
      const marked = [...membersOf(id)].some((mid) => symbolMark(mid));
      return { id, cls: "sym cluster" + (marked ? " chg-changed" : ""), w: Math.max(textW(label, 500, 13, true), textW(`${count} functions · open`, 400, 11)) + 32, h: 46, name: label, sym: { kind: "", tests: [] }, kindText: `${count} functions · open`, toggle: true };
    };
    const labelOf = (key) => key.startsWith("bucket:") ? cl.buckets[key].label : key === "cluster:shared" ? "shared helpers" : "standalone";
    inside = loose.map(node);
    for (const [where, ids] of Object.entries(boxes)) inside.push({ id: where, cls: "group cluster-open", label: `${labelOf(where.slice(5))}  ▾`, toggle: true, children: ids.map(node) });
    const counts = {};
    for (const [id, r] of Object.entries(repOf)) if (!own.has(r)) counts[r] = (counts[r] || 0) + 1;
    for (const [key, n] of Object.entries(counts)) inside.push(closed(key, labelOf(key), n));
    for (const e of edges) { e.a = repOf[e.a] || e.a; e.b = repOf[e.b] || e.b; }
    const seenE = new Set();
    for (let i = edges.length - 1; i >= 0; i--) {
      const e = edges[i], key = e.a + ">" + e.b;
      if (e.a === e.b || seenE.has(key)) edges.splice(i, 1);
      else seenE.add(key);
    }
  }
  if (typesOnly) inside.push({ id: "types", cls: "sym ghost more", w: 120, h: 32, name: "types only", more: "-" });
  const boundary = { id: "boundary", cls: `boundary role-${c.role}`, label: c.name, children: [...inside, ...rx] };
  const stubBox = (id) => { const n = box(byId[id], "ctx"); if (laneOf[id]) n.lane = laneOf[id]; return n; };
  const nodes = [boundary, ...groupNodes, ...ext.map(stubBox), ...stubs.map(stubBox)];
  layout(nodes, edges, { dir: "RIGHT", layer: 56, gap: 14 }, (id) => {
    if (/^(bucket|cluster):/.test(id)) { openClusters[c.id].add(id); refit = true; return route(); }
    if (id.startsWith("open:")) { openClusters[c.id].delete(id.slice(5)); refit = true; return route(); }
    if (own.has(id)) return go(view.focus, id, { v: view.mode });
    if (ghostById[id]) return go(view.focus, id, { v: view.mode }); // select; Go to jumps, double-click opens the file
    if (/^(more|imp|all):/.test(id)) return jump(id.slice(id.indexOf(":") + 1), null, { force: true });
    if (id.startsWith("group:")) return jump(id.slice(6), null, { force: true });
    if (byId[id] && byId[id].ext) return go(view.focus, id, { v: view.mode });
    if (byId[id]) return jump(id, null, { force: true });
  }, enter, (id) => {
    if (typeof openInEditor !== "function") return;
    const target = openTargetFor(id);
    if (target) openInEditor(target.file, target.line);
  });
  legendInside = c;
}

// Responsibility groups for big leaves (agent-defined groups come later): an entry point is a function
// called from outside the leaf, or one that calls into the leaf without being called. Each entry owns
// the helpers only it reaches; helpers reached from several entries are "shared helpers"; functions
// with no calls in or out are "standalone". Over 14 entries, entries are bucketed by file.
const openClusters = {}; // leaf id -> opened groups, for this session
function clusterLeaf(c) {
  if (!c.symbols || c.symbols.length <= 24) return null;
  const own = new Set(c.symbols.map((s) => s.id));
  const callsIn = c.calls || [];
  const inn = callsIn.filter(([a, b]) => own.has(a) && own.has(b) && a !== b);
  const called = new Set(inn.map((x) => x[1])), calls = new Set(inn.map((x) => x[0]));
  const fromOutside = new Set(callsIn.filter(([a, b]) => !own.has(a) && own.has(b)).map((x) => x[1]));
  const entries = c.symbols.map((s) => s.id).filter((id) => fromOutside.has(id) || (!called.has(id) && calls.has(id)));
  const isEntry = new Set(entries);
  const reach = {};
  for (const r of entries) {
    const seen = new Set([r]), stack = [r];
    while (stack.length) {
      const x = stack.pop();
      for (const [a, b] of inn) if (a === x && !seen.has(b) && !isEntry.has(b)) { seen.add(b); stack.push(b); }
    }
    for (const x of seen) if (x !== r) (reach[x] ||= []).push(r);
  }
  const helpers = {}, shared = [], lone = [];
  for (const s of c.symbols) {
    if (isEntry.has(s.id)) continue;
    const rs = reach[s.id];
    if (!rs) lone.push(s.id);
    else if (rs.length === 1) (helpers[rs[0]] ||= []).push(s.id);
    else shared.push(s.id);
  }
  const buckets = {};
  if (entries.length > 14) for (const id of entries) {
    const f = symById[id].file.split("/").pop().replace(/\.[jt]sx?$/, "");
    (buckets["bucket:" + f] ||= { label: f, members: [] }).members.push(id);
  }
  return { entries, helpers, shared, lone, buckets };
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

function pairScreen(screen, ids) {
  if (!DIFF || !DIFF.screens || !screen) return null;
  const base = DIFF.screens.find((s) => s.id === screen.id || (s.name && s.name === screen.name));
  if (!base || !base.root) return null;
  const changed = [...ids].filter((id) => symbolMark(id));
  if (!changed.length) return null;
  const hit = new Set(changed);
  if (!regionsWith(base.root, hit).length || !regionsWith(screen.root, hit).length) return null;
  return base;
}

function drawSketch(c) {
  layoutGen++;
  setStage("sketch");
  clearKey();
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
  const bar = el("div", "sketch-bar");
  const parent = parentOf[c.id];
  const upBtn = el("button", "up", `↑ ${parent ? byId[parent].name : M.workspace}`);
  upBtn.title = "Up one level (Esc)";
  upBtn.onclick = up;
  bar.append(upBtn, picker);
  const before = pairScreen(screen, ids);
  const left = el("div", "sketch-main");
  left.append(bar);
  let shown = frame;
  if (before) {
    const pair = el("div", "sketch-pair");
    const col = (label, root, device) => {
      const column = el("div", "col");
      column.append(el("div", "when", label));
      const one = el("div", "frame " + device);
      one.append(region(root, hl, false));
      column.append(one);
      return column;
    };
    pair.append(col("Before", before.root, before.device || screen.device), col("After", screen.root, screen.device));
    shown = pair.querySelectorAll(".frame")[1];
    left.append(pair);
  } else left.append(frame);
  pane.append(left, componentPanel(symById[focusComp]));
  // Keep the frame's top in view when the highlight fits below it; otherwise bring the highlight
  // up under the bar. The bar stays put either way, so other screens stay discoverable.
  const target = shown.querySelector(".hl");
  if (target) requestAnimationFrame(() => {
    const barH = bar.offsetHeight + 16;
    const top = target.getBoundingClientRect().top - left.getBoundingClientRect().top + left.scrollTop;
    const bottom = top + target.offsetHeight;
    left.scrollTop = bottom + 24 <= left.clientHeight ? 0 : top - barH - 24;
  });
}

function region(r, hl, inside) {
  const d = el("div", `wf ${r.layout}` + (r.style ? " " + r.style.map((s) => "s-" + s).join(" ") : ""));
  if (r.cols) d.style.gridTemplateColumns = `repeat(${Number(r.cols)}, auto)`;
  const cond = typeof r.when === "string" ? r.when.trim() : "";
  if (cond) {
    d.classList.add("cond");
    d.append(el("span", "cond-tag", cond));
  }
  const on = hl.has(r.component);
  if (on) d.classList.add("hl");
  else if (inside && r.component) d.classList.add("ol");
  if (r.component && symById[r.component]) {
    const s = symById[r.component];
    d.title = s.name;
    d.tabIndex = 0;
    d.setAttribute("role", "button");
    d.setAttribute("aria-label", `${s.name} in ${s.leaf.name}`);
    d.onkeydown = (ev) => { if (ev.target === d && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); d.onclick(ev); } };
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
  const chips = (title, items, cls, onClick, folded) => {
    if (!items.length) return;
    let into = p;
    if (folded) {
      // Detail on demand: the list stays closed until asked for.
      into = el("details");
      const sum = el("summary");
      sum.append(el("h5", "", `${title} (${items.length})`));
      into.append(sum);
      p.append(into);
    } else p.append(el("h5", "", title));
    const row = el("div", "chips");
    for (const it of items) {
      const c = onClick ? link(it.name, () => onClick(it)) : el("span", "chip " + cls, it);
      if (onClick) c.className = "chip link-chip";
      row.append(c);
    }
    into.append(row);
  };
  chips("Props", s.props || [], "mono");
  const renders = (s.leaf.calls || []).filter(([a, , v]) => a === s.id && v === "renders").map(([, b]) => symById[b]).filter(Boolean);
  chips("Renders", renders, "link", (x) => jump(x.leaf.id, x.id, { force: true }));
  chips("Reads", s.reads || [], "mono", null, true);
  const n = (s.tests || []).length;
  p.append(el("p", n ? "tests" : "tests none", n ? `✓ ${n} linked test case${n > 1 ? "s" : ""}` : "No test links found"));
  return p;
}

// ---------- layout and render ----------

async function layout(nodes, edges, opt, onClick, enter, onDbl) {
  const gen = ++layoutGen;
  const toElk = (n) => ({
    id: n.id,
    ...(n.children ? {}: { width: n.w, height: n.h }),
    ...(n.children ? {
      children: n.children.map(toElk),
      layoutOptions: { "elk.padding": "[top=40,left=20,bottom=20,right=20]" },
    } : {}),
  });
  const a = availSize();
  const graph = { id: "root", layoutOptions: { ...elkOptions(opt), "elk.aspectRatio": String(a.w / a.h) }, children: nodes.map(toElk), edges: edges.map(elkEdge) };
  let out;
  try { out = await elk.layout(graph); } catch (err) {
    if (gen !== layoutGen) return;
    return empty("Layout failed: " + err.message);
  }
  if (gen !== layoutGen) return;
  externalGroups = {};
  render(out, nodes, edges, onClick, enter, onDbl);
}

function elkOptions(opt) {
  return {
    "elk.algorithm": "layered",
    "elk.direction": opt.dir,
    "elk.hierarchyHandling": "INCLUDE_CHILDREN",
    "org.eclipse.elk.json.edgeCoords": "ROOT",
    "elk.edgeRouting": "ORTHOGONAL",
    "elk.layered.spacing.nodeNodeBetweenLayers": String(opt.layer),
    "elk.spacing.nodeNode": String(opt.gap),
    "elk.spacing.edgeLabel": "4",
    "elk.edgeLabels.placement": "CENTER",
    "elk.layered.edgeLabels.centerLabelPlacementStrategy": "SPACE_EFFICIENT_LAYER",
    "elk.layered.edgeLabels.sideSelection": "SMART_DOWN",
    "elk.spacing.labelLabel": "8",
    "elk.spacing.edgeNode": "16",
    "elk.layered.spacing.edgeNodeBetweenLayers": "16",
    "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
    "elk.spacing.componentComponent": String(opt.gap * 1.5),
    "elk.padding": "[top=12,left=12,bottom=12,right=12]",
  };
}

// Edge labels wrap to a narrow column so left-to-right layers stay close; the mechanism pill sits below.
const LABEL_MAX = 100;
function labelBox(e) {
  if (!e.lines) e.lines = e.text ? wrap(e.text, LABEL_MAX, 11.5, 3) : [];
  const viaW = e.via ? textW(e.via, 600, 10.5, true) + 12 : 0;
  const countW = e.count > 1 ? textW(String(e.count), 600, 10, true) + 14 : 0;
  return { width: Math.max(viaW, ...e.lines.map((l) => textW(l, 400, 11.5)), 0) + countW + 6, height: e.lines.length * 13 + (e.via ? 19 : 0) + 2, countW };
}
const elkEdge = (e) => ({ id: e.id, sources: [e.a], targets: [e.b], labels: e.text || e.via ? [{ text: e.text || "", ...labelBox(e) }] : [] });

// Distance from an inner anchor to each side of the boundary. Ties break above, right, below, left.
function sideRanks(anchor, width, height) {
  return [
    ["above", anchor.y],
    ["right", width - anchor.x],
    ["below", height - anchor.y],
    ["left", anchor.x],
  ].map(([side, d], i) => ({ side, d, i })).sort((a, b) => a.d - b.d || a.i - b.i);
}

function assignSides(items, width, height) {
  const out = {};
  for (const it of items) out[it.id] = sideRanks({ x: it.x, y: it.y }, width, height)[0].side;
  return out;
}

// More than five externals on one side: those with one kind and one caller share a box.
function groupExternals(ids, meta) {
  const alone = (id) => ({ id, members: [id] });
  if (ids.length <= 5) return ids.map(alone);
  const buckets = new Map(), order = [];
  for (const id of ids) {
    const info = meta[id] || {};
    const callers = info.callers || [];
    const key = callers.length === 1 ? `${info.kind}\0${callers[0]}` : `solo\0${id}`;
    if (!buckets.has(key)) { buckets.set(key, []); order.push(key); }
    buckets.get(key).push(id);
  }
  const out = [];
  for (const key of order) {
    const members = buckets.get(key);
    if (members.length > 1 && !key.startsWith("solo\0")) {
      const [kind, caller] = key.split("\0");
      out.push({ id: `xg:${kind}:${caller}`, members: members.slice(), grouped: true, kind, caller });
    } else for (const id of members) out.push(alone(id));
  }
  return out;
}

function groupBox(g) {
  const title = (KINDS[g.kind] || g.kind || "Outside") + ` (${g.members.length})`;
  const names = g.members.map((id) => (byId[id] && byId[id].name) || id);
  const w = Math.max(180, textW(title, 600, 14) + 32, ...names.map((n) => textW(n, 400, 12) + 36));
  const lines = names.slice(0, 8);
  if (names.length > 8) lines.push(`+${names.length - 8} more`);
  return {
    id: g.id, cls: `node ext grouped kind-${g.kind}`, w, h: 46 + lines.length * 16,
    name: title, lines, members: g.members.slice(), touches: g.caller ? [g.caller] : [],
  };
}

// Point a crossing edge at the grouped box and fold edges that now share both ends.
function retargetCrossing(edges, memberOf) {
  const out = new Map();
  for (const e of edges) {
    const a = memberOf[e.a] || e.a, b = memberOf[e.b] || e.b;
    if (a === b) continue;
    const key = a + ">" + b;
    const labels = labelList(e);
    if (!out.has(key)) {
      out.set(key, { ...e, a, b, labels, rels: [...(e.rels || [])], count: relCount(e), lines: null });
      continue;
    }
    const slot = out.get(key);
    const merged = [...slot.labels, ...labels];
    out.set(key, {
      ...slot, labels: merged, rels: [...slot.rels, ...(e.rels || [])],
      count: slot.count + relCount(e), text: edgeLabelText(merged), lines: null,
      title: [slot.title, e.title].filter(Boolean).join("\n"),
      via: [...new Set([slot.via, e.via].filter(Boolean).join(" · ").split(" · ").filter(Boolean))].join(" · ") || undefined,
      cls: joinEdgeClass(slot, e),
    });
  }
  for (const slot of out.values()) if (slot.labels) slot.text = edgeLabelText(slot.labels);
  return [...out.values()];
}

// A short orthogonal path between two boxes. It stays in the space they span.
function routeInside(a, b) {
  const acx = a.x + a.width / 2, acy = a.y + a.height / 2, bcx = b.x + b.width / 2, bcy = b.y + b.height / 2;
  const dx = bcx - acx, dy = bcy - acy;
  if (Math.abs(dx) >= Math.abs(dy)) {
    const x0 = dx >= 0 ? a.x + a.width : a.x, x1 = dx >= 0 ? b.x : b.x + b.width;
    if (Math.abs(acy - bcy) < 1) return [{ x: x0, y: acy }, { x: x1, y: bcy }];
    const mid = (x0 + x1) / 2;
    return [{ x: x0, y: acy }, { x: mid, y: acy }, { x: mid, y: bcy }, { x: x1, y: bcy }];
  }
  const y0 = dy >= 0 ? a.y + a.height : a.y, y1 = dy >= 0 ? b.y : b.y + b.height;
  if (Math.abs(acx - bcx) < 1) return [{ x: acx, y: y0 }, { x: bcx, y: y1 }];
  const mid = (y0 + y1) / 2;
  return [{ x: acx, y: y0 }, { x: acx, y: mid }, { x: bcx, y: mid }, { x: bcx, y: y1 }];
}

// True when a route runs along the frame instead of across the interior.
function hugsFrame(pts, w, h) {
  if (!pts || pts.length < 3 || w < 40 || h < 40) return false;
  const slack = 8;
  const outer = pts.filter((p) => p.x <= slack || p.y <= slack || p.x >= w - slack || p.y >= h - slack);
  if (outer.length < 2) return false;
  let len = 0;
  for (let i = 1; i < pts.length; i++) len += Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
  const straight = Math.hypot(pts[pts.length - 1].x - pts[0].x, pts[pts.length - 1].y - pts[0].y) || 1;
  return len > straight * 1.35 && outer.length * 2 >= pts.length;
}

// A long segment in the padding band is a frame route. ELK's 12px padding sits inside this.
const FRAME_BAND = 24;
const FRAME_RUN = 48;

function frameRun(pts, w, h) {
  if (!pts || w < 40 || h < 40) return false;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i];
    if (Math.hypot(b.x - a.x, b.y - a.y) <= FRAME_RUN) continue;
    const maxX = Math.max(a.x, b.x), minX = Math.min(a.x, b.x);
    const maxY = Math.max(a.y, b.y), minY = Math.min(a.y, b.y);
    if (maxX <= FRAME_BAND || minX >= w - FRAME_BAND || maxY <= FRAME_BAND || minY >= h - FRAME_BAND) return true;
  }
  return false;
}

function onBoxBorder(p, box) {
  if (!p || !box) return false;
  const w = box.width != null ? box.width : box.w, h = box.height != null ? box.height : box.h;
  const right = box.x + w, bot = box.y + h, s = 1.5;
  const onV = (Math.abs(p.x - box.x) <= s || Math.abs(p.x - right) <= s) && p.y >= box.y - s && p.y <= bot + s;
  const onH = (Math.abs(p.y - box.y) <= s || Math.abs(p.y - bot) <= s) && p.x >= box.x - s && p.x <= right + s;
  return onV || onH;
}

function meetsBoxes(pts, a, z) {
  return !!(pts && pts.length >= 2 && onBoxBorder(pts[0], a) && onBoxBorder(pts[pts.length - 1], z));
}

function innerEdgeOk(pts, a, z, w, h) {
  return meetsBoxes(pts, a, z) && !frameRun(pts, w, h);
}

// Strict interior. A segment that only touches a border does not cut the box.
function cutsBox(p, q, box) {
  const w = box.width != null ? box.width : box.w, h = box.height != null ? box.height : box.h;
  const eps = 0.75;
  const left = box.x + eps, right = box.x + w - eps, top = box.y + eps, bot = box.y + h - eps;
  if (right <= left || bot <= top) return false;
  if (Math.abs(p.x - q.x) >= Math.abs(p.y - q.y)) {
    const y = (p.y + q.y) / 2;
    if (y <= top || y >= bot) return false;
    const x0 = Math.min(p.x, q.x), x1 = Math.max(p.x, q.x);
    return x1 > left && x0 < right;
  }
  const x = (p.x + q.x) / 2;
  if (x <= left || x >= right) return false;
  const y0 = Math.min(p.y, q.y), y1 = Math.max(p.y, q.y);
  return y1 > top && y0 < bot;
}

function pathClear(pts, boxes) {
  for (let i = 1; i < pts.length; i++) for (const box of boxes) if (cutsBox(pts[i - 1], pts[i], box)) return false;
  return true;
}

// Open vertical channels between columns of boxes. The centre is the route's x.
function columnGaps(boxes) {
  const spans = boxes.map((b) => {
    const w = b.width != null ? b.width : b.w;
    return [b.x, b.x + w];
  }).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cols = [];
  for (const [l, r] of spans) {
    const last = cols[cols.length - 1];
    if (!last || l > last[1] + 1) cols.push([l, r]);
    else last[1] = Math.max(last[1], r);
  }
  const gaps = [];
  for (let i = 1; i < cols.length; i++) {
    const l = cols[i - 1][1], r = cols[i][0];
    if (r - l >= 8) gaps.push((l + r) / 2);
  }
  return gaps;
}

// Leave each box on the side that faces the gap, run along the gap, enter from that side.
function routeGap(a, b, gx) {
  const acx = a.x + a.width / 2, bcx = b.x + b.width / 2;
  const y0 = a.y + a.height / 2, y1 = b.y + b.height / 2;
  const x0 = gx >= acx ? a.x + a.width : a.x;
  const x1 = gx >= bcx ? b.x + b.width : b.x;
  const raw = [{ x: x0, y: y0 }, { x: gx, y: y0 }, { x: gx, y: y1 }, { x: x1, y: y1 }];
  return raw.filter((p, i) => i === 0 || p.x !== raw[i - 1].x || p.y !== raw[i - 1].y);
}

function gapAnchor(pts, w, h, a, z) {
  let best = null, len = 0;
  for (let i = 1; i < (pts || []).length; i++) {
    const p = pts[i - 1], q = pts[i], d = Math.hypot(q.x - p.x, q.y - p.y);
    if (d <= FRAME_RUN || d < len) continue;
    const maxX = Math.max(p.x, q.x), minX = Math.min(p.x, q.x);
    const maxY = Math.max(p.y, q.y), minY = Math.min(p.y, q.y);
    const band = maxX <= FRAME_BAND || minX >= w - FRAME_BAND || maxY <= FRAME_BAND || minY >= h - FRAME_BAND;
    if (!band) continue;
    len = d;
    best = (p.x + q.x) / 2;
  }
  if (best != null) return best;
  if (pts && pts.length) return pts.reduce((t, p) => t + p.x, 0) / pts.length;
  return (a.x + a.width / 2 + z.x + z.width / 2) / 2;
}

// After ELK. A frame run, or an end that misses its box, is redrawn. routeInside wins when it
// misses every box; otherwise the nearest clear column gap. Edges that already meet both boxes
// and stay outside the band are returned unchanged.
function settleInnerEdge(pts, a, z, boxes, w, h) {
  const drawn = pts || [];
  if (innerEdgeOk(drawn, a, z, w, h)) return drawn;
  const inside = routeInside(a, z);
  if (pathClear(inside, boxes) && !frameRun(inside, w, h)) return inside;
  const ax = gapAnchor(drawn, w, h, a, z);
  const gaps = columnGaps(boxes).slice().sort((p, q) => Math.abs(p - ax) - Math.abs(q - ax) || p - q);
  let fallback = null;
  for (const gx of gaps) {
    const via = routeGap(a, z, gx);
    if (!meetsBoxes(via, a, z)) continue;
    if (!fallback) fallback = via;
    if (pathClear(via, boxes) && !frameRun(via, w, h)) return via;
  }
  return fallback || inside;
}

function edgeMatches(edge, id, groups) {
  if (!id) return false;
  if (edge.a === id || edge.b === id) return true;
  for (const end of [edge.a, edge.b]) {
    const g = groups && groups[end];
    if (g && g.members && g.members.includes(id)) return true;
  }
  return false;
}

// Above and below the frame, each sideways edge takes its own lane unless a straight drop
// already lands on its box. The farthest box on a side of an exit takes the lane closest
// to the frame, so a nearer drop does not cross it. Labels sit beside that drop, and the
// row grows to fit them.
const SIDE_GAP = 18, SIDE_LANE = 18, FRAME_OX = 8;
const LINE_GAP = 10, LANE_PITCH = 18, LANE_INSET = 14, LANE_CLEAR = 12, BOX_LABEL_GAP = 8, DIRECT_DROP = 16;

function outsideEnd(e, sideOf) {
  if (sideOf[e.a] && !sideOf[e.b]) return e.a;
  if (sideOf[e.b] && !sideOf[e.a]) return e.b;
  return null;
}

function exitX(e, outsideId, at, origin) {
  const innerId = e.a === outsideId ? e.b : e.a;
  const ids = (e.bundle || [innerId]).filter((id) => id !== "boundary" && at && at[id]);
  if (!ids.length) return null;
  return origin + ids.reduce((t, id) => t + at[id].x + at[id].width / 2, 0) / ids.length;
}

function edgeLabelBox(e) {
  return e && (e.text || e.via) ? labelBox(e) : null;
}

function labelStackH(id, edges) {
  const boxes = edges.filter((e) => e.a === id || e.b === id).map(edgeLabelBox).filter(Boolean);
  if (!boxes.length) return 0;
  return boxes.reduce((t, b) => t + b.height, 0) + (boxes.length - 1) * 4;
}

function lanePlan(items) {
  const laneOf = items.map(() => -1);
  const sxOf = (it) => it.sx == null ? it.cx : it.sx;
  const spanOf = (it) => {
    const sx = sxOf(it);
    return [Math.min(sx, it.cx), Math.max(sx, it.cx)];
  };
  // A span covers a drop when the drop sits strictly inside it. That span has to
  // stay closer to the frame, or the drop falls through it.
  const covers = (a, b) => {
    const [l, r] = spanOf(a);
    return b.cx > l + 0.5 && b.cx < r - 0.5;
  };
  const jog = [];
  items.forEach((it, i) => {
    const sx = sxOf(it);
    const alone = items.every((o, j) => j === i || Math.abs(sxOf(o) - sx) > DIRECT_DROP);
    const covered = items.some((o, j) => j !== i && covers(o, it));
    if (Math.abs(sx - it.cx) <= DIRECT_DROP && alone && !covered) return;
    jog.push(i);
  });
  const reach = (it) => Math.abs(it.cx - sxOf(it));
  const oneWay = (o, k) => covers(items[jog[o]], items[jog[k]]) && !covers(items[jog[k]], items[jog[o]]);
  const assigned = jog.map(() => false), lane = jog.map(() => 0), taken = [];
  for (let step = 0; step < jog.length; step++) {
    const waiting = [];
    for (let k = 0; k < jog.length; k++) {
      if (assigned[k]) continue;
      if (jog.some((_, o) => !assigned[o] && oneWay(o, k))) continue;
      waiting.push(k);
    }
    const pool = waiting.length ? waiting : jog.map((_, k) => k).filter((k) => !assigned[k]);
    pool.sort((a, b) => reach(items[jog[b]]) - reach(items[jog[a]]) || a - b);
    const k = pool[0];
    const [l, r] = spanOf(items[jog[k]]);
    const padL = l - 6, padR = r + 6;
    let minLane = 0;
    for (let o = 0; o < jog.length; o++) if (assigned[o] && oneWay(o, k)) minLane = Math.max(minLane, lane[o] + 1);
    let L = minLane;
    for (;; L++) {
      if (!taken[L]) taken[L] = [];
      if (taken[L].every(([a, b]) => padR <= a || padL >= b)) break;
    }
    taken[L].push([padL, padR]);
    lane[k] = L;
    assigned[k] = true;
    laneOf[jog[k]] = L;
  }
  return { laneOf, laneCount: laneOf.some((n) => n >= 0) ? Math.max(...laneOf) + 1 : 0 };
}

function sideGutter(laneCount, labelH) {
  if (!laneCount) return labelH ? labelH + BOX_LABEL_GAP + 12 : 16;
  const last = LANE_INSET + (laneCount - 1) * LANE_PITCH;
  return last + LANE_CLEAR + labelH + BOX_LABEL_GAP;
}

function spreadCenters(ids, size, want, labelW, exits, bx) {
  const order = ids.slice().sort((p, q) => want[p].x - want[q].x || (p < q ? -1 : p > q ? 1 : 0));
  const left = {};
  let minCenter = -Infinity, nextLeft = bx;
  for (const id of order) {
    const w = size[id].w, lw = labelW(id) || 0;
    let center = Math.max(bx + want[id].x, minCenter, nextLeft + w / 2);
    const own = new Set(exits[id] || []);
    const foreign = Object.entries(exits).filter(([k]) => k !== id).flatMap(([, xs]) => xs).filter((x) => !own.has(x));
    for (let n = 0; n < 8; n++) {
      const hit = foreign.find((x) => Math.abs(x - center) <= DIRECT_DROP);
      if (hit == null) break;
      center = hit + DIRECT_DROP + 1;
    }
    left[id] = center - w / 2;
    minCenter = lw ? center + LINE_GAP + lw + LINE_GAP : center;
    nextLeft = left[id] + w + SIDE_GAP;
  }
  return left;
}

function verticalItems(ids, leftOf, edges, sideOf, at, origin, size) {
  const onSide = new Set(ids);
  const items = [];
  for (const e of edges) {
    const o = outsideEnd(e, sideOf);
    if (!o || !onSide.has(o)) continue;
    const sx = exitX(e, o, at, origin);
    if (sx == null && e.a !== "boundary" && e.b !== "boundary") continue;
    items.push({ e, o, sx, cx: leftOf[o] + size[o].w / 2 });
  }
  return items;
}

function stampRoutes(items, plan, side, edgeY, pos, size) {
  const dir = side === "below" ? 1 : -1;
  const byBox = new Map();
  for (const it of items) {
    if (!byBox.has(it.o)) byBox.set(it.o, []);
    byBox.get(it.o).push(it);
  }
  const routes = {};
  for (const [o, group] of byBox) {
    const top = pos[o].y, bot = top + size[o].h;
    let cursor = side === "below" ? top - BOX_LABEL_GAP : bot + BOX_LABEL_GAP;
    for (const it of group) {
      const lane = plan.laneOf[items.indexOf(it)];
      const sx = it.sx == null ? it.cx : it.sx;
      const endY = side === "below" ? top : bot;
      const ly = edgeY + dir * (LANE_INSET + lane * LANE_PITCH);
      let pts = lane < 0
        ? [{ x: it.cx, y: edgeY }, { x: it.cx, y: endY }]
        : [{ x: sx, y: edgeY }, { x: sx, y: ly }, { x: it.cx, y: ly }, { x: it.cx, y: endY }];
      pts = pts.filter((p, k) => k === 0 || p.x !== pts[k - 1].x || p.y !== pts[k - 1].y);
      const lb = edgeLabelBox(it.e);
      let label = null;
      if (lb) {
        const y = side === "below" ? cursor - lb.height : cursor;
        label = { x: it.cx + LINE_GAP, y, width: lb.width, height: lb.height };
        cursor = side === "below" ? y - 4 : cursor + lb.height + 4;
      }
      routes[it.e.id] = { pts, label };
    }
  }
  return routes;
}

function placeAround(arranged) {
  const { W, H, nodes, edges: cross, sideOf, want, at } = arranged;
  const size = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const ids = (s) => nodes.filter((n) => sideOf[n.id] === s).map((n) => n.id);
  const above = ids("above"), below = ids("below");
  const column = (list) => {
    list.sort((p, q) => want[p].y - want[q].y);
    const out = [];
    let y = 0;
    for (const id of list) {
      const top = Math.max(want[id].y - size[id].h / 2, y);
      out.push([id, top]);
      y = top + size[id].h + SIDE_GAP;
    }
    return out;
  };
  const left = column(ids("left")), right = column(ids("right"));
  const colW = (list) => Math.max(0, ...list.map(([id]) => size[id].w));
  const labFor = (id) => Math.max(0, ...cross.filter((e) => e.a === id || e.b === id).map((e) => labelBox(e).width));
  const labW = (list) => Math.max(0, ...list.map(([id]) => labFor(id)));
  const labelW = (id) => Math.max(0, ...cross.filter((e) => e.a === id || e.b === id).map((e) => (edgeLabelBox(e) || {}).width || 0));
  const bx = left.length ? colW(left) + labW(left) + 2 * SIDE_LANE + 8 : 0;
  const origin = bx + FRAME_OX;
  const exits = {};
  for (const id of [...above, ...below]) exits[id] = [];
  for (const e of cross) {
    const o = outsideEnd(e, sideOf);
    if (o && exits[o]) {
      const sx = exitX(e, o, at, origin);
      if (sx != null) exits[o].push(sx);
    }
  }
  const aboveLeft = spreadCenters(above, size, want, labelW, exits, bx);
  const belowLeft = spreadCenters(below, size, want, labelW, exits, bx);
  const aboveItems = verticalItems(above, aboveLeft, cross, sideOf, at, origin, size);
  const belowItems = verticalItems(below, belowLeft, cross, sideOf, at, origin, size);
  const abovePlan = lanePlan(aboveItems), belowPlan = lanePlan(belowItems);
  const aboveH = above.length ? Math.max(...above.map((id) => size[id].h)) : 0;
  const aboveLab = above.length ? Math.max(...above.map((id) => labelStackH(id, cross))) : 0;
  const belowLab = below.length ? Math.max(...below.map((id) => labelStackH(id, cross))) : 0;
  const aboveGutter = above.length ? sideGutter(abovePlan.laneCount, aboveLab) : 0;
  const belowGutter = below.length ? sideGutter(belowPlan.laneCount, belowLab) : 0;
  const by = aboveH + aboveGutter;
  const pos = {};
  for (const [id, top] of left) pos[id] = { x: bx - 2 * SIDE_LANE - 8 - labW(left) - size[id].w, y: by + top };
  const rx = bx + W + (right.length ? labW(right) + 2 * SIDE_LANE + 8 : 0);
  for (const [id, top] of right) pos[id] = { x: rx, y: by + top };
  for (const id of above) pos[id] = { x: aboveLeft[id], y: aboveH - size[id].h };
  const belowY = by + H + belowGutter;
  for (const id of below) pos[id] = { x: belowLeft[id], y: belowY };
  const sideRoutes = {
    ...stampRoutes(aboveItems, abovePlan, "above", by, pos, size),
    ...stampRoutes(belowItems, belowPlan, "below", by + H, pos, size),
  };
  const corners = nodes.map((n) => [pos[n.id].x + size[n.id].w, pos[n.id].y + size[n.id].h]);
  const overhang = [...above, ...below].map((id) => pos[id].x + size[id].w / 2 + LINE_GAP + labelW(id));
  return {
    ...arranged, pos, bx, by, size, sideRoutes,
    width: Math.max(bx + W, ...corners.map((p) => p[0]), ...overhang) + 8,
    height: Math.max(by + H, ...corners.map((p) => p[1])),
  };
}

// ELK lays out the inside of a concept. Edges with both ends inside stay in that interior.
// Externals sit on the nearest side of the boundary (above, right, below, left). Above and
// below, each edge keeps its own lane or a straight drop, and the row spreads for the label.
// The inside is tried unwrapped, wrapped into rows and top to bottom; whichever scales largest
// wins, with a preference for unwrapped left to right.
async function layoutBridged(boundary, outside, edges, onClick, enter, onDbl) {
  const gen = ++layoutGen;
  const inner = new Set(boundary.children.map((n) => n.id));
  const insideEdges = edges.filter((e) => inner.has(e.a) && inner.has(e.b));
  const onFrame = (e) => e.a === "boundary" || e.b === "boundary";
  const crossing = edges.filter((e) => onFrame(e) || inner.has(e.a) !== inner.has(e.b));
  const OX = 8, OY = 28, LANE = 18;
  const avail = availSize();
  const innerEndId = (id) => id === "boundary" || inner.has(id);
  const otherEnd = (e) => (innerEndId(e.b) ? e.a : e.b);
  const innerEnds = (e) => (e.bundle || [innerEndId(e.b) ? e.b : e.a]).filter((id) => inner.has(id));

  // Anchors come from the inner layout, so each try places and groups its own outside.
  const arrange = (p1) => {
    const at = Object.fromEntries(p1.children.map((n) => [n.id, n]));
    const W = p1.width + 2 * OX, H = p1.height + OY + 8;
    const endsOf = (e) => innerEnds(e).map((id) => at[id]).filter(Boolean);
    const anchor = {};
    for (const n of outside) {
      const ns = crossing.filter((e) => otherEnd(e) === n.id).flatMap(endsOf);
      anchor[n.id] = ns.length
        ? { x: OX + ns.reduce((t, k) => t + k.x + k.width / 2, 0) / ns.length, y: OY + ns.reduce((t, k) => t + k.y + k.height / 2, 0) / ns.length }
        : { x: W / 2, y: H / 2 };
    }
    // Container-end groups stay incoming on the left and outgoing on the right.
    const laneSide = {};
    for (const e of crossing) {
      if (e.lane !== "in" && e.lane !== "out") continue;
      const id = otherEnd(e);
      const side = e.lane === "in" ? "left" : "right";
      if (!laneSide[id]) laneSide[id] = side;
      else if (laneSide[id] !== side) laneSide[id] = "mix";
    }
    const chosen = assignSides(outside.map((n) => ({ id: n.id, ...anchor[n.id] })), W, H);
    for (const [id, side] of Object.entries(laneSide)) if (side === "left" || side === "right") chosen[id] = side;
    const meta = {};
    for (const n of outside) {
      const callers = [...new Set(crossing.filter((e) => otherEnd(e) === n.id).flatMap((e) => innerEnds(e)))];
      meta[n.id] = { kind: (byId[n.id] && byId[n.id].kind) || "", callers };
    }
    const bySide = { above: [], right: [], below: [], left: [] };
    for (const n of outside) bySide[chosen[n.id]].push(n.id);
    const groups = [], memberOf = {}, sideOf = {};
    for (const s of ["above", "right", "below", "left"]) {
      // Kind-groups are for externals. A concept stub stays its own box so it matches one drawer entry.
      const extIds = bySide[s].filter((id) => byId[id] && byId[id].ext);
      const conceptIds = bySide[s].filter((id) => !byId[id] || !byId[id].ext);
      for (const g of groupExternals(extIds, meta)) {
        if (g.grouped) g.id = `xg:${s}:${g.kind}:${g.caller}`;
        groups.push(g);
        sideOf[g.id] = s;
        if (g.grouped) for (const id of g.members) memberOf[id] = g.id;
      }
      for (const id of conceptIds) {
        groups.push({ id, members: [id] });
        sideOf[id] = s;
      }
    }
    const nodes = groups.map((g) => (g.grouped ? groupBox(g) : outside.find((n) => n.id === g.id))).filter(Boolean);
    const want = {};
    for (const g of groups) {
      const pts = g.members.map((id) => anchor[id]);
      want[g.id] = { x: pts.reduce((t, p) => t + p.x, 0) / pts.length, y: pts.reduce((t, p) => t + p.y, 0) / pts.length };
    }
    return { at, W, H, nodes, edges: retargetCrossing(crossing, memberOf), sideOf, want, groups };
  };

  // Two first-tier boxes joined by an edge sit in one column; leave room for that edge's label.
  // Stated edges keep a route so they still pull layers together, but no label lane.
  const pinned = new Set(boundary.children.filter((n) => n.pinned).map((n) => n.id));
  const tierLink = insideEdges.some((e) => pinned.has(e.a) && pinned.has(e.b) && e.text);
  const layoutInside = (dir, wrapping, ratio) => elk.layout({
    id: "inner",
    layoutOptions: { ...elkOptions({ dir, layer: 30, gap: tierLink ? 60 : 24 }), ...(wrapping ? { "elk.layered.wrapping.strategy": wrapping, "elk.aspectRatio": String((avail.w / avail.h) * ratio) } : {}) },
    children: boundary.children.map((n) => ({ id: n.id, width: n.w, height: n.h, ...(n.pinned ? { layoutOptions: { "elk.layered.layering.layerConstraint": "FIRST" } } : {}) })),
    edges: insideEdges.map(elkEdge),
  });

  try {
    const tries = [];
    let layoutErr = null;
    // Bias: unwrapped left to right is preferred; top to bottom must scale 10% better and wrapping
    // (which adds long return loops between rows) 25% better before either is chosen.
    const modes = [["RIGHT", null, 1, 1], ...["MULTI_EDGE", "SINGLE_EDGE"].flatMap((w) => [0.5, 0.8, 1.1].map((r) => ["RIGHT", w, r, 1.25])), ["DOWN", null, 1, 1.1]];
    for (const [dir, w, r, bias] of modes) {
      try {
        const p1 = await layoutInside(dir, w, r);
        tries.push({ dir, wrapping: w, ratio: r, bias, p1, ...placeAround(arrange(p1)) });
      } catch (err) {
        if (!layoutErr) {
          const into = insideEdges.filter((e) => pinned.has(e.b) && !pinned.has(e.a)).map((e) => `${e.a}->${e.b}`).join(",");
          layoutErr = new Error(`${dir} ${err.message} [${into}]`);
        }
      }
    }
    if (gen !== layoutGen) return;
    if (!tries.length) throw layoutErr || new Error("no layout");
    const score = (t) => Math.min(avail.w / t.width, avail.h / t.height) / t.bias; // must beat unwrapped by its bias
    const best = tries.reduce((p, q) => (score(q) > score(p) ? q : p));
    const { p1, at, W, H, bx, by, pos, size } = best;
    const diagram = document.getElementById("diagram");
    if (diagram) diagram.dataset.layout = (best.dir === "DOWN" ? "down" : best.wrapping ? `${best.wrapping} ${best.ratio}` : "unwrapped") + " · around";

    externalGroups = {};
    for (const g of best.groups) if (g.grouped) externalGroups[g.id] = g;

    const dx = bx + OX, dy = by + OY;
    const shift = (p) => ({ x: p.x + dx, y: p.y + dy });
    const used = {};
    const crossEdges = best.edges.map((e) => {
      const incoming = e.b === "boundary" || inner.has(e.b);
      const o = incoming ? e.a : e.b;
      if (!pos[o] || !size[o]) return { id: e.id, sections: [], labels: [] };
      const where = best.sideOf[o];
      const box = { ...pos[o], w: size[o].w, h: size[o].h };
      if (where === "above" || where === "below") {
        const planned = best.sideRoutes[e.id];
        if (!planned || planned.pts.length < 2) return { id: e.id, sections: [], labels: [] };
        let pts = planned.pts.map((p) => ({ x: p.x, y: p.y }));
        if (incoming) pts.reverse();
        pts = pts.filter((p, i) => i === 0 || p.x !== pts[i - 1].x || p.y !== pts[i - 1].y);
        const label = planned.label;
        return {
          id: e.id, sections: [{ startPoint: pts[0], endPoint: pts[pts.length - 1], bendPoints: pts.slice(1, -1) }],
          labels: label ? [{ text: e.text || "", ...label }] : [],
        };
      }
      const ns = (e.bundle || [incoming ? e.b : e.a]).map((id) => at[id]).filter(Boolean);
      if (!ns.length && e.a !== "boundary" && e.b !== "boundary") return { id: e.id, sections: [], labels: [] };
      if (!ns.length) {
        const lb = labelBox(e);
        const cy = box.y + box.h / 2;
        let pts, label;
        if (where === "left" || where === "right") {
          const onLeft = where === "left";
          const key = onLeft ? "frameW" : "frameE";
          const k = (used[key] = (used[key] || 0) + 1) - 1;
          const y = Math.max(by + 20, Math.min(by + H - 20, cy + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 8));
          const edgeX = onLeft ? bx : bx + W, laneX = onLeft ? bx - LANE : bx + W + LANE, boxX = onLeft ? box.x + box.w : box.x;
          pts = [{ x: edgeX, y }, { x: laneX, y }, { x: laneX, y: cy }, { x: boxX, y: cy }];
          label = { x: onLeft ? box.x + box.w + 4 : box.x - lb.width - 4, y: cy - lb.height - 2 };
        }
        if (incoming) pts.reverse();
        pts = pts.filter((p, i) => i === 0 || p.x !== pts[i - 1].x || p.y !== pts[i - 1].y);
        return {
          id: e.id, sections: [{ startPoint: pts[0], endPoint: pts[pts.length - 1], bendPoints: pts.slice(1, -1) }],
          labels: e.text || e.via ? [{ text: e.text || "", ...label, ...lb }] : [],
        };
      }
      // A bundled line normally stops on the frame. One that came from a container-end
      // relationship still has to land on a child the code reaches: the near child on
      // that side, so the arrow does not cross its siblings.
      const n = e.lane === "in" ? ns.reduce((p, q) => (q.x < p.x ? q : p))
        : e.lane === "out" ? ns.reduce((p, q) => (q.x + q.width > p.x + p.width ? q : p))
        : ns[0];
      const lb = labelBox(e);
      const cy = box.y + box.h / 2;
      let pts, label;
      const onLeft = where === "left";
      const key = (onLeft ? "W" : "E") + n.id, k = (used[key] = (used[key] || 0) + 1) - 1;
      const mid = e.lane ? n.y + n.height / 2 : ns.reduce((t, q) => t + q.y + q.height / 2, 0) / ns.length;
      const py = dy + mid + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 8;
      const edgeX = onLeft ? bx : bx + W, laneX = onLeft ? bx - LANE : bx + W + LANE;
      const y0 = py - dy, [x0, x1] = onLeft ? [0, n.x] : [n.x + n.width, p1.width + OX];
      const blocked = (!e.lane && e.bundle) || p1.children.some((q) => q !== n && y0 > q.y - 4 && y0 < q.y + q.height + 4 && q.x < x1 && q.x + q.width > x0);
      const innerX = onLeft ? dx + n.x : dx + n.x + n.width, boxX = onLeft ? box.x + box.w : box.x;
      pts = [...(blocked ? [] : [{ x: innerX, y: py }]), { x: edgeX, y: py }, { x: laneX, y: py }, { x: laneX, y: cy }, { x: boxX, y: cy }];
      label = { x: onLeft ? box.x + box.w + 4 : box.x - lb.width - 4, y: cy - lb.height - 2 };
      if (incoming) pts.reverse();
      pts = pts.filter((p, i) => i === 0 || p.x !== pts[i - 1].x || p.y !== pts[i - 1].y);
      return {
        id: e.id, sections: [{ startPoint: pts[0], endPoint: pts[pts.length - 1], bendPoints: pts.slice(1, -1) }],
        labels: e.text || e.via ? [{ text: e.text || "", ...label, ...lb }] : [],
      };
    });
    const insideById = Object.fromEntries(insideEdges.map((e) => [e.id, e]));
    const insideOut = p1.edges.map((e) => {
      const meta = insideById[e.id];
      const a = at[e.sources[0]], z = at[e.targets[0]];
      const drawn = (e.sections || []).flatMap((s) => [s.startPoint, ...(s.bendPoints || []), s.endPoint]).filter(Boolean);
      if (a && z) {
        const path = settleInnerEdge(drawn, a, z, p1.children, p1.width, p1.height);
        if (path !== drawn) {
          const lb = meta && (meta.text || meta.via) ? labelBox(meta) : null;
          e = {
            ...e,
            sections: [{ startPoint: path[0], endPoint: path[path.length - 1], bendPoints: path.slice(1, -1) }],
            labels: lb ? [{ text: meta.text || "", x: -9999, y: -9999, width: lb.width, height: lb.height }] : [],
          };
        }
      }
      return { ...e, sections: (e.sections || []).map((q) => ({ startPoint: shift(q.startPoint), endPoint: shift(q.endPoint), bendPoints: (q.bendPoints || []).map(shift) })), labels: (e.labels || []).map((l) => ({ ...l, ...shift(l) })) };
    });
    const out = {
      width: best.width, height: best.height,
      edges: [...insideOut, ...crossEdges],
      children: [
        { id: "boundary", x: bx, y: by, width: W, height: H, children: p1.children.map((k) => ({ ...k, x: k.x + OX, y: k.y + OY })) },
        ...best.nodes.map((n) => ({ id: n.id, x: pos[n.id].x, y: pos[n.id].y, width: n.w, height: n.h })),
      ],
    };
    if (gen !== layoutGen) return;
    render(out, [boundary, ...best.nodes], [...insideEdges, ...best.edges], onClick, enter, onDbl);
  } catch (err) {
    if (gen !== layoutGen) return;
    return empty("Layout failed: " + err.message);
  }
}

const labelW = (e) => textW(e.text, 400, 11.5) + 6 + (e.via ? textW(e.via, 600, 10.5, true) + 18 : 0);

// Labels may stack after ELK and the longest-segment snap. Shift each one along its edge,
// then to the other side of the line, until it clears other labels and boxes. A container
// (the boundary) only blocks its title band and anything that sticks out of it.
const LABEL_PAD = 3;
const LABEL_STEP = 10;

function boxSize(r) {
  return { w: r.width != null ? r.width : r.w, h: r.height != null ? r.height : r.h };
}

function overlaps(a, b, pad) {
  const as = boxSize(a), bs = boxSize(b);
  return a.x < b.x + bs.w + pad && a.x + as.w + pad > b.x && a.y < b.y + bs.h + pad && a.y + as.h + pad > b.y;
}

function obstacleHits(label, box) {
  if (!overlaps(label, box, LABEL_PAD)) return false;
  if (!box.container) return true;
  const lw = boxSize(label).w, lh = boxSize(label).h, bw = boxSize(box).w, bh = boxSize(box).h;
  const inside = label.x >= box.x && label.y >= box.y + 32 && label.x + lw <= box.x + bw && label.y + lh <= box.y + bh;
  return !inside;
}

function polyLen(pts) {
  let n = 0;
  for (let i = 1; i < pts.length; i++) n += dist(pts[i - 1], pts[i]);
  return n;
}

function pointAt(pts, t) {
  let left = Math.max(0, t);
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i], d = dist(a, b);
    if (left <= d || i === pts.length - 1) {
      const k = d ? Math.max(0, Math.min(left, d)) / d : 0;
      return { x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k, vertical: Math.abs(b.x - a.x) <= Math.abs(b.y - a.y) };
    }
    left -= d;
  }
  const last = pts[pts.length - 1];
  return { x: last.x, y: last.y, vertical: true };
}

function closestT(pts, x, y) {
  let best = 0, bestD = Infinity, acc = 0;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i], dx = b.x - a.x, dy = b.y - a.y, d2 = dx * dx + dy * dy;
    const k = d2 ? Math.max(0, Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / d2)) : 0;
    const px = a.x + dx * k, py = a.y + dy * k, dd = (px - x) ** 2 + (py - y) ** 2;
    if (dd < bestD) { bestD = dd; best = acc + k * Math.sqrt(d2); }
    acc += Math.sqrt(d2);
  }
  return best;
}

function anchorAt(pts, t, w, h, side) {
  const p = pointAt(pts, t);
  if (p.vertical) return side > 0 ? { x: p.x + 6, y: p.y - h / 2 } : { x: p.x - w - 6, y: p.y - h / 2 };
  return side > 0 ? { x: p.x - w / 2, y: p.y - h - 2 } : { x: p.x - w / 2, y: p.y + 4 };
}

function labelSpots(label) {
  const spots = [{ x: label.x, y: label.y }];
  const pts = label.pts;
  if (!pts || pts.length < 2) return spots;
  const t0 = closestT(pts, label.x + label.width / 2, label.y + label.height / 2);
  const total = polyLen(pts);
  for (const side of [1, -1]) {
    for (let d = 0; d <= total; d += LABEL_STEP) {
      if (t0 + d <= total) spots.push(anchorAt(pts, t0 + d, label.width, label.height, side));
      if (d && t0 - d >= 0) spots.push(anchorAt(pts, t0 - d, label.width, label.height, side));
    }
  }
  return spots;
}

function separateLabels(labels, obstacles) {
  const placed = [];
  for (const label of labels) {
    let chosen = null;
    for (const spot of labelSpots(label)) {
      const box = { x: spot.x, y: spot.y, width: label.width, height: label.height };
      const blocked = (obstacles || []).some((o) => obstacleHits(box, o)) || placed.some((p) => overlaps(box, p, LABEL_PAD));
      if (!blocked) { chosen = spot; break; }
    }
    if (chosen) { label.x = chosen.x; label.y = chosen.y; }
    placed.push({ x: label.x, y: label.y, width: label.width, height: label.height });
  }
  return labels;
}

function collapseStackedPairs(labels) {
  let changed = false;
  for (let i = 0; i < labels.length; i++) {
    if (labels[i].drop) continue;
    for (let j = i + 1; j < labels.length; j++) {
      const a = labels[i], b = labels[j];
      if (b.drop || !a.a || !b.a) continue;
      const same = (a.a === b.a && a.b === b.b) || (a.a === b.b && a.b === b.a);
      if (!same || !overlaps(a, b, LABEL_PAD)) continue;
      const hosts = (x) => (x.rels || []).some((r) => r.kind === "hosts");
      const lead = hosts(a) && !hosts(b) ? [b, a] : [a, b];
      a.text = edgeLabelText([lead[0].text, lead[1].text]);
      if (a.meta) a.meta.text = a.text;
      b.drop = true;
      changed = true;
    }
  }
  return changed;
}

function placeEdgeLabels(out, em, obstacles) {
  const labels = [];
  for (const e of out.edges) {
    const m = em[e.id];
    if (!m) continue;
    if (!m.lines) labelBox(m);
    for (const l of e.labels || []) {
      const pts = (e.sections || []).flatMap((q) => [q.startPoint, ...(q.bendPoints || []), q.endPoint]);
      const near = pts.some((p, i) => i && Math.abs((pts[i - 1].x + p.x) / 2 - (l.x + l.width / 2)) < l.width + 60 && Math.abs((pts[i - 1].y + p.y) / 2 - (l.y + l.height / 2)) < l.height + 60);
      if (pts.length > 1 && !near) {
        let best = 1, len = -1;
        for (let i = 1; i < pts.length; i++) { const d = dist(pts[i - 1], pts[i]); if (d > len) { len = d; best = i; } }
        const vertical = pts[best - 1].x === pts[best].x;
        l.x = (pts[best - 1].x + pts[best].x) / 2 + (vertical ? 6 : 4);
        l.y = (pts[best - 1].y + pts[best].y) / 2 - (vertical ? l.height / 2 : l.height + 2);
      }
      labels.push({ x: l.x, y: l.y, width: l.width, height: l.height, pts, a: m.a, b: m.b, text: m.text, rels: m.rels, meta: m, elk: l });
    }
  }
  separateLabels(labels, obstacles);
  if (collapseStackedPairs(labels)) {
    for (const rec of labels) {
      if (rec.drop) continue;
      rec.meta.lines = null;
      const box = labelBox(rec.meta);
      rec.width = box.width;
      rec.height = box.height;
      rec.elk.width = box.width;
      rec.elk.height = box.height;
    }
    separateLabels(labels.filter((rec) => !rec.drop), obstacles);
  }
  for (const rec of labels) {
    rec.elk.x = rec.x;
    rec.elk.y = rec.y;
    rec.elk.hidden = !!rec.drop;
  }
}

function render(out, nodes, edges, onClick, enter, onDbl) {
  setStage("diagram");
  // Grouped (big) leaves keep 13px names at 9px or more and pan; everything else fits whole.
  minScale = nodes.some((n) => n.children && n.children.some((k) => k.toggle || (k.children && k.toggle))) ? 0.7 : 0;
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
  for (const [gid, g] of Object.entries(externalGroups)) {
    if (!rects[gid]) continue;
    for (const id of g.members || []) if (!rects[id]) rects[id] = rects[gid];
  }

  placeEdgeLabels(out, em, Object.entries(rects).map(([id, r]) => ({
    x: r.x, y: r.y, w: r.w, h: r.h, container: !!(meta[id] && meta[id].children),
  })));

  const edgeEls = [];
  for (const e of out.edges) {
    const m = em[e.id];
    if (!m) continue;
    const g = svgEl("g", { class: "edge " + (m.cls || "") });
    for (const s of e.sections || []) {
      const pts = [s.startPoint, ...(s.bendPoints || []), s.endPoint];
      const arrow = `url(#${m.cls && m.cls.includes("integration") ? "arrow-int" : "arrow"})`;
      g.append(svgEl("path", { d: rounded(pts), "marker-end": arrow, ...(m.cls && m.cls.includes("both") ? { "marker-start": arrow } : {}) }));
    }
    for (const l of e.labels || []) {
      if (l.hidden) continue;
      if (!m.lines) labelBox(m); // edges re-pointed at ports were measured on a copy
      m.lines.forEach((line, i) => {
        const t = svgEl("text", { x: l.x + 3, y: l.y + 11 + i * 13 });
        t.textContent = line;
        g.append(t);
      });
      if (m.via) {
        const x = l.x + 3, w = textW(m.via, 600, 10.5, true) + 12;
        const pill = svgEl("g", { class: "via", transform: `translate(${x},${l.y + (m.lines || []).length * 13 + 2})` });
        const vt = svgEl("text", { x: 6, y: 12 });
        vt.textContent = m.via;
        pill.append(svgEl("rect", { width: w, height: 16, rx: 8 }), vt);
        g.append(pill);
      }
      if (!g.querySelector(".count") && m.count > 1) {
        const cw = labelBox(m).countW;
        const badge = svgEl("g", { class: "count", transform: `translate(${l.x + l.width - cw},${l.y})` });
        const bt = svgEl("text", { x: cw / 2, y: 11, "text-anchor": "middle" });
        bt.textContent = String(m.count);
        badge.append(svgEl("rect", { width: cw, height: 14, rx: 7 }), bt);
        g.append(badge);
      }
    }
    if (m.title) { const t = svgEl("title"); t.textContent = m.title; g.append(t); }
    const rels = m.rels || [];
    const stated = rels.find((r) => r.backing === "stated");
    if (rels.length > 1 || stated) {
      // A wide invisible stroke makes the thin line easy to click.
      for (const p of [...g.querySelectorAll("path")]) g.prepend(svgEl("path", { d: p.getAttribute("d"), class: "hit" }));
      const id = rels.length > 1
        ? "bundle:" + rels.map((r) => M.relationships.indexOf(r)).filter((i) => i >= 0).join(",")
        : "rel:" + M.relationships.indexOf(stated);
      g.classList.add("links");
      if (view.sel === id) g.classList.add("hot", "picked");
      g.onclick = (ev) => { ev.stopPropagation(); if (!moved) go(view.focus, id, { v: view.mode }); };
    }
    edgeG.append(g);
    edgeEls.push({ g, a: m.a, b: m.b });
  }

  // Where a lateral jump came from: its box or group frame, the jumped-to symbol and the edges between
  // them only, fading after a moment so it marks the way without flooding a dense view.
  const glowing = new Set();
  if (glow && view.from && view.from !== "~") {
    const box = project(view.from, view.focus);
    const member = new Set();
    for (const { n } of placed) {
      const m = meta[n.id];
      if (!m) continue;
      if (n.id === view.from || n.id === box || m.concept === view.from) glowing.add(n.id);
      if (m.more === view.from || (m.sym && m.sym.concept === view.from)) member.add(n.id);
    }
    if (sel && rects[sel]) glowing.add(sel);
    for (const x of edgeEls) {
      const toBox = glowing.has(x.a) && !meta[x.a].children || glowing.has(x.b) && !meta[x.b].children;
      const link = sel && ((x.a === sel && member.has(x.b)) || (x.b === sel && member.has(x.a)));
      if (link || (toBox && !sel)) x.g.classList.add("glow");
    }
    clearTimeout(glowTimer);
    glowTimer = setTimeout(() => { glow = false; for (const x of document.querySelectorAll("#diagram .glow")) x.classList.remove("glow"); }, 2500);
  }

  const linked = sel && (symById[sel] || ghostById[sel]);
  const near = new Set();
  if (linked) for (const x of edgeEls) if (edgeMatches(x, sel, externalGroups)) near.add(x.a).add(x.b);

  for (const { n, x, y } of placed) {
    const m = meta[n.id];
    if (m.children) {
      const g = svgEl("g", { class: m.cls + (glowing.has(n.id) ? " glow" : ""), transform: `translate(${x},${y})` });
      if (m.concept) {
        g.dataset.concept = m.concept;
        g.onmouseenter = () => linkHover(m.concept, true);
        g.onmouseleave = () => linkHover(m.concept, false);
      }
      if (m.lane) g.dataset.lane = m.lane;
      g.append(svgEl("rect", { class: "frame", width: n.width, height: n.height, rx: 14 }));
      const t = svgEl("text", { class: "label", x: 16, y: 25 });
      t.textContent = m.label;
      g.append(t);
      if (m.concept || m.toggle) {
        g.classList.add("clickable");
        t.setAttribute("tabindex", 0);
        t.setAttribute("role", "button");
        t.onclick = (ev) => { ev.stopPropagation(); if (!moved) onClick(n.id); };
        t.onkeydown = (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onClick(n.id); } };
      }
      boxG.append(g);
      continue;
    }
    const groupedSel = !!(sel && externalGroups[n.id] && externalGroups[n.id].members.includes(sel));
    const g = svgEl("g", { class: m.cls + (n.id === sel || groupedSel ? " sel" : "") + (glowing.has(n.id) ? " glow" : ""), transform: `translate(${x},${y})`, tabindex: 0, role: "button", "aria-label": m.name || n.id });
    const ov = overlayClass(n.id, m);
    if (ov) g.classList.add(ov);
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
      // Markers sit top right, right to left: env count, then start.
      let px = n.width - 10;
      if (m.env) { px -= textW(`env ${m.env}`, 600, 10.5, true) + 12; g.append(envPill(`env ${m.env}`, px, 9, `${m.env} environment variable${m.env > 1 ? "s" : ""} read here`)); px -= 6; }
      if (m.entry) {
        px -= textW(START, 600, 10.5, true) + 12;
        const files = (leafList(byId[n.id]).flatMap((l) => l.entry_file ? [].concat(l.entry_file) : (l.entryFiles || []))).join(", ");
        const p = envPill(START, px, 9, `Starts here: owns the entry point ${files}`);
        p.classList.add("start");
        g.append(p);
        px -= 6;
      }
      if (m.tag) {
        px -= textW(m.tag, 600, 10.5, true) + 12;
        const p = envPill(m.tag, px, 9, m.tag);
        p.classList.add("mark-" + m.tag);
        g.append(p);
      }
      m.lines.forEach((line, i) => {
        const t = svgEl("text", { class: "sum", x: 16, y: 46 + i * 16 });
        t.textContent = line;
        g.append(t);
      });
    }
    if (sel && rects[sel] && linked && !near.has(n.id) && n.id !== sel) g.classList.add("dim");
    g.onclick = (ev) => { ev.stopPropagation(); if (!moved) onClick(n.id); };
    g.ondblclick = (ev) => { ev.stopPropagation(); if (onDbl) onDbl(n.id); };
    g.onkeydown = (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onClick(n.id); } };
    g.onmouseenter = () => { hot(edgeEls, n.id, true); touch(m.touches, true); };
    g.onmouseleave = () => { hot(edgeEls, n.id, false); touch(m.touches, false); };
    g.dataset.id = n.id;
    if (m.lane) g.dataset.lane = m.lane;
    const concept = byId[n.id] ? n.id : m.cls.includes("ghost") && m.sym ? m.sym.concept : null;
    if (concept && n.id !== view.focus) {
      g.dataset.concept = concept;
      g.addEventListener("mouseenter", () => linkHover(concept, true));
      g.addEventListener("mouseleave", () => linkHover(concept, false));
    }
    nodeG.append(g);
  }
  if (sel) hot(edgeEls, sel, true);
  svg.onclick = () => { if (!moved && view.sel) go(view.focus, null, { v: view.mode }); };

  legendFromDiagram(svg);
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
  // Headless render.js reads this SVG. edges line up with g.edge in DOM order.
  if (window.cbiOnDiagram) window.cbiOnDiagram(svg, out.edges.map((e) => em[e.id] || null));
  if (M) drawer();
  loadTreeAfterPaint();
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
  const kindLine = m.kindText || m.sym.kind || "";
  const shown = m.mark && !kindLine.includes(m.mark) ? (kindLine ? `${kindLine} · ${m.mark}` : m.mark) : kindLine;
  const kind = svgEl("text", { class: "kind", x: 12, y: 36 });
  kind.textContent = shown;
  g.append(kind);
  if (m.envText) g.append(envPill(m.envText, 12 + textW(shown, 400, 11) + 8, 24, (m.sym.env || []).map(envName).join(", ")));
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

// A bundled stub stands for links to several inner boxes; hovering its source box lights them up.
function touch(ids, on) {
  for (const id of ids || []) {
    const g = document.querySelector(`#diagram [data-id="${CSS.escape(id)}"]`);
    if (g) g.classList.toggle("touched", on);
  }
}

function hot(edgeEls, id, on) {
  for (const x of edgeEls) {
    if (!edgeMatches(x, id, externalGroups)) continue;
    const stay = !on && view.sel && edgeMatches(x, view.sel, externalGroups);
    x.g.classList.toggle("hot", on || stay);
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
  if (window.cbiOnDiagram) window.cbiOnDiagram(svg, []);
  loadTreeAfterPaint();
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

// The key lists every colour on screen, read back after rendering: the diagram and the drawer dots.
// Miniatures of the real marks, in short sections. It floats bottom-left and folds to a "Key" pill.
let legendInside = null;
let externalGroups = {}; // grouped external box id -> {kind, caller, members}
let lastDiagram = null;
const KEY_STORE = "cbi.keyCollapsed";
function keyCollapsed() {
  if (window.cbiRender) return true; // the headless render page draws its own key
  try { const v = localStorage.getItem(KEY_STORE); if (v !== null) return v === "1"; } catch { /* private mode */ }
  return innerWidth <= 1100; // narrow windows start folded
}
function setKeyCollapsed(v) { try { localStorage.setItem(KEY_STORE, v ? "1" : "0"); } catch { /* private mode */ } }

function mini(w, h, build) {
  const s = svgEl("svg", { width: w, height: h, viewBox: `0 0 ${w} ${h}`, "aria-hidden": "true" });
  build(s);
  return s;
}
const miniBox = (cls, stripe) => mini(26, 16, (s) => {
  const g = svgEl("g", { class: cls });
  g.append(svgEl("rect", { class: "body", x: 1, y: 1, width: 24, height: 14, rx: 3 }));
  if (stripe) g.append(svgEl("rect", { class: "stripe", x: 1, y: 3.5, width: 2.5, height: 9, rx: 1 }));
  s.append(g);
});
const miniArea = (cls) => mini(26, 16, (s) => {
  const g = svgEl("g", { class: cls });
  g.append(svgEl("rect", { class: "frame", x: 1, y: 1, width: 24, height: 14, rx: 4 }));
  s.append(g);
});
let keyMarker = 0;
const miniLine = (cls) => mini(32, 12, (s) => {
  const id = "keyarrow" + keyMarker++;
  const m = svgEl("marker", { id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto-start-reverse" });
  m.append(svgEl("path", { d: "M0,1 L9,5 L0,9 z", fill: "context-stroke" }));
  const defsEl = svgEl("defs");
  defsEl.append(m);
  const g = svgEl("g", { class: "edge " + cls });
  g.append(svgEl("path", { d: "M3,6 H29", "marker-end": `url(#${id})`, ...(cls.includes("both") ? { "marker-start": `url(#${id})` } : {}) }));
  s.append(defsEl, g);
});
const miniEnv = () => mini(34, 18, (s) => s.append(envPill("env", 1, 0.5, "")));
const miniBadge = () => mini(34, 18, (s) => {
  const g = svgEl("g", { class: "sym" }), b = svgEl("g", { class: "badge" }), t = svgEl("text", { x: 6, y: 13 });
  t.textContent = "✓ 3";
  b.append(svgEl("rect", { width: textW("✓ 3", 600, 11) + 12, height: 18, rx: 9 }), t);
  g.append(b);
  s.append(g);
});

function overlayRows() {
  if (view.overlay === "links") return ["Tests", [[miniBox("node ov-yes", true), "Has tests"], [miniBox("node ov-no", true), "No tests"]]];
  if (view.overlay === "coverage") return ["Coverage", [
    [miniBox("node ov-yes", true), "Covered"], [miniBox("node ov-part", true), "Partly covered"],
    [miniBox("node ov-no", true), "Uncovered"], [miniBox("node ov-none", true), "No coverage"],
  ]];
  if (view.overlay === "result") return ["Results", [
    [miniBox("node ov-pass", true), "Passing"], [miniBox("node ov-fail", true), "Failing"],
    [miniBox("node ov-skip", true), "Skipped"], [miniBox("node ov-none", true), "No result"],
  ]];
  return null;
}

function legendFromDiagram(svg) {
  if (svg) lastDiagram = svg;
  const lg = document.getElementById("legend");
  lg.replaceChildren();
  // Drawer dots carry role and kind colours that the diagram may not draw.
  const drawer = document.getElementById("drawer");
  const has = (sel) => !!(svg && svg.querySelector(sel)) || !!(drawer && drawer.querySelector(sel));
  const sections = [];
  const sec = (title, rows) => { if (rows.length) sections.push([title, rows]); };
  const overlay = overlayRows();
  if (overlay) sec(overlay[0], overlay[1]);
  else if (svg) {
    sec("Area", legendInside ? [[miniArea(`boundary role-${legendInside.role}`), `Inside ${legendInside.name}`], [miniArea("outside-area"), "Outside"]] : []);
    sec("Parts", [
      ...Object.entries(ROLES).filter(([k]) => has(`.node.role-${k}, .group.role-${k}, .boundary.role-${k} .sym:not(.ghost), .dot.role-${k}`)).map(([k, label]) => [miniBox(`node role-${k}`, true), label]),
      ...(has(".sym.ghost, .group") ? [[miniBox("sym ghost"), "In another concept"]] : []),
    ]);
    sec("Outside systems", Object.entries(KINDS).filter(([k]) => has(`.kind-${k}`)).map(([k, label]) => [miniBox(`node ext kind-${k}`), label]));
    sec("Lines", [
      has(".edge:not(.integration):not(.port):not(.ghosted):not(.reexport)") && [miniLine(""), "Uses or calls"],
      has(".edge.port:not(.stated), .edge.ghosted") && [miniLine("port"), "Crosses the boundary"],
      has(".edge.integration") && [miniLine("integration"), "Integration point"],
      has(".edge.stated") && [miniLine("port stated"), "Stated by the concept map; no direct call resolved"],
      has(".edge.both") && [miniLine("both"), "Both directions"],
      has(".edge.reexport") && [miniLine("call ghosted reexport"), "Re-export"],
    ].filter(Boolean));
    sec("Changes", [
      has(".chg-added") && [miniBox("node chg-added", true), "Added"],
      has(".chg-removed") && [miniBox("node chg-removed", true), "Removed"],
      has(".chg-changed") && [miniBox("node chg-changed", true), "Changed"],
      has(".chg-provisional") && [miniBox("node chg-provisional", true), "Provisional"],
      has(".edge.chg-new") && [miniLine("chg-new"), "New line"],
      has(".edge.chg-removed") && [miniLine("chg-removed"), "Removed line"],
      has(".edge.chg-volume") && [miniLine("chg-volume"), "Volume changed"],
      has(".edge.chg-mechanism") && [miniLine("chg-mechanism"), "Mechanism changed"],
    ].filter(Boolean));
    sec("Markers", [
      has(".env.start") && [mini(52, 18, (s) => { const p = envPill(START, 1, 0.5, ""); p.classList.add("start"); s.append(p); }), "Starts here: owns a deployable entry point"],
      has(".env:not(.start)") && [miniEnv(), "Env vars read"],
      has(".badge") && [miniBadge(), "Linked tests (static links, not results)"],
    ].filter(Boolean));
  }
  lg.hidden = !sections.length;
  if (!sections.length) return;
  if (keyCollapsed()) {
    const pill = el("button", "key-pill", "Key");
    pill.type = "button";
    pill.title = "Show the key";
    pill.onclick = () => { setKeyCollapsed(false); legendFromDiagram(svg); refit = true; route(); };
    lg.append(pill);
    return;
  }
  const card = el("div", "key-card"), head = el("div", "key-head"), grid = el("div", "key-grid");
  const fold = el("button", "", "–");
  fold.type = "button";
  fold.title = "Hide the key";
  fold.setAttribute("aria-label", "Hide the key");
  fold.onclick = () => { setKeyCollapsed(true); legendFromDiagram(svg); refit = true; route(); };
  head.append(el("strong", "", "Key"), fold);
  for (const [title, rows] of sections) {
    grid.append(el("div", "key-title", title));
    for (const [sw, label] of rows) {
      const cell = el("div", "key-sw");
      cell.append(sw);
      grid.append(cell, el("div", "key-label", label));
    }
  }
  card.append(head, grid);
  lg.append(card);
}

function clearKey() {
  if (view.overlay) return legendFromDiagram(null);
  document.getElementById("legend").hidden = true;
}

// ---------- camera: zoom and pan by moving the SVG viewBox, so text stays vector-crisp ----------

let cam = { x: 0, y: 0, w: 100, h: 100 };
let content = { w: 100, h: 100 };
let rects = {};
let moved = false;
let anim = null;
let animToken = 0;

// A drill's zoom keeps stepping after the next view is drawn unless it is stopped.
function haltAnim() {
  animToken++;
  cancelAnimationFrame(anim);
}

function setCam(c) {
  cam = c;
  document.getElementById("diagram").setAttribute("viewBox", `${c.x} ${c.y} ${c.w} ${c.h}`);
}

// The space a fitted map gets: the stage less padding and the open key card.
function availSize() {
  const s = stageSize();
  return { w: s.w - 48 - (keyCollapsed() ? 0 : 266), h: s.h - 48 };
}

function stageSize() {
  const s = document.getElementById("diagram").getBoundingClientRect();
  return { w: s.width || 800, h: s.height || 600 };
}

// Fit the content into the stage, keeping clear of the key card.
// With minK, a map too big to fit stays readable and opens on the selection or its top-left corner instead.
function fitCam(minK = 0) {
  const s = stageSize(), pad = 48;
  // The key card sits bottom-left over the canvas: keep the map clear of it while it is open.
  const lg = document.getElementById("legend");
  const left = lg.hidden || !lg.querySelector(".key-card") ? 0 : lg.offsetWidth + 16, top = 0;
  let k = Math.min(1.4, (s.w - left - pad) / content.w, (s.h - top - pad) / content.h);
  if (k < minK) {
    k = minK;
    const w = s.w / k, h = s.h / k, r = rects[view.sel];
    if (r) return { x: r.x + r.w / 2 - w / 2, y: r.y + r.h / 2 - h / 2, w, h };
    const b = rects.boundary || { x: 0, y: 0 };
    return { x: -(left + pad / 2) / k, y: Math.max(0, b.y - pad / k) - top / k, w, h };
  }
  const w = s.w / k, h = s.h / k;
  return { x: content.w / 2 - w / 2 - left / 2 / k, y: content.h / 2 - h / 2 - top / 2 / k, w, h };
}

let minScale = 0;
function fit(animated, full) { const c = fitCam(full ? 0 : minScale); animated ? animate(c, 250) : setCam(c); }

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
  const s0 = stageSize();
  const most = Math.max(content.w, content.h * s0.w / s0.h) * 2.5; // whole map well inside the view
  const w = Math.min(Math.max(cam.w * f, 300), most);
  const k = w / cam.w;
  setCam({ x: cx - (cx - cam.x) * k, y: cy - (cy - cam.y) * k, w, h: cam.h * k });
}

function animate(to, ms, done) {
  const token = ++animToken;
  cancelAnimationFrame(anim);
  const from = { ...cam }, t0 = performance.now();
  const ease = (t) => 1 - Math.pow(1 - t, 3);
  const step = (now) => {
    if (token !== animToken) return;
    const t = Math.min(1, (now - t0) / ms), e = ease(t);
    setCam({ x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e, w: from.w + (to.w - from.w) * e, h: from.h + (to.h - from.h) * e });
    if (t < 1) anim = requestAnimationFrame(step);
    else if (done) done();
  };
  anim = requestAnimationFrame(step);
}

let treeScript = false;
function loadTreeAfterPaint() {
  // tree.js holds every symbol. A static script would parse before the first diagram,
  // and a requestAnimationFrame callback still runs before that paint, so wait one more turn.
  // Headless render has no tree.js; a 404 would flip the page to cbi-render-failed.
  if (window.cbiRender || treeScript || treeNodes) return;
  treeScript = true;
  requestAnimationFrame(() => {
    setTimeout(() => {
      const s = document.createElement("script");
      s.src = "data/tree.js";
      document.body.appendChild(s);
    }, 0);
  });
}

// Hidden wheel readout: #debug in the URL or press ? to toggle.
let debug = /(^|[#&])debug\b/.test(location.hash);
function showWheel(ev) {
  const box = document.getElementById("debug");
  box.hidden = false;
  box.textContent = `deltaX ${ev.deltaX.toFixed(1)}  deltaY ${ev.deltaY.toFixed(1)}  deltaMode ${ev.deltaMode}  ctrl ${ev.ctrlKey}  meta ${ev.metaKey}  shift ${ev.shiftKey}`;
}

function initCamera() {
  const svg = document.getElementById("diagram");
  // On the whole stage (legend and empty space included), so no horizontal swipe reaches the browser.
  const stage = document.getElementById("stage");
  stage.addEventListener("wheel", (ev) => {
    if (debug) showWheel(ev);
    if (stage.dataset.mode !== "diagram") return; // the sketch scrolls natively
    ev.preventDefault();
    const r = svg.getBoundingClientRect();
    // Figma convention: scroll pans both axes; pinch (arrives as ctrl+wheel) or Cmd/Ctrl+wheel zooms at the cursor.
    if (ev.ctrlKey || ev.metaKey) return zoomBy(Math.min(1.25, Math.max(0.8, Math.exp(ev.deltaY * 0.01))), ev.clientX - r.left, ev.clientY - r.top);
    const s = stageSize();
    const unit = ev.deltaMode === 1 ? 16 : ev.deltaMode === 2 ? s.h : 1; // some mice report lines or pages
    let dx = ev.deltaX, dy = ev.deltaY;
    if (ev.shiftKey && !dx) [dx, dy] = [dy, 0]; // Shift+wheel scrolls sideways on mice without a horizontal axis
    setCam({ ...cam, x: cam.x + dx * unit * cam.w / s.w, y: cam.y + dy * unit * cam.h / s.h });
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
  svg.addEventListener("dblclick", (ev) => { if (ev.target === svg || ev.target.closest(".boundary, .group")) fit(true, true); });
  document.getElementById("stage").addEventListener("click", () => {
    glow = false;
    for (const x of document.querySelectorAll("#diagram .glow")) x.classList.remove("glow");
  }, true);
  document.getElementById("details").onclick = () => {
    document.body.classList.toggle("no-drawer");
    requestAnimationFrame(() => fit(true));
  };
  document.getElementById("zin").onclick = () => zoomBy(1 / 1.25);
  document.getElementById("zout").onclick = () => zoomBy(1.25);
  document.getElementById("zfit").onclick = () => fit(true, true);
  addEventListener("resize", () => { if (!location.search.includes("zoom")) fit(false); });
}

// ---------- drawer ----------

function integrationPoints(c) {
  const inside = (id) => !c || id === c.id || ancestors(id).includes(c.id);
  return M.relationships.filter((r) => {
    const a = byId[r.from], b = byId[r.to];
    // The mockup assumed external ids started with "x."; the model uses ext instead.
    if (!a || !b || !(a.ext || b.ext) || !(r.at || r.via)) return false;
    if (c && c.ext) return r.from === c.id || r.to === c.id;
    return inside(a.ext ? r.to : r.from);
  });
}

function integrationList(d, points, open = true) {
  if (!points.length) return;
  const det = el("details");
  const title = `Integration points (${points.length})`;
  det.open = drawerOpen(title, open);
  const sum = el("summary");
  sum.append(el("h3", "", title));
  det.append(sum);
  d.append(det);
  const ul = el("ul", "ints");
  for (const r of points) {
    const li = el("li");
    const head = el("div", "rel");
    const a = byId[r.from], b = byId[r.to];
    const nav = (x) => link(x.name, () => (x.ext ? go(view.focus, x.id) : jump(x.id, null, { force: true })));
    head.append(nav(a), " → ", nav(b));
    const foot = el("div", "where");
    if (r.via) foot.append(el("span", "pill", r.via));
    if (r.at) {
      const [file, fn] = r.at.split(":");
      const where = `${file.split("/").pop()} · ${fn}`;
      const sym = Object.values(symById).find((x) => x.file === file && x.name === fn);
      foot.append(sym ? link(where, () => jump(sym.leaf.id, sym.id, { force: true })) : el("span", "path", where));
      foot.lastChild.classList.add("path");
      foot.title = r.at;
    }
    for (const m of relChangeClass([r]).split(" ")) if (m.startsWith("chg-")) {
      const name = m.slice(4);
      foot.append(el("span", "pill mark-" + name, MARK_LABEL[name] || name));
    }
    li.append(head, foot);
    ul.append(li);
  }
  det.append(ul);
}

function envList(d, c, open = true) {
  const env = c ? envOf(c) : M.concepts.flatMap(envOf);
  if (!env.length) return;
  const det = el("details");
  const title = `Environment (${env.length})`;
  det.open = drawerOpen(title, open);
  const sum = el("summary");
  sum.append(el("h3", "", title));
  det.append(sum);
  d.append(det);
  const ul = el("ul", "ints");
  for (const e of env.sort((a, b) => a.name.localeCompare(b.name))) {
    const li = el("li");
    const head = el("div", "envrow");
    head.append(el("span", "envname", envName(e.name)));
    if (e.default != null) head.append(el("span", "path", `default ${e.default || '""'}`));
    if (e.declared) head.append(el("span", "path", e.declared));
    const who = el("div", "rel");
    const ids = [...new Set(e.symbols)].filter(Boolean);
    const syms = ids.map((id) => symById[id]).filter(Boolean);
    if (syms.length) syms.forEach((x, i) => { if (i) who.append(", "); who.append(link(x.name, () => jump(x.leaf.id, x.id, { force: true }))); });
    else if (ids.length) {
      who.append([...new Set(ids.map((id) => id.split("#")[0].split("/").pop()))].join(", "));
      if (e.leaf && e.leaf.id !== view.focus && e.leaf.id !== view.sel) who.append(" in ", link(e.leaf.name, () => jump(e.leaf.id, null, { force: true })));
    } else who.append("read at module level in ", link(e.leaf.name, () => jump(e.leaf.id, null, { force: true })));
    li.append(head, who);
    ul.append(li);
  }
  det.append(ul);
}

// Layout draws the drawer once up front and again when the diagram is ready.
// The shell restores open sections between those two draws. A later draw of the
// same hash keeps them. A new hash starts from the defaults.
let drawerStamp = null;
let drawerKept = null;

function drawerSectionName(text) {
  return String(text || "").replace(/\s*\(\d+\)\s*$/, "").trim();
}

function readDrawerOpen(root) {
  const kept = {};
  if (!root || !root.querySelectorAll) return kept;
  for (const details of root.querySelectorAll("details")) {
    const summary = details.querySelector ? details.querySelector("summary") : null;
    const name = drawerSectionName(summary && summary.textContent);
    if (name) kept[name] = details.open === true;
  }
  return kept;
}

function drawerOpen(title, fallback) {
  if (!drawerKept) return fallback;
  const name = drawerSectionName(title);
  if (!Object.prototype.hasOwnProperty.call(drawerKept, name)) return fallback;
  return drawerKept[name];
}

function drawer() {
  hideUsagePop();
  const d = document.getElementById("drawer");
  drawerKept = drawerStamp === location.hash ? readDrawerOpen(d) : null;
  drawerStamp = location.hash;
  d.replaceChildren();
  d.append(copyButton());
  const s = view.sel && symById[view.sel];
  const here = view.focus && byId[view.focus];
  if (view.sel) {
    // A selection replaces the concept's own overview; this is the explicit way back to it.
    const b = link(`← ${here ? here.name : M.workspace} overview`, () => go(view.focus, null, { v: view.mode, w: view.screen }));
    b.classList.add("overview");
    d.append(b);
  }
  if (view.sel && externalGroups[view.sel]) return groupDrawer(d, externalGroups[view.sel]);
  if (view.sel && view.sel.startsWith("bundle:")) return bundleDrawer(d, view.sel);
  if (s && here && !here.children && s.leaf !== here) return linkDrawer(d, here, s);
  if (view.sel && view.sel.startsWith("rel:")) return relationDrawer(d, M.relationships[+view.sel.slice(4)]);
  if (s) return symbolDrawer(d, s);
  const g = view.sel && ghostById[view.sel];
  const c = byId[view.sel] || byId[view.focus];
  if (!c) {
    d.append(el("h2", "", M.workspace), el("p", "", M.summary));
    d.append(el("p", "hint", "Click a box to open it. Scroll to pan, pinch to zoom. Esc goes up. Backspace goes back."));
    integrationList(d, integrationPoints(null), false);
    envList(d, null, false);
    return;
  }
  d.append(el("h2", "", c.name), el("p", "", c.summary));
  if (!view.sel && c.id === view.focus) {
    const u = usage(c);
    usageList(d, "Used by", u.by, true);
    usageList(d, "Uses", u.to, false);
  }
  if (c.children) list(d, "Parts", c.children.map((k) => link(k.name, () => go(k.id))));
  integrationList(d, integrationPoints(c));
  if (!c.ext) envList(d, c);

  const rels = M.relationships.filter((r) => {
    if ((r.from !== c.id && r.to !== c.id) || r.label === TYPES || r.at) return false;
    const other = byId[r.from === c.id ? r.to : r.from];
    return other && !(other.ext && r.via);
  });
  if (rels.length) list(d, "Relationships", rels.map((r) => {
    const li = el("span", "rel");
    const other = byId[r.from === c.id ? r.to : r.from];
    const b = link(other.name, () => (other.ext ? go(view.focus, other.id) : jump(other.id, null, { force: true })));
    if (r.from === c.id) li.append(r.label + " ", b);
    else li.append(b, ` ${r.label} `, el("span", "self", c.name));
    return li;
  }));
  endpointList(d, "Endpoints", conceptEndpoints(c));
  if (c.ext) return;

  const files = [], tests = [];
  (function collect(n) {
    files.push(...(n.files || []));
    tests.push(...(n.tests || []));
    for (const k of n.children || []) collect(k);
  })(c);
  if (!c.children && c.symbols) {
    const counts = {};
    for (const x of c.symbols) counts[x.kind] = (counts[x.kind] || 0) + 1;
    const tested = c.symbols.filter((x) => x.tests && x.tests.length).length;
    const line = Object.entries(counts).map(([k, n]) => `${n} ${k}${n > 1 ? (k === "class" ? "es" : "s") : ""}`).join(", ");
    if (line) list(d, "Code", [el("span", "", line), el("span", "", `${tested} of ${c.symbols.length} linked to a test`)]);
  }
  const fileItem = (f) => {
    const row = el("span", "path", f);
    if (typeof openInEditor === "function") row.append(" ", link(typeof editorLabel === "function" ? editorLabel() : "Open in editor", () => openInEditor(f, 1)));
    return row;
  };
  fold(d, `Files (${files.length})`, files.map(fileItem), false);
  fold(d, `Tests (${tests.length})`, tests.map((t) => {
    const li = el("span", "path", t.file);
    li.append(el("span", "n", t.cases + (t.cases === 1 ? " case" : " cases")));
    if (typeof openInEditor === "function" && t.file) li.append(" ", link(typeof editorLabel === "function" ? editorLabel() : "Open in editor", () => openInEditor(t.file, 1)));
    return li;
  }), false);
}

function groupDrawer(d, g) {
  const title = (KINDS[g.kind] || g.kind || "Outside") + ` (${g.members.length})`;
  d.append(el("h2", "", title), el("p", "", "Same kind, one caller."));
  const open = (id) => go(view.focus, id);
  list(d, "Each", g.members.map((id) => link((byId[id] && byId[id].name) || id, () => open(id))));
}

// One drawn line stands for several relationships. List every one; evidence opens a stated line.
function bundleDrawer(d, sel) {
  const rels = sel.slice(7).split(",").map((n) => M.relationships[+n]).filter(Boolean);
  d.append(el("h2", "", "Relationships"), el("p", "", "These share one line."));
  const open = (c) => (c.ext ? go(view.focus, c.id) : jump(c.id, null, { force: true }));
  list(d, "Each", rels.map((r) => {
    const li = el("span", "rel");
    const a = byId[r.from], b = byId[r.to];
    li.append(link(a.name, () => open(a)), ` ${r.label} `, link(b.name, () => open(b)));
    if (r.backing === "stated") li.append(" ", link("evidence", () => go(view.focus, "rel:" + M.relationships.indexOf(r), { v: view.mode })));
    return li;
  }));
}

// A relationship the concept map states but no resolved call backs: say what the code does show.
function relationDrawer(d, r) {
  if (!r) return;
  const a = byId[r.from], b = byId[r.to];
  const head = el("h2");
  head.append(link(a.name, () => jump(a.id, null, { force: true })), ` ${r.label} `, link(b.name, () => jump(b.id, null, { force: true })));
  d.append(head, el("p", "", "Stated by the concept map; no direct call between them was resolved."));
  endpointList(d, "Endpoints", r.endpoints);
  const ev = r.evidence || [];
  if (!ev.length) { d.append(el("h3", "", "Evidence"), el("p", "", "Nothing in the scan links them yet.")); return; }
  const items = ev.map((x) => {
    const li = el("span", "rel");
    const where = x.line ? `${x.file.split("/").pop()}:${x.line}` : x.file.split("/").pop();
    const sym = x.symbol && symById[x.symbol];
    const at = sym ? link(where, () => jump(sym.leaf.id, sym.id, { force: true })) : el("span", "path", where);
    at.classList.add("path");
    if (x.kind === "injected" && x.field && x.type) li.append("via injected ", el("code", "", `${x.field}: ${x.type}`), " ", el("code", "", `this.${x.field}.${x.method}()`), " at ", at);
    else if (x.kind === "injected") li.append("injected call to ", el("code", "", x.method), " at ", at);
    else {
      const names = (x.names || []).filter(Boolean);
      li.append("type import");
      if (names.length) li.append(" ", el("code", "", names.join(", ")));
      li.append(" at ", at);
    }
    return li;
  });
  list(d, "Evidence", items);
}

// A ghost is selected: show every call between its concept and this one, both ways.
function linkDrawer(d, here, s) {
  const there = s.leaf;
  d.append(el("h2", "", s.name), el("p", "", `${s.kind} in ${there.name}`));
  const go2 = el("button", "action", `Go to ${there.name}`);
  go2.onclick = () => jump(there.id, s.id, { force: true });
  d.append(go2);
  if (typeof editorButton === "function" && s.file) {
    const open = editorButton(s.file, s.line);
    if (open) d.append(open);
  }
  const name = (id) => link(`${symById[id].name} (${symById[id].leaf.name})`, () => go(view.focus, id, { v: view.mode }));
  for (const [a, b] of [[there, here], [here, there]]) {
    const rows = (here.calls || []).filter(([x, y]) => symById[x] && symById[y] && symById[x].leaf === a && symById[y].leaf === b);
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
  if (typeof editorButton === "function" && s.file) {
    const open = editorButton(s.file, s.line);
    if (open) d.append(open);
  }
  const calls = s.leaf.calls || [], tests = s.tests || [];
  const out = calls.filter(([a]) => a === s.id), into = calls.filter(([, b]) => b === s.id);
  const pick = (rows, verb, end) => rows.filter((r) => r[2] === verb).map((r) => r[end]);
  callList(d, "Calls", pick(out, "calls", 1), s.leaf);
  callList(d, "Renders", pick(out, "renders", 1), s.leaf);
  callList(d, "Called by", pick(into, "calls", 0), s.leaf);
  callList(d, "Rendered by", pick(into, "renders", 0), s.leaf);
  endpointList(d, "Endpoints", s.httpOut);
  endpointList(d, "Called by clients", s.httpIn);
  list(d, `Tests (${tests.length})`, tests.length ? tests.slice(0, 12).map((t) => el("span", "", t)) : [el("span", "rel", "No test links found by static analysis.")]);
  if (tests.length > 12) d.append(el("p", "", `and ${tests.length - 12} more`));
  codeDiff(d, diffIds(s));
}

function leafList(c) { return c.children ? c.children.flatMap(leafList) : [c]; }

// Env vars read anywhere under a concept, merged by name. "*" is the whole environment passed on.
function envOf(c) {
  if (c.ext) return [];
  const out = {};
  const add = (l) => {
    for (const e of l.env || []) {
      const x = (out[e.name] ||= { name: e.name, default: e.default, declared: e.declared || null, symbols: [], leaf: l });
      if (x.default == null && e.default != null) x.default = e.default;
      if (!x.declared && e.declared) x.declared = e.declared;
      x.symbols.push(...e.symbols);
    }
    for (const k of l.children || []) add(k);
  };
  add(c);
  return Object.values(out);
}
const envName = (n) => (n === "*" ? "whole env" : n);

function endpointTarget(row) {
  const prefer = row.fn && symById[row.fn] ? row.fn : null;
  const id = prefer || (row.id && (symById[row.id] ? row.id : ownerShown(row.id)));
  return id && symById[id];
}

function conceptEndpoints(c) {
  const seen = new Set();
  const rows = [];
  for (const r of M.relationships || []) {
    if (r.from !== c.id && r.to !== c.id) continue;
    for (const ep of r.endpoints || []) {
      const key = `${ep.method} ${ep.path} ${ep.id || ""}`;
      if (seen.has(key)) continue;
      seen.add(key);
      rows.push(ep);
    }
  }
  return rows;
}

function endpointList(d, title, rows) {
  if (!rows || !rows.length) return;
  const seen = new Set();
  const kept = [];
  for (const row of rows) {
    const key = `${row.method} ${row.path} ${row.id || row.name || ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    kept.push(row);
  }
  list(d, title, kept.map((row) => {
    const li = el("span", "rel");
    li.append(el("code", "", row.method), " ", el("span", "path", row.path));
    const target = endpointTarget(row);
    const label = row.name || (target && target.name);
    if (target && label) li.append(" ", link(label, () => jump(target.leaf.id, target.id, { force: true })));
    else if (label) li.append(" ", el("code", "", label));
    return li;
  }));
}

function list(d, title, items) {
  d.append(el("h3", "", title));
  const ul = el("ul");
  for (const it of items) { const li = el("li"); li.append(it); ul.append(li); }
  d.append(ul);
}

function fold(d, title, items, open) {
  if (!items.length) return;
  const det = el("details");
  det.open = drawerOpen(title, open);
  const sum = el("summary", "", "");
  sum.append(el("h3", "", title));
  det.append(sum);
  const ul = el("ul");
  for (const it of items) { const li = el("li"); li.append(it); ul.append(li); }
  det.append(ul);
  d.append(det);
}

// The block is the one `cbi build` wrote from `cbi context`. A selection wins; otherwise
// the concept in view; otherwise the workspace, which is the top of the map.
function agentText() {
  const blocks = (AGENT && AGENT.blocks) || {};
  if (view.sel && blocks[view.sel]) return blocks[view.sel];
  if (view.focus && blocks[view.focus]) return blocks[view.focus];
  return blocks[AGENT.workspace] || "";
}

function showToast(message) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 1500);
}

function inField(node) {
  const el = !node ? null : node.nodeType === 1 ? node : node.parentElement;
  if (!el || !el.closest) return false;
  if (el.closest("input, textarea")) return true;
  const box = el.closest("[contenteditable]");
  return !!box && box.getAttribute("contenteditable") !== "false";
}

function textSelected() {
  const sel = window.getSelection();
  return !!sel && !sel.isCollapsed;
}

function wantsBrowserCopy(node) {
  return inField(node) || textSelected();
}

// The desktop Edit menu calls this. False means the page has a normal copy to do.
function cbiCopy() {
  if (wantsBrowserCopy(document.activeElement)) return false;
  copyAgent();
  return true;
}

function copyAgent() {
  const text = agentText();
  if (!text) { showToast("Nothing to copy"); return; }
  const done = () => showToast("Copied");
  const fallback = () => {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    showToast(ok ? "Copied" : "Copy failed");
  };
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, fallback);
  else fallback();
}

function copyButton() {
  const button = el("button", "copy-agent", "Copy for agent");
  button.type = "button";
  button.title = "Copy a description for an agent (Cmd/Ctrl+C)";
  button.onclick = (ev) => { ev.preventDefault(); ev.stopPropagation(); copyAgent(); };
  return button;
}

function link(text, fn) {
  const b = el("button", "link", text);
  b.type = "button";
  b.onclick = fn;
  return b;
}

// Test overlay (V11). Worst result wins: fail, then skipped, then pass.
function symbolState(s) {
  return { tested: !!(s.tests && s.tests.length), cov: s.cov == null ? null : s.cov, result: s.result || null };
}

function conceptState(c) {
  if (!c || c.ext) return null;
  const leaves = leafList(c);
  const syms = leaves.flatMap((l) => l.symbols || []);
  const tested = syms.some((s) => s.tests && s.tests.length) || leaves.some((l) => (l.tests || []).some((t) => t.cases));
  const covs = syms.map((s) => s.cov).filter((v) => v != null);
  const results = syms.map((s) => s.result).filter(Boolean);
  const result = results.includes("fail") ? "fail" : results.includes("skipped") ? "skipped" : results.includes("pass") ? "pass" : null;
  return { tested, cov: covs.length ? Math.round(covs.reduce((a, b) => a + b, 0) / covs.length) : null, result };
}

function overlayClass(id, m) {
  if (!view.overlay || (m.cls && (m.cls.includes("ghost") || m.cls.includes("ctx")))) return "";
  const state = m.sym ? symbolState(m.sym) : conceptState(byId[id]);
  if (!state) return "";
  if (view.overlay === "links") return state.tested ? "ov-yes" : "ov-no";
  if (view.overlay === "coverage") {
    if (state.cov == null) return "ov-none";
    if (state.cov >= 80) return "ov-yes";
    if (state.cov > 0) return "ov-part";
    return "ov-no";
  }
  if (view.overlay === "result") return state.result ? "ov-" + state.result : "ov-none";
  return "";
}

function paintOverlay() {
  const t = view.overlay || "";
  for (const b of document.querySelectorAll("#overlay button")) b.classList.toggle("on", (b.dataset.t || "") === t);
}

function initOverlay() {
  const bar = document.getElementById("overlay");
  if (!bar || bar.dataset.ready) return;
  bar.dataset.ready = "1";
  bar.onclick = (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    go(view.focus, view.sel, { v: view.mode, w: view.screen, t: b.dataset.t || "" });
  };
}

// Symbols and env vars that are in the tree but not already on a concept, so search still works
// before concepts exist and still finds methods the leaf diagram rolls up.
function addTreeHits() {
  if (!M || !treeNodes || treeAdded) return;
  treeAdded = true;
  const seen = new Set(Object.keys(symById));
  const envNames = new Set(entries.filter((e) => e.kind.startsWith("env")).map((e) => e.name));
  const owned = {};
  for (const c of Object.values(byId)) if (c.files) for (const f of c.files) owned[f] = c;
  const named = new Set(entries.map((e) => e.name));
  for (const n of treeNodes) {
    if (n.kind === "symbol" && !seen.has(n.id) && owned[n.path]) {
      const leaf = owned[n.path];
      entries.push({ name: n.name, text: n.name.toLowerCase(), kind: `${n.display_kind} · ${leaf.name}`, c: leaf });
    } else if ((n.kind === "env" || n.display_kind === "env var") && n.name !== "*" && !envNames.has(n.name)) {
      envNames.add(n.name);
      entries.push({ name: n.name, text: n.name.toLowerCase(), kind: "env var" });
    } else if (n.display_kind === "test case" || n.display_kind === "doc" || (n.display_kind === "folder" && !named.has(n.name))) {
      if (!n.name) continue;
      const leaf = owned[n.path];
      named.add(n.name);
      entries.push({ name: n.name, text: n.name.toLowerCase(), kind: leaf ? `${n.display_kind} · ${leaf.name}` : n.display_kind, c: leaf });
    }
  }
}

// ---------- search ----------

let entries = [];
function initSearch() {
  entries = [];
  treeAdded = false;
  for (const c of Object.values(byId)) entries.push({ name: c.name, text: (c.name + " " + (c.summary || "")).toLowerCase(), kind: c.ext ? "outside" : "concept", c });
  for (const s of Object.values(symById)) entries.push({ name: s.name, text: s.name.toLowerCase(), kind: `${s.kind} · ${s.leaf.name}`, s });
  for (const l of Object.values(byId).filter((c) => c.env)) for (const e of l.env) {
    if (e.name !== "*") {
      const sym = e.symbols && symById[e.symbols[0]];
      entries.push({ name: e.name, text: e.name.toLowerCase(), kind: `env var · ${l.name}`, c: l, envSym: sym && sym.id });
    }
  }
  addTreeHits();
  const q = document.getElementById("q"), hits = document.getElementById("hits");
  let shown = [], on = 0;
  const pick = (h) => {
    hits.hidden = true;
    q.value = "";
    q.blur();
    if (h.s) jump(h.s.leaf.id, h.s.id, { force: true });
    else if (h.envSym) jump(h.c.id, h.envSym, { force: true });
    else if (!h.c) return;
    else if (h.c.ext || (h.c.flat && !parentOf[h.c.id])) jump(null, h.c.id, { force: true });
    else if (h.c.flat) jump(parentOf[h.c.id], h.c.id, { force: true });
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
