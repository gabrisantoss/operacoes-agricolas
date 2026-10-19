const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
process.env.TZ = 'America/Sao_Paulo';
const source = fs.readFileSync(path.join(__dirname, '../web_app/static/app.js'), 'utf8').split('\ninit().catch')[0];
function setup(blocked = false) {
  const nodes = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, { value: '', textContent: '', innerHTML: '', tagName: 'INPUT', type: 'text' });
    return nodes.get(id);
  };
  const store = new Map();
  const storage = { getItem: key => store.get(key) ?? null, setItem: (key,value) => store.set(key,value) };
  const window = { location: { hostname:'localhost', protocol:'http:' }, open: url => window.opened = url };
  for (const kind of ['localStorage','sessionStorage']) Object.defineProperty(window, kind, { get() { if (blocked) throw new Error('blocked'); return storage; } });
  class FixedDate extends Date { constructor(...args) { super(...(args.length ? args : ['2026-05-01T01:30:00Z'])); } }
  const context = vm.createContext({window,document:{querySelector:node,querySelectorAll:()=>[]},Date:FixedDate,URLSearchParams,Map,Set,AbortController,setTimeout,clearTimeout,console});
  vm.runInContext(source+'\nglobalThis.appTest = {state,localDate,today,daysAgo,initialActiveTab,storageSet,saveHistoryFilters,restoreHistoryFilters,loadReferences,updateAnnualReportHint,downloadReport};',context);
  for (const id of ['historySearch','historyField','historyOrigin','historyDestination','historyVariety','historyStart','historyEnd','historyDateReference']) node('#'+id);
  for (const [id,values] of [['historyField',['todos','nota']],['historyDateReference',['data_colheita','data_plantio']]]) Object.assign(node('#'+id),{tagName:'SELECT',options:values.map(value=>({value}))});
  node('#historyStart').type=node('#historyEnd').type='date';
  return {a:context.appTest,context,node,store,window};
}
test('civil dates use local day at UTC midnight and across month boundary',()=>{
  const {a}=setup();
  assert.equal(a.today(),'2026-04-30');
  assert.equal(a.daysAgo(1),'2026-04-29');
  assert.equal(a.localDate(new Date('2026-05-01T01:30:00Z')),'2026-04-30');
});
test('blocked local and session storage never prevent application preferences',()=>{
  const {a}=setup(true);
  assert.equal(a.initialActiveTab(),'lancamento');
  assert.doesNotThrow(()=>{a.storageSet('localStorage','x','v');a.saveHistoryFilters();a.restoreHistoryFilters();});
});
test('session restores combined filters, general search, dates and date reference safely',()=>{
  const {a,node,store}=setup();
  const values={historySearch:'DEMO',historyField:'nota',historyOrigin:'100-001',historyDestination:'200-001',historyVariety:'V-A',historyStart:'2026-04-01',historyEnd:'2026-05-31',historyDateReference:'data_plantio'};
  for (const [id,value] of Object.entries(values)) node('#'+id).value=value;
  a.state.currentHistoryUsePeriod=true;a.saveHistoryFilters();
  for(const id of Object.keys(values))node('#'+id).value='';
  a.state.currentHistoryUsePeriod=false;a.restoreHistoryFilters();
  for(const [id,value] of Object.entries(values))assert.equal(node('#'+id).value,value);
  assert.equal(a.state.currentHistoryUsePeriod,true);
  store.set('notas.historyFilters.v1','invalid json');assert.doesNotThrow(()=>a.restoreHistoryFilters());
  node('#historyField').value='todos';store.set('notas.historyFilters.v1',JSON.stringify({historyField:'invalid'}));a.restoreHistoryFilters();assert.equal(node('#historyField').value,'todos');
});
test('out of order autocomplete responses cannot overwrite newer results',async()=>{
  const {a,node,context}=setup();const pending=[];
  context.api=()=>new Promise(resolve=>pending.push(resolve));
  const old=a.loadReferences('fazendas','old'),fresh=a.loadReferences('fazendas','new');
  pending[1]({items:[{label:'NEW DEMO'}]});await fresh;
  pending[0]({items:[{label:'OLD DEMO'}]});await old;
  assert.match(node('#fazendasList').innerHTML,/NEW DEMO/);assert.doesNotMatch(node('#fazendasList').innerHTML,/OLD DEMO/);
});
test('cache hit invalidates pending autocomplete, and changed source farm rejects stale fields',async()=>{
  const {a,node,context}=setup();const pending=[];context.api=()=>new Promise(resolve=>pending.push(resolve));
  const first=a.loadReferences('fazendas','a');pending.shift()({items:[{label:'A DEMO'}]});await first;
  const old=a.loadReferences('fazendas','b');await a.loadReferences('fazendas','a');pending.shift()({items:[{label:'B DEMO'}]});await old;
  assert.match(node('#fazendasList').innerHTML,/A DEMO/);
  node('#fazMuda').value='100-A';const field=a.loadReferences('talhoes','T1');node('#fazMuda').value='100-B';pending.shift()({items:[{label:'STALE FIELD'}]});await field;
  assert.equal(node('#talhoesList').innerHTML,'');
});
test('annual period is explicit and download covers the whole selected year',()=>{
  const {a,node,window}=setup();node('#reportStart').value='2026-04-01';node('#reportEnd').value='2026-05-31';node('#reportDateReference').value='data_plantio';
  a.updateAnnualReportHint();assert.match(node('#annualReportPeriod').textContent,/01\/01\/2026 a 31\/12\/2026/);assert.match(node('#annualReportPeriod').textContent,/Data de plantio/);
  a.downloadReport('pdf','fechamento');let url=new URL(window.opened,'http://localhost');assert.equal(url.searchParams.get('start'),'2026-01-01');assert.equal(url.searchParams.get('end'),'2026-12-31');assert.equal(url.searchParams.get('date_reference'),'data_plantio');
  a.downloadReport('pdf','mudas');url=new URL(window.opened,'http://localhost');assert.equal(url.searchParams.get('start'),'2026-04-01');assert.equal(url.searchParams.get('end'),'2026-05-31');
});
