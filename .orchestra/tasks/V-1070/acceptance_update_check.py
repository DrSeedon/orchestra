"""Verify only the two requested research amendments and refresh artifact hashes."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

TASK = Path(__file__).resolve().parent
ROOT = TASK.parents[2]
sys.path.insert(0, str(ROOT))
from scripts.secret_scan import scan_text


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = []
    old_path = TASK / 'artifact-manifest.json'
    baseline_sha = sha(old_path)
    baseline = json.loads(old_path.read_text())
    changed = []
    for row in baseline['files']:
        path = TASK / row['file']
        assert path.is_file(), row['file']
        if sha(path) != row['sha256'] or path.stat().st_size != row['bytes']:
            changed.append(row['file'])
    assert set(changed) <= {'report.md', 'method.md'}, changed
    output.append('baseline_artifact_manifest_sha256 ' + baseline_sha)
    output.append('PASS: prior existing artifacts unchanged except report.md/method.md: ' + ', '.join(changed))
    output.append('PASS: raw runner/boundary logs, numeric results, samples and prior experiment stdout unchanged')
    for row in json.loads((TASK / 'code-manifest.json').read_text()):
        assert sha(ROOT / row['file']) == row['sha256'], row['file']
    output.append('PASS: baseline product source hashes unchanged')

    licenses = json.loads((TASK / 'sources/licenses/manifest.json').read_text())
    for row in licenses['sources']:
        if 'file' in row:
            path = TASK / 'sources/licenses' / row['file']
            assert sha(path) == row['sha256'] and path.stat().st_size == row['bytes']
    metadata = json.loads((TASK / 'sources/licenses/rapid-orientation-0.0.11-pypi.json').read_text())
    assert metadata['info']['version'] == '0.0.11'
    assert metadata['info']['license'] == 'Apache-2.0'
    assert 'all four retained versioned Rapid sources match wheel bytes' in (TASK / 'logs/license-sources-stdout.txt').read_text()
    for filename in ['rapid-0.0.11-LICENSE', 'RapidOrientation-LICENSE', 'PaddleOCR-LICENSE', 'Tesseract-LICENSE']:
        text = (TASK / 'sources/licenses' / filename).read_text()
        assert 'Apache License' in text and 'Version 2.0, January 2004' in text
    output.append('PASS: exact Rapid version, copied-source provenance, complete license snapshots and hashes checked')

    report = (TASK / 'report.md').read_text()
    hub_row = next(line for line in report.splitlines() if line.startswith('| Hub Claude'))
    assert 'не гарантию исключения ПД' in hub_row and 'корневые файлы' in hub_row
    assert 'не объявляет документацию API' in report
    for filename in ('report.md', 'method.md', 'sources/THIRD_PARTY_NOTICES.md'):
        document = TASK / filename
        for link in re.findall(r'\]\(([^)]+)\)', document.read_text()):
            if '://' not in link and not link.startswith('#'):
                assert (document.parent / link.split('#', 1)[0]).exists(), (filename, link)
    output.append('PASS: generic hub caveat, code/documentation license separation and relative links checked')

    scanned = 0
    for path in TASK.rglob('*'):
        if path.is_file() and path.suffix.lower() not in {'.png', '.jpg', '.webp', '.pyc'}:
            findings = scan_text(path.read_text(errors='replace'), str(path.relative_to(ROOT)))
            assert not findings, findings
            scanned += 1
    output.append(f'PASS: canonical provider-shape scan of {scanned} text artifacts; no private credential stores accessed')
    output.append('No new inference, installs, vision experiments or product tests; previous 24-test PASS preserved.')
    output.append('RESEARCH DONE: both narrow research amendments verified.')
    transcript = '\n'.join(output) + '\n'
    (TASK / 'logs/acceptance-update-check.txt').write_text(transcript)

    # This log is complete before hashing. Only the self-referential manifest is excluded.
    rows = [{'file': str(path.relative_to(TASK)), 'bytes': path.stat().st_size, 'sha256': sha(path)}
            for path in sorted(TASK.rglob('*')) if path.is_file() and path != old_path]
    old_path.write_text(json.dumps({'checked_at_utc': datetime.now(timezone.utc).isoformat(),
                                    'excluded_self': 'artifact-manifest.json', 'files': rows}, indent=2))
    check = json.loads(old_path.read_text())
    assert {row['file'] for row in check['files']} == {
        str(path.relative_to(TASK)) for path in TASK.rglob('*') if path.is_file() and path != old_path}
    for row in check['files']:
        assert sha(TASK / row['file']) == row['sha256'], row['file']
    print(transcript, end='')
    print('PASS: final artifact manifest covers every retained file except itself:', len(rows), 'files')


if __name__ == '__main__':
    main()
