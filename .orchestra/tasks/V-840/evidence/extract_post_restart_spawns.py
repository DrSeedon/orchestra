import csv
import datetime as dt
import json
import sqlite3
from pathlib import Path

OUT=Path(__file__).resolve().parent
RESTART='2026-10-14T07:47:19+00:00'
c=sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro',uri=True)
c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
calls=c.execute("SELECT id,session_id,ts,tool_use_id,content FROM logs WHERE type='tool' AND tool_name='mcp__orchestra__spawn_worker' AND ts>=? ORDER BY id",(RESTART,)).fetchall()
out=[]
for call in calls:
    try: payload=json.loads(call['content'][call['content'].index('{'):])
    except (ValueError,json.JSONDecodeError): payload={}
    name=str(payload.get('name') or '')
    result=c.execute("SELECT id,ts FROM logs WHERE session_id=? AND tool_use_id=? AND type='tool_result' AND id>? ORDER BY id LIMIT 1",(call['session_id'],call['tool_use_id'],call['id'])).fetchone()
    child=c.execute('SELECT id,name,task_id,backend_type,created_at,worktree_path,status FROM sessions WHERE parent_id=? AND name=? AND created_at>=? ORDER BY created_at LIMIT 1',(call['session_id'],name,call['ts'][:19])).fetchone() if name else None
    sid=child['id'] if child else ''
    turn=c.execute('SELECT ts,turn_duration_ms,api_duration_ms,provider_api_duration_ms,model_estimate_duration_ms FROM turn_usage WHERE session_id=? ORDER BY ts LIMIT 1',(sid,)).fetchone() if sid else None
    action=c.execute("SELECT ts,type,tool_name FROM logs WHERE session_id=? AND type='tool' ORDER BY id LIMIT 1",(sid,)).fetchone() if sid else None
    def delta(a,b):
        if not a or not b:return ''
        return (dt.datetime.fromisoformat(b)-dt.datetime.fromisoformat(a)).total_seconds()
    out.append({'call_id':call['id'],'result_id':result['id'] if result else '',
      'parent_session_id':call['session_id'],'child_session_id':sid,'worker_name':name,
      'task_id':child['task_id'] if child else payload.get('task_id',''),
      'runtime':child['backend_type'] if child else '',
      'repo_path':payload.get('repo_path',''),'spawn_call_ts':call['ts'],
      'spawn_return_ts':result['ts'] if result else '',
      'spawn_call_to_return_s':delta(call['ts'],result['ts'] if result else ''),
      'session_created_at':child['created_at'] if child else '',
      'call_to_session_created_s':delta(call['ts'],child['created_at'] if child else ''),
      'first_tool_ts':action['ts'] if action else '',
      'first_tool_name':action['tool_name'] if action else '',
      'call_to_first_tool_s':delta(call['ts'],action['ts'] if action else ''),
      'first_turn_end_ts':turn['ts'] if turn else '',
      'call_to_first_turn_end_s':delta(call['ts'],turn['ts'] if turn else ''),
      'return_to_first_turn_end_s':delta(result['ts'] if result else '',turn['ts'] if turn else ''),
      'first_turn_duration_s':turn['turn_duration_ms']/1000 if turn and turn['turn_duration_ms'] is not None else '',
      'first_turn_api_s':turn['api_duration_ms']/1000 if turn and turn['api_duration_ms'] is not None else '',
      'first_turn_provider_api_s':turn['provider_api_duration_ms']/1000 if turn and turn['provider_api_duration_ms'] is not None else '',
      'first_turn_model_estimate_s':turn['model_estimate_duration_ms']/1000 if turn and turn['model_estimate_duration_ms'] is not None else '',
      'session_status_at_snapshot':child['status'] if child else ''})
with (OUT/'spawns_post_restart.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(out[0]) if out else []);w.writeheader();w.writerows(out)
print('restart_utc',RESTART,'calls',len(out),'matched_children',sum(bool(r['child_session_id']) for r in out),'first_turns_complete',sum(bool(r['first_turn_end_ts']) for r in out))
for r in out: print(json.dumps({k:r[k] for k in ('worker_name','task_id','runtime','repo_path','spawn_call_ts','spawn_call_to_return_s','call_to_first_tool_s','first_turn_end_ts','call_to_first_turn_end_s','first_turn_duration_s','first_turn_api_s','first_turn_provider_api_s','session_status_at_snapshot')},ensure_ascii=False))
c.rollback();c.close()
