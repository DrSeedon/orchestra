import csv
import datetime as dt
import json
import sqlite3
from pathlib import Path

OUT=Path(__file__).resolve().parent
calls=list(csv.DictReader((OUT/'tool_calls_7d.csv').open()))
c=sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro',uri=True);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
out=[]
def payload(call):
    row=c.execute('SELECT content FROM logs WHERE id=?',(int(call['call_id']),)).fetchone()
    try:return json.loads(row['content'][row['content'].index('{'):]) if row else {}
    except (ValueError,json.JSONDecodeError):return {}
for tool in ('mcp__orchestra__merge_worker','mcp__orchestra__get_worker_logs'):
    selected=sorted((r for r in calls if r['tool_name']==tool),key=lambda r:float(r['duration_s']),reverse=True)[:3]
    for call in selected:
        obj=payload(call)
        row={'tool_name':tool,'call_id':call['call_id'],'result_id':call['result_id'],
             'caller_session_id':call['session_id'],'call_ts':call['call_ts'],
             'result_ts':call['result_ts'],'elapsed_s':call['duration_s'],
             'worker_name':obj.get('name',''),'limit':obj.get('limit','')}
        if tool.endswith('merge_worker'):
            before=dt.datetime.fromisoformat(call['call_ts'])-dt.timedelta(seconds=5)
            after=dt.datetime.fromisoformat(call['result_ts'])+dt.timedelta(seconds=5)
            op=c.execute("SELECT state,created_at,started_at,finished_at,finalization_stage FROM merge_operations WHERE worker_name=? AND created_at BETWEEN ? AND ? ORDER BY abs(julianday(created_at)-julianday(?)) LIMIT 1",(row['worker_name'],before.isoformat(),after.isoformat(),call['call_ts'])).fetchone()
            if op:
                row.update({f'merge_{k}':op[k] for k in ('state','created_at','started_at','finished_at','finalization_stage')})
                row['call_to_operation_created_s']=(dt.datetime.fromisoformat(op['created_at'])-dt.datetime.fromisoformat(call['call_ts'])).total_seconds()
                row['operation_runtime_s']=(dt.datetime.fromisoformat(op['finished_at'])-dt.datetime.fromisoformat(op['started_at'])).total_seconds() if op['finished_at'] and op['started_at'] else ''
                row['operation_finish_to_tool_result_s']=(dt.datetime.fromisoformat(call['result_ts'])-dt.datetime.fromisoformat(op['finished_at'])).total_seconds() if op['finished_at'] else ''
        else:
            parent=c.execute('SELECT scope FROM sessions WHERE id=?',(call['session_id'],)).fetchone()
            worker=c.execute('SELECT id,backend_type FROM sessions WHERE name=? AND scope=? ORDER BY created_at DESC LIMIT 1',(row['worker_name'],parent['scope'] if parent else '')).fetchone()
            stats=c.execute('SELECT count(*) n,coalesce(sum(length(content)),0) chars FROM logs WHERE session_id=?',(worker['id'],)).fetchone() if worker else None
            response=c.execute('SELECT count(*) n,coalesce(sum(length(content)),0) chars FROM (SELECT content FROM logs WHERE session_id=? ORDER BY id DESC LIMIT 5000)',(worker['id'],)).fetchone() if worker else None
            row.update({'worker_runtime':worker['backend_type'] if worker else '',
                        'worker_session_id':worker['id'] if worker else '',
                        'worker_log_rows':stats['n'] if stats else '',
                        'worker_log_content_chars_all':stats['chars'] if stats else '',
                        'api_default_response_rows':response['n'] if response else '',
                        'api_default_response_content_chars':response['chars'] if response else ''})
            result=c.execute('SELECT length(content) FROM logs WHERE id=?',(int(call['result_id']),)).fetchone()
            row['returned_result_chars']=result[0] if result else ''
        out.append(row)
fields=sorted({k for r in out for k in r})
with (OUT/'mcp_outlier_samples.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
for r in out:print(json.dumps(r,ensure_ascii=False))
c.rollback();c.close()
