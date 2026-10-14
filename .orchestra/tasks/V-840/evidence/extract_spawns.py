import csv
import datetime as dt
import json
import sqlite3
from pathlib import Path

OUT=Path(__file__).resolve().parent
summary=json.loads((OUT/'tool_summary_7d.json').read_text())
cutoff=summary['cutoff_utc']
conn=sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro',uri=True)
conn.row_factory=sqlite3.Row
conn.execute('PRAGMA query_only=ON')
conn.execute('BEGIN')
calls=list(csv.DictReader((OUT/'tool_calls_7d.csv').open()))
spawns=[r for r in calls if r['tool_name']=='mcp__orchestra__spawn_worker']
out=[]
for call in spawns:
    row=conn.execute('SELECT content FROM logs WHERE id=?',(call['call_id'],)).fetchone()
    content=row['content'] if row else ''
    try:
        payload=json.loads(content[content.index('{'):])
    except (ValueError, json.JSONDecodeError):
        payload={}
    name=str(payload.get('name') or '')
    child=conn.execute(
        'SELECT id,name,task_id,backend_type,created_at,worktree_path FROM sessions '
        'WHERE parent_id=? AND name=? AND created_at>=? ORDER BY created_at LIMIT 1',
        (call['session_id'],name,call['call_ts'][:19]),
    ).fetchone() if name else None
    child_id=child['id'] if child else ''
    first_turn=conn.execute(
        'SELECT ts,turn_duration_ms,api_duration_ms,provider_api_duration_ms,model_estimate_duration_ms '
        'FROM turn_usage WHERE session_id=? ORDER BY ts LIMIT 1',(child_id,)
    ).fetchone() if child_id else None
    first_event=conn.execute(
        "SELECT ts,type FROM logs WHERE session_id=? AND type IN ('tool','text','tool_result') ORDER BY id LIMIT 1",
        (child_id,),
    ).fetchone() if child_id else None
    first_tool=conn.execute(
        "SELECT ts,tool_name FROM logs WHERE session_id=? AND type='tool' ORDER BY id LIMIT 1",
        (child_id,),
    ).fetchone() if child_id else None
    def seconds(ts1,ts2):
        if not ts1 or not ts2:return ''
        return (dt.datetime.fromisoformat(ts2)-dt.datetime.fromisoformat(ts1)).total_seconds()
    out.append({
        'call_id':call['call_id'],'parent_session_id':call['session_id'],'child_session_id':child_id,
        'worker_name':name,'task_id':child['task_id'] if child else payload.get('task_id',''),
        'runtime':child['backend_type'] if child else '',
        'repo_path':payload.get('repo_path',''),
        'spawn_call_ts':call['call_ts'],'spawn_return_ts':call['result_ts'],
        'spawn_call_to_return_s':call['duration_s'],
        'session_created_at':child['created_at'] if child else '',
        'call_to_session_created_s':seconds(call['call_ts'],child['created_at'] if child else ''),
        'first_logged_action_ts':first_event['ts'] if first_event else '',
        'first_action_type':first_event['type'] if first_event else '',
        'call_to_first_action_s':seconds(call['call_ts'],first_event['ts'] if first_event else ''),
        'first_tool_ts':first_tool['ts'] if first_tool else '',
        'first_tool_name':first_tool['tool_name'] if first_tool else '',
        'first_turn_end_ts':first_turn['ts'] if first_turn else '',
        'call_to_first_turn_end_s':seconds(call['call_ts'],first_turn['ts'] if first_turn else ''),
        'return_to_first_turn_end_s':seconds(call['result_ts'],first_turn['ts'] if first_turn else ''),
        'first_turn_duration_s':(first_turn['turn_duration_ms']/1000 if first_turn and first_turn['turn_duration_ms'] is not None else ''),
        'first_turn_api_s':(first_turn['api_duration_ms']/1000 if first_turn and first_turn['api_duration_ms'] is not None else ''),
        'first_turn_provider_api_s':(first_turn['provider_api_duration_ms']/1000 if first_turn and first_turn['provider_api_duration_ms'] is not None else ''),
        'first_turn_model_estimate_s':(first_turn['model_estimate_duration_ms']/1000 if first_turn and first_turn['model_estimate_duration_ms'] is not None else ''),
    })
fields=list(out[0]) if out else []
with (OUT/'spawns_7d.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
recent=[r for r in out if r['spawn_call_ts']>='2026-10-14T00:00:00+00:00']
print('window',cutoff,'spawn_calls',len(out),'matched_child',sum(bool(r['child_session_id']) for r in out),'first_turn_logged',sum(bool(r['first_turn_end_ts']) for r in out))
print('since_2026-10-14',len(recent),'matched_child',sum(bool(r['child_session_id']) for r in recent),'first_turn_logged',sum(bool(r['first_turn_end_ts']) for r in recent))
for r in recent:
 print(json.dumps({k:r[k] for k in ('worker_name','task_id','runtime','repo_path','spawn_call_ts','spawn_call_to_return_s','session_created_at','call_to_session_created_s','first_logged_action_ts','call_to_first_action_s','first_tool_name','first_turn_end_ts','call_to_first_turn_end_s','return_to_first_turn_end_s','first_turn_duration_s','first_turn_api_s','first_turn_provider_api_s')},ensure_ascii=False))
conn.rollback();conn.close()
