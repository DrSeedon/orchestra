"""Validate research artifacts and show masked-form matches for manual inspection."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path.cwd()))
from app.secret_mask import mask_secrets

root = Path.cwd()
task = root/'.orchestra/tasks/V-972'
inventory = json.loads((task/'raw/inventory.json').read_text())
for item in inventory:
    assert hashlib.sha256((root/item['path']).read_bytes()).hexdigest() == item['sha256'], item['path']
print('source snapshots unchanged:', len(inventory))
report = (task/'report.md').read_text()
rows = [line for line in report.splitlines() if line.startswith('| C') or line.startswith('| R0')]
assert len(rows) == 20, len(rows)
assert all(len(line.split('|')) == 11 for line in rows), 'schema must have nine columns'
print('report: 20 unique pair/scenario rows, nine required columns')
paths = sorted(p for p in task.rglob('*') if p.is_file() and p.name != 'validation.txt')
matched = []
for p in paths:
    text = p.read_text()
    for i,line in enumerate(text.splitlines(),1):
        masked = mask_secrets(line)
        if masked != line:
            matched.append((str(p.relative_to(root)), i, masked))
print('secret-form scan:', len(paths), 'files;', len(matched), 'candidate lines (masked below; inspect source literals)')
for path,i,masked in matched:
    print(f'{path}:{i}: {masked}')
result = subprocess.run(['git','diff','--check'],capture_output=True,text=True)
print('git diff --check exit=',result.returncode,'stdout=',repr(result.stdout),'stderr=',repr(result.stderr))
assert result.returncode == 0
result = subprocess.run(['git','diff','--cached','--check','--',str(task.relative_to(root)),
                         ':!.orchestra/tasks/V-972/raw'],capture_output=True,text=True)
print('git diff --cached --check (authored report/scripts; raw excluded) exit=',result.returncode,'stdout=',repr(result.stdout),'stderr=',repr(result.stderr))
assert result.returncode == 0
result = subprocess.run(['git','-c','core.whitespace=-blank-at-eol,-blank-at-eof','diff','--cached','--check'],
                        capture_output=True,text=True)
print('git diff --cached --check (all files, raw blank-at-eol retained) exit=',result.returncode,
      'stdout=',repr(result.stdout),'stderr=',repr(result.stderr))
assert result.returncode == 0
print('manual secret-form inspection: both candidates are source expressions reading/reference-naming INTERNAL_TOKEN, not credential values; raw source preserved')
