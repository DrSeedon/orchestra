"""Bounded real headless renderer check: inline local assets and synthetic data only."""
import json,os,resource,socket
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/".orchestra/tasks/agy-acp-safe-20261117"
OUT=EVIDENCE/"r2"
OUT.mkdir(parents=True,exist_ok=True)
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
logs=json.loads((EVIDENCE/"ordered-transcript.json").read_text())["logs"]
card={"id":"synthetic-card","owner_id":"synthetic-owner","binding":"synthetic-binding","kind":"question","title":"Synthetic choice <script>bad()</script>","state":"pending","details":{"command":"echo synthetic"},"options":[{"optionId":"yes","name":"Choice A"},{"optionId":"no","name":"Choice B"}]}
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path='/home/kesha/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome',args=['--disable-gpu'])
    try:
        page=browser.new_page(viewport={"width":1280,"height":900})
        errors=[];requests=[];answers=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def route(req):
            url=req.request.url;requests.append(url)
            if url=='http://127.0.0.1/fixture':return req.fulfill(content_type='text/html',body='<html><body class="h-screen overflow-hidden flex flex-col dark"><div id="chat" class="flex-1 overflow-y-auto p-4 space-y-3"></div></body></html>')
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
        # The focused fixture does not boot app.js (which starts the full dashboard).
        # Load its real pure stamping helper, without replacing production behavior.
        app_source=(ROOT/'app/static/js/app.js').read_text()
        stamp='function _stampChatLogNode'+app_source.split('function _stampChatLogNode',1)[1].split('\n}\n',1)[0]+'\n}'
        page.add_script_tag(content=stamp)
        # Same stylesheet order and body layout as dashboard.html, with its dark tokens.
        for name in ('design-system.css','style.css','vendor/tailwind.css'):
            page.add_style_tag(content=(ROOT/'app/static/css'/name).read_text())
        page.add_style_tag(content='#chat { width:100%; max-width:1080px; margin:0 auto; }')
        renderer_checks=page.evaluate("""() => {
            const require=(value,message)=>{if(!value)throw Error(message)};
            const chat=document.querySelector('#chat');
            // Real entry routing: late durable A cannot finalize current B.
            addChatEntry('stream','B live',null,null,{item_id:'acp:ui:B'});
            addChatEntry('text','A final',null,null,{event_id:'acp:ui:A'});
            let a=chat.querySelector('[data-segment-id="acp:ui:A"]');
            let b=chat.querySelector('[data-segment-id="acp:ui:B"]');
            require(a && b && b.textContent.trim()==='B live' && b.classList.contains('streaming'),'late A destroyed B');
            require(a.compareDocumentPosition(b)&Node.DOCUMENT_POSITION_FOLLOWING,'A not before B');
            // Reconnect snapshots replace, then subsequent deltas append once.
            addChatEntry('stream','B live',null,null,{item_id:'acp:ui:B',replace:true});
            addChatEntry('stream',' + delta',null,null,{item_id:'acp:ui:B'});
            addChatEntry('text','B final',null,null,{event_id:'acp:ui:B'});
            require(b.textContent.includes('B final') && !b.classList.contains('streaming'),'B did not finalize');
            addChatEntry('thinking_stream','D live',null,null,{item_id:'acp:ui:D'});
            addChatEntry('thinking','C final',null,null,{event_id:'acp:ui:C'});
            let d=chat.querySelector('[data-segment-id="acp:ui:D"]');
            require(d && d.classList.contains('codex-thinking-card') && !d.classList.contains('chat-bot'),'thinking_stream leaked into chat-bot');
            require(d.classList.contains('streaming'),'thinking C destroyed D');
            require(d.querySelector('.codex-activity-body').style.display==='none','thinking_stream not collapsed');
            require(d.querySelector('.codex-activity-body').textContent.trim()==='D live','thinking body mismatch');
            addChatEntry('thinking','D final',null,null,{event_id:'acp:ui:D'});
            // A durable node remains the identity source after bounded cache eviction.
            _acpSegments.delete('acp:ui:A');
            addChatEntry('text','A final',null,null,{event_id:'acp:ui:A'});
            require(chat.querySelectorAll('[data-segment-id="acp:ui:A"]').length===1,'evicted identity duplicated');
            // Non-ACP/no-ID streams continue down the unchanged legacy branch.
            require(_renderAcpSegment('stream','legacy',null,null,{})===false,'legacy intercepted');
            const id='acp:ui:tool';const payload={tool_use_id:id,tool_name:'run_command'};
            const host=document.createElement('div');host.className='chat-tool';chat.appendChild(host);
            _renderFullToolCall('run_command: {}',payload,host);
            addChatEntry('tool_update','run_command: {"CommandLine":"echo late synthetic"}',null,null,payload);
            let tool=_toolForResult(chat,payload,null,false);
            require(chat.querySelectorAll('[data-tool-use-id="'+id+'"]').length===1,'input created duplicate tool card');
            require(tool.dataset.toolContent.includes('echo late synthetic'),'late input missing');
            _queueOrApplyCodexToolUpdate(chat,'tool_stream','A',{...payload,replace:true},null);
            _queueOrApplyCodexToolUpdate(chat,'tool_stream','AB',{...payload,replace:true},null);
            require(tool.querySelector('.codex-live-output').textContent==='AB','A -> AB duplicated');
            // Reconnect replay and non-prefix replacement are snapshots as well.
            _queueOrApplyCodexToolUpdate(chat,'tool_stream','AB',{...payload,replace:true},null);
            require(tool.querySelector('.codex-live-output').textContent==='AB','reconnect duplicated AB');
            _queueOrApplyCodexToolUpdate(chat,'tool_stream','reset',{...payload,replace:true},null);
            require(tool.querySelector('.codex-live-output').textContent==='reset','replacement appended');
            _renderFullToolResult('AB',null,payload,null,document.createElement('div'),n=>chat.appendChild(n),false);
            addChatEntry('tool_update','run_command: {"CommandLine":"echo final arguments"}',null,null,payload);
            tool=_toolForResult(chat,payload,null,false);
            require(tool.dataset.toolContent.includes('final arguments') && tool.textContent.includes('AB'),'late input lost terminal result');
            require(chat.querySelectorAll('[data-tool-use-id="'+id+'"]').length===1,'terminal input duplicated card');
            const compactPayload={tool_use_id:'acp:ui:compact',tool_name:'run_command'};
            chat.appendChild(buildCompactToolLine('tool','run_command: {}',null,compactPayload));
            addChatEntry('tool_update','run_command: {"CommandLine":"echo compact args"}',null,null,compactPayload);
            const compact=chat.querySelector('[data-compact-tool]');
            require(compact.dataset.toolContent.includes('compact args') && compact.querySelector('.compact-preview').textContent.includes('compact args'),'compact input did not update');
            require(chat.querySelectorAll('[data-compact-tool]').length===1,'duplicate compact card');
            const mcp={...compactPayload,tool_name:'mcp__orchestra__task_get'};
            addChatEntry('tool_update','mcp__orchestra__task_get: {"id":"synthetic"}',null,null,mcp);
            require(compact.dataset.toolRaw==='mcp__orchestra__task_get' && compact.children[1].textContent==='Orchestra','compact canonical name stale');
            const checks={compact_input_update:true,late_final_keeps_live_segment:true,thinking_segments:true,legacy_fallback:true,
                input_updates_one_card:true,late_input_preserves_result:true,tool_snapshots_and_replay:true};
            chat.replaceChildren();_acpSegments.clear();_pendingAcpToolInputs.clear();
            return checks;
        }""")
        # Real tool renderer functions, browser DOM/layout, stored metadata from backend.
        page.evaluate("""rows=>{for(const row of rows){if(row.type==='tool'){let div=document.createElement('div');document.querySelector('#chat').appendChild(div);_renderFullToolCall(row.content,row,div)}else if(row.type==='tool_result'){_renderFullToolResult(row.content,row.ts,row,null,document.createElement('div'),x=>document.querySelector('#chat').appendChild(x),false)}else if(row.type==='text'){let p=document.createElement('p');p.textContent=row.content;document.querySelector('#chat').appendChild(p)}}}""",logs)
        # Replay the actual new mock stdio -> AgentSession -> immutable DB transcript.
        late=json.loads((OUT/'late-input-transcript.json').read_text())
        page.evaluate('''rows=>{const chat=document.querySelector('#chat');
            for(const row of rows){
                if(row.type==='tool'){const node=document.createElement('div');node.className='chat-tool';chat.appendChild(node);_renderFullToolCall(row.content,row,node)}
                else if(row.type==='tool_update')addChatEntry(row.type,row.content,row.ts,null,row);
                else if(row.type==='tool_result')_renderFullToolResult(row.content,row.ts,row,null,document.createElement('div'),x=>chat.appendChild(x),false);
            }
            const id=rows[0].tool_use_id,card=_toolForResult(chat,{tool_use_id:id},null,false);
            if(chat.querySelectorAll('[data-tool-use-id="'+CSS.escape(id)+'"]').length!==1 || !card.dataset.toolContent.includes('echo late synthetic') || !card.textContent.includes('AB'))throw Error('real journal replay failed');
        }''',late['logs'])
        renderer_checks['real_stdio_journal_replay']=True
        page.evaluate('card=>document.querySelector("#chat").appendChild(renderNativeRequestCard(JSON.stringify(card)))',card)
        page.wait_for_timeout(50)
        page.get_by_role('button',name='Choice A',exact=True).click()
        page.wait_for_function('document.querySelector("[data-native-request-id] span").textContent === "responded"')
        page.locator('[data-tool-raw-name]').first.click()
        # Keep the entire native card and expanded Bash details in the review image.
        height=page.locator('#chat').evaluate('(node)=>Math.min(2400,Math.max(900,node.scrollHeight+32))')
        page.set_viewport_size({'width':1280,'height':height})
        text=page.locator('body').text_content()
        names=page.locator('[data-tool-raw-name]').evaluate_all('(els)=>els.map(x=>x.dataset.toolRawName)')
        contrast=page.evaluate(r'''() => {
            const pre=document.querySelector('.native-request-card pre');
            const style=getComputedStyle(pre);
            const luminance=color=>{
                const channels=color.match(/[\d.]+/g).slice(0,3).map(x=>{x=Number(x)/255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4});
                return channels[0]*.2126+channels[1]*.7152+channels[2]*.0722;
            };
            const fg=luminance(style.color), bg=luminance(style.backgroundColor);
            return {ratio:(Math.max(fg,bg)+.05)/(Math.min(fg,bg)+.05),foreground:style.color,background:style.backgroundColor,
                bodyBackground:getComputedStyle(document.body).backgroundColor,
                disabledButtons:[...document.querySelectorAll('.native-request-card button')].every(x=>x.disabled)};
        }''')
        assert contrast['ratio']>=4.5 and contrast['disabledButtons'],contrast
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
        (OUT/'ui-check.json').write_text(json.dumps({'passed':True,'renderer':'actual chat/tool-renderers/live-activity JS in headless Chromium','requests':requests,'native_answers':answers,'page_errors':errors,'regressions':renderer_checks,'contrast':contrast,'network_namespace':'lo only','note':'UI endpoint responses synthetic; actual native HTTP/RPC covered by Python integration tests'},indent=2))
        print('REAL_HEADLESS_UI_PASS',flush=True)
    finally:browser.close()
