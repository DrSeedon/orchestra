import csv
import datetime as dt
import json
import re
import sqlite3
import subprocess
from pathlib import Path

OUT=Path(__file__).resolve().parent
calls=list(csv.DictReader(subprocess.run(['git','show','e303361d:.orchestra/tasks/V-840/evidence/tool_calls_7d.csv'],capture_output=True,text=True,check=True).stdout.splitlines()))
c=sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro',uri=True);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON')
merges=[]
for call in (x for x in calls if x['tool_name']=='mcp__orchestra__merge_worker'):
    inp=c.execute('SELECT content FROM logs WHERE id=?',(int(call['call_id']),)).fetchone()
    try:args=json.loads(inp['content'][inp['content'].index('{'):])
    except (ValueError,json.JSONDecodeError):args={}
    name=str(args.get('name') or '')
    before=dt.datetime.fromisoformat(call['call_ts'])-dt.timedelta(seconds=5)
    after=dt.datetime.fromisoformat(call['result_ts'])+dt.timedelta(seconds=5)
    op=c.execute("SELECT * FROM merge_operations WHERE worker_name=? AND created_at BETWEEN ? AND ? ORDER BY abs(julianday(created_at)-julianday(?)) LIMIT 1",(name,before.isoformat(),after.isoformat(),call['call_ts'])).fetchone()
    result=c.execute('SELECT content,tool_is_error FROM logs WHERE id=?',(int(call['result_id']),)).fetchone()
    text=result['content'] if result else ''
    state_match=re.search(r'"operation_state"\s*:\s*"([A-Z]+)"|Merge operation [0-9a-f-]+:\s*([A-Z]+)',text)
    tool_state=next((g for g in state_match.groups() if g), '') if state_match else ''
    tool_output_chars=None
    m=re.search(r'result\s*\((\d[\d,]*)\s*characters\)',text)
    if m:tool_output_chars=int(m.group(1).replace(',',''))
    row={'call_id':call['call_id'],'result_id':call['result_id'],'caller_session_id':call['session_id'],'worker_name':name,
      'call_ts':call['call_ts'],'result_ts':call['result_ts'],'tool_duration_s':float(call['duration_s']),
      'tool_is_error':result['tool_is_error'] if result else '', 'tool_terminal_state_text':tool_state,'oversize_payload_chars':tool_output_chars}
    if op:
        row.update({'operation_id':op['operation_id'],'operation_state_db':op['state'],'created_at':op['created_at'],'started_at':op['started_at'],'finished_at':op['finished_at'],'finalization_stage':op['finalization_stage'],
          'call_to_operation_created_s':(dt.datetime.fromisoformat(op['created_at'])-dt.datetime.fromisoformat(call['call_ts'])).total_seconds() if op['created_at'] else '',
          'operation_started_to_finish_s':(dt.datetime.fromisoformat(op['finished_at'])-dt.datetime.fromisoformat(op['started_at'])).total_seconds() if op['started_at'] and op['finished_at'] else '',
          'operation_finish_to_result_s':(dt.datetime.fromisoformat(call['result_ts'])-dt.datetime.fromisoformat(op['finished_at'])).total_seconds() if op['finished_at'] else ''})
        try:
            data=json.loads(op['result_json'] or '{}')
            gate=data.get('test_gate') or {}
            mut=gate.get('mutation_gate') or {}
            accept=data.get('acceptance') or {}
            row.update({'acceptance_status':accept.get('status',''),'test_gate_status':gate.get('status',''),'test_gate_mapped_file_count':len(gate.get('mapped_files') or []),'mutation_gate_status':mut.get('status',''),'mutation_gate_test_count':len(mut.get('tests') or []),'mutation_gate_selected_node_count':len(mut.get('selected_nodes') or [])})
        except (TypeError,json.JSONDecodeError):pass
    merges.append(row)
merges.sort(key=lambda r:r['tool_duration_s'],reverse=True)
with (OUT/'merge_profiles_7d.csv').open('w',newline='') as f:
    keys=sorted({k for r in merges for k in r});w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(merges)
for r in merges[:12]:
    print(json.dumps({k:r.get(k) for k in ('worker_name','call_ts','tool_duration_s','call_to_operation_created_s','operation_started_to_finish_s','operation_finish_to_result_s','operation_state_db','acceptance_status','test_gate_status','test_gate_mapped_file_count','mutation_gate_status','mutation_gate_test_count','tool_is_error','oversize_payload_chars')},ensure_ascii=False))
c.close()
