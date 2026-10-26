const {test}=require('node:test');
const assert=require('node:assert/strict');
const {paginate,selectChats,stateOf}=require('../src/tg_mcp/static/table-state.js');
const rows=Array.from({length:36},(_,i)=>({account:i%2?'a':'b',chat:String(i+1),title:`Чат ${i+1}`,accountName:i%2?'Основной':'Второй',kind:i%3?'group':'private',enabled:true,accountEnabled:true,rag_enabled:true,s3_enabled:false,inherited:i%2===0,eligible:100,indexed:100,backfill_complete:true}));
test('page boundaries and invalid sizes never hide the last or first row',()=>{
  assert.deepEqual(paginate(rows,4,10).items.map(c=>c.chat),['31','32','33','34','35','36']);
  assert.equal(paginate(rows,99,10).page,4);
  assert.equal(paginate([],8,25).page,1);assert.equal(paginate([],8,25).start,0);
  assert.equal(paginate(rows,0,0).items[0].chat,'1');
});
test('filtering happens before pagination and out-of-range pages clamp',()=>{
  const selected=selectChats(rows,{query:'Чат 3',account:'a',sort:'title'});
  assert.deepEqual(selected.map(c=>c.title),['Чат 30','Чат 32','Чат 34','Чат 36']);
  assert.equal(paginate(selected,4,10).page,1);
  assert.equal(selectChats(rows,{query:'NOT FOUND'}).length,0);
});
test('rules, source types and S3 filters compose without mutating source order',()=>{
  const original=rows.map(c=>c.chat);
  assert(selectChats(rows,{rule:'fixed'}).every(c=>c.kind==='private'));
  assert(selectChats(rows,{kind:'group',rule:'own',s3:'off'}).every(c=>c.kind==='group'&&!c.inherited&&!c.s3_enabled));
  assert.deepEqual(rows.map(c=>c.chat),original);
});
test('failed or disabled source cannot appear ready; unknown coverage stays pending',()=>{
  const base=rows[1];
  assert.equal(stateOf({...base,indexed:undefined}),'pending');
  assert.equal(stateOf({...base,media_errors:1}),'error');
  assert.equal(stateOf({...base,s3_enabled:true,mediaConfigured:false}),'pending');
  assert.equal(stateOf({...base,accountEnabled:false}),'account_off');
  assert.equal(stateOf({...base,enabled:false}),'paused');
  assert.equal(stateOf({...base,ragRunning:false}),'paused');
  assert.equal(stateOf({...base,rag_enabled:false}),'off');
});
test('ties stay deterministic across polling and numeric title sort reverses',()=>{
  assert.deepEqual(selectChats([...rows].reverse(),{sort:'title'}).map(c=>c.chat),rows.map(c=>c.chat));
  assert.equal(selectChats(rows,{sort:'title',reverse:true})[0].chat,'36');
});
