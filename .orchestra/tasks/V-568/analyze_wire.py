"""Exact UTF-8 partitions of captured CLI request bodies and experiment checks."""
import collections,hashlib,json,pathlib,re
H=pathlib.Path(__file__).resolve().parent;L=H/'local'
def dump(x):return json.dumps(x,ensure_ascii=False,separators=(',',':')).encode()
def sh(x):return hashlib.sha256(x).hexdigest()
def strings(x):
 if isinstance(x,str):yield x
 elif isinstance(x,dict):
  for v in x.values():yield from strings(v)
 elif isinstance(x,list):
  for v in x:yield from strings(v)
rows=[json.loads(l) for l in (L/'native.jsonl').open()];docs={};skilltexts=[]
for r in rows:
 a=r.get('attachment',{})
 if a.get('type')=='nested_memory':
  t=a['content']['content'];docs[sh(t.encode())]=t
 if a.get('type')=='skill_listing':skilltexts.append(a['content'])
result={}
for name,file in [('precompact','captured-precompact-request.json'),('postcompact','captured-request.json')]:
 raw=(L/file).read_bytes();p=json.loads(raw);assert dump(p)==raw
 categories=collections.Counter();message_bytes=0;alltexts='\n'.join(strings(p['messages']))
 # A non-overlapping partition of each whole content node. Mixed nodes labelled explicitly.
 for m in p['messages']:
  content=m['content'];bs=[content] if isinstance(content,str) else content
  for b in bs:
   bsiz=len(dump(b));message_bytes+=bsiz
   if isinstance(b,dict) and b.get('type')!='text':key=m['role']+'/'+b.get('type','unknown')
   else:
    s=b if isinstance(b,str) else b.get('text','')
    if any(t in s for t in docs.values()):key='repository_instructions_with_wrappers'
    elif '[Orchestra platform note:' in s:key='role_reinjection_with_memory_and_wrappers'
    elif 'The following skills' in s or '<available_skills>' in s:key='skill_index_with_wrapper'
    elif re.search(r'(^|\n)(\[from:|<system-reminder>\s*\[from:)',s):key='worker_messages'
    elif s.strip().startswith('<total_tokens>'):key='token_reminder'
    elif s.startswith('The following deferred tools'):key='deferred_tool_index'
    elif s.startswith('The user sent a new message while you were working:'):key='midturn_feedback_and_messages'
    else:key=m['role']+'/other_text_including_history_and_platform'
   categories[key]+=bsiz
 vals={k:len(dump(v)) for k,v in p.items()}
 result[name]={'raw_bytes':len(raw),'sha256':sh(raw),'top_level_values_bytes':vals,'top_level_syntax_bytes':len(raw)-sum(vals.values()),'content_node_bytes':dict(categories),'messages_envelope_bytes':vals['messages']-message_bytes,'message_count':len(p['messages']),'tools':[{'name':x['name'],'bytes':len(dump(x))} for x in p['tools']],'system_blocks':[{'bytes':len(dump(x)),'text_bytes':len(x.get('text','').encode()),'sha256':sh(dump(x))} for x in p['system']],'duplicate_rule_occurrences':[{'sha256':k,'text_bytes':len(t.encode()),'occurrences':alltexts.count(t)} for k,t in docs.items()],'skill_exact_matches':[{'bytes':len(t.encode()),'occurrences':alltexts.count(t)} for t in skilltexts]}
# Scope references can be expanded losslessly back to the complete input block per path.
protocol=json.loads((H/'experiment-protocol.json').read_text());after=(L/'input-after.txt').read_text();before=(L/'input-before.txt').read_text();scopes=[];lookup={}
for path,key,body in re.findall(r'<scope path="([^"]+)" rules_sha256="([^"]+)">\n?(.*?)\n?</scope>',after,re.S):
 if key not in lookup:
  assert sh(body.encode())==key;lookup[key]=body
 else:assert 'Apply exactly the complete rules' in body
 scopes.append((path,key,lookup[key]))
assert len(scopes)==10 and len(lookup)==2
assert [(p,k) for p,k,b in scopes]==[(d['path'],d['sha256']) for d in protocol['source_docs']]
assert all(f'<scope path="{p}" rules_sha256="{k}">\n{b}\n</scope>' in before for p,k,b in scopes)
experiments=[];reqs=[]
for file in sorted(L.glob('[1-6]-*-request-0.json')):
 p=json.loads(file.read_text());reqs.append(p);variant='before' if 'before' in file.name else 'after'
 texts=list(strings(p['messages']));system='\n'.join(strings(p['system']));explicit=(L/f'input-{variant}.txt').read_text();stored=(L/'system.txt').read_text()
 assert any(explicit in x for x in texts);assert stored in system;assert p['tools']==[]
 experiments.append({'file':file.name,'bytes':len(file.read_bytes()),'tools':len(p['tools']),'explicit_input_present_verbatim':True,'stored_role_and_memory_present_verbatim':True,'system_sha256':sh(dump(p['system'])),'messages_sha256':sh(dump(p['messages'])),'cache_controls':[x.get('cache_control') for x in p['system'] if isinstance(x,dict)]})
comparisons=[]
for a,b in [(0,1),(1,2),(2,3),(0,4),(2,5)]:
 x,y=reqs[a],reqs[b];comparisons.append({'from':a+1,'to':b+1,'system_equal':x['system']==y['system'],'messages_equal':x['messages']==y['messages'],'tools_equal':x['tools']==y['tools'],'changed_top_keys':[k for k in x if x[k]!=y.get(k)]})
(H/'wire-analysis.json').write_text(json.dumps({'native_replay':result,'experiment':experiments,'comparisons':comparisons,'lossless_scope_expansion':True},ensure_ascii=False,indent=2))
print(json.dumps({'replay':{k:{'bytes':v['raw_bytes'],'parts':v['content_node_bytes'],'top':v['top_level_values_bytes'],'duplicates':v['duplicate_rule_occurrences']} for k,v in result.items()},'comparisons':comparisons,'lossless_scope_expansion':True},ensure_ascii=False,indent=2))
