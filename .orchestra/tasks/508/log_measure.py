import sqlite3,json,re,collections
from pathlib import Path
p=Path(__file__).parent;x=json.loads((p/'sample.json').read_text());c=sqlite3.connect('file:/mnt/data/Projects/Python/orchestra/data/orchestra.db?mode=ro',uri=True);c.row_factory=sqlite3.Row
c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
q="""SELECT l.id,l.ts,l.type,l.tool_name,l.content,s.name,s.scope FROM sessions s JOIN logs l ON l.session_id=s.id WHERE l.ts>=? AND l.ts<? AND l.type='tool_result' AND (l.tool_name='merge_worker' OR l.tool_name LIKE '%__merge_worker') ORDER BY l.id"""
print('WINDOW',x['start'],x['end']);print('SQL',q)
rs=[dict(r) for r in c.execute(q,(x['start'],x['end']))]
phrase='Record review coverage for this exact snapshot, then start a new operation.'
refused=[r for r in rs if phrase in r['content'] or 'RECORD_REVIEW_THEN_NEW_OPERATION' in r['content']]
ids=set()
print('MERGE_TOOL_RESULT_ROWS',len(rs),'COVERAGE_REFUSAL_ROWS',len(refused))
for r in refused:
 ids.update(re.findall(r'Merge operation ([0-9a-f-]{36})',r['content']))
 print('REFUSAL',json.dumps(r,ensure_ascii=False))
print('DISTINCT_OPERATION_IDS',len(ids),'PERSISTED',sum(bool(c.execute('select 1 from merge_operations where operation_id=?',(i,)).fetchone()) for i in ids))
for term in ['kesha-tg-bot','VPN-Service','seedon']:
 sessions=[dict(r) for r in c.execute('select id,name,scope,base_branch,is_orchestrator from sessions where scope like ?',('%/'+term,))]
 print('PROJECT_SESSIONS',term,len(sessions))
 print('PROJECT_RECEIPTS',term,sum(r['scope'].endswith('/'+term) for r in x['receipts']))
 for s in sessions:
  if not s['is_orchestrator']:continue
  matches=c.execute("select id,ts,type,tool_name,content from logs where session_id=? and ts>=? and ts<? and (tool_name like '%codex_review%' or (type='tool_result' and (instr(content,'Needed a single revision')>0 or instr(content,'open task run conflicts')>0 or instr(content,'merge produced no new commits')>0))) order by id",(s['id'],x['start'],x['end'])).fetchall()
  for m in matches:
   print('PROJECT_EVENT',term,json.dumps(dict(m),ensure_ascii=False))
c.rollback()
