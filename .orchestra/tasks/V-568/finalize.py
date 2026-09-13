"""Freeze metadata and verify report inputs without additional model calls."""
import hashlib,json,pathlib,random,collections
H=pathlib.Path(__file__).resolve().parent
p=json.loads((H/'profile.json').read_text());p['source']['native_path']='/home/kesha/.claude/projects/-home-kesha-orchestra/'+p['source']['session_id']+'.jsonl';(H/'profile.json').write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n')
rs=json.loads((H/'local/turn-content.json').read_text());selection=random.Random(568).sample([r for r in rs if r['category']=='dispatch_or_message_may_contain_judgment'],12)
reasons={10408:'Corrects own mistaken inference from images.',9716:'Evaluates numerical evidence and chooses a quality tradeoff.',8511:'Accepts test evidence and designs next cross-product investigation.',9805:'Prioritizes task meaning over decorative content.',9278:'Distinguishes competing failure mechanisms and supplies conditional recovery choices.',9933:'Defines acceptance limits and challenges an unverified launcher change.',9994:'Derives output requirements, identifies resolution risk and authorization boundary.',8868:'Changes validation method after prior tests missed visual failures.'}
(H/'dispatch-audit.json').write_text(json.dumps({'method':'Random(568).sample from 715 dispatch-labelled turns; inspection of selected assistant text and named tool inputs; NOT a measurement of necessary model capability. Four not fully adjudicated remain unknown, not simple.','sample_size':12,'judgment_observed':8,'rows':[{'usage_id':r['usage_id'],'category':'judgment_observed' if r['usage_id'] in reasons else 'not_adjudicated','reason':reasons.get(r['usage_id'],''),'log_first':r['log_first'],'log_last':r['log_last']} for r in selection]},ensure_ascii=False,indent=2))
js=(H/'local/apprentice.js').read_bytes()
assert b'GPT-5.6 Luna, 7% success rate at $0.77 per task' in js
assert b'GPT-5.6 Luna, 13% success rate at $0.16 per task' in js
(H/'external-sources.json').write_text(json.dumps({'retrieved_date':'2026-09-13','sources':[{'url':'https://github.com/donvito/codex-astra-luna-orchestrator','opened':'README, Plus/Pro table and configurations','findings':{'Plus_orchestrator':'Luna max','Pro_orchestrator':'Astra medium','reviewer':'Astra low','concurrency':4}},{'url':'https://neocognition.io/blog/apprentice-bench/','bundle_url':'https://neocognition.io/assets/index-BhJAP4UZ.js','bundle_sha256':hashlib.sha256(js).hexdigest(),'bundle_bytes':len(js),'Luna_GUI_score':7,'Luna_API_score':13,'Luna_GUI_cost_per_task':0.77,'Luna_API_cost_per_task':0.16,'learning_ablation_scores':[11,31,35,43],'limitation':'Configuration-level scores on one accounts-payable job, not Orchestra.'},{'url':'https://platform.claude.com/docs/en/build-with-claude/prompt-caching','opened':'Prefix order tools/system/messages and cache TTL; API documentation does not establish subscription pool tariff.'}]},indent=2))
uses={};sizes=[]
for r in map(json.loads,(H/'local/native.jsonl').open()):
 bs=r.get('message',{}).get('content',[])
 if not isinstance(bs,list):continue
 for b in bs:
  if b.get('type')=='tool_use':uses[b['id']]=b['name']
  if b.get('type')!='tool_result':continue
  cc=b.get('content');parts=[cc] if isinstance(cc,str) else [x.get('text','') for x in cc or [] if isinstance(x,dict)]
  for text in parts:
   try:obj=json.loads(text)
   except (ValueError,TypeError):continue
   compact=json.dumps(obj,ensure_ascii=False,separators=(',',':'));sizes.append({'tool':uses.get(b.get('tool_use_id')),'before_bytes':len(text.encode()),'after_bytes':len(compact.encode())})
(H/'json-minification.json').write_text(json.dumps({'method':'Every text block in native user/tool_result for which json.loads succeeds; serialize ensure_ascii=False, compact separators. Non-JSON responses excluded.','count':len(sizes),'before_bytes':sum(x['before_bytes'] for x in sizes),'after_bytes':sum(x['after_bytes'] for x in sizes),'rows':sizes},indent=2))
assert len(sizes)==189 and sum(x['before_bytes'] for x in sizes)==262685 and all(x['before_bytes']==x['after_bytes'] for x in sizes)
r=json.loads((H/'experiment-results.json').read_text());assert len(r)==6 and all(x['correct'] and x['rc']==0 and x['requests']==1 for x in r)
checks={'all_six_outputs_correct':True,'actual_model_requests':6,'sum_total_cost_usd':sum(x['cost_usd'] for x in r),'input_token_reduction':62378-34930,'warm_cost_before_mean':(r[1]['cost_usd']+r[4]['cost_usd'])/2,'warm_cost_after_mean':(r[3]['cost_usd']+r[5]['cost_usd'])/2,'same_output_transition_penalty':r[2]['cost_usd']-r[4]['cost_usd'],'same_output_warm_saving':r[4]['cost_usd']-r[3]['cost_usd'],'estimated_duplicate_exposure_bytes':1617*13460}
checks['conditional_57_session_penalty']=57*checks['same_output_transition_penalty'];checks['conditional_58_session_penalty']=58*checks['same_output_transition_penalty'];checks['conditional_28_session_penalty']=28*checks['same_output_transition_penalty'];(H/'verification.json').write_text(json.dumps(checks,indent=2));print(json.dumps(checks,indent=2))
# Keep derived evidence reviewable: one measured record per line, values unchanged.
for name in ['profile.json','turn-census.json','duplicate-exposure.json','json-minification.json']:
 path=H/name;value=json.loads(path.read_text());parts=[]
 for key,v in value.items():
  encoded=('[\n'+',\n'.join('    '+json.dumps(row,ensure_ascii=False) for row in v)+'\n  ]') if isinstance(v,list) else json.dumps(v,ensure_ascii=False)
  parts.append('  '+json.dumps(key)+': '+encoded)
 text='{\n'+',\n'.join(parts)+'\n}\n';assert json.loads(text)==value;path.write_text(text)
