"""Offline Claude serialization capture; loopback server never forwards requests."""
import http.server,json,os,pathlib,shutil,subprocess,threading,sys
HERE=pathlib.Path(__file__).resolve().parent;LOCAL=HERE/'local';HOME=LOCAL/'capture-home';WORK=LOCAL/'capture-work'
HOME.mkdir(exist_ok=True);WORK.mkdir(exist_ok=True);(HOME/'.claude').mkdir(exist_ok=True)
(HOME/'.claude.json').write_text('{"hasCompletedOnboarding":true}')
source=json.loads((HERE/'profile.json').read_text())['source'];sid=source['session_id'];project=HOME/'.claude/projects'/str(WORK).replace('/','-');project.mkdir(parents=True,exist_ok=True)
raw=(LOCAL/'native.jsonl').read_bytes()
variant='precompact' if len(sys.argv)>1 else 'current'
if variant=='precompact':
 lines=raw.splitlines(keepends=True);cut=next(i for i,l in enumerate(lines) if json.loads(l).get('subtype')=='compact_boundary');raw=b''.join(lines[:cut])
(project/(sid+'.jsonl')).write_bytes(raw)
# Explicit source copies: native history stays intact; no live hooks/MCP are launched.
shutil.copyfile('/home/kesha/orchestra/CLAUDE.md',WORK/'CLAUDE.md')
if pathlib.Path('/home/kesha/.claude/CLAUDE.md').exists():shutil.copyfile('/home/kesha/.claude/CLAUDE.md',HOME/'.claude/CLAUDE.md')
for src,dst in [('/home/kesha/.claude/skills',HOME/'.claude/skills'),('/home/kesha/orchestra/.claude/skills',WORK/'.claude/skills')]:
 if pathlib.Path(src).exists() and not dst.exists():
  dst.parent.mkdir(exist_ok=True);dst.symlink_to(src,target_is_directory=True)
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_POST(self):
  data=self.rfile.read(int(self.headers.get('Content-Length',0)))
  try:obj=json.loads(data)
  except ValueError:obj={}
  if 'messages' in obj:
   (LOCAL/f'captured-{variant}-request.json').write_bytes(data)
   print(json.dumps({'path':self.path,'bytes':len(data),'system_blocks':len(obj.get('system',[])),'tools':len(obj.get('tools',[])),'messages':len(obj['messages'])}),flush=True)
  self.send_response(400);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"type":"error","error":{"type":"invalid_request_error","message":"V568 offline capture complete"}}')
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
env={'PATH':'/usr/bin:/bin','HOME':str(HOME),'CLAUDE_CONFIG_DIR':str(HOME/'.claude'),'ANTHROPIC_API_KEY':'v568-local-dummy','ANTHROPIC_BASE_URL':f'http://127.0.0.1:{server.server_port}','CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC':'1','NO_PROXY':'127.0.0.1','LANG':'C.UTF-8'}
cmd=['/usr/bin/claude','-p','--resume',sid,'--fork-session','--no-session-persistence','--setting-sources','','--strict-mcp-config','--mcp-config',json.dumps({'mcpServers':{'orchestra':{'command':'/usr/bin/python3','args':[str(HERE/'mock_mcp.py')]}}}),'--disallowed-tools',','.join(json.loads((LOCAL/'disallowed.json').read_text())),'--output-format','json','--model',source['model'],'V568 offline serialization probe. No actions.']
try:
 r=subprocess.run(cmd,cwd=WORK,env=env,capture_output=True,text=True,timeout=35);(LOCAL/'capture.stdout').write_text(r.stdout);(LOCAL/'capture.stderr').write_text(r.stderr);print('rc',r.returncode,r.stdout[-400:])
finally:server.shutdown()
