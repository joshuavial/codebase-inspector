const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function element(tag) {
  return {
    tag, children: [], textContent: "", className: "",
    append(...children) { this.children.push(...children); },
    getContext() { return { measureText: (text) => ({ width: String(text).length * 7 }) }; },
  };
}
const sandbox = {
  ELK: function () {},
  document: { createElement: element },
  window: { addEventListener() {}, cbiLoad() {} },
  location: { hash: "", search: "", href: "http://local/" },
  addEventListener() {},
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, "../src/cbi/viewer/app.js"), "utf8"), sandbox);
const parent = element("div");
sandbox.parent = parent;
const render = (id = null) => {
  parent.children = [];
  vm.runInContext(`changeSummary(parent, ${JSON.stringify(id)})`, sandbox);
};
const text = (node) => [node.textContent, ...node.children.map(text)].join(" ");

render();
assert.strictEqual(parent.children.length, 0, "ordinary viewer has no summary placeholder");
vm.runInContext(`DIFF = {changes: {groups: [{id: "funding"}]}}`, sandbox);
render();
assert.match(text(parent), /Summary pending: run cbi tasks/);
render("funding");
assert.match(text(parent), /Summary pending: run cbi tasks/);
render("unchanged");
assert.strictEqual(parent.children.length, 0, "unchanged concepts have no pending task");

const narrative = "<img src=x onerror=alert(1)> Funding callers now use the new entry point.";
sandbox.summaryFixture = { overall: { state: "answered", narrative, citations: ["funding.py#allocate"] },
  concepts: { funding: { state: "answered", narrative: "Funding changed.", citations: ["funding.py"] } } };
vm.runInContext("DIFF.changes.summaries = summaryFixture", sandbox);
render();
assert.match(text(parent), /Agent summary/);
assert.ok(text(parent).includes(narrative), "narrative remains plain text");
assert.match(text(parent), /Sources: funding.py#allocate/);
assert.strictEqual(parent.children[0].children[1].textContent, narrative);
assert.strictEqual(parent.children[0].children[1].children.length, 0, "summary creates no markup from answer text");
render("funding");
assert.match(text(parent), /Funding changed/);
assert.ok(!text(parent).includes(narrative), "concept uses its own summary");
vm.runInContext("HISTORY = {}; historyCompare = false", sandbox);
render();
assert.strictEqual(parent.children.length, 0, "history browsing hides comparison summaries");
console.log("change summary checks passed");
