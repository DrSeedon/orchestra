"""Local publication-boundary checks for V-1028; never reads credentials or a DB."""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, '.')
import app
from app.secret_mask import mask_secrets

TASK = Path('.orchestra/tasks/V-1028')
FILES = [
    'app/session.py', 'app/session_turns.py', 'app/message_deliveries.py',
    'app/hub_outbox.py', 'app/report_holds.py', 'app/turn_signals.py',
    'app/quota_queue.py', 'app/manager.py', 'app/harness/loop.py',
    'app/static/js/app.js', 'app/static/js/utils.js', 'app/static/js/i18n.js',
    'tests/test_auto_report_send_result.py', 'tests/test_v1028_auto_report.py',
    'tests/test_v1028_report_holds.py', 'tests/test_v1028_report_hold_frontend.py',
    'tests/test_v1028_hub_outbox_report.py',
]
assert Path(app.__file__).resolve() == (Path.cwd() / 'app/__init__.py').resolve()
checked = []
for name in FILES:
    path = Path(name)
    text = path.read_text()
    if path.suffix == '.py':
        ast.parse(text, filename=name)
    elif path.suffix == '.js':
        subprocess.run([shutil.which('node'), '--check', name], check=True, capture_output=True)
    checked.append({'file': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
assert 'on_parent_report=reported' in Path('app/session.py').read_text()
assert 'if target and target in {parent, s.parent_id}:' in Path('app/session_turns.py').read_text()
assert "AND 0 AND last_error" not in Path('app/report_holds.py').read_text()
assert 'if (s.report_quota_hold) {' in Path('app/static/js/app.js').read_text()
changed_artifacts = []
for path in sorted(TASK.glob('*')):
    if not path.is_file() or path.suffix not in {'.log', '.patch', '.md', '.json'}:
        continue
    original = path.read_text()
    sanitized = mask_secrets(original).replace(str(Path.cwd()), '.')
    if sanitized != original:
        path.write_text(sanitized)
        changed_artifacts.append(str(path))
result = {'imported_app': 'app/__init__.py', 'syntax_and_restored_source_checks': 'passed',
          'publication_filter': 'app.secret_mask.mask_secrets',
          'normalized_or_masked_artifacts': changed_artifacts, 'verified_files': checked}
(TASK / 'verified-files.json').write_text(json.dumps(result, indent=2) + '\n')
print('Verified import identity, Python/JS syntax, restored mutation sites, and publication artifacts.')
