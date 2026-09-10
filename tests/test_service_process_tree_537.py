"""Restart/crash a disposable supervisor; prove no old writer or tool survives.

No Orchestra endpoint, production unit, database or provider CLI is used.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

import pytest


@pytest.mark.parametrize('crash', [False, True], ids=['restart', 'supervisor-crash'])
def test_systemd_retires_whole_generation_before_replacement(tmp_path, crash):
    if not shutil.which('systemd-run') or subprocess.run(
        ['systemctl', '--user', 'show-environment'], capture_output=True,
    ).returncode:
        pytest.skip('requires a systemd user manager')
    unit = f'orchestra-test-537-{uuid.uuid4().hex}.service'
    script = tmp_path / 'supervisor.py'
    records = tmp_path / 'generations.jsonl'
    lock = tmp_path / 'thread.lock'
    history = tmp_path / 'history.txt'
    root = Path(__file__).resolve().parents[1]
    script.write_text('''import asyncio, fcntl, json, os, signal, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from app.runtime_process_group import RuntimeProcessGroup
records, lock, history = map(Path, sys.argv[2:5])
if len(sys.argv) > 5:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    handle = lock.open('a')
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    previous = history.read_text() if history.exists() else ''
    history.write_text(previous + 'continued\\n')
    child = os.fork()
    if child == 0:
        os.setsid()
        while True: time.sleep(1)
    print(json.dumps({'writer': os.getpid(), 'tool': child, 'previous': previous}), flush=True)
    while True: time.sleep(1)
async def main():
    group, reason = RuntimeProcessGroup.create()
    if group is None: raise RuntimeError(reason)
    proc = await asyncio.create_subprocess_exec(
        *group.command([sys.executable, __file__, *sys.argv[1:5], 'writer']),
        stdout=asyncio.subprocess.PIPE)
    record = json.loads(await proc.stdout.readline())
    record['supervisor'] = os.getpid()
    record['cgroup'] = str(group.path)
    with records.open('a') as out:
        out.write(json.dumps(record) + '\\n')
        out.flush()
    await asyncio.Event().wait()
asyncio.run(main())
''')
    def run(*args):
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=15)

    def generation(count):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if records.exists():
                rows = records.read_text().splitlines()
                if len(rows) >= count:
                    return json.loads(rows[count - 1])
            time.sleep(0.05)
        status = subprocess.run(['systemctl', '--user', 'status', unit], capture_output=True, text=True)
        pytest.fail(f'No generation {count}: {status.stdout} {status.stderr}')

    try:
        run('systemd-run', '--user', '--quiet', f'--unit={unit}',
            '-p', 'Delegate=yes', '-p', 'KillMode=control-group',
            '-p', 'SendSIGKILL=yes', '-p', 'TimeoutStopSec=1',
            '-p', 'Restart=on-failure', '-p', 'RestartSec=0.1',
            '-p', 'MemoryMax=2G', '-p', 'Nice=15',
            sys.executable, str(script), str(root), str(records), str(lock), str(history))
        old = generation(1)
        if crash:
            run('systemctl', '--user', 'kill', '--kill-whom=main', '--signal=KILL', unit)
        else:
            run('systemctl', '--user', 'restart', unit)
        new = generation(2)
        assert old['supervisor'] != new['supervisor']
        assert old['writer'] != new['writer']
        assert new['previous'] == 'continued\n', 'replacement must read saved history after acquiring the same lock'
        assert f'/{unit}/runtime-' in new['cgroup']
        for key in ('supervisor', 'writer', 'tool'):
            stat = Path(f'/proc/{old[key]}/stat')
            assert not stat.exists() or stat.read_text().rpartition(')')[2].split()[0] == 'Z', key
    finally:
        subprocess.run(['systemctl', '--user', 'stop', unit], capture_output=True, timeout=15)
        subprocess.run(['systemctl', '--user', 'reset-failed', unit], capture_output=True, timeout=15)
