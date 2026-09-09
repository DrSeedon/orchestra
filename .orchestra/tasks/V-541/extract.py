"""Read only numerical telemetry in one SQLite read transaction; no log/message export."""
import datetime, gzip, hashlib, json, pathlib, sqlite3, subprocess
root=pathlib.Path(__file__).resolve().parent
pid=int(subprocess.check_output(['systemctl','show','orchestra','-p','MainPID','--value']))
env=pathlib.Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
path=next(v.split(b'=',1)[1].decode() for v in env if v.startswith(b'ORCHESTRA_DB_PATH='))
c=sqlite3.connect('file:'+path+'?mode=ro',uri=True); c.row_factory=sqlite3.Row
c.execute('BEGIN')
turns=[dict(r) for r in c.execute("select id,ts,session_id,model,ok,cost_usd,cost_unaccounted,input_tokens,cache_read_tokens,cache_create_tokens,output_tokens,quota_seven_day_pct,quota_five_hour_pct,quota_sampled_at from turn_usage where runtime='claude' order by ts,id")]
ids={s:i for i,s in enumerate(sorted({r['session_id'] for r in turns}))}
for r in turns:r['session_id']=ids[r['session_id']]
snaps=[dict(r) for r in c.execute("select id,ts,five_hour_pct,seven_day_pct,five_hour_resets_at,seven_day_resets_at from usage_snapshots where ts >= '2026-08-03' order by ts,id")]
c.rollback();c.close()
obj={'source':path,'pid':pid,'captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'turns':turns,'snapshots':snaps}
raw=json.dumps(obj,separators=(',',':')).encode()
with gzip.GzipFile(filename=str(root/'telemetry.json.gz'),mode='wb',mtime=0) as f:f.write(raw)
print(json.dumps({'source':path,'pid':pid,'captured_at':obj['captured_at'],'turns':len(turns),'snapshots':len(snaps),'uncompressed_sha256':hashlib.sha256(raw).hexdigest(),'turn_range':[turns[0]['ts'],turns[-1]['ts']],'snapshot_range':[snaps[0]['ts'],snaps[-1]['ts']]} ,indent=2))
