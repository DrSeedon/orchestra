"""V-919: a run job survives an Orchestra restart and the next generation adopts it.

Real child processes: the old generation either shuts down gracefully or is SIGKILLed in a
separate interpreter, the way systemd/OOM kill the service while KillMode=process keeps
its children.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    return db_path


@pytest.fixture
def target(db):
    from app.db import save_session
    from app.session import AgentSession

    session = AgentSession(
        id="s-919", name="w919", scope="/scope-919", cwd="/scope-919",
        model="gpt-5.6-luna", system_prompt="t", created_at=datetime.now(timezone.utc),
    )
    save_session(session._to_db_dict())
    sent = []

    class Manager:
        async def ensure_loaded_by_id(self, sid):
            return session

        async def send(self, sid, message, *, provenance):
            sent.append(message.text)

    return session, Manager(), sent


def _process(job_id):
    from app.db import bg_get_job
    return json.loads(bg_get_job(job_id)["config"]).get("_process") or {}


async def _recorded(job_id):
    for _ in range(200):
        if _process(job_id).get("pid"):
            return _process(job_id)
        await asyncio.sleep(0.05)
    pytest.fail("run job did not record its process")


async def _settled(job_id):
    from app.db import bg_get_job
    for _ in range(300):
        if bg_get_job(job_id)["status"] != "active":
            return bg_get_job(job_id)
        await asyncio.sleep(0.05)
    pytest.fail("adopted run job never finished")


def _alive(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _kill(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


@pytest.mark.asyncio
async def test_graceful_restart_leaves_run_alive_and_next_generation_delivers_its_result(
    target, tmp_path,
):
    from app.bg_jobs import BgJobManager

    session, manager, sent = target
    gate = tmp_path / "gate"
    old = BgJobManager()
    old.set_session_manager(manager)
    created = await old.create(
        "run", {"command": f"echo before; while [ ! -e {gate} ]; do sleep 0.05; done; "
                           "echo after-919"},
        "long job", session.id, session.name, session.scope, "w919", timeout_seconds=600,
    )
    pid = (await _recorded(created["id"]))["pid"]
    try:
        await old.shutdown()
        await asyncio.sleep(0.3)
        assert _alive(pid), "shutdown killed the run job"

        new = BgJobManager()
        new.set_session_manager(manager)
        await new.restore_from_db()
        adopter = new._tasks[created["id"]]
        gate.touch()
        row = await _settled(created["id"])
        # The row turns terminal before the adopter's finally reaps the group and unlinks
        # the recovery files, so wait for the adopter itself, not for the DB status.
        done, _pending = await asyncio.wait({adopter}, timeout=30)
        assert done, "adopting task never completed"
        await adopter

        assert row["status"] == "triggered"
        assert len(sent) == 1 and "completed" in sent[0]
        assert "before" in sent[0] and "after-919" in sent[0]
        assert not any("INTERRUPTED" in text for text in sent)
        assert not Path(_process(created["id"])["out"]).exists()
    finally:
        _kill(pid)


_CRASHING_GENERATION = textwrap.dedent("""
    import asyncio, json, os, signal, sys
    from pathlib import Path
    from app import db
    db.DB_PATH = Path(sys.argv[1])
    from app.bg_jobs import BgJobManager

    async def main():
        jobs = BgJobManager()
        created = await jobs.create("run", {"command": sys.argv[2]}, "crash job",
                                    "s-919", "w919", "/scope-919", "w919",
                                    timeout_seconds=600)
        for _ in range(200):
            process = json.loads(db.bg_get_job(created["id"])["config"]).get("_process")
            if process and process.get("pid"):
                break
            await asyncio.sleep(0.05)
        print(created["id"], flush=True)
        os.kill(os.getpid(), signal.SIGKILL)

    asyncio.run(main())
""")


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_code", [0, 7])
async def test_sigkilled_generation_run_is_adopted_with_its_exit_code(
    db, target, tmp_path, exit_code,
):
    from app.bg_jobs import BgJobManager

    session, manager, sent = target
    gate = tmp_path / "gate"
    command = (f"echo started-919; while [ ! -e {gate} ]; do sleep 0.05; done; "
               f"echo finished-919; exit {exit_code}")
    crashed = subprocess.run(
        [sys.executable, "-c", _CRASHING_GENERATION, str(db), command],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert crashed.returncode == -signal.SIGKILL, crashed.stderr
    job_id = crashed.stdout.strip()
    pid = _process(job_id)["pid"]
    try:
        assert _alive(pid), "the run job died with its generation"
        new = BgJobManager()
        new.set_session_manager(manager)
        await new.restore_from_db()
        gate.touch()
        row = await _settled(job_id)

        assert len(sent) == 1 and "finished-919" in sent[0]
        if exit_code == 0:
            assert row["status"] == "triggered" and "completed" in sent[0]
        else:
            assert row["status"] == "failed" and f"exit code {exit_code}" in sent[0]
    finally:
        _kill(pid)


@pytest.mark.asyncio
async def test_run_killed_during_restart_is_reported_interrupted_not_rerun(target, tmp_path):
    from app.bg_jobs import BgJobManager

    session, manager, sent = target
    old = BgJobManager()
    old.set_session_manager(manager)
    created = await old.create(
        "run", {"command": "sleep 300"}, "doomed job",
        session.id, session.name, session.scope, "w919", timeout_seconds=600,
    )
    pid = (await _recorded(created["id"]))["pid"]
    await old.shutdown()
    _kill(pid)  # e.g. the OOM killer took the command while Orchestra was down
    await asyncio.sleep(0.3)

    new = BgJobManager()
    new.set_session_manager(manager)
    await new.restore_from_db()
    row = await _settled(created["id"])

    assert row["status"] == "failed"
    assert len(sent) == 1 and "INTERRUPTED" in sent[0]


@pytest.mark.asyncio
async def test_cancel_still_kills_the_run_process(target):
    from app.bg_jobs import BgJobManager

    session, manager, _sent = target
    jobs = BgJobManager()
    jobs.set_session_manager(manager)
    created = await jobs.create(
        "run", {"command": "sleep 300"}, "cancelled job",
        session.id, session.name, session.scope, "w919", timeout_seconds=600,
    )
    pid = (await _recorded(created["id"]))["pid"]
    try:
        await jobs.cancel(created["id"])
        for _ in range(100):
            if not _alive(pid):
                break
            await asyncio.sleep(0.05)
        assert not _alive(pid)
    finally:
        _kill(pid)
