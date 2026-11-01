"""Retain raw stdout privately; publish normalized derivatives with byte hashes."""
import difflib
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
TASK = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / 'tests/conftest.py'))
from app.secret_mask import mask_secrets
from scripts.secret_scan import scan_text

raw_dir = TASK / 'private/raw'
derived = TASK / 'stdout'
derived.mkdir(exist_ok=True)
records = []
for raw_path in sorted(raw_dir.rglob('*')):
    if not raw_path.is_file():
        continue
    relative = raw_path.relative_to(raw_dir)
    if relative.as_posix() == 'finalize.txt':
        continue  # The active stream is finalized by the caller, after exit.
    raw = raw_path.read_bytes()
    normalized = raw.decode().replace(str(ROOT), '/<hub-copy>')
    normalized = re.sub(r'/home/[^\s\'"<>)]*', '/<hub-copy-path>', normalized)
    normalized = mask_secrets(normalized)
    destination = derived / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(normalized)
    records.append({'raw': 'private/raw/' + relative.as_posix(),
                    'published': 'stdout/' + relative.as_posix(),
                    'raw_sha256': hashlib.sha256(raw).hexdigest(),
                    'published_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
                    'normalized': destination.read_bytes() != raw})
(TASK / 'stdout-manifest.json').write_text(json.dumps(records, indent=2) + '\n')

source = (ROOT / 'app/db.py').read_text()
current = source[source.index('def search_logs('):source.index('\ndef get_log_context(')]
baseline = (TASK / 'baseline_search.py').read_text()
(TASK / 'implementation.diff').write_text(''.join(difflib.unified_diff(
    baseline.splitlines(True), current.splitlines(True),
    fromfile='before/app/db.py:search_logs', tofile='after/app/db.py:search_logs')))

# Verify nested ignores with the actual root negations, without a repository commit.
ignore_repo = TASK / 'tmp/ignore-check'
ignore_repo.mkdir(parents=True, exist_ok=True)
subprocess.run(['git', 'init', '-q', str(ignore_repo)], check=True)
(ignore_repo / '.gitignore').write_bytes((ROOT / '.gitignore').read_bytes())
nested = ignore_repo / '.orchestra/tasks/V-1089'
nested.mkdir(parents=True, exist_ok=True)
(nested / '.gitignore').write_bytes((TASK / '.gitignore').read_bytes())
ignored = subprocess.run(['git', '-C', str(ignore_repo), 'check-ignore', '--no-index', '-v',
                         '.orchestra/tasks/V-1089/private/raw/probe.txt',
                         '.orchestra/tasks/V-1089/tmp/a'], check=True, capture_output=True, text=True)
assert len(ignored.stdout.splitlines()) == 2
print(ignored.stdout, end='')

paths = [ROOT / 'app/db.py', ROOT / 'tests/test_log_search_v1089.py', ROOT / 'CHANGELOG.md']
paths.extend(p for p in TASK.rglob('*') if p.is_file()
             and not set(p.relative_to(TASK).parts) & {'private', 'tmp', '__pycache__'})
findings = []
for path in paths:
    body = path.read_text()
    findings.extend(scan_text(body, str(path.relative_to(ROOT))))
    assert str(ROOT) not in body
    if path.is_relative_to(TASK):
        assert not re.search(r'/home/[A-Za-z0-9_.-]+/', body)
assert not findings, '\n'.join(findings)
manifest = [{'path': str(p.relative_to(ROOT)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(paths) if p.name != 'artifact-manifest.json']
(TASK / 'artifact-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('Secret-form scan: clean. Host paths normalized; original stdout bytes retained privately.')
print('Absolute imported app path is retained in private/raw/profile.jsonl; public alias /<hub-copy>/app/__init__.py.')
print('No production data, provider, network API, service or repository remote accessed.')
