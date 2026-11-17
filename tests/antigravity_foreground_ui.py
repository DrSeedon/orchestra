"""Bounded real headless renderer check: inline local assets and synthetic data only."""
import json,os,resource,socket
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/".orchestra/tasks/agy-acp-safe-20261117"
assert os.environ.get("ORCHESTRA_ACP_OFFLINE")=="1"
assert socket.if_nameindex()==[(1,"lo")]
assert len(Path("/proc/net/route").read_text().splitlines())==1
resource.setrlimit(resource.RLIMIT_CORE,(0,0));Path('/proc/self/oom_score_adj').write_text('1000')
mem=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))*1024
assert mem>=8*1024**3
cg=Path('/sys/fs/cgroup')/Path('/proc/self/cgroup').read_text().strip().split(':',2)[2].lstrip('/')
limits={name:(cg/name).read_text().strip() for name in ('memory.max','memory.current','pids.max','pids.current') if (cg/name).exists()}
if limits.get('memory.max','max')!='max':assert int(limits['memory.max'])-int(limits['memory.current'])>=4*1024**3
if limits.get('pids.max','max')!='max':assert int(limits['pids.max'])-int(limits['pids.current'])>1200
(OUT/'ui-resources.json').write_text(json.dumps({'mem_available':mem,'cgroup':limits,'headless_limit':1}))
logs=json.loads((OUT/"ordered-transcript.json").read_text())["logs"]
card={"id":"synthetic-card","owner_id":"synthetic-owner","binding":"synthetic-binding","kind":"question","title":"Synthetic choice <script>bad()</script>","state":"pending","details":{"command":"echo synthetic"},"options":[{"optionId":"yes","name":"Choice A"},{"optionId":"no","name":"Choice B"}]}
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path='/home/kesha/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome',args=['--disable-gpu'])
    try:
        page=browser.new_page(viewport={"width":1280,"height":900})
        errors=[];requests=[];answers=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def route(req):
            url=req.request.url;requests.append(url)
            if url=='http://127.0.0.1/fixture':return req.fulfill(content_type='text/html',body='<html><body><div id="chat"></div></body></html>')
            if url.startswith('http://127.0.0.1/api/native-requests/csrf'):return req.fulfill(content_type='application/json',body='{"token":"synthetic-csrf"}')
            if url.endswith('/respond'):
                answers.append(req.request.post_data_json);return req.fulfill(content_type='application/json',body='{"state":"responded"}')
            if url.startswith('http://127.0.0.1/api/native-requests'):return req.fulfill(content_type='application/json',body=json.dumps([card]))
            req.abort()
        page.route('**/*',route);page.goto('http://127.0.0.1/fixture')
        page.add_script_tag(content="window.$=s=>document.querySelector(s);window.T=(s,a={})=>s.replace(/\\{(\\w+)\\}/g,(_,k)=>a[k]??k);window.NOTIFY_USER_TOOL='mcp__orchestra__notify_user';window.taskNum=x=>String(x||'');window._escHtml=x=>String(x).replace(/&/g,'&amp;').replace(/</g,'&lt;');window.selectedAgent='synthetic';window.agentColors={};window.HIDE_THINKING=false;window.scrollAfterLoad=false;window.localMessages=new Set();window.currentScope='/synthetic';window._chatViewGeneration=0;window.api=async(url,opts={})=>{let r=await fetch(url,opts);if(!r.ok)throw Error(r.status);return r.json()};")
        for name in ('purify.min.js','marked.min.js','diff_match_patch.js'):
            page.add_script_tag(content=(ROOT/'app/static/css/vendor'/name).read_text())
        for name in ('utils.js','tool-renderers.js','live-activity.js','chat.js'):
            page.add_script_tag(content=(ROOT/'app/static/js'/name).read_text())
        # Real tool renderer functions, browser DOM/layout, stored metadata from backend.
        page.evaluate("""rows=>{for(const row of rows){if(row.type==='tool'){let div=document.createElement('div');document.querySelector('#chat').appendChild(div);_renderFullToolCall(row.content,row,div)}else if(row.type==='tool_result'){_renderFullToolResult(row.content,row.ts,row,null,document.createElement('div'),x=>document.querySelector('#chat').appendChild(x),false)}else if(row.type==='text'){let p=document.createElement('p');p.textContent=row.content;document.querySelector('#chat').appendChild(p)}}}""",logs)
        page.evaluate('card=>document.querySelector("#chat").appendChild(renderNativeRequestCard(JSON.stringify(card)))',card)
        page.wait_for_timeout(50)
        page.get_by_role('button',name='Choice A',exact=True).click()
        page.wait_for_function('document.querySelector("[data-native-request-id] span").textContent === "responded"')
        page.locator('[data-tool-raw-name]').first.click()
        text=page.locator('body').text_content()
        names=page.locator('[data-tool-raw-name]').evaluate_all('(els)=>els.map(x=>x.dataset.toolRawName)')
        page.screenshot(path=str(OUT/'ui-renderer.png'),full_page=True)
        (OUT/'ui-renderer-dom.json').write_text(json.dumps({'text':text,'canonical_names':names},ensure_ascii=False,indent=2))
        # Tool patches update the existing card to its latest terminal snapshot;
        # earlier immutable snapshots remain in the journal, not duplicate cards.
        assert 'echo synthetic' in text and 'late output' in text
        assert 'mcp__orchestra__task_get' in names
        assert len(answers)==1 and answers[0]['option_id']=='yes' and answers[0]['binding']=='synthetic-binding'
        assert not page.evaluate('typeof bad !== "undefined"')
        assert not errors,errors
        page.screenshot(path=str(OUT/'ui-renderer.png'),full_page=True)
        (OUT/'ui-check.json').write_text(json.dumps({'passed':True,'renderer':'actual chat/tool-renderers/live-activity JS in headless Chromium','requests':requests,'native_answers':answers,'page_errors':errors,'network_namespace':'lo only','note':'UI endpoint responses synthetic; actual native HTTP/RPC covered by Python integration tests'},indent=2))
        print('REAL_HEADLESS_UI_PASS',flush=True)
    finally:browser.close()
