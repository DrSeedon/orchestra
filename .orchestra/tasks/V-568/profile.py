"""Metadata-only live inventory. Raw source retained only under ignored local/."""
import collections,hashlib,json,pathlib,re,sqlite3,subprocess,statistics
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[2]
def sha(x):return hashlib.sha256(x).hexdigest()
def write(name,x):(HERE/name).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
pid=subprocess.check_output(['systemctl','show','orchestra','-p','MainPID','--value'],text=True).strip()
env=dict(x.split(b'=',1) for x in pathlib.Path('/proc/'+pid+'/environ').read_bytes().split(b'\0') if b'=' in x)
db=env[b'ORCHESTRA_DB_PATH'].decode();c=sqlite3.connect('file:'+db+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
s=dict(c.execute("select id,name,session_id,model,cwd,system_prompt from sessions where name='Orchestra-orchestrator'").fetchone())
(HERE/'local/system.txt').write_text(s.pop('system_prompt'))
p=pathlib.Path('/home/kesha/.claude/projects/-home-kesha-orchestra')/(s['session_id']+'.jsonl')
raw=p.read_bytes();(HERE/'local/native.jsonl').write_bytes(raw);rows=[json.loads(l) for l in raw.splitlines()]
requests={};blocks=collections.defaultdict(lambda:{'count':0,'bytes':0});attachments=collections.defaultdict(lambda:{'count':0,'bytes':0}); prompts=[];boundaries=[]
for i,r in enumerate(rows):
 if r['type']=='system' and r.get('subtype')=='compact_boundary':boundaries.append({'index':i,'ts':r['timestamp'],'metadata':r.get('compactMetadata')})
 if r['type']=='attachment':
  a=r['attachment']; key=a.get('type','unknown');attachments[key]['count']+=1;attachments[key]['bytes']+=len(json.dumps(a,ensure_ascii=False,separators=(',',':')).encode())
 if r['type'] not in ('user','assistant'):continue
 m=r['message'];content=m.get('content',''); bs=[{'type':'text','text':content}] if isinstance(content,str) else content
 if r['type']=='assistant' and m.get('id') and m.get('usage'):requests[m['id']]={'ts':r['timestamp'],'usage':m['usage'],'model':m.get('model')}
 for b in bs:
  kind=r['type']+'/'+b.get('type','unknown');text=b.get('text','')
  if r['type']=='user' and '[Orchestra platform note:' in text:
   kind='user/role_reinjection';prompts.append({'index':i,'bytes':len(text.encode()),'sha256':sha(text.encode()),'ts':r['timestamp']})
  elif r['type']=='user' and ('[from:' in text or 'sent you a message' in text):kind='user/worker_report_or_message'
  data=json.dumps(b,ensure_ascii=False,separators=(',',':')).encode();blocks[kind]['count']+=1;blocks[kind]['bytes']+=len(data)
static=(HERE/'local/system.txt').read_text();modules=[]
for p in sorted((ROOT/'.orchestra/pipelines/default/prompts').rglob('*.md')):
 text=p.read_text().strip()
 if text and text in static:modules.append({'path':str(p.relative_to(ROOT)),'bytes':len(text.encode()),'occurrences':static.count(text)})
mem=re.findall(r'<worker-memory>.*?</worker-memory>',static,re.S)
req=list(requests.values());sizes=[sum(x['usage'].get(k,0) for k in ['input_tokens','cache_creation_input_tokens','cache_read_input_tokens']) for x in req]
start='2026-09-06T00:00:00+00:00';end='2026-09-13T00:00:00+00:00'
q="""select s.role,u.runtime,u.model,count(*) turns,sum(input_tokens) input,sum(output_tokens) output,sum(cache_create_tokens) cache_write,sum(cache_read_tokens) cache_read,sum(u.cost_usd) cost_usd from turn_usage u join sessions s on s.id=u.session_id where u.ts>=? and u.ts<? group by s.role,u.runtime,u.model"""
try: weekly=[dict(r) for r in c.execute(q,(start,end))]
except sqlite3.OperationalError: weekly=[]
write('profile.json',{'source':{**s,'db':db,'native_path':'/home/kesha/.claude/projects/-home-kesha-orchestra/'+s['session_id']+'.jsonl','native_sha256':sha(raw),'native_bytes':len(raw)},'window':[start,end],'weekly':weekly,'native_types':dict(collections.Counter(r['type'] for r in rows)),'serialized_content_blocks':dict(blocks),'serialized_attachments':dict(attachments),'role_reinjections':prompts,'compact_boundaries':boundaries,'native_requests':len(req),'request_context_tokens':{'min':min(sizes),'median':statistics.median(sizes),'max':max(sizes),'sum':sum(sizes)},'requests':req,'stored_role_prompt_bytes':len(static.encode()),'matched_modules':modules,'memory_bytes':sum(len(x.encode()) for x in mem),'classification_limit':'Native journal is not a wire dump; block JSON bytes are serialized journal content, attachments require CLI rendering; worker-message detection is conservative.'})
print(json.dumps({'requests':len(req),'median_request_context':statistics.median(sizes),'max_request_context':max(sizes),'stored_role_bytes':len(static.encode()),'blocks':dict(blocks),'attachments':dict(attachments),'boundaries':len(boundaries)},ensure_ascii=False))
