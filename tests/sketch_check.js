const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function makeEl() {
  const node = {
    className: "",
    textContent: "",
    style: {},
    children: [],
    append(...kids) { node.children.push(...kids); },
    setAttribute() {},
    getContext() { return { measureText: (s) => ({ width: String(s).length * 7 }) }; },
  };
  node.classList = {
    add(...names) { node.className = `${node.className} ${names.join(" ")}`.trim(); },
  };
  return node;
}

const sandbox = {
  console,
  setTimeout,
  clearTimeout,
  structuredClone,
  ELK: function () { this.layout = async () => ({}); },
  document: {
    createElement: makeEl,
    createElementNS: makeEl,
    createTextNode(text) { return { textContent: text, children: [] }; },
    getElementById() { return null; },
    querySelectorAll() { return []; },
  },
  location: { href: "http://local/", hash: "", search: "" },
  history: { replaceState() {}, state: null },
  addEventListener() {},
};
sandbox.window = { addEventListener() {}, cbiLoad() {} };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync(path.join(__dirname, "..", "src/cbi/viewer/app.js"), "utf8"),
  sandbox,
  { filename: "app.js" },
);

const shown = sandbox.region(
  { id: "nav", layout: "row", when: " flag: arrears-view ", text: "Arrears" },
  new Set(),
  false,
);
assert.ok(shown.className.split(/\s+/).includes("cond"));
assert.ok(shown.className.split(/\s+/).includes("wf"));
const tag = shown.children.find((child) => child.className === "cond-tag");
assert.strictEqual(tag.textContent, "flag: arrears-view");

const plain = sandbox.region({ id: "title", layout: "row", when: "  " }, new Set(), false);
assert.ok(!plain.className.split(/\s+/).includes("cond"));
assert.ok(!plain.children.some((child) => child.className === "cond-tag"));
