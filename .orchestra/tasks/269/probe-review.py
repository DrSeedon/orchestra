"""Review probes for #269 — NOT part of the branch. Run from /tmp snapshot only."""
import asyncio
import sqlite3

import pytest


class _Chat:
    id = 42


class _Msg:
    chat = _Chat()
    message_thread_id = 7


class _Manager:
    def __init__(self, fail_on: str = ""):
        self.sent: list[tuple[str, str]] = []
        self.fail_on = fail_on

    async def send(self, session_id: str, message: str) -> None:
        if self.fail_on and self.fail_on in message:
            raise RuntimeError("backend is not up yet")
        self.sent.append((session_id, message))


class _KeyErrorManager:
    """Reproduces app/manager.py:1145 — an unknown session raises KeyError."""

    async def send(self, session_id: str, message: str) -> None:
        raise KeyError(f"session not found: {session_id}")


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "t.db")
    from app.db import init_db

    init_db()
    from app import restart_inbox

    return restart_inbox


async def _noop():
    return None


# ── P1: the restart that never happens ────────────────────────────────────────

@pytest.mark.asyncio
async def test_probe_p1_aborted_restart_strands_the_queued_message(inbox, monkeypatch):
    """restart_preflight fails to drain -> 409, admission REOPENS, process keeps living.

    The message queued during the closed window has exactly one drain point
    (app/main.py:295, lifespan startup), which is not reached because there is no restart.
    """
    import app.main as app_main
    import app.tg_bridge as tb
    from app.routes import system as sys_routes

    told = []
    manager = _Manager()
    monkeypatch.setattr(tb, "_manager", manager)
    monkeypatch.setattr(tb, "bot", object())
    monkeypatch.setattr(tb, "_tg_send_safe",
                        lambda chat_id, text, **kw: told.append(text) or _noop())

    # a mutating call that never finishes -> drain budget expires
    async def never_drains():
        return False

    monkeypatch.setattr(app_main, "drain_mutating_requests", never_drains)
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 1)

    # user presses /restart; preflight closes admission, then fails
    preflight = asyncio.create_task(sys_routes.restart_preflight())
    await asyncio.sleep(0)  # admission is closed inside preflight
    verdict = await preflight

    # ... but the message arrives while the gate was still shut
    app_main.close_mutating_admission()
    await tb._flush_batch("sid-1", [(_Msg(), "ау", None)])
    app_main.open_mutating_admission()  # what system.py:1744 does on the failed preflight

    assert verdict["ok"] is False, "preflight must refuse: this is the 409 branch"
    assert told and "перезапус" in told[0].lower(), "the user was PROMISED delivery"
    assert manager.sent == [], "not delivered live"
    stranded = inbox.pending()
    assert len(stranded) == 1
    # The process is alive and admission is open again. Nothing in app/ drains the queue.
    assert app_main.mutating_admission_open() is True
    print(f"\nP1: promised={told[0][:60]!r}\nP1: still pending after abort = {stranded}")


# ── P2: the watchdog reopens admission mid-restart ────────────────────────────

@pytest.mark.asyncio
async def test_probe_p2_watchdog_reopens_admission_while_the_restart_is_still_draining(monkeypatch):
    """_ADMISSION_WATCHDOG_S=120 vs _DRAIN_DEADLINE_S=900: for up to 780s of a real restart
    the gate is OPEN again, so _flush_batch resumes pushing into sessions about to die."""
    import app.main as app_main
    from app.routes import system as sys_routes

    monkeypatch.setattr(sys_routes, "_ADMISSION_WATCHDOG_S", 0.05)
    app_main.close_mutating_admission()
    try:
        await sys_routes._reopen_admission_if_still_alive()
        reopened = app_main.mutating_admission_open()
    finally:
        app_main.open_mutating_admission()
    assert reopened is True
    print(f"\nP2: watchdog={sys_routes._ADMISSION_WATCHDOG_S}s (real 120s) reopened the gate; "
          f"_DRAIN_DEADLINE_S={sys_routes._DRAIN_DEADLINE_S}s")


# ── P3: a session that no longer exists ───────────────────────────────────────

@pytest.mark.asyncio
async def test_probe_p3_dead_session_row_is_stuck_forever_and_nobody_is_told(inbox):
    inbox.enqueue("sid-gone", "[10:00] ау")
    for attempt in range(3):  # three consecutive restarts
        assert await inbox.deliver_pending(_KeyErrorManager()) == 0
    still = inbox.pending()
    assert len(still) == 1, "the row never leaves the queue and no TTL exists"
    print(f"\nP3: after 3 restarts the row is still pending: {still}")


