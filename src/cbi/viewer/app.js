// Bare viewer: breadcrumb, children list and detail pane. Model text is only ever
// set through textContent, never parsed as HTML.
"use strict";

const model = { nodes: new Map(), children: new Map(), roots: [] };

function cbiLoad(name, value) {
  if (name !== "tree") return;
  for (const node of value.nodes) model.nodes.set(node.id, node);
  for (const node of value.nodes) {
    if (node.parent_id && model.nodes.has(node.parent_id)) {
      if (!model.children.has(node.parent_id)) model.children.set(node.parent_id, []);
      model.children.get(node.parent_id).push(node);
    } else {
      model.roots.push(node);
    }
  }
  for (const list of model.children.values()) list.sort(byPosition);
  window.addEventListener("hashchange", render);
  render();
}

function byPosition(a, b) {
  const ca = model.children.has(a.id) ? 0 : 1, cb = model.children.has(b.id) ? 0 : 1;
  if (a.start_line && b.start_line) return a.start_line - b.start_line;
  return ca - cb || a.name.localeCompare(b.name);
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function link(node, text) {
  const a = el("a", text);
  a.href = "#" + encodeURIComponent(node.id);
  return a;
}

function render() {
  const wanted = decodeURIComponent(location.hash.slice(1));
  const selected = model.nodes.get(wanted) || model.roots[0];
  if (!selected) return;
  // A node with children is opened; a leaf is shown inside its parent.
  const focus = model.children.has(selected.id) ? selected : model.nodes.get(selected.parent_id) || selected;
  renderCrumbs(focus);
  renderChildren(focus, selected);
  renderDetail(selected);
}

function renderCrumbs(focus) {
  const crumbs = document.getElementById("crumbs");
  crumbs.replaceChildren();
  const chain = [];
  for (let n = focus; n; n = model.nodes.get(n.parent_id)) chain.unshift(n);
  chain.forEach((n, i) => {
    if (i) crumbs.append(el("span", " / ", "sep"));
    crumbs.append(link(n, n.name || n.id));
  });
}

function renderChildren(focus, selected) {
  const list = document.getElementById("children");
  list.replaceChildren();
  const kids = model.children.get(focus.id) || model.roots;
  for (const child of kids) {
    const item = el("li", null, child.id === selected.id ? "selected" : "");
    item.append(el("span", child.display_kind, "kind"), link(child, child.name));
    if (child.loc) item.append(el("span", child.loc === 1 ? "1 line" : child.loc + " lines", "loc"));
    list.append(item);
  }
  if (!kids.length) list.append(el("li", "No children.", "empty"));
}

function renderDetail(node) {
  const detail = document.getElementById("detail");
  detail.replaceChildren();
  detail.append(el("h1", node.name || node.id), el("p", node.display_kind, "kind"));
  if (node.path) {
    const lines = node.start_line ? `:${node.start_line}-${node.end_line}` : "";
    detail.append(el("p", node.path + lines, "path"));
  }
  // Symbols get no summaries in this increment, so only files and above say one is missing.
  if (node.summary || (node.kind !== "symbol" && node.kind !== "test")) {
    detail.append(el("h2", "Summary"), el("p", node.summary || "No summary yet.", node.summary ? "" : "empty"));
  }
  if (node.signature) detail.append(el("h2", "Signature"), el("pre", node.signature));
  if (node.doc) detail.append(el("h2", "Doc"), el("pre", node.doc));
  detail.append(el("p", node.id, "id"));
}
