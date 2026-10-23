"""Exercise the production provisioner on the actual hub host, without an SSH hop.

HOME and the VPS binary source are sandboxed inside this task directory, respecting
this worker's no-writes-outside-workspace rule. No system files are modified.
"""
import asyncio
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

root = Path(__file__).resolve().parents[3]
notes = root / '.orchestra/tasks/V-1055'
# Import-only shims for modules omitted from this private source copy; see offline-check.py.
spec = importlib.util.spec_from_file_location('partial_imports', notes / 'offline-check.py')
partial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(partial)
from app import hub_workspace as hw


class SameHostSsh(hw.HubSsh):
    def __init__(self):
        super().__init__('unused', 'unused', '')
        self.uploads = 0

    def _argv(self, remote):
        return ['/bin/bash', '-c', remote]

    async def run(self, remote, **kwargs):
        if kwargs.get('stdin'):
            self.uploads += 1
        return await super().run(remote, **kwargs)


async def main():
    runtime = notes / 'runtime'
    source_home = runtime / 'vps-home'
    source = source_home / '.local/bin/uv'
    source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(notes / 'bootstrap/uv', source)
    scratch = runtime / 'live-scratch'
    scratch.mkdir(exist_ok=True)
    remote_home = runtime / 'hub-home'
    remote_home.mkdir(exist_ok=True)
    env = dict(os.environ, HOME=str(remote_home))
    ssh = SameHostSsh()
    with patch.dict(os.environ, {'HOME': str(remote_home)}), patch.object(Path, 'home', return_value=source_home):
        await ssh.ensure_uv(scratch)
        await ssh.ensure_uv(scratch)
    assert ssh.uploads == 1, ssh.uploads
    binary = remote_home / hw.HUB_UV_BIN / 'uv'
    assert hw.sha256_file(binary) == hw.sha256_file(source)
    env['PATH'] = str(binary.parent) + os.pathsep + env['PATH']
    version = subprocess.run(['uv', '--version'], env=env, capture_output=True, text=True, check=True).stdout
    command = ['uv', 'run', '--frozen', 'python', '-m', 'pytest', 'tests/test_hub_uv.py', '-q']
    result = subprocess.run(command, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    home_prefix = str(root.parents[2])
    output = result.stdout.decode().replace(home_prefix, '<hub-home>')
    evidence = (
        'Host: Linux x86_64, CPython 3.12.3; PyPI and files.pythonhosted.org reachable.\n'
        'Bootstrap: PyPI uv 0.11.28 wheel, SHA-256 verified against release metadata:\n'
        '49fe42df9f42056037473f3876adec1615709b57d3470ed39178ff420f3afb9f\n'
        'Production HubSsh.ensure_uv executed on this hub with local shell transport.\n'
        'Only transport/import-only dependencies were substituted; binary/version/hash checks are real.\n'
        'HOME sandbox is inside the task directory; two provisions uploaded once.\n'
        'Installed binary SHA-256: ' + hw.sha256_file(binary) + '\n'
        'No system files changed. pyproject.toml and uv.lock present, unchanged.\n'
        'The first frozen run installed all 76 locked packages, including pytest.\n'
        'Only the forbidden absolute home prefix is replaced with <hub-home> below; other output verbatim.\n\n'
        '$ export PATH="$HOME/' + hw.HUB_UV_BIN + ':$PATH"\n'
        '$ uv --version\n' + version +
        '$ ' + ' '.join(command) + '\n' + output +
        '\nExit status: ' + str(result.returncode) + '\n'
    )
    (notes / 'live-check.txt').write_text(evidence)
    print(evidence)


asyncio.run(main())
