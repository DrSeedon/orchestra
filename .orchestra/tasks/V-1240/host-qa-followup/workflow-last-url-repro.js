// Real API/visibility/watcher functions, synthetic inputs, no network or browser.
const fs = require('fs');
const assert = require('assert/strict');
const app = fs.readFileSync('app/static/js/app.js','utf8');
const chat = fs.readFileSync('app/static/js/chat.js','utf8');
const code = app.slice(app.indexOf('const _POLL_MAX_BACKOFF_MS'), app.indexOf('function scheduleRefresh()'))
    + '\n' + app.slice(app.indexOf('const _API_TIMEOUT_MS'), app.indexOf('// === Rate Limit Banner'))
    + '\n' + chat.slice(chat.indexOf('async function _refreshWorkflowCard('), chat.indexOf('function _renderFullToolCall('));
const document = {hidden:true, addEventListener(){}};
const navigator = {onLine:true};
const window = {addEventListener(){}};
const Connection = {observe(){}, ok(){}, restartFromBody(){return false;}, fail(){}};
const T = x => x;
const card = {isConnected:true, dataset:{}, addEventListener(){}};
let rendered=null;
function _renderWorkflowStatus(_card,data) { rendered=data; }
let resolveRendered;
const renderedDone = new Promise(resolve => resolveRendered=resolve);
const detail={available:true,finished:true,run_id:'V-776-fixture'};
let fetch = async url => {
    window.__workflowApiPath=String(url);
    return new Response(JSON.stringify(detail),{status:200,headers:{'Content-Type':'application/json'}});
};
eval(code+`
(async () => {
    _watchWorkflowCard(card,'V-776-fixture');
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(rendered?.run_id,'V-776-fixture');
    assert.equal(_pollCanRun(),false);
    await api('/api/background-fixture');
    const oldPredicate = window.__workflowApiPath.endsWith('/api/bg/workflows/V-776-fixture');
    assert.equal(oldPredicate,false);
    assert.equal(rendered.run_id,'V-776-fixture');
    console.log(JSON.stringify({hidden:document.hidden,workflowRendered:true,oldWaitPredicate:oldPredicate,lastUrl:window.__workflowApiPath,networkCalls:0}));
})().catch(error=>{console.error(error);process.exitCode=1});`);
