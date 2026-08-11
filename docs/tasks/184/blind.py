import json, pathlib, random, sys
RUNS = pathlib.Path('runs')
key = {}
out = []
random.seed(184)
for cid in [f'C{i}' for i in range(1,8)]:
    files = sorted(RUNS.glob(f'*_{cid}_r*.json'))
    ids = [f'{cid}-{i:02d}' for i in range(1, len(files)+1)]
    random.shuffle(ids)
    for f, bid in zip(files, ids):
        d = json.loads(f.read_text())
        key[bid] = d['tag']
        out.append((bid, d.get('text', 'ERROR: '+str(d.get('error'))[:200])))
pathlib.Path('runs/_key.json').write_text(json.dumps(key, indent=1))
for cid in [f'C{i}' for i in range(1,8)]:
    p = pathlib.Path(f'runs/_blind_{cid}.txt')
    p.write_text('\n\n'.join(f'--- {b} ---\n{t.strip()}' for b, t in out if b.startswith(cid+'-')))
print('ok', len(key))
