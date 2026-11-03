const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
function element(tag) {
  return { tag, children: [], textContent: '', dataset: {}, attributes: {},
    setAttribute(k,v) { this.attributes[k] = v; },
    append(...nodes) { this.children.push(...nodes); },
    replaceChildren(...nodes) { this.children = nodes; },
    querySelector() { return null; },
    getContext() { return {measureText: s => ({width: String(s).length * 7})}; },
  };
}
const panel = element('aside');
const app = {ELK: function(){}, document: {createElement: element, getElementById: () => panel},
  window: {addEventListener(){}, cbiLoad(){}}, location:{hash:'',search:'',href:'http://local/'}, addEventListener(){}};
vm.createContext(app);
vm.runInContext(fs.readFileSync('src/cbi/viewer/app.js','utf8'), app);
vm.runInContext(`
  DIFF = {base:'aaa', head:'bbb', changes:{groups:[]}, overview:{items:[{
    id:'app', name:'Application', state:'changed', change_scope:'descendants', measures:{files:{total:1}}, own_modules:[],
    children:[{id:'tasks',name:'Task runner',state:'changed',change_scope:'direct',state_label:'Changed here',
      measures:{files:{total:1}}, own_modules:[{name:'src', measures:{files:{total:1}}, files:[{
        id:'repo:src/tasks.py',name:'tasks.py',path:'src/tasks.py',state:'changed',symbols:[{
          id:'repo:src/tasks.py#run',name:'run',state:'changed',verb:'Body changed',untested:true}]}]}],children:[]}]
  }]}};
  view = {focus:'tasks'};
  byId.app={id:'app'};byId.tasks={id:'tasks'};parentOf.tasks='app';parentOf.app=null;
  changesPanel();
`, app);
const text = n => typeof n === 'string' ? n : [n.textContent,...n.children.map(text)].join(' ');
const all = n => [n,...n.children.filter(c => typeof c !== 'string').flatMap(all)];
assert.match(text(panel), /Application.*Changes inside.*Task runner.*Changed here/s);
assert.match(text(panel), /Body changed/);
assert.match(text(panel), /No static test link/);
assert.ok(!text(panel).includes('symbol-changed'));
const evidence = all(panel).find(n => n.className === 'change-evidence');
const details = all(evidence).filter(n => n.tag === 'details');
assert.ok(details.length >= 3, 'evidence, modules and files each disclose');
assert.ok(details.every(n => !n.open), 'implementation evidence starts closed');
assert.strictEqual(all(panel).filter(n => n.attributes?.['aria-current'] === 'true').length, 1);
vm.runInContext(`view.sel='repo:src/tasks.py#run';symById[view.sel]={leaf:{id:'tasks'}}`,app);
assert.strictEqual(app.selectedChangeConcept().id,'tasks', 'symbol inspection retains the concept');
assert.strictEqual(app.diffConceptItems().length,2);
assert.ok(text(panel).indexOf('Review signals') < text(panel).indexOf('Changed concepts'), 'large index cannot bury the selected explanation');
assert.strictEqual(typeof app.diffAreaTabs,'undefined');
console.log('changes index checks passed');
vm.runInContext(`
  DIFF.changes.summaries={overall:{state:'answered',narrative:'The task interface changed. Delivery was introduced.',citations:['src/tasks.py']},
    concepts:{tasks:{state:'answered',narrative:'Task execution accepts an explicit limit. Effects on users and safety are unknown.',citations:['src/tasks.py']}}};
  DIFF.overview.items[0].children[0].relationships=[
    {from:'tasks',from_name:'Task runner',to:'delivery',to_name:'Delivery',label:'sends',state:'added',mechanism:'HTTP',at:'src/tasks.py#run'},
    {from:'entry',from_name:'Entry point',to:'tasks',to_name:'Task runner',label:'calls',state:'unchanged'}];
  byId.delivery={id:'delivery'};byId.entry={id:'entry'};
  changesPanel();
`,app);
assert.match(text(panel), /Task execution accepts an explicit limit/);
assert.match(text(panel), /Observed relationship changes.*Added:.*Task runner.*sends.*Delivery/s);
assert.match(text(panel), /Possible downstream context \(inferred\)/);
assert.match(text(panel), /Risk is unknown from structural evidence/);
assert.match(text(panel), /Inspect first: Task runner → sends → Delivery \(added\)/);
assert.ok(text(panel).indexOf('Task execution accepts') < text(panel).indexOf('Evidence'), 'narrative precedes evidence');
console.log('review signals checks passed');
const filePanel = element('aside');
app.filePanel=filePanel;
vm.runInContext(`fileEvidenceDrawer(filePanel, changeFile('repo:src/tasks.py'))`,app);
assert.match(text(filePanel), /tasks.py.*src\/tasks.py.*Copy git show command/s);
assert.match(text(filePanel), /run — Body changed/);
app.copied='';app.copyText = value => { app.copied=value; };
app.copyChangeSource('src/tasks.py','removed');
assert.strictEqual(app.copied,'git show aaa:src/tasks.py','removed file source comes from base');
console.log('file evidence checks passed');

vm.runInContext("shownSide='base'",app);
app.copyChangeSource('src/tasks.py','added');
assert.strictEqual(app.copied,'git show bbb:src/tasks.py','added file source comes from head even during base inspection');

const sourceLink = app.changeSourceLink('src/tasks.py:run', {id:'tasks'});
app.jumped=null; app.jump=(focus,sel) => {app.jumped={focus,sel};};
vm.runInContext("shownSide='head'",app);
sourceLink.onclick();
assert.strictEqual(app.jumped.sel,'repo:src/tasks.py', 'relationship evidence opens the actual file drawer');