# ── P4: the drain itself hitting a broken DB ──────────────────────────────────

@pytest.mark.asyncio
async def test_probe_p4_drain_failure_is_swallowed_by_create_task(inbox, monkeypatch):
    """enqueue has a fallback; deliver_pending has none, and lifespan never awaits the task."""
    def boom():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(inbox, "pending", boom)
    task = asyncio.create_task(inbox.deliver_pending(_Manager()))
    await asyncio.sleep(0.05)
    assert task.done() and task.exception() is not None
    print(f"\nP4: lifespan task died with {task.exception()!r}; nothing retrieves it")


# ── P5: schema on a pre-existing database ─────────────────────────────────────

def test_probe_p5_create_table_if_not_exists_is_safe_on_an_existing_db(tmp_path, monkeypatch):
    """Build a DB with the PRE-change schema, put a row in a neighbour table, migrate."""
    import subprocess

    import importlib.util

    old_db_py = subprocess.run(
        ["git", "show", "5114939b~1:app/db.py"],
        cwd="/home/kesha/orchestra", capture_output=True, text=True, check=True).stdout
    db_file = tmp_path / "old.db"
    old_path = tmp_path / "old_db_module.py"
    old_path.write_text(old_db_py)
    spec = importlib.util.spec_from_file_location("old_db_module", old_path)
    old_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old_mod)
    ns = old_mod.__dict__
    old_mod.DB_PATH = db_file
    import app.db as newdb
    monkeypatch.setattr(newdb, "DB_PATH", db_file)

    # old schema, created by the pre-change init_db
    ns["init_db"]()
    conn = sqlite3.connect(db_file)
    tables_before = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.execute("INSERT INTO mailbox (sender, recipient, body, created_at, scope) "
                 "VALUES ('a','b','payload',1.0,'s')")
    conn.commit()
    conn.close()
    assert "restart_inbox" not in tables_before

    newdb.init_db()          # first boot on the new code
    newdb.init_db()          # and again — idempotent?

    conn = sqlite3.connect(db_file)
    tables_after = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    survived = conn.execute("SELECT body FROM mailbox").fetchall()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(restart_inbox)")]
    conn.close()
    assert "restart_inbox" in tables_after
    assert survived == [("payload",)], "pre-existing data must survive"
    assert tables_before <= tables_after, "no table disappeared"
    print(f"\nP5: added={sorted(tables_after - tables_before)} cols={cols} data intact")


# ── P6: crash between the send and the mark ───────────────────────────────────

@pytest.mark.asyncio
async def test_probe_p6_crash_after_send_before_mark_gives_a_duplicate_not_a_loss(inbox,
                                                                                 monkeypatch):
    inbox.enqueue("sid-1", "[10:00] ау")
    manager = _Manager()
    _real_mark = inbox.mark_delivered

    def die(row_id):
        raise SystemExit("process killed between the send and the mark")

    monkeypatch.setattr(inbox, "mark_delivered", die)
    with pytest.raises(SystemExit):
        await inbox.deliver_pending(manager)
    assert manager.sent == [("sid-1", "[10:00] ау")], "the side effect DID happen"
    assert len(inbox.pending()) == 1, "and the row is still queued -> replay, i.e. a duplicate"

    monkeypatch.setattr(inbox, "mark_delivered", _real_mark)
    survivor = _Manager()
    assert await inbox.deliver_pending(survivor) == 1
    print("\nP6: delivered twice across the crash (at-least-once), never zero times")


# ── P7: two drains racing (two processes / a fast double start) ───────────────

@pytest.mark.asyncio
async def test_probe_p7_concurrent_drains_double_deliver(inbox):
    inbox.enqueue("sid-1", "[10:00] ау")
    manager = _Manager()

    class _Slow(_Manager):
        async def send(self, session_id, message):
            await asyncio.sleep(0.05)
            self.sent.append((session_id, message))

    slow = _Slow()
    a, b = await asyncio.gather(inbox.deliver_pending(slow), inbox.deliver_pending(slow))
    print(f"\nP7: two concurrent drains delivered {a}+{b}, manager saw {len(slow.sent)} sends")
    assert len(slow.sent) == 2, "no claim/lock: both drains read the same pending row"
    assert manager.sent == []
