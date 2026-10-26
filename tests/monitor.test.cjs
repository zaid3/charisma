const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { readFileSync } = require('node:fs');
const source = readFileSync('charisma/static/monitor.js', 'utf8');
function boot({ lang='en', images=[], inputs=[], overflow=false, fetchThrows=false }={}) {
  const listeners=new Map(), requests=[];
  const window={ fetch(url,options) { if(fetchThrows) throw new Error('unavailable'); requests.push({url,options,payload:JSON.parse(options.body)}); return Promise.resolve({ok:true}); },
    addEventListener(name,fn){listeners.set(name,fn)},removeEventListener(name){listeners.delete(name)} };
  const document={currentScript:{src:'https://monitor.example/monitor.js',dataset:{siteKey:'public-key-fixture',page:'checkout'}},readyState:'complete',documentElement:{lang,scrollWidth:overflow?1200:500,clientWidth:500},querySelectorAll(selector){return selector.startsWith('img')?images:inputs}};
  vm.runInNewContext(source,{window,document,URL,location:{origin:'https://website.example'}});
  return { window, requests, emit(name,event){listeners.get(name)?.(event)}, listeners };
}
test('runtime events exclude private messages, stacks, query strings and paths',()=>{
  const app=boot();
  app.emit('error',{error:{name:'TypeError',message:'private@email.example',stack:'PRIVATE STACK'},filename:'https://website.example/users/private/app.js?token=secret',lineno:10,colno:4});
  assert.deepEqual(app.requests[0].payload,{code:'script-error',error:'TypeError',file:'app.js',line:10,column:4,count:1,page:'checkout'});
  const sent=JSON.stringify(app.requests); for(const privateValue of ['private@email','PRIVATE STACK','users/private','token=secret']) assert.ok(!sent.includes(privateValue));
  assert.equal(app.requests[0].options.credentials,'omit');
});
test('cross-origin script paths and rejected values are never transmitted',()=>{
  const app=boot();app.emit('error',{filename:'https://other.example/private.js',error:{name:'Error'}});
  app.emit('unhandledrejection',{reason:{name:'Error',message:'private'}});
  assert.equal(app.requests[0].payload.file,'');assert.ok(!JSON.stringify(app.requests).includes('private'));
});
test('reports are deduplicated and capped at 30 per page load',()=>{
  const app=boot();for(let i=0;i<100;i++){app.emit('error',{lineno:i});app.emit('error',{lineno:i});}
  assert.equal(app.requests.length,30);
});
test('selected UX checks inspect rendered elements without collecting their content',()=>{
  const visible={getClientRects:()=>[{}]};
  const app=boot({lang:'',images:[visible],inputs:[{...visible,type:'text',labels:[],getAttribute:()=>null,title:''}],overflow:true});
  assert.deepEqual(app.requests.map(r=>r.payload.code),['missing-language','missing-alt','missing-label','horizontal-overflow']);
});
test('decorative images, hidden controls and labelled fields are not flagged',()=>{
  const app=boot({inputs:[{getClientRects:()=>[],type:'text'},{getClientRects:()=>[{}],type:'hidden'},{getClientRects:()=>[{}],type:'text',labels:[{}]}]});assert.equal(app.requests.length,0);
});
test('stopping removes listeners and prevents explicit scans',()=>{
  const app=boot();app.window.Charisma.stop();app.emit('error',{});app.window.Charisma.scan();assert.equal(app.requests.length,0);assert.equal(app.listeners.size,0);
});
test('monitor failures and unusual rejection objects do not break the website',()=>{
  const app=boot({fetchThrows:true});assert.doesNotThrow(()=>app.emit('error',{}));
  const reason={get name(){throw new Error('getter')}};assert.doesNotThrow(()=>app.emit('unhandledrejection',{reason}));
});
