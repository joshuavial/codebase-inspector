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
let notice = {hidden: true, textContent: ""};
let stage = {getBoundingClientRect() {return {width: 800, height: 600};}};
sandbox.document.getElementById = id => id === 'legend' ? {hidden:true} : id === 'diagram-zoom-note' ? notice : stage;
vm.runInContext(`
  view = {focus:'tasks', tab:'concept'};
  parentOf.tasks='app'; parentOf.other='app';
  symById.changedA={leaf:{id:'tasks'}};symById.changedB={leaf:{id:'tasks'}};symById.foreign={leaf:{id:'other'}};
  SYMBOL_MARK=new Map([['changedA','changed'],['changedB','changed'],['foreign','changed']]);
  rects={changedA:{x:950,y:500,w:100,h:40},changedB:{x:1200,y:500,w:100,h:40},foreign:{x:3500,y:1200,w:100,h:40}};
  content={w:4000,h:2000};
  setCam = camera => { actualCamera = camera; };
  fit(false);
`,sandbox);
assert.strictEqual(sandbox.actualCamera.w,800,'large comparisons start with readable text at scale 1');
assert.strictEqual(sandbox.actualCamera.x + sandbox.actualCamera.w/2,1125,'centre the selected concept changed nodes, excluding foreign changes');
assert.strictEqual(notice.hidden,false);
assert.match(notice.textContent,/Readable zoom.*Use Fit/);
sandbox.fit(false,true);
assert.ok(sandbox.actualCamera.w > 4000,'one-click full Fit includes the full graph');
assert.strictEqual(notice.hidden,true);
stage={getBoundingClientRect(){return {width:390,height:480};}};
sandbox.fit(false);
assert.strictEqual(sandbox.actualCamera.w,390,'phone view keeps readable minimum');
assert.strictEqual(sandbox.actualCamera.x+sandbox.actualCamera.w/2,1125);
vm.runInContext("content={w:200,h:150};rects={};",sandbox);
sandbox.fit(false);
assert.ok(sandbox.actualCamera.w<390,'small graph still fits');
assert.strictEqual(notice.hidden,true);
console.log('readable comparison camera checks passed');
