"""Real OS containment, without provider CLIs or the running Orchestra service.

Run inside a disposable `systemd-run --user -p Delegate=yes` unit on Linux.
"""
import asyncio
import fcntl
import os
from pathlib import Path
import signal
import sys
from unittest.mock import AsyncMock

import pytest

from app.runtime_process_group import RuntimeProcessGroup


@pytest.fixture
def group():
    group, reason = RuntimeProcessGroup.create()
    if group is None:
        if os.environ.get('ORCHESTRA_CGROUP_TEST_REQUIRED') == '1':
            pytest.fail(reason)
        pytest.skip(reason)
    return group


@pytest.mark.asyncio
async def test_detached_descendant_is_killed_before_lock_can_be_reused(group, tmp_path):
    lock = tmp_path / 'thread.lock'
    # Wrapper -> native writer -> setsid tool. Writer and tool ignore SIGTERM;
    # the tool keeps inherited stdout open even after its parent has died.
    script = tmp_path / 'writer.py'
    script.write_text('''import fcntl, os, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
lock = open(sys.argv[1], 'w')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
pid = os.fork()
if pid == 0:
    os.setsid()
    print(os.getpid(), flush=True)
    while True: time.sleep(1)
print(os.getpid(), flush=True)
while True: time.sleep(1)
''')
    wrapper = 'import subprocess,sys; subprocess.run([sys.executable,*sys.argv[1:]])'
    proc = await asyncio.create_subprocess_exec(
        *group.command([sys.executable, '-c', wrapper, str(script), str(lock)]),
        stdout=asyncio.subprocess.PIPE,
    )
    try:
        pids = [int(await asyncio.wait_for(proc.stdout.readline(), 5)) for _ in range(2)]
        assert group.populated()
        for pid in [proc.pid, *pids]:
            assert str(group.path).removeprefix('/sys/fs/cgroup') in Path(f'/proc/{pid}/cgroup').read_text()
        with lock.open('r') as handle:
            with pytest.raises(BlockingIOError):
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        await group.stop(proc, 0.3)
        assert not group.path.exists()
        with lock.open('r') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for pid in pids:
            stat = Path(f'/proc/{pid}/stat')
            assert not stat.exists() or stat.read_text().rpartition(')')[2].split()[0] == 'Z'
    finally:
        if group.path.exists():
            await group.stop(proc, 1)


@pytest.mark.asyncio
async def test_immediate_stop_cannot_leave_late_launcher(group):
    proc = await asyncio.create_subprocess_exec(
        *group.command([sys.executable, '-c', 'import time; time.sleep(60)']),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await group.stop(proc, 1)
    assert proc.returncode is not None
    assert not group.path.exists()


@pytest.mark.asyncio
async def test_failed_launch_never_executes_outside_group(tmp_path):
    group = RuntimeProcessGroup(tmp_path / 'missing-group')
    marker = tmp_path / 'should-not-exist'
    proc = await asyncio.create_subprocess_exec(
        *group.command([sys.executable, '-c', f'open({str(marker)!r}, "w").close()']),
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert await asyncio.wait_for(proc.wait(), 5) != 0
    assert not marker.exists()


@pytest.mark.asyncio
async def test_codex_failed_cleanup_retains_owner_for_retry():
    from app.backend_codex import CodexBackend
    backend = CodexBackend(model='gpt-5.6-sol', cwd='/tmp')
    group = RuntimeProcessGroup(Path('/unused-test-group'))
    group.stop = AsyncMock(side_effect=PermissionError('denied'))
    backend._process_group = group
    with pytest.raises(PermissionError, match='denied'):
        await backend.disconnect()
    assert backend.has_owned_processes
    assert backend._process_group is group
    group.stop = AsyncMock()
    await backend.disconnect()
    assert not backend.has_owned_processes


@pytest.mark.asyncio
async def test_codex_hibernate_wake_resumes_same_thread_over_real_stdio(group, tmp_path, monkeypatch):
    from app.backend_codex import CodexBackend
    # The fixture proves delegation is present; connect creates its own group.
    group.path.rmdir()
    native = tmp_path / 'fake_app_server.py'
    calls = tmp_path / 'requests.jsonl'
    native.write_text('''import json, sys
from pathlib import Path
for line in sys.stdin:
    msg = json.loads(line)
    with Path(sys.argv[1]).open('a') as out: out.write(json.dumps(msg) + '\\n')
    if 'id' not in msg: continue
    result = {}
    if msg['method'] == 'thread/resume':
        result = {'thread': {'id': msg['params']['threadId']}}
    print(json.dumps({'id': msg['id'], 'result': result}), flush=True)
''')
    backend = CodexBackend(model='gpt-5.6-sol', cwd=str(tmp_path), resume_thread_id='same-thread')
    monkeypatch.setattr(backend, '_codex_command', lambda: [sys.executable, str(native), str(calls)])
    old_pid = None
    for _ in range(2):
        try:
            await asyncio.wait_for(backend.connect(), 5)
            assert backend.hibernate_safe
            assert backend.session_id == 'same-thread'
            assert backend.pid != old_pid
            old_pid = backend.pid
            path = backend._process_group.path
        finally:
            await asyncio.wait_for(backend.disconnect(), 5)
        assert not path.exists()
        assert not backend.has_owned_processes
    import json
    resumes = [json.loads(line) for line in calls.read_text().splitlines()
               if json.loads(line)['method'] == 'thread/resume']
    assert len(resumes) == 2
    assert all(call['params']['threadId'] == 'same-thread' for call in resumes)
