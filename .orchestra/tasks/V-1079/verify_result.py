"""Read-only scope, source identity and publication-shape checks for V-1079."""
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
TASK = ROOT / '.orchestra/tasks/V-1079'
sys.path.insert(0, str(ROOT))
import tests.conftest  # Required before any application import in standalone probes.
import app
from app.backend_codex import CodexBackend
from app.publication_secrets import HUB_SECRET_SHAPES

print('APP_IMPORT=' + str(Path(app.__file__).resolve()))
print('BACKEND_IMPORT=' + str(Path(sys.modules[CodexBackend.__module__].__file__).resolve()))
print('PYTHON=' + sys.executable)
original = json.loads((ROOT / '.orchestra/tasks/V-1076/source-baseline.json').read_text())
changes = []
missing = []
for name, expected in original.items():
    path = ROOT / name
    if not path.exists():
        missing.append(name)
    elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        changes.append(name)
print('CHANGED_V1076_BASELINE_FILES=' + json.dumps(changes))
print('MISSING_V1076_BASELINE_FILES=' + json.dumps(missing))
expected_changes = {'app/backend_codex.py', 'app/session.py', 'app/session_hibernate.py',
                    'tests/test_backend_codex.py', 'CHANGELOG.md'}
# V-1076 itself is historical evidence and is not rewritten by this task.
inherited_changes = {'TODO.md'}  # Supplied copy already includes the newer V-1077 note.
assert set(changes) == expected_changes | inherited_changes and not missing
print('PRESERVED_NEWER_INPUT_FILES=' + json.dumps(sorted(inherited_changes)))

snapshots = {name: (TASK / (name + '.before.py')).read_bytes()
             for name in ('backend_codex', 'session', 'session_hibernate')}
for name, content in snapshots.items():
    assert hashlib.sha256(content).hexdigest() == original['app/' + name + '.py']
    after = (ROOT / 'app' / (name + '.py')).read_text()
    diff = ''.join(difflib.unified_diff(content.decode().splitlines(keepends=True),
                                       after.splitlines(keepends=True),
                                       fromfile='supplied/app/' + name + '.py',
                                       tofile='app/' + name + '.py'))
    (TASK / (name + '.diff')).write_text(diff)

# Scan the exact files that will be returned, not any host secret inventory.
spec = importlib.util.spec_from_file_location('task_secret_scan', ROOT / 'scripts/secret_scan.py')
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)
paths = [ROOT / name for name in sorted(expected_changes)] + [ROOT / 'tests/test_codex_compact_state.py']
paths += [path for path in sorted(TASK.rglob('*')) if path.is_file()
          and not any(part in ('tmp', '__pycache__', 'private-verbatim') for part in path.relative_to(TASK).parts)]
findings = []
for path in paths:
    content = path.read_text()
    findings.extend(scanner.scan_text(content, str(path.relative_to(ROOT))))
    for label, pattern in HUB_SECRET_SHAPES:
        for match in pattern.finditer(content):
            findings.append(f'{path.relative_to(ROOT)}:{content.count(chr(10), 0, match.start()) + 1}: {label}')
print('SHAPE_SCANNED_FILES=' + str(len(paths)))
print('SHAPE_FINDINGS=' + json.dumps(findings))
assert not findings

manifest_paths = [ROOT / name for name in sorted(expected_changes)] + [ROOT / 'tests/test_codex_compact_state.py']
manifest = {'supplied_source_sha256': {name: hashlib.sha256(value).hexdigest() for name, value in snapshots.items()},
            'review_base_backend_sha256': hashlib.sha256(
                (TASK / 'backend_codex.preack-review.before.py').read_bytes()).hexdigest(),
            'preserved_input_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                       for name in inherited_changes},
            'result_sha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in manifest_paths},
            'historical_evidence_sha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                           for path in sorted((ROOT / '.orchestra/tasks/V-1076').iterdir())
                                           if path.is_file()}}
(TASK / 'source-manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
print('SOURCE_MANIFEST=source-manifest.json')
print('CLAUDE_LINK_PROVIDED=' + str((ROOT / 'CLAUDE.md').is_symlink()))
