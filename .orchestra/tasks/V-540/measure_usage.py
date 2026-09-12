"""Read only live Claude usage; never export conversation content or credentials."""
import argparse
import json
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

pid = int(subprocess.check_output(['systemctl', 'show', 'orchestra', '-p', 'MainPID', '--value']))
env = dict(x.split(b'=', 1) for x in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0') if b'=' in x)
path = env[b'ORCHESTRA_DB_PATH'].decode()
c = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
c.row_factory = sqlite3.Row
parser = argparse.ArgumentParser()
parser.add_argument('--start', help='Inclusive ISO timestamp')
parser.add_argument('--end', help='Exclusive ISO timestamp')
args = parser.parse_args()
end = datetime.fromisoformat(args.end) if args.end else datetime.now(timezone.utc)
start = datetime.fromisoformat(args.start) if args.start else end - timedelta(days=7)
if start.tzinfo is None or end.tzinfo is None or start >= end:
    parser.error('use timezone-aware timestamps with start < end')
params = (start.isoformat(), end.isoformat())
print(json.dumps({'pid': pid, 'db': path, 'start_inclusive': params[0], 'end_exclusive': params[1]}))
q = '''SELECT count(*) turns, sum(cache_create_tokens) cache_create_tokens,
sum(cache_read_tokens) cache_read_tokens, sum(u.cost_usd) cost_usd,
sum(cache_create_tokens>100000) large_create_turns,
sum(case when cache_create_tokens>100000 then u.cost_usd else 0 end) large_turn_cost_usd
FROM turn_usage u JOIN sessions s ON s.id=u.session_id
WHERE u.runtime='claude' AND u.ts>=? AND u.ts<?'''
for label, suffix in [('all_claude',''), ('Orchestra-orchestrator', " AND s.name='Orchestra-orchestrator'")]:
 print(label, json.dumps(dict(c.execute(q+suffix, params).fetchone())))
print('agents', json.dumps([dict(r) for r in c.execute('''SELECT s.name, count(*) turns, sum(cache_create_tokens) cache_create_tokens, sum(cache_read_tokens) cache_read_tokens, sum(u.cost_usd) cost_usd, sum(cache_create_tokens>100000) large_create_turns FROM turn_usage u JOIN sessions s ON s.id=u.session_id WHERE u.runtime='claude' AND u.ts>=? AND u.ts<? GROUP BY s.name ORDER BY turns DESC LIMIT 20''',params)]))
print('log_types',json.dumps([dict(r) for r in c.execute("SELECT type,count(*) n FROM logs WHERE session_id=(SELECT id FROM sessions WHERE name='Orchestra-orchestrator' LIMIT 1) AND ts>=? GROUP BY type",(params[0],))]))
print('orchestrator_metadata', json.dumps([dict(r) for r in c.execute("SELECT id,session_id,cli_pid,backend_type,length(system_prompt) prompt_chars FROM sessions WHERE name='Orchestra-orchestrator'")]))
