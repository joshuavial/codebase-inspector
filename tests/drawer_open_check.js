const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function makeEl(tag) {
  const node = {
    tag: String(tag || "").toLowerCase(),
    className: "",
    _text: "",
    children: [],
    style: {},
    open: false,
    hidden: false,
    type: "",
    title: "",
    dataset: {},
    get textContent() {
      if (node.children.length) return node.children.map((child) => child.textContent || "").join("");
      return node._text;
    },
    set textContent(value) {
      node._text = value == null ? "" : String(value);
      node.children = [];
    },
    append(...kids) {
      for (const kid of kids) {
        if (kid == null || kid === false) continue;
        if (typeof kid === "string" || typeof kid === "number") {
          const text = makeEl("");
          text.textContent = String(kid);
          node.children.push(text);
        } else node.children.push(kid);
      }
    },
    replaceChildren(...kids) {
      node.children = [];
      node.append(...kids);
    },
    querySelector(sel) {
      return node.querySelectorAll(sel)[0] || null;
    },
    querySelectorAll(sel) {
      const out = [];
      const visit = (current) => {
        for (const child of current.children || []) {
          if (child.tag === sel) out.push(child);
          visit(child);
        }
      };
      visit(node);
      return out;
    },
    setAttribute() {},
    addEventListener() {},
    getContext() { return { measureText: (text) => ({ width: String(text).length * 7 }) }; },
  };
  node.classList = { add() {}, toggle() {}, remove() {}, contains() { return false; } };
  return node;
}

const drawer = makeEl("aside");
const sandbox = {
  console,
  setTimeout,
  clearTimeout,
  structuredClone,
  ELK: function () { this.layout = async () => ({}); },
  document: {
    createElement: makeEl,
    createElementNS: makeEl,
    createTextNode(text) {
      const node = makeEl("");
      node.textContent = text;
      return node;
    },
    getElementById(id) { return id === "drawer" ? drawer : null; },
    querySelectorAll() { return []; },
  },
  location: { href: "http://local/", hash: "", search: "" },
  history: { replaceState() {}, pushState() {}, back() {}, state: null },
  addEventListener() {},
};
sandbox.window = { addEventListener() {}, cbiLoad() {}, innerWidth: 800, innerHeight: 600 };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

const setup = `
M = { workspace: "fixture", summary: "", relationships: [], concepts: [] };
const concept = { id: "cli", name: "cli", summary: "the cli", files: ["src/cli.ts"], tests: [] };
byId[concept.id] = concept;
view.focus = concept.id;
view.sel = null;
location.hash = "#c=cli";

function sectionOpen(title) {
  const sections = [];
  for (const details of document.getElementById("drawer").querySelectorAll("details")) {
    const summary = details.querySelector("summary");
    const name = String(summary && summary.textContent || "").replace(/\\s*\\(\\d+\\)\\s*$/, "").trim();
    sections.push({ title: name, open: details.open === true, details });
  }
  const found = sections.find((section) => section.title === title);
  if (!found) throw new Error("missing " + title + ": " + JSON.stringify(sections.map((section) => section.title)));
  return found;
}

drawer();
var drawerCheck = { first: sectionOpen("Files").open };
sectionOpen("Files").details.open = true;
drawer();
drawerCheck.sameView = sectionOpen("Files").open;
const other = { id: "other", name: "other", summary: "", files: ["src/other.ts"], tests: [] };
byId[other.id] = other;
view.focus = other.id;
location.hash = "#c=other";
drawer();
drawerCheck.nextView = sectionOpen("Files").open;
`;

vm.runInContext(
  fs.readFileSync(path.join(__dirname, "..", "src/cbi/viewer/app.js"), "utf8") + setup,
  sandbox,
  { filename: "app.js" },
);

assert.strictEqual(sandbox.drawerCheck.first, false);
assert.strictEqual(sandbox.drawerCheck.sameView, true);
assert.strictEqual(sandbox.drawerCheck.nextView, false);
