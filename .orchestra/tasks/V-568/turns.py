"""Conservative action census; tool categories are not model-capability labels."""
import collections,json,pathlib,sqlite3,bisect,hashlib
HERE=pathlib.Path(__file__).resolve().parent;p=json.loads((HERE/'profile.json').read_text());c=sqlite3.connect('file:'+p['source']['db']+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
start,end=p['window'];sessions=list(c.execute("select distinct s.id,s.name from sessions s join turn_usage u on s.id=u.session_id where s.role='orchestrator' and u.runtime='claude' and u.ts>=? and u.ts<?",(start,end)))
judgment={'merge_worker','resolve_merge_operation','codex_review','change_worker_model','update_worker_prompt','kill_worker','stop_worker'}
dispatch={'spawn_worker','send_message','task_create','task_update','update_progress','update_worker_description'}
status={'list_agents','list_orchestrators','worker_wip','get_worker_info','get_worker_logs','bg_list','task_get','task_list','delivery_status','message_delivery_status','file_delivery_status','task_create_status','test_lock_status','project_goal','project_wait'}
records=[];samples=[]
for sess in sessions:
 turns=[dict(x) for x in c.execute("select * from turn_usage where session_id=? and runtime='claude' and ts>=? and ts<? order by ts,id",(sess['id'],start,end))]
 ends=[r['ts'] for r in turns]; prior=c.execute('select max(ts) from turn_usage where session_id=? and ts<?',(sess['id'],start)).fetchone()[0] or start
 logs=[[] for _ in turns]
 for row in c.execute("select id,ts,type,tool_name,content from logs where session_id=? and ts>? and ts<=? order by ts,id",(sess['id'],prior,ends[-1])):
  idx=bisect.bisect_left(ends,row['ts'])
  if idx<len(logs):logs[idx].append(dict(row))
 for u,ls in zip(turns,logs):
  toolnames=[(x['tool_name'] or x['content'].split(':',1)[0]).removeprefix('mcp__orchestra__') for x in ls if x['type']=='tool'];names=set(toolnames)
  texts=[x['content'] for x in ls if x['type']=='text'];users=[x['content'] for x in ls if x['type']=='user_message']
  substantive=any(t.strip() not in ('','[[ORCHESTRA:SILENT_TURN]]') for t in texts)
  if names & judgment:category='judgment_or_lifecycle_action'
  elif names & dispatch:category='dispatch_or_message_may_contain_judgment'
  elif names and names<=status and not substantive:category='status_tools_no_substantive_text'
  elif names and names<=status:category='status_tools_with_text_unknown_judgment'
  elif not ls:category='no_logs'
  elif not names and not substantive:category='no_tools_no_substantive_text'
  else:category='other_unknown'
  rec={'usage_id':u['id'],'session':sess['name'],'ts':u['ts'],'category':category,'tools':dict(collections.Counter(toolnames)),'log_count':len(ls),'log_first':ls[0]['id'] if ls else None,'log_last':ls[-1]['id'] if ls else None,'text_bytes':sum(len(t.encode()) for t in texts),'cost_usd':u['cost_usd'],'cache_read':u['cache_read_tokens']}
  records.append(rec);samples.append({**rec,'text':'\n'.join(texts),'user':'\n'.join(users),'tool_inputs':'\n'.join(x['content'] for x in ls if x['type']=='tool')})
summary={}
for r in records:
 s=summary.setdefault(r['category'],{'turns':0,'cost_usd':0,'cache_read':0});s['turns']+=1;s['cost_usd']+=r['cost_usd'];s['cache_read']+=r['cache_read']
(HERE/'turn-census.json').write_text(json.dumps({'window':[start,end],'count':len(records),'rule':'First matching category by explicit tool sets; lifecycle/dispatch tool names do not establish cognitive difficulty. Logs attributed (previous turn_end,current turn_end]; incoming messages may arrive mid-turn. Historical missing rows remain unknown.','summary':summary,'records':records},ensure_ascii=False,indent=2))
(HERE/'local/turn-content.json').write_text(json.dumps(samples,ensure_ascii=False))
print(json.dumps(summary,ensure_ascii=False,indent=2))
