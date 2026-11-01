"""Prepare public synthetic observations and verify research artifacts only."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

TASK=Path(__file__).resolve().parent
ROOT=TASK.parents[2]
sys.path.insert(0,str(ROOT))
from scripts.secret_scan import scan_text

truth=json.loads((TASK/'ground-truth.json').read_text())
observations=[]
for number in (1,5,9):
    sample=truth[number-1]
    for variant in ('original','full','compact','half'):
        accepted=[f['text'] for f in sample['fields']]
        if variant in ('compact','half'):
            accepted[2]=None
        observations.append({'number':number,'variant':variant,'selected_fields':['Build','Date','ID'],
            'accepted_readings':accepted,'correct':sum(x is not None for x in accepted),'incorrect':0,
            'unread':sum(x is None for x in accepted),
            'method':'nonblind semantic inspection by current researcher; no separate model judge; null=abstention'})
(TASK/'semantic-observations.json').write_text(json.dumps(observations,indent=2))

excerpts={
    'app/tg_bridge.py':[(264,295),(429,457),(614,633),(4405,4428)],
    'app/routes/tg.py':[(285,315)],
    'app/static/js/chat.js':[(800,841),(1090,1092),(3669,3677),(3964,4003)],
    'app/static/js/app.js':[(2144,2177)],
    'app/backend_claude.py':[(1361,1366),(1724,1759),(1791,1805),(1977,2020)],
    'app/backend_codex.py':[(782,825),(1345,1354),(1939,1988),(2023,2036)],
    'app/backend_hub.py':[(33,39),(484,519),(636,646),(856,886)],
    'app/hub_workspace.py':[(352,410)],
    'app/harness/images.py':[(1,59)],
    'app/harness/llm.py':[(397,465),(478,485),(654,692)],
    'app/harness/tools.py':[(248,252),(459,459),(483,489)],
    'app/harness/oneshot.py':[(18,79)],
    'app/harness/mcp.py':[(323,343)],
    'app/harness/loop.py':[(516,523)],
    'app/mcp_stdio.py':[(4484,4556),(4617,4629)],
    'app/backend_harness.py':[(159,162),(391,419),(430,488)],
    'app/routes/system.py':[(281,307),(324,365)],
    'app/models.py':[(59,168),(536,545)],
    'app/model_catalog.py':[(35,84)],
    'app/usage_contract.py':[(28,53)],
    'app/hub_image.py':[(191,214),(264,290)],
    'app/hub_image_mcp.py':[(19,31)],
}
lines=[]
for filename,ranges in excerpts.items():
    source=(ROOT/filename).read_text().splitlines()
    for start,end in ranges:
        lines.append(f'\n$ source excerpt {filename}:{start}-{end}')
        lines.extend(f'{i}: {source[i-1]}' for i in range(start,min(len(source),end)+1))
(TASK/'logs/code-excerpts.txt').write_text('\n'.join(lines)+'\n')

# Only remove task-owned setup environments/caches and redundant public HTML.
deps=TASK/'deps'
if deps.exists():
    print('isolated_dependency_bytes',sum(p.stat().st_size for p in deps.rglob('*') if p.is_file()))
    shutil.rmtree(deps)
if (TASK/'tmp').exists():
    shutil.rmtree(TASK/'tmp')
for filename in ('openai-vision.html','openai-vision-text.txt'):
    (TASK/'sources'/filename).unlink(missing_ok=True)
for directory in TASK.rglob('__pycache__'):
    if directory.is_dir(): shutil.rmtree(directory)

assert not (TASK/'deps').exists()
for row in json.loads((TASK/'code-manifest.json').read_text()):
    assert hashlib.sha256((ROOT/row['file']).read_bytes()).hexdigest()==row['sha256'],row['file']
print('PASS: all 12 baseline source hashes unchanged')
for row in json.loads((TASK/'sample-manifest.json').read_text()):
    assert hashlib.sha256((TASK/'samples'/row['file']).read_bytes()).hexdigest()==row['sha256'],row['file']
print('PASS: all sample hashes match final generator artifacts')

result=json.loads((TASK/'rapid-results.json').read_text())
assert result['correct']==12 and result['N_unique']==12
assert all(row['correct'] and all(v==row['expected_label'] for v in row['labels']) for row in result['cases'])
assert all(row['batch_crops_identical'] for row in result['cases'])
print('PASS: final rotation correction sign and identical center crops checked')
assert '24 passed' in (TASK/'logs/pytest-stdout.txt').read_text()
print('PASS: 24 existing offline vision tests passed; see preserved pytest stdout')
issues=[]; count=0
for path in sorted(TASK.rglob('*')):
    if not path.is_file() or path.suffix.lower() in {'.png','.jpg','.webp','.pyc'} or path.name=='final-audit.txt':continue
    count+=1
    issues.extend(scan_text(path.read_text(errors='replace'),str(path.relative_to(ROOT))))
assert not issues,issues
print('PASS: canonical scripts.secret_scan.scan_text provider-shape filter:',count,'text artifacts; no credential stores read')

for document in (TASK/'report.md',TASK/'method.md'):
    text=document.read_text()
    for link in re.findall(r'\]\(([^)]+)\)',text):
        if '://' in link or link.startswith('#'):continue
        target=document.parent/link.split('#',1)[0]
        if target.name=='final-audit.txt':continue  # stdout opened by the caller
        assert target.exists(),link
print('PASS: relative artifact links resolve')
manifest=[]
for path in sorted(TASK.rglob('*')):
    if path.is_file() and path.name not in ('artifact-manifest.json','final-audit.txt'):
        manifest.append({'file':str(path.relative_to(TASK)),'bytes':path.stat().st_size,
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
(TASK/'artifact-manifest.json').write_text(json.dumps({'checked_at_utc':datetime.now(timezone.utc).isoformat(),'files':manifest},indent=2))
print('research_artifact_files',len(manifest),'bytes',sum(r['bytes'] for r in manifest))
print('RESEARCH DONE; product/runtime/paid inference untouched; native usage and real-workload quality unverified')
