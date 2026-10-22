"""Capture command output in memory and redact local identity before writing logs."""
from pathlib import Path
import subprocess
import sys

from app.secret_mask import mask_secrets

root = Path.cwd()
label, *command = sys.argv[1:]
result = subprocess.run(command, capture_output=True, text=True, errors='replace')
output = result.stdout + result.stderr
output = output.replace(str(root), '.')
output = output.replace(str(Path.home()), '<home>')
if len(root.parts) > 2 and root.parts[1] == 'home':
    output = output.replace('/home/' + root.parts[2], '<hub-home>')
    output = output.replace(root.parts[2], '<hub-user>')
output = mask_secrets(output)
assert str(root) not in output
if len(root.parts) > 2 and root.parts[1] == 'home':
    assert root.parts[2] not in output
Path('.orchestra/tasks/V-1034', label + '.log').write_text(output)
summary = [line for line in output.splitlines() if line.startswith('FAILED ') or ' passed' in line or ' failed' in line or 'ERROR ' in line]
print('\n'.join(summary[-12:]) or f'{label}: exit {result.returncode}')
raise SystemExit(result.returncode)
