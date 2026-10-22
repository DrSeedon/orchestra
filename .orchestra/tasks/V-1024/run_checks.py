"""Offline test entrypoint for this copy, where uv is unavailable."""
import os
from pathlib import Path
import resource
import sys

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / '.orchestra/tasks/V-1024'
(ARTIFACTS / 'tmp').mkdir(exist_ok=True)
os.environ['TMPDIR'] = str(ARTIFACTS / 'tmp')
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ.pop('NOTIFY_SOCKET', None)
os.nice(15)
resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
import app
import pytest
print(f'Imported app: {Path(app.__file__).resolve().relative_to(ROOT)}', flush=True)
raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider', *sys.argv[1:]]))
