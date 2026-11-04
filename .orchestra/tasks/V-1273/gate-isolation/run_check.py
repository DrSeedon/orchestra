# sanitized-publication-copy
# Earlier private originals: private/tasks/V-1273/originals/ (root-held; not accessed).
"""Offline verification without inherited bytecode suppression; sanitize before writing."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
DEST = Path(__file__).resolve().parent
mode = sys.argv[1]
env = dict(os.environ)
env.pop('PYTHONDONTWRITEBYTECODE', None)
env['TMPDIR'] = str(DEST / 'tmp')

def sanitize(value):
    value = value.replace(str(DEST / 'tmp'), '<task-tmp>')
    value = value.replace(str(ROOT), '<workspace>')
    value = value.replace('pytest-of-' + ROOT.parts[2], 'pytest-of-<account>')
    value = re.sub(r'/usr/lib/python[\d.]+', '<python-stdlib>', value)
    return value.replace('/usr/bin/python3', '<python-bin>/python3')

if mode == 'mapped':
    from app.merge_test_gate import select_tests, pytest_argv
    selected = select_tests(['app/hub_workspace.py', 'tests/test_hub_untracked_delete_v1273.py', 'CHANGELOG.md'], worktree=str(ROOT))
    argv = pytest_argv(selected, orchestra_project=True, rootdir=str(ROOT), inifile=str(ROOT / 'pyproject.toml'))
    command = ['uv', 'run', '--frozen', 'python', *argv[1:]]
elif mode == 'mutation':
    command = ['uv', 'run', '--frozen', 'python', '.orchestra/tasks/V-1273/mutate.py']
elif mode == 'fixture-mutation':
    command = ['uv', 'run', '--frozen', 'python', '.orchestra/tasks/V-1273/gate-isolation/fixture_mutation.py']
else:
    command = ['uv', 'run', '--frozen', 'python', '-m', 'pytest',
               'tests/test_hub_untracked_delete_v1273.py::test_two_imports_after_scanner_guard_commit_survivors',
               '-q', '--timeout=120', '--timeout-method=signal']
try:
    result = subprocess.run(command, cwd=ROOT, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=480)
    output, code = result.stdout, result.returncode
except subprocess.TimeoutExpired as exc:
    output = exc.stdout or b''
    if isinstance(output, bytes):
        output = output.decode('utf-8', 'replace')
    code = 124
header = ('# sanitized-publication-copy\n'
          '# Prior private originals: private/tasks/V-1273/originals/ (root-held; not accessed).\n'
          '# New run: paths normalized in memory; no unsanitized log persisted.\n'
          '# PYTHONDONTWRITEBYTECODE absent in test subprocess environment.\n')
(DEST / (mode + '.txt')).write_text(header + sanitize(output))
(DEST / (mode + '-command.json')).write_text(json.dumps({
    'sanitized-publication-copy': True, 'argv': [sanitize(p) for p in command],
    'PYTHONDONTWRITEBYTECODE': 'absent', 'exit_code': code,
}, ensure_ascii=False, indent=2) + '\n')
print(sanitize(output[-7000:]))
print('EXIT_CODE:', code)
raise SystemExit(code)
