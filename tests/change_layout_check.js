const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const root = path.resolve(__dirname, "..");
const sandbox = {
  ELK: function () {},
  document: { createElement() { return { getContext() { return { measureText: (s) => ({ width: String(s).length * 7 }) }; } }; } },
  window: { addEventListener() {}, cbiLoad() {} },
  location: { hash: "", search: "", href: "http://local/" },
  localStorage: { getItem() { return null; } },
  innerWidth: 1440,
  addEventListener() {},
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(root, "src/cbi/viewer/app.js"), "utf8"), sandbox);
vm.runInContext(`
  DIFF = {overview: {items: [{id: "app", state: "changed", change_scope: "descendants", children: [
    {id: "tasks", state: "added", change_scope: "direct"}
  ]}]}};
  byId.app = {id: "app"}; byId.tasks = {id: "tasks"};
  CONCEPT_MARK = new Map([["app", "changed"], ["tasks", "added"]]);
  PROVISIONAL = new Set(["tasks"]);
`, sandbox);
assert.strictEqual(sandbox.conceptTag("app"), "Changes inside", "parent rollup must differ from a direct edit");
assert.strictEqual(sandbox.conceptTag("tasks"), "Added", "uncertain ownership must not replace lifecycle state");
assert.match(sandbox.conceptClass("tasks"), /chg-added/);
assert.match(sandbox.conceptClass("tasks"), /ownership-uncertain/);
assert.match(sandbox.conceptClass("app"), /chg-inside/);
assert.strictEqual(sandbox.keyCollapsed(), true, "comparison legend starts collapsed at desktop width");
vm.runInContext("CONCEPT_MARK = new Map(); PROVISIONAL = new Set(); M = {relationships: []};", sandbox);
const filtered = sandbox.filterScopeKids([{id: "quiet", symbols: []}], null, "changed");
assert.strictEqual(filtered.kids.length, 0, "empty changed scope must not silently reveal unchanged code");
assert.strictEqual(filtered.changedIds.size, 0);
const html = fs.readFileSync(path.join(root, "src/cbi/viewer/index.html"), "utf8");
assert.match(html, /id="diagram" role="group"/);
assert.match(html, /id="changes" aria-label="Changes"/);
assert.ok(html.indexOf('id="layout-notice"') > html.indexOf("</main>"), "diagnostics must stay outside the canvas");
console.log("change layout checks passed");
vm.runInContext(`
  minScale = 0.7;
  requestedMinimum = null;
  fitCam = (minimum) => { requestedMinimum = minimum; return {}; };
  setCam = () => {};
  fit(false);
`, sandbox);
assert.strictEqual(sandbox.requestedMinimum, 0, 'comparison navigation fits the whole diagram instead of enforcing a cropping scale');
