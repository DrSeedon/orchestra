"""Independent checks of frozen numerical evidence, not production regression tests."""
from pathlib import Path
import gzip,hashlib,json,math,re
p=Path(__file__).resolve().parent
raw=gzip.open(p/'telemetry.json.gz','rb').read();j=json.loads(raw)
m=json.loads((p/'measurements.json').read_text());a=json.loads((p/'analysis.json').read_text())
assert hashlib.sha256(raw).hexdigest()==m['sha256']
t=[t for t in j['turns'] if t['runtime']=='claude' and '2026-09-01T07:00'<=t['ts']<'2026-09-08T07:00']
assert len(t)==1540
cost=sum((5*r['input_tokens']+.5*r['cache_read_tokens']+10*r['cache_create_tokens']+25*r['output_tokens'])/1e6 for r in t)
assert math.isclose(cost,3508.4439265)
assert [d['from_pct']-d['to_pct'] for d in a['claude_weeks'][-1]['drops']]==[16,66]
assert a['claude_weeks'][-1]['positive_pp']==178
assert all(not r['drops'] and r['positive_pp']==100 for r in a['claude_weeks'][:3])
s=json.loads((p/'site.json').read_text());points={x['id']:x for x in s['points']}
for ident,value in [('claude_max_20x::claude-opus-5',10715.25),('claude_max_20x::claude-fable-5',1648.5105),('chatgpt_pro_20x::gpt-5.6-sol',6726.72)]:
 x=points[ident];assert math.isclose(x['monthly_tokens']*x['list_blended_usd_per_mtok']/1e6,value)
assert s['conventions']['monthWeeks']==4
assert not any('astra' in x['model'].lower() for x in s['points'])
assert all('opus' not in r['provider_usage'].lower() for r in j['snapshots'])
for file in [p/'research.md',p.parents[1]/'kb/models-and-quotas.md']:
 for target in re.findall(r'\]\(([^)]+)\)',file.read_text()):
  if '://' not in target:assert (file.parent/target.split('#')[0]).exists(),target
print('PASS: frozen SHA256, 1540 turns, API sum, two internal drops, three monotonic cycles, site monthly arithmetic, absent Astra/Opus rows, local report and KB links.')
