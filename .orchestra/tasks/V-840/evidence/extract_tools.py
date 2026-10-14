import csv
import datetime as dt
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

DB = Path('/home/kesha/orchestra/data/orchestra.db')
OUT = Path(__file__).resolve().parent
NOW = dt.datetime.now(dt.timezone.utc)
CUTOFF = NOW - dt.timedelta(days=7)
STAMP = CUTOFF.isoformat(timespec='microseconds')


def parse_ts(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))


conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
conn.row_factory = sqlite3.Row
conn.execute('PRAGMA query_only=ON')
conn.execute('BEGIN')
max_id = conn.execute('SELECT max(id) FROM logs').fetchone()[0]

# The id sequence follows event time; binary search bounds the seven-day range
# without reading the multi-gigabyte historical log payload.
lo, hi = 1, max_id
while lo < hi:
    mid = (lo + hi) // 2
    row = conn.execute('SELECT ts FROM logs WHERE id=?', (mid,)).fetchone()
    if row and row['ts'] < STAMP:
        lo = mid + 1
    else:
        hi = mid
lower_id = lo

rows = conn.execute(
    "SELECT id,session_id,ts,type,tool_use_id,tool_name FROM logs "
    "WHERE id>=? AND type IN ('tool','tool_result') ORDER BY id", (lower_id,)
).fetchall()
sessions = {r['id']: (r['backend_type'] or 'unknown') for r in conn.execute(
    'SELECT id,backend_type FROM sessions')}
calls = []
calls_by_key = defaultdict(list)
results = defaultdict(list)
for row in rows:
    if row['type'] == 'tool':
        calls.append(row)
        if row['tool_use_id']:
            calls_by_key[(row['session_id'], row['tool_use_id'])].append(row)
    elif row['tool_use_id']:
        results[(row['session_id'], row['tool_use_id'])].append(row)

paired = []
missing = []
negative_pairs = []
paired_call_ids = set()
for call in calls:
    key = (call['session_id'], call['tool_use_id'] or '')
    if not call['tool_use_id']:
        missing.append(call)
        continue
    candidates = [r for r in results.get(key, ()) if r['id'] > call['id']]
    if not candidates:
        missing.append(call)
        continue
    result = candidates[0]
    elapsed = (parse_ts(result['ts']) - parse_ts(call['ts'])).total_seconds()
    if elapsed < 0:
        negative_pairs.append({
            'call_id':call['id'],'result_id':result['id'],'session_id':call['session_id'],
            'runtime':sessions.get(call['session_id'],'unknown'),'tool_name':call['tool_name'] or 'unknown',
            'tool_use_id':call['tool_use_id'],'call_ts':call['ts'],'result_ts':result['ts'],
            'duration_s':elapsed,
        })
        continue
    paired.append({
        'call_id': call['id'], 'result_id': result['id'],
        'session_id': call['session_id'], 'runtime': sessions.get(call['session_id'], 'unknown'),
        'tool_name': call['tool_name'] or 'unknown', 'tool_use_id': call['tool_use_id'] or '',
        'call_ts': call['ts'], 'result_ts': result['ts'], 'duration_s': elapsed,
    })
    paired_call_ids.add(call['id'])

windowed = [r for r in paired if parse_ts(r['call_ts']) >= CUTOFF]
missing_window = [r for r in missing if parse_ts(r['ts']) >= CUTOFF]
calls_window = [r for r in calls if parse_ts(r['ts']) >= CUTOFF]

with (OUT / 'tool_calls_7d.csv').open('w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=list(windowed[0]) if windowed else [
        'call_id','result_id','session_id','runtime','tool_name','tool_use_id','call_ts','result_ts','duration_s'])
    writer.writeheader(); writer.writerows(windowed)
with (OUT / 'unpaired_calls_7d.csv').open('w', newline='') as f:
    writer = csv.writer(f); writer.writerow(['call_id','session_id','runtime','tool_name','tool_use_id','call_ts'])
    for r in missing_window:
        writer.writerow([r['id'], r['session_id'], sessions.get(r['session_id'],'unknown'), r['tool_name'], r['tool_use_id'], r['ts']])
