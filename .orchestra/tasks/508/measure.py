"""Read-only seven-day receipt census; no app DB initialization."""
import sqlite3,json,sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
root=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(root))
import app, app.review_coverage as coverage
DB=Path('/mnt/data/Projects/Python/orchestra/data/orchestra.db')
end=datetime.now(timezone.utc); start=end-timedelta(days=7)
c=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True); c.row_factory=sqlite3.Row
c.execute('PRAGMA query_only=ON'); c.execute('BEGIN')
print('DATABASE',DB,'mode=ro; query_only=ON; single read transaction')
print('WINDOW',start.isoformat(),end.isoformat(),'requested_at (receipts), created_at (operations), [start,end)')
print('APP',app.__file__)
q='''SELECT r.*, s.is_orchestrator AS session_is_orchestrator FROM review_receipts r LEFT JOIN sessions s ON s.id=r.session_id WHERE julianday(r.requested_at)>=julianday(?) AND julianday(r.requested_at)<julianday(?) ORDER BY r.requested_at'''
print('SQL',q)
rows=[dict(r) for r in c.execute(q,(start.isoformat(),end.isoformat()))]
def stats(rs):
 return dict(n=len(rs),empty_task=sum(not r['task_id'] for r in rs),empty_paths=sum(not json.loads(r['production_paths_json'] or '[]') for r in rs),orchestrator=sum(r['session_is_orchestrator']==1 for r in rs),unresolved_session=sum(r['session_is_orchestrator'] is None for r in rs),all_three=sum(not r['task_id'] and not json.loads(r['production_paths_json'] or '[]') and r['session_is_orchestrator']==1 for r in rs))
print('COUNTS_ALL',json.dumps(stats(rows)))
for kind in sorted(set(r['subject_kind'] for r in rows)):
 print('COUNTS_KIND',kind,json.dumps(stats([r for r in rows if r['subject_kind']==kind])))
print('STATUS',json.dumps({k:sum(r['status']==k for r in rows) for k in sorted(set(r['status'] for r in rows))}))
q2='SELECT * FROM merge_operations WHERE julianday(created_at)>=julianday(?) AND julianday(created_at)<julianday(?) ORDER BY created_at'
print('SQL',q2)
ops=[dict(r) for r in c.execute(q2,(start.isoformat(),end.isoformat()))]
blocked=[o for o in ops if 'RECORD_REVIEW_THEN_NEW_OPERATION' in o['result_json']]
print('OPERATIONS',len(ops),'RECORD_REVIEW_THEN_NEW_OPERATION',len(blocked))
for o in blocked:
 print('BLOCK',o['operation_id'],o['scope'],o['worker_name'],o['created_at'])
# Whitelisted metadata only; no prompts, logs, credentials or artifact contents.
keys=['receipt_id','scope','session_id','session_is_orchestrator','worker_name','task_id','subject_kind','mode','status','failure_code','return_code','coverage_outcome','author_outcome','requested_at','completed_at','target_sha','worker_head','production_snapshot_sha256','production_diff_sha256','production_paths_json','artifact_path','artifact_sha256','artifact_bytes','artifact_exists','verdict_present','jsonl_response_present','job_id']
data={'start':start.isoformat(),'end':end.isoformat(),'receipts':[{k:r[k] for k in keys} for r in rows],'operations':[{k:o[k] for k in ['operation_id','session_id','scope','worker_name','accepted_task_id','accepted_worker_head','created_at','result_json','accepted_admission_json']} for o in ops]}
for operation in data['operations']:
 result=json.loads(operation.pop('result_json') or '{}')
 operation['next_action_code']=(result.get('next_action') or {}).get('code','')
 admission=json.loads(operation.pop('accepted_admission_json') or '{}')
 review=admission.get('review_coverage') or {}
 operation['review_subject']={k:v for k,v in review.items() if k in ('receipt_id','target_sha','worker_head','production_snapshot_sha256','production_diff_sha256','production_paths','status','reason','coverage_outcome')}
(root/'.orchestra/tasks/508/sample.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
for r in rows:
 if r['subject_kind']=='implementation' and r['session_is_orchestrator']==1:
  print('ORCHESTRATOR_IMPLEMENTATION',json.dumps({k:r[k] for k in keys},ensure_ascii=False))
c.rollback();c.close()
