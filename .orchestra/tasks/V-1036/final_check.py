import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))
from app.secret_mask import mask_secrets

paths = [
    'app/message_deliveries.py', 'app/initial_deliveries.py', 'app/quota_queue.py',
    'app/mcp_stdio.py', 'app/manager.py', 'app/routes/sessions.py',
    'tests/test_delivery_visible_1036.py', 'tests/test_mcp_delivery_visible_1036.py',
    'tests/test_quota_admission_e2e.py',
]
for path in paths:
    p = Path(path)
    compile(p.read_text(), path, 'exec')
    print('syntax OK', path, hashlib.sha256(p.read_bytes()).hexdigest())

checked = []
for path in Path('.orchestra/tasks/V-1036').glob('*'):
    if path.suffix not in {'.md', '.log', '.py'}:
        continue
    source = path.read_text()
    filtered = mask_secrets(source)
    if filtered != source:
        raise SystemExit(f'Artifact needs secret review: {path}')
    checked.append(str(path))
print(f'Artifact secret filter: {len(checked)} files checked, no secret-shaped values detected.')