negative_window=[r for r in negative_pairs if parse_ts(r['call_ts']) >= CUTOFF]
with (OUT / 'negative_duration_pairs_7d.csv').open('w', newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(negative_window[0]) if negative_window else [
        'call_id','result_id','session_id','runtime','tool_name','tool_use_id','call_ts','result_ts','duration_s'])
    writer.writeheader();writer.writerows(negative_window)

groups = defaultdict(list)
for row in windowed:
    groups[(row['tool_name'], row['runtime'])].append(row['duration_s'])
turns = conn.execute(
    "SELECT runtime,COUNT(*) AS n,SUM(turn_duration_ms) AS ms,"
    "SUM(tool_duration_sum_ms) AS tool_ms, SUM(tool_union_duration_ms) AS tool_union_ms,"
    "SUM(tool_intervals_missing) AS missing_intervals "
    "FROM turn_usage WHERE ts>=? AND turn_duration_ms IS NOT NULL GROUP BY runtime",
    (STAMP,)
).fetchall()
turn_totals = {r['runtime']: {'count':r['n'],'turn_seconds':(r['ms'] or 0)/1000,
                               'tool_duration_sum_seconds':(r['tool_ms'] or 0)/1000,
                               'tool_union_seconds':(r['tool_union_ms'] or 0)/1000,
                               'missing_tool_intervals':r['missing_intervals'] or 0}
               for r in turns}
summary = []
all_turn_seconds = sum(v['turn_seconds'] for v in turn_totals.values())
for (tool, runtime), vals in sorted(groups.items()):
    vals.sort()
    import math
    def pct(p): return vals[max(0, math.ceil(len(vals)*p)-1)]
    total = sum(vals)
    summary.append({'tool_name':tool,'runtime':runtime,'count':len(vals),
                    'p50_s':pct(.50),'p90_s':pct(.90),'p99_s':pct(.99),'sum_s':total,
                    'share_of_all_turn_seconds_pct':100*total/all_turn_seconds if all_turn_seconds else None})

with (OUT / 'tool_group_summary_7d.csv').open('w', newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(summary[0]) if summary else [])
    writer.writeheader(); writer.writerows(summary)
with (OUT / 'unpaired_by_tool_runtime_7d.csv').open('w', newline='') as f:
    writer=csv.writer(f); writer.writerow(['tool_name','runtime','unpaired_calls'])
    missing_counts=Counter((r['tool_name'] or 'unknown', sessions.get(r['session_id'],'unknown')) for r in missing_window)
    for (tool,runtime),n in sorted(missing_counts.items(),key=lambda x:(-x[1],x[0])):
        writer.writerow([tool,runtime,n])

report = {
    'db':str(DB),'cutoff_utc':STAMP,'snapshot_max_id':max_id,'lower_id':lower_id,
    'metadata_rows_scanned':len(rows),'calls_in_window':len(calls_window),
    'calls_by_runtime':dict(Counter(sessions.get(r['session_id'],'unknown') for r in calls_window)),
    'paired_in_window':len(windowed),
    'unpaired_calls_in_window':len(missing_window),
    'negative_duration_pairs_in_window':len(negative_window),
    'tool_result_rows_without_matching_call_in_window':sum(1 for r in rows if r['type']=='tool_result' and r['tool_use_id'] and parse_ts(r['ts']) >= CUTOFF and not any(c['id'] < r['id'] for c in calls_by_key.get((r['session_id'],r['tool_use_id']),()))),
    'total_paired_tool_seconds':sum(r['duration_s'] for r in windowed),
    'turn_usage_totals_by_runtime':turn_totals,
    'turn_wall_seconds_sum':sum(v['turn_seconds'] for v in turn_totals.values()),
    'tool_seconds_as_turn_time_share':sum(r['duration_s'] for r in windowed)/sum(v['turn_seconds'] for v in turn_totals.values()) if turn_totals else None,
    'groups':summary,
}
(OUT / 'tool_summary_7d.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('groups','turn_ends')},indent=2))
print('GROUPS')
for r in summary: print(json.dumps(r,ensure_ascii=False))
conn.rollback(); conn.close()
