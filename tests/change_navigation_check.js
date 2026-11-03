const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const app = {
  ELK: function () {},
  document: {createElement() {return {getContext() {return {measureText: s => ({width: String(s).length * 7})};}};}},
  window: {addEventListener() {}, cbiLoad() {}},
  location: {hash: '', search: '', href: 'http://local/'},
  URLSearchParams,
  addEventListener() {},
};
vm.createContext(app);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/cbi/viewer/app.js'), 'utf8'), app);
vm.runInContext(`
  DIFF = {overview:{items:[
    {id:'a', name:'Producer', state:'changed', children:[]},
    {id:'b', name:'Delivery', state:'added', children:[{id:'worker',name:'Worker',state:'changed',children:[]}]}
  ]}, changes:{groups:[],summaries:{concepts:{a:{narrative:'Producer changed.'},b:{narrative:'Delivery was introduced.'}}}}};
  const allNodes={a:{id:'a',name:'Producer'},b:{id:'b',name:'Delivery',children:[{id:'worker',symbols:[]}]},worker:{id:'worker',name:'Worker',symbols:[]}};
  Object.assign(byId,allNodes);
  parentOf.a=null;parentOf.b=null;parentOf.worker='b';
  ADDED=new Set(['b']);HEAD_ONLY=new Set();
  CONCEPT_MARK=new Map([['a','changed'],['worker','changed']]);PROVISIONAL=new Set();
  M={relationships:[]};
  writes=[];backCalls=0;
  writeHash=(hash,options={})=>{
    writes.push({hash,options});location.hash=hash ? '#'+hash : '';
    const state=new URLSearchParams(hash);
    shownSide=state.get('side')==='base'?'base':'head';
    if(shownSide==='base')delete byId.b;else byId.b=allNodes.b;
    view={focus:state.get('c'),sel:state.get('s'),scope:state.get('scope')||'',
      from:state.get('from'),backHash:state.get('bh'),tab:'concept'};
  };
  back=()=>{backCalls+=1;};
  writeHash('c=a&s=previous&side=base&scope=a');
  setDiffScope('b');
`, app);
let state = new URLSearchParams(app.location.hash.slice(1));
assert.strictEqual(state.get('side'), null, 'selecting a new concept switches Base to Head');
assert.strictEqual(state.get('c'), 'b', 'new concept receives focus even while absent on Base');
assert.strictEqual(state.get('s'), null, 'previous symbol selection is cleared');
assert.strictEqual(app.selectedChangeConcept().id, 'b', 'explanation follows requested concept');
assert.strictEqual(vm.runInContext('DIFF.changes.summaries.concepts[selectedChangeConcept().id].narrative', app), 'Delivery was introduced.');

vm.runInContext(`writeHash('c=a&scope=a');jump('b',null,{force:true});`, app);
state = new URLSearchParams(app.location.hash.slice(1));
assert.strictEqual(state.get('c'), 'b');
assert.strictEqual(state.get('scope'), null, 'cross-concept relationship jumps clear the prior concept scope');
assert.strictEqual(state.get('from'), 'a', 'lateral navigation retains its origin');
assert.strictEqual(state.get('bh'), 'c=a&scope=a', 'Back retains the exact prior scope');
assert.strictEqual(app.selectedChangeConcept().id, 'b');
assert.deepStrictEqual(Array.from(vm.runInContext(`filterScopeKids(byId.b.children,'b',diffViewScope()).kids.map(row=>row.id)`, app)), ['worker'], 'changed descendants at the destination remain visible');
vm.runInContext(`go('a');`, app);
assert.strictEqual(app.backCalls, 1, 'return to the origin still uses the existing Back restoration');

vm.runInContext(`writeHash('c=a&scope=a');go('worker');`, app);
state = new URLSearchParams(app.location.hash.slice(1));
assert.strictEqual(state.get('scope'), null, 'direct diagram navigation shares cross-scope handling');
assert.strictEqual(app.selectedChangeConcept().id, 'worker');

vm.runInContext(`writeHash('c=b&scope=b');jump('worker','run',{force:true});`, app);
state = new URLSearchParams(app.location.hash.slice(1));
assert.strictEqual(state.get('scope'), 'b', 'child evidence navigation stays within the chosen scope');
vm.runInContext(`go('b');`, app);
state = new URLSearchParams(app.location.hash.slice(1));
assert.strictEqual(state.get('scope'), 'b', 'ancestor navigation keeps the selected subtree');

vm.runInContext(`writeHash('c=worker&scope=worker');go('b');`, app);
state = new URLSearchParams(app.location.hash.slice(1));
assert.strictEqual(state.get('scope'), 'worker', 'moving up can retain a descendant scope');
assert.deepStrictEqual(Array.from(vm.runInContext(`filterScopeKids(byId.b.children,'b',diffViewScope()).kids.map(row=>row.id)`, app)), ['worker']);

vm.runInContext(`writeHash('c=a&scope=all');go('b');`, app);
assert.strictEqual(new URLSearchParams(app.location.hash.slice(1)).get('scope'), 'all', 'Full map stays explicit');
vm.runInContext(`writeHash('c=a&scope=a');go('b',null,{scope:'b'});`, app);
assert.strictEqual(new URLSearchParams(app.location.hash.slice(1)).get('scope'), 'b', 'an explicit scope choice remains authoritative');
vm.runInContext(`writeHash('c=a&scope=a');symById.foreign={leaf:{id:'worker'}};go('a','foreign');`, app);
assert.strictEqual(new URLSearchParams(app.location.hash.slice(1)).get('scope'), null, 'foreign symbol citations also clear an unrelated scope');
console.log('change navigation checks passed');
