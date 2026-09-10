"""Real kernel fd accounting, isolated from the pytest runner and live service."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("scenario", ["match", "repeat", "cancel", "recv_cancel_before", "recv_cancel_after", "cleanup", "bash", "managed_spawn_cancel", "bash_spawn_cancel"])
def test_pidfd_lifecycle(scenario, tmp_path):
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), scenario],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "ORCHESTRA_DB_PATH": str(tmp_path / "probe.db"),
             "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        capture_output=True, text=True, timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout, end="")


def pidfds():
    found = {}
    for name in os.listdir('/proc/self/fd'):
        try:
            if os.readlink(f'/proc/self/fd/{name}') == 'anon_inode:[pidfd]':
                found[name] = Path(f'/proc/self/fdinfo/{name}').read_text()
        except FileNotFoundError:
            pass
    return found


async def probe(scenario):
    import asyncio
    import socket
    from unittest.mock import AsyncMock, patch
    import app.bg_jobs as bg
    from app.pidfd_exec import _send_pidfd, pidfd_open_self
    from app.harness.tools import bash

    before = pidfds()
    iterations = 12
    mgr = bg.BgJobManager()
    mgr._trigger = AsyncMock()
    mgr._expire = lambda *_: None

    for _ in range(iterations):
        if scenario in {'managed_spawn_cancel', 'bash_spawn_cancel'}:
            spawned = asyncio.Event()
            release = asyncio.Event()
            original_spawn = bg._spawn_bg_process
            async def delayed_spawn(*args, **kwargs):
                proc = await original_spawn(*args, **kwargs)
                await proc.communicate()
                spawned.set()
                await release.wait()
                return proc
            with patch.object(bg, '_spawn_bg_process', delayed_spawn):
                coro = (bash('true', os.getcwd()) if scenario == 'bash_spawn_cancel'
                        else mgr._spawn_managed_process('probe', 'true', shell=True))
                task = asyncio.create_task(coro)
                await spawned.wait()
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                release.set()
                # Drain this isolated process, including deferred ownership cleanup.
                pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
                await asyncio.gather(*pending)
                assert not mgr._procs
        elif scenario == 'match':
            await mgr._run_command_watch('probe', 'printf match', 'match', 0, '', '', '', 5)
            assert not mgr._procs
        elif scenario == 'repeat':
            # End each non-matching watch at its between-command sleep.
            real_sleep = asyncio.sleep
            async def cancel_at_interval(delay):
                if delay == 99:
                    raise asyncio.CancelledError
                await real_sleep(delay)
            with patch.object(bg.asyncio, 'sleep', cancel_at_interval):
                await mgr._run_command_watch('probe', 'true', 'no-match', 99, '', '', '', 5)
        elif scenario == 'cancel':
            spawned = asyncio.Event()
            original = mgr._spawn_managed_process
            processes = []
            async def spawn(*args, **kwargs):
                proc = await original(*args, **kwargs)
                processes.append(proc)
                spawned.set()
                return proc
            with patch.object(mgr, '_spawn_managed_process', spawn):
                task = asyncio.create_task(mgr._run_command_watch(
                    'probe', 'exec sleep 20', 'match', 0, '', '', '', 30))
                await spawned.wait()
                task.cancel()
                await task
            # Reap leaked children independently, without closing the fd under test.
            proc = processes[0]
            if proc.returncode is None:
                proc.kill()
            await proc.communicate()
        elif scenario.startswith('recv_cancel_'):
            parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            source = pidfd_open_self()
            _send_pidfd(child, source)
            os.close(source)
            loop = asyncio.get_running_loop()
            original = loop.add_reader
            def add_reader(fd, callback, *args):
                def ready():
                    if scenario == 'recv_cancel_before':
                        task.cancel()
                    callback(*args)
                    if scenario == 'recv_cancel_after':
                        task.cancel()
                original(fd, ready)
            try:
                with patch.object(loop, 'add_reader', add_reader):
                    task = asyncio.create_task(bg._recv_pidfd(parent))
                    with pytest.raises(asyncio.CancelledError):
                        await task
            finally:
                parent.close()
                child.close()
        elif scenario == 'cleanup':
            proc = await bg._spawn_bg_process('exec sleep 20', shell=True)
            first = asyncio.create_task(bg._kill_proc(proc))
            await asyncio.sleep(0)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            await bg._kill_proc(proc)
            await bg._kill_proc(proc)
        elif scenario == 'bash':
            assert await bash('printf probe', os.getcwd()) == 'exit_code=0\nprobe'
    after = pidfds()
    print(f'{scenario}: N={iterations} before={len(before)} after={len(after)} delta={len(after)-len(before)}', flush=True)
    assert after == before, after


if __name__ == '__main__':
    import asyncio
    print(f'watcher={type(asyncio.get_child_watcher()).__name__}', flush=True)
    asyncio.run(probe(sys.argv[1]))
