import asyncio
import sys
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_managed_home_lock_serializes_another_process(tmp_path):
    import app.backend_codex as module

    home = tmp_path / "managed-root" / "same-home"
    acquired = tmp_path / "child-acquired"
    script = """
import asyncio
import sys
from pathlib import Path
from app.backend_codex import _managed_home_lock

async def main():
    print("READY", flush=True)
    async with _managed_home_lock(Path(sys.argv[1])):
        Path(sys.argv[2]).write_text("acquired")

asyncio.run(main())
"""
    process = None
    try:
        async with module._managed_home_lock(home):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                script,
                str(home),
                str(acquired),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(Path(__file__).parents[1]),
            )
            assert await asyncio.wait_for(process.stdout.readline(), timeout=5) == b"READY\n"
            await asyncio.sleep(0.05)
            assert not acquired.exists()
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
        assert process.returncode == 0, (stdout, stderr)
        assert acquired.read_text() == "acquired"
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()


@pytest.mark.asyncio
async def test_same_managed_home_connect_is_single_flight_and_repeatable(
    monkeypatch, tmp_path,
):
    import app.backend_codex as module

    root = tmp_path / "managed-root"
    base = tmp_path / "base"
    base.mkdir()
    monkeypatch.setattr(module, "_CODEX_HOME_ROOT", root)
    monkeypatch.setattr(module, "_base_codex_home", lambda: base)
    session_id = "same-managed-home"
    home = root / session_id
    home.mkdir(parents=True)
    active = 0
    max_active = 0

    async def connect_unlocked(_self):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        try:
            await asyncio.sleep(0)
        finally:
            active -= 1

    monkeypatch.setattr(module.CodexBackend, "_connect_unlocked", connect_unlocked)

    for _ in range(10):
        backends = [
            module.CodexBackend(
                model="gpt-5.6-sol",
                cwd=str(tmp_path),
                mcp_servers={"orchestra": {
                    "command": "python",
                    "env": {"ORCHESTRA_SESSION_ID": session_id},
                }},
            )
            for _ in range(2)
        ]
        await asyncio.gather(*(backend.connect() for backend in backends))

    assert max_active == 1


@pytest.mark.asyncio
async def test_cancelled_managed_home_connect_releases_single_flight_waiter(
    monkeypatch, tmp_path,
):
    import app.backend_codex as module

    root = tmp_path / "managed-root"
    base = tmp_path / "base"
    base.mkdir()
    monkeypatch.setattr(module, "_CODEX_HOME_ROOT", root)
    monkeypatch.setattr(module, "_base_codex_home", lambda: base)
    session_id = "cancelled-managed-home"
    home = root / session_id
    home.mkdir(parents=True)
    first_started = asyncio.Event()
    never = asyncio.Event()
    calls = 0
    active = 0
    max_active = 0

    async def connect_unlocked(_self):
        nonlocal calls, active, max_active
        calls += 1
        active += 1
        max_active = max(max_active, active)
        try:
            if calls == 1:
                first_started.set()
                await never.wait()
        finally:
            active -= 1

    monkeypatch.setattr(module.CodexBackend, "_connect_unlocked", connect_unlocked)

    def backend():
        return module.CodexBackend(
            model="gpt-5.6-sol",
            cwd=str(tmp_path),
            mcp_servers={"orchestra": {
                "command": "python",
                "env": {"ORCHESTRA_SESSION_ID": session_id},
            }},
        )

    owner = asyncio.create_task(backend().connect())
    await first_started.wait()
    waiter = asyncio.create_task(backend().connect())
    await asyncio.sleep(0)
    owner.cancel()
    await asyncio.gather(owner, return_exceptions=True)
    await asyncio.wait_for(waiter, timeout=1)

    assert calls == 2
    assert max_active == 1
