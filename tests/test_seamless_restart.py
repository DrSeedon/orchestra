"""#237 — production-shaped oracles for seamless Codex restart.

These tests are intentionally RED until docs/tasks/237/plan.md is implemented.  The
transport case runs on a real uvloop event loop because the default asyncio probe was the
false positive that hid the production failure.
"""

import asyncio
import json
import os
import re
import runpy
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import uvloop


class _OwnedPipeProcess:
    """Process double that keeps the CLI sides of caller-owned stdio pipes."""

    def __init__(self, cli_stdin: int, cli_stdout: int):
        self.pid = os.getpid()
        self.returncode = None
        self.stdin = None
        self.stdout = None
        self.stderr = None
        self.cli_stdin = cli_stdin
        self.cli_stdout = cli_stdout
        self._exited = asyncio.Event()

    async def wait(self):
        await self._exited.wait()
        return self.returncode

    def terminate(self):
        self.returncode = 0
        self._exited.set()

    def kill(self):
        self.terminate()



def _adoptable_backend():
    """Двойник бэкенда, УМЕЮЩЕГО передаваться (#230 T5).

    Рестарт спрашивает способность (`adopt`), а не имя рантайма, поэтому двойник, который
    изображает Codex, обязан её иметь: без неё он изображает рантайм, чей ход рестарт обязан
    ждать, и тест мерил бы не то, что называется в его имени.
    """
    async def _adopt(*a, **k):
        return None

    return SimpleNamespace(adopt=_adopt)


async def _wait_until(predicate, *, timeout: float = 2.0, message: str):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(message)


async def _read_jsonl_until_quiet(fd: int, *, timeout: float = 2.0) -> bytes:
    """Read one nonblocking JSONL frame and prove no duplicate bytes follow it."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    quiet_after = None
    data = bytearray()
    was_blocking = os.get_blocking(fd)
    os.set_blocking(fd, False)
    try:
        while loop.time() < deadline:
            try:
                chunk = os.read(fd, 4096)
            except BlockingIOError:
                chunk = None
            if chunk:
                data.extend(chunk)
                if b"\n" in data:
                    quiet_after = loop.time() + 0.05
            elif quiet_after is not None and loop.time() >= quiet_after:
                return bytes(data)
            await asyncio.sleep(0.01)
    finally:
        os.set_blocking(fd, was_blocking)
    raise AssertionError(f"adopted writer did not emit one complete quiet JSONL frame: {data!r}")


def _pipe_pair():
    cli_to_us_r, cli_to_us_w = os.pipe()
    us_to_cli_r, us_to_cli_w = os.pipe()
    return cli_to_us_r, cli_to_us_w, us_to_cli_r, us_to_cli_w


def test_t1_codex_uvloop_parent_pipes_preserve_two_generation_cutpoints(monkeypatch):
    """Production connect must own numeric FDs and carry every frame exactly once.

    The cut points are deliberate and independent:
    1. a partial JSONL frame is already in StreamReader._buffer while its tail is still in
       the kernel pipe;
    2. that frame is parsed but remains in the notification queue at the next handover;
    3. a tool event and the terminal event remain in the kernel pipe;
    4. a third Python generation receives the exact ordered sequence, without replay.
    """
    import app.backend_codex as module

    spawned = SimpleNamespace(proc=None, child_originals=())
    parent_owned_fds = []

    async def create_process(*_args, **kwargs):
        stdin = kwargs.get("stdin")
        stdout = kwargs.get("stdout")
        assert isinstance(stdin, int) and stdin >= 0, (
            "Codex spawn must receive Orchestra-owned child stdin FD, not PIPE")
        assert isinstance(stdout, int) and stdout >= 0, (
            "Codex spawn must receive Orchestra-owned child stdout FD, not PIPE")
        assert stdin != stdout
        spawned.child_originals = (stdin, stdout)
        spawned.proc = _OwnedPipeProcess(os.dup(stdin), os.dup(stdout))
        return spawned.proc

    async def scenario():
        monkeypatch.setattr(module.asyncio, "create_subprocess_exec", create_process)
        monkeypatch.setattr(
            module,
            "_codex_scope_support",
            AsyncMock(return_value=(False, {}, "test: direct child")),
        )

        first = module.CodexBackend(model="gpt-5.6-luna", cwd="/tmp")
        first._request = AsyncMock(
            side_effect=lambda method, _params: (
                {"thread": {"id": "thread-237"}} if method == "thread/start" else {}
            )
        )
        first._notify = AsyncMock()
        first._drain_stderr = AsyncMock()

        second = third = None
        try:
            await asyncio.wait_for(first.connect(), timeout=3)
            assert first.fd_in is not None and first.fd_in >= 0
            assert first.fd_out is not None and first.fd_out >= 0
            assert first.fd_in != first.fd_out
            assert first.is_alive is True
            parent_owned_fds.extend((first.fd_in, first.fd_out))
            for fd in spawned.child_originals:
                with pytest.raises(OSError):
                    os.fstat(fd)

            started = {
                "method": "turn/started",
                "params": {"seq": 1, "threadId": "thread-237", "turn": {"id": "turn-237"}},
            }
            encoded = (json.dumps(started) + "\n").encode()
            split = len(encoded) // 2
            os.write(spawned.proc.cli_stdout, encoded[:split])
            await _wait_until(
                lambda: bytes(getattr(first._out, "_buffer", b"")) == encoded[:split],
                message="partial frame never reached the uvloop StreamReader buffer",
            )

            # A live child never exits here. quiesce must cancel the reader without awaiting
            # proc.wait(); that 30-second stall was the second hidden production defect.
            assert await asyncio.wait_for(first.quiesce_for_handover(), timeout=1) is True
            os.write(spawned.proc.cli_stdout, encoded[split:])

            second = module.CodexBackend(model="gpt-5.6-luna", cwd="/tmp")
            await second.adopt(
                os.dup(first.fd_in),
                os.dup(first.fd_out),
                "thread-237",
                "turn-237",
                leftover=first.leftover,
            )
            parent_owned_fds.extend((second.fd_in, second.fd_out))
            await _wait_until(
                lambda: second._notifications.qsize() == 1,
                message="generation 2 did not parse the split turn/started frame",
            )

            write_probe = {
                "method": "orchestra/handover-probe",
                "params": {"marker": "237-gen2-adopted-stdin"},
            }
            await second._notify(write_probe["method"], write_probe["params"])
            written = await _read_jsonl_until_quiet(spawned.proc.cli_stdin)
            assert written == (json.dumps(write_probe, ensure_ascii=False) + "\n").encode(), (
                "generation 2 must write one exact frame through the adopted stdin side; "
                "a crossed writer can preserve stdout while making control requests impossible")

            # Preserve the parsed-but-unconsumed frame as a prefix. The following complete
            # frames are written only after the reader is quiesced, so they remain in kernel.
            assert await asyncio.wait_for(
                second.quiesce_for_handover(), timeout=1
            ) is True
            tool = {"method": "item/completed", "params": {"seq": 2, "item": {"type": "toolCall"}}}
            terminal = {
                "method": "turn/completed",
                "params": {"seq": 3, "threadId": "thread-237", "turn": {"id": "turn-237"}},
            }
            os.write(
                spawned.proc.cli_stdout,
                ((json.dumps(tool) + "\n") + (json.dumps(terminal) + "\n")).encode(),
            )

            third = module.CodexBackend(model="gpt-5.6-luna", cwd="/tmp")
            await third.adopt(
                os.dup(second.fd_in),
                os.dup(second.fd_out),
                "thread-237",
                "turn-237",
                leftover=second.leftover,
            )
            parent_owned_fds.extend((third.fd_in, third.fd_out))
            await _wait_until(
                lambda: third._notifications.qsize() == 3,
                message="generation 3 did not receive prefix + kernel frames",
            )
            messages = [third._notifications.get_nowait() for _ in range(3)]
            assert [m["method"] for m in messages] == [
                "turn/started", "item/completed", "turn/completed",
            ]
            assert [m["params"]["seq"] for m in messages] == [1, 2, 3]
            assert len({m["params"]["seq"] for m in messages}) == 3, (
                "handover must not duplicate an input, tool, or terminal frame")
        finally:
            for backend in (third, second):
                if backend is not None:
                    backend._disconnecting = True
                    await backend.teardown_adopted()
            if spawned.proc is not None:
                spawned.proc.terminate()
            # CLI stdin must remain open through both handovers; EOF here would mean one
            # generation closed a descriptor still owned by the next generation.  Use a
            # nonblocking read: timing out a blocking executor thread would leak that thread.
            if spawned.proc is not None:
                was_blocking = os.get_blocking(spawned.proc.cli_stdin)
                os.set_blocking(spawned.proc.cli_stdin, False)
                try:
                    with pytest.raises(BlockingIOError):
                        os.read(spawned.proc.cli_stdin, 1)
                finally:
                    os.set_blocking(spawned.proc.cli_stdin, was_blocking)
            if first._proc is not None:
                await first.disconnect()
            if spawned.proc is not None:
                for fd in (spawned.proc.cli_stdin, spawned.proc.cli_stdout):
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            for fd in dict.fromkeys(parent_owned_fds):
                with pytest.raises(OSError):
                    os.fstat(fd)

    loop = uvloop.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(scenario())
    finally:
        asyncio.set_event_loop(None)
        loop.close()


@pytest.mark.asyncio
async def test_t1_adopted_writer_uses_the_stdin_side_exactly_once():
    """Reachability control for the crossed-stdin/stdout mutation while T1 remains RED."""
    from app.backend_codex import CodexBackend

    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipe_pair()
    backend = CodexBackend(model="gpt-5.6-luna", cwd="/tmp")
    probe = {
        "method": "orchestra/handover-probe",
        "params": {"marker": "237-adopted-stdin-control"},
    }
    try:
        await backend.adopt(cli_in_w, cli_out_r, "thread-237", "turn-237")
        await backend._notify(probe["method"], probe["params"])
        written = await _read_jsonl_until_quiet(cli_in_r)
        assert written == (json.dumps(probe, ensure_ascii=False) + "\n").encode()
    finally:
        backend._disconnecting = True
        await backend.teardown_adopted()
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "orchestra-237.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    return db_path


def _save_handover_row(
    cwd,
    *,
    session_id=None,
    row_id="23700000-0000-4000-8000-000000000001",
    name="codex-237",
):
    from app.db import save_handover_state, save_session

    save_session({
        "id": row_id,
        "name": name,
        "scope": str(cwd),
        "cwd": str(cwd),
        "model": "gpt-5.6-luna",
        "backend_type": "codex",
        "system_prompt": "",
        "status": "running",
        "session_id": session_id,
        "cost_usd": 0.0,
        "worktree_path": None,
        "branch": None,
        "is_orchestrator": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "role": "worker",
        "pipeline": "default",
        "color": "#818cf8",
    })
    save_handover_state(
        row_id,
        "turn-237",
        "",
        4242,
        999,
    )


@pytest.mark.asyncio
async def test_t2_handover_names_are_systemd_safe_and_round_trip(isolated_db, tmp_path, monkeypatch):
    from app.manager import SessionManager

    _save_handover_row(tmp_path, session_id="thread-237")

    class Backend:
        fd_in = 11
        fd_out = 12
        active_turn_id = "turn-237"
        leftover = ""
        pid = 4242
        cli_started_at = 999

        async def quiesce_for_handover(self):
            return True

    session = SimpleNamespace(
        id="23700000-0000-4000-8000-000000000001",
        name="codex-237",
        _backend=Backend(),
    )
    stored = []
    monkeypatch.setattr(
        "app.fdstore.store_fds", lambda name, fds: stored.append((name, tuple(fds)))
    )

    manager = SessionManager()
    assert await manager._hand_over_backend(session) is True
    mapping = dict(stored)
    assert mapping == {
        "agent.23700000-0000-4000-8000-000000000001.stdin": (11,),
        "agent.23700000-0000-4000-8000-000000000001.stdout": (12,),
    }, f"stdin/stdout must keep their exact identity, got {mapping}"
    assert all(re.fullmatch(r"[A-Za-z0-9_.-]+", name) for name in mapping), (
        "FDNAME must exclude the LISTEN_FDNAMES ':' delimiter and control characters")

    from app.manager import _inherited_named_fds

    # systemd does not promise the order in which stored descriptors return.  Exercise both
    # orders: the adoptable view must preserve side identity, while the orphan view deliberately
    # discards the side but must retain the complete descriptor set used by #258.
    for items in (list(mapping.items()), list(reversed(mapping.items()))):
        monkeypatch.setattr("app.fdstore.acquire_fds", lambda items=items: {
            name: fds[0] for name, fds in items
        })
        assert manager._inherited_agent_pipes() == {
            "23700000-0000-4000-8000-000000000001": (11, 12)
        }
        assert sorted(_inherited_named_fds()) == [
            ("23700000-0000-4000-8000-000000000001", 11),
            ("23700000-0000-4000-8000-000000000001", 12),
        ]


def test_t2_fdstore_rejects_a_name_systemd_would_silently_replace(monkeypatch):
    from app import fdstore

    sent = []
    monkeypatch.setattr(fdstore, "_notify", lambda payload, fds: sent.append((payload, fds)))

    with pytest.raises(ValueError, match="FDNAME"):
        fdstore.store_fds("agent:session:stdin", [11])
    assert sent == [], "unsafe names must fail before anything reaches systemd"

    fdstore.store_fds("agent.session.stdin", [11])
    assert sent[-1] == ("FDSTORE=1\nFDNAME=agent.session.stdin", [11])


@pytest.mark.asyncio
async def test_t2_complete_inherited_pair_adopts_even_with_null_native_session_id(
    isolated_db, tmp_path, monkeypatch
):
    from app.manager import SessionManager

    _save_handover_row(tmp_path, session_id=None)
    incomplete_id = "23700000-0000-4000-8000-000000000002"
    _save_handover_row(
        tmp_path,
        session_id=None,
        row_id=incomplete_id,
        name="codex-incomplete-237",
    )
    monkeypatch.setattr("app.fdstore.acquire_fds", lambda: {
        "agent.23700000-0000-4000-8000-000000000001.stdin": 21,
        "agent.23700000-0000-4000-8000-000000000001.stdout": 22,
        f"agent.{incomplete_id}.stdin": 23,
    })

    adopted = []
    loaded = []

    class Session:
        def __init__(self, row):
            self.id = row["id"]
            self.name = row["name"]

        async def adopt_backend(self, fd_in, fd_out, **metadata):
            adopted.append((self.id, fd_in, fd_out, metadata))

    manager = SessionManager()

    async def load(row):
        loaded.append(row["id"])
        session = Session(row)
        manager.sessions[session.id] = session
        return session

    monkeypatch.setattr(manager, "_load_from_db", load)
    await manager.auto_resume_all()

    complete_id = "23700000-0000-4000-8000-000000000001"
    assert loaded == [complete_id], (
        "a NULL-session row without both inherited ends is not resumable; #258 owns cleanup")
    assert adopted == [(complete_id, 21, 22, {
        "active_turn_id": "turn-237",
        "leftover": "",
        "cli_pid": 4242,
        "cli_started_at": 999,
    })], (
        "a complete inherited pair is stronger evidence of a live turn than session_id; "
        "excluding the row routes its valid survivor into orphan cleanup")


@pytest.fixture(autouse=True)
def _restore_restart_gates():
    yield
    from app import main as app_main
    from app.deps import manager
    app_main.open_mutating_admission()
    manager.end_drain()


@pytest.mark.asyncio
async def test_t3_restart_closes_both_admissions_before_its_first_wait(monkeypatch):
    from app import main as app_main
    from app.deps import manager
    from app.routes import system

    order = []
    real_begin = manager.begin_drain
    real_close = app_main.close_mutating_admission

    def begin():
        order.append("agent")
        real_begin()

    def close():
        order.append("http")
        real_close()

    async def first_wait():
        assert len(order) >= 2 and set(order[:2]) == {"agent", "http"}, (
            f"both gates must close atomically before yielding; got {order}")
        raise RuntimeError("stop after observing the first await")

    monkeypatch.setattr(manager, "begin_drain", begin)
    monkeypatch.setattr(app_main, "close_mutating_admission", close)
    monkeypatch.setattr(app_main, "drain_mutating_requests", first_wait)

    with pytest.raises(RuntimeError, match="stop after observing"):
        await system.restart_server()


@pytest.mark.asyncio
async def test_t3_inflight_mutating_http_blocks_signal_until_it_finishes(monkeypatch):
    from app import main as app_main
    from app.deps import manager
    from app.routes import system

    inflight = {"count": 1}
    kill = MagicMock()
    monkeypatch.setattr(system, "_drain_sessions", lambda: [])
    monkeypatch.setattr(system, "_DRAIN_DEADLINE_S", 2)
    monkeypatch.setattr(system.os, "kill", kill)
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: inflight["count"])
    monkeypatch.setattr(
        manager,
        "prepare_restart_handover",
        AsyncMock(return_value={"ok": True, "handed_over": []}),
        raising=False,
    )

    task = asyncio.create_task(system._restart_service_after_response())
    await asyncio.sleep(0.8)
    assert not kill.called, (
        "an admitted mutating handler can have committed an effect but not returned it; "
        "signalling here makes its outcome unknown")
    inflight["count"] = 0
    await asyncio.wait_for(task, timeout=3)
    kill.assert_called_once_with(os.getpid(), system.signal.SIGINT)


@pytest.mark.asyncio
async def test_t3_active_codex_is_handed_over_without_waiting_for_idle(monkeypatch):
    from app import main as app_main
    from app.deps import manager
    from app.routes import system

    active_codex = SimpleNamespace(
        id="codex-active", name="codex-active", backend_type="codex", is_busy=True,
        _backend=_adoptable_backend(),
    )
    order = []

    async def prepare(sessions):
        assert sessions == [active_codex]
        order.append("prepare")
        return {"ok": True, "handed_over": ["codex-active"]}

    monkeypatch.setattr(system, "_drain_sessions", lambda: [active_codex])
    monkeypatch.setattr(system, "_DRAIN_DEADLINE_S", 0.1)
    monkeypatch.setattr(app_main, "drain_mutating_requests", AsyncMock(return_value=True))
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 0)
    monkeypatch.setattr(manager, "prepare_restart_handover", prepare, raising=False)
    monkeypatch.setattr(system.os, "kill", lambda *_args: order.append("signal"))

    outcome = await asyncio.wait_for(system._restart_service_after_response(), timeout=2)

    assert order == ["prepare", "signal"], (
        "an active Codex turn must be handed over before the signal, not drained to idle")
    assert outcome["ok"] is True and outcome["handed_over"] == ["codex-active"]


@pytest.mark.asyncio
async def test_t3_handover_refusal_aborts_restart_and_reopens_both_admissions(monkeypatch):
    from app import main as app_main
    from app.deps import manager
    from app.routes import system

    stuck = SimpleNamespace(
        id="stuck", name="stuck", backend_type="codex", is_busy=True,
        _backend=_adoptable_backend(),
    )
    kill = MagicMock()
    monkeypatch.setattr(system, "_drain_sessions", lambda: [stuck])
    monkeypatch.setattr(system, "_DRAIN_DEADLINE_S", 0.1)
    monkeypatch.setattr(system.os, "kill", kill)
    monkeypatch.setattr(app_main, "drain_mutating_requests", AsyncMock(return_value=True))
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 0)
    monkeypatch.setattr(
        manager,
        "prepare_restart_handover",
        AsyncMock(return_value={"ok": False, "reason": "pending request"}),
        raising=False,
    )

    outcome = await asyncio.wait_for(system._restart_service_after_response(), timeout=2)

    assert kill.called is False, "failed handover must abort instead of cutting a live turn"
    assert outcome["ok"] is False and "pending request" in outcome["reason"]
    assert manager.draining is False, "aborted restart must reopen agent-turn admission"
    assert app_main.mutating_admission_verdict(
        "POST", "/api/sessions/worker/send"
    )["allowed"] is True, "aborted restart must reopen mutating HTTP admission"


@pytest.mark.asyncio
async def test_t3_fleet_handover_rolls_back_an_earlier_success(monkeypatch):
    """Провалившаяся транзакция обязана вернуть слух ВСЕМ, включая отказавшего.

    Переписан после ревью #237 (B1/S1). Прежняя версия подменяла `_hand_over_backend`
    моком и РУКАМИ ставила `_handover_quiescing = True` — состояние, которого прод на этом
    пути не производит: он его как раз снимает. Оракул был зелен на двойнике,
    противоречащем реализации, и не покрывал строку, где агент оставался живым и глухим
    навсегда. Здесь работает НАСТОЯЩИЙ `_hand_over_backend`, а квиесцирование ставит сам
    двойник транспорта — ровно как `quiesce_for_handover` в бою.
    """
    from app.manager import SessionManager

    class _Transport:
        """Двойник ТРАНСПОРТА, повторяющий его контракт, а не удобную тесту позу."""

        def __init__(self, fd_in, fd_out):
            self.fd_in, self.fd_out = fd_in, fd_out
            self.active_turn_id, self.leftover = "", ""
            self.pid, self.cli_started_at = 0, 0
            self._handover_quiescing = False
            #: то, что на самом деле решает судьбу агента: жив ли его читатель
            self.hears = True

        async def quiesce_for_handover(self):
            self._handover_quiescing = True
            self.hears = False  # настоящий quiesce отменяет читателя и ставит пайп на паузу
            return True

        async def resume_after_aborted_handover(self):
            self._handover_quiescing = False
            self.hears = True

    first_backend, second_backend = _Transport(11, 12), _Transport(13, 14)
    first = SimpleNamespace(
        id="first-237", name="first-237", backend_type="codex", _backend=first_backend
    )
    second = SimpleNamespace(
        id="second-237", name="second-237", backend_type="codex", _backend=second_backend
    )
    manager = SessionManager()
    removed = []
    monkeypatch.setattr("app.fdstore.remove_fds", lambda name: removed.append(name))
    monkeypatch.setattr("app.db.save_handover_state", lambda *a, **k: None)

    def _store(name, fds):
        if name.startswith("agent.second-237."):
            raise OSError("systemd fd store is full")

    monkeypatch.setattr("app.fdstore.store_fds", _store)

    prepare = getattr(manager, "prepare_restart_handover", None)
    assert prepare is not None, "T3 requires one fleet-level all-or-none handover transaction"
    result = await prepare([first, second])

    assert result["ok"] is False
    assert removed == ["agent.first-237.stdin", "agent.first-237.stdout"]
    assert first_backend.hears is True, "успевший передаться агент оглох после отката"
    assert second_backend.hears is True, (
        "ОТКАЗАВШИЙ агент остался живым и глухим: quiesce отменил его читателя, "
        "а вернуть его не вернули")
    assert getattr(manager, "_prepared_restart_sessions", set()) == set(), (
        "a failed fleet handover must leave no session marked prepared")


@pytest.mark.asyncio
async def test_t3_aborted_handover_replays_prefix_and_resumes_reader():
    from app.backend_codex import CodexBackend

    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipe_pair()
    backend = CodexBackend(model="gpt-5.6-luna", cwd="/tmp")
    try:
        await backend.adopt(cli_in_w, cli_out_r, "thread-237", "turn-237")
        first = {"method": "item/completed", "params": {"seq": 1}}
        os.write(cli_out_w, (json.dumps(first) + "\n").encode())
        await _wait_until(
            lambda: backend._notifications.qsize() == 1,
            message="reader did not enter its body before quiesce",
        )
        # Половина СЛЕДУЮЩЕГО кадра — без неё оракул слеп к порядку (ревью #237, B3):
        # разобранное событие пришло РАНЬШЕ этих байт, и вернуть его надо перед ними.
        # На пустом буфере зелены обе реализации, и верная, и уничтожающая оба кадра.
        second = {"method": "turn/completed", "params": {"seq": 2}}
        tail = (json.dumps(second) + "\n").encode()
        head, tail = tail[:20], tail[20:]
        os.write(cli_out_w, head)
        await _wait_until(
            lambda: len(getattr(backend._out, "_buffer", b"")) >= len(head),
            message="partial frame did not reach the reader buffer before quiesce",
        )
        assert await backend.quiesce_for_handover() is True

        resume = getattr(backend, "resume_after_aborted_handover", None)
        assert resume is not None, "rollback must restore the reader, not only clear a flag"
        await resume()
        os.write(cli_out_w, tail)
        await _wait_until(
            lambda: backend._notifications.qsize() == 2,
            message="resumed reader lost the carried event or the half-written frame",
        )
        frames = [backend._notifications.get_nowait() for _ in range(2)]
        assert [frame["params"]["seq"] for frame in frames] == [1, 2], \
            "перенесённые события обязаны вернуться ПЕРЕД недописанным кадром, а не после"
        assert backend._handover_quiescing is False
    finally:
        backend._disconnecting = True
        await backend.teardown_adopted()
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_t3_non_adoptable_runtime_deadline_aborts_without_signal(monkeypatch):
    from app import main as app_main
    from app.deps import manager
    from app.routes import system

    claude = SimpleNamespace(
        id="claude-active", name="claude-active", backend_type="claude", is_busy=True
    )
    kill = MagicMock()
    monkeypatch.setattr(system, "_drain_sessions", lambda: [claude])
    monkeypatch.setattr(system, "_DRAIN_DEADLINE_S", 0.1)
    monkeypatch.setattr(system.os, "kill", kill)
    monkeypatch.setattr(app_main, "drain_mutating_requests", AsyncMock(return_value=True))
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 0)
    prepare = AsyncMock(return_value={"ok": True, "handed_over": []})
    monkeypatch.setattr(manager, "prepare_restart_handover", prepare, raising=False)

    outcome = await asyncio.wait_for(system._restart_service_after_response(), timeout=2)

    assert kill.called is False, "an unsupported live runtime must block, never be cut"
    assert outcome["ok"] is False and outcome["cut_ids"] == ["claude-active"]
    prepare.assert_not_awaited()


@pytest.mark.asyncio
async def test_t3_signal_failure_rolls_back_the_complete_prepared_fleet(monkeypatch):
    from app import main as app_main
    from app.manager import SessionManager
    from app.routes import system

    local_manager = SessionManager()
    removed = []
    backends = []
    sessions = []
    for suffix in ("one", "two"):
        # `adopt` — то, по чему рестарт решает, можно ли не ждать эту сессию (#230 T5)
        backend = SimpleNamespace(_handover_quiescing=False,
                                  adopt=_adoptable_backend().adopt)

        async def resume(backend=backend):
            backend._handover_quiescing = False

        backend.resume_after_aborted_handover = AsyncMock(side_effect=resume)
        session = SimpleNamespace(
            id=f"codex-{suffix}",
            name=f"codex-{suffix}",
            backend_type="codex",
            is_busy=True,
            _backend=backend,
        )
        backends.append(backend)
        sessions.append(session)

    async def hand_over(session):
        session._backend._handover_quiescing = True
        return True

    local_manager._hand_over_backend = AsyncMock(side_effect=hand_over)
    monkeypatch.setattr(system, "manager", local_manager)
    monkeypatch.setattr(system, "_drain_sessions", lambda: sessions)
    monkeypatch.setattr(system, "_DRAIN_DEADLINE_S", 0.1)
    monkeypatch.setattr(app_main, "drain_mutating_requests", AsyncMock(return_value=True))
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 0)
    monkeypatch.setattr("app.fdstore.remove_fds", lambda name: removed.append(name))

    def fail_signal(*_args):
        raise OSError("synthetic signal failure")

    monkeypatch.setattr(system.os, "kill", fail_signal)

    with pytest.raises(OSError, match="synthetic signal failure"):
        await asyncio.wait_for(system._restart_service_after_response(), timeout=2)

    assert sorted(removed) == [
        "agent.codex-one.stdin",
        "agent.codex-one.stdout",
        "agent.codex-two.stdin",
        "agent.codex-two.stdout",
    ]
    for backend in backends:
        backend.resume_after_aborted_handover.assert_awaited_once_with()
        assert backend._handover_quiescing is False
    assert getattr(local_manager, "_prepared_restart_sessions", set()) == set()
    assert local_manager.draining is False
    assert app_main.mutating_admission_verdict(
        "POST", "/api/sessions/worker/send"
    )["allowed"] is True


@pytest.mark.asyncio
async def test_t3_late_unsupported_turn_after_codex_prepare_rolls_back_without_signal(monkeypatch):
    from app import main as app_main
    from app.deps import manager
    from app.routes import system

    codex = SimpleNamespace(
        id="codex-prepared", name="codex-prepared", backend_type="codex", is_busy=True,
        _backend=_adoptable_backend(),
    )
    claude = SimpleNamespace(
        id="claude-late", name="claude-late", backend_type="claude", is_busy=False
    )
    kill = MagicMock()
    rollback = AsyncMock()

    async def prepare(sessions):
        assert sessions == [codex]
        claude.is_busy = True
        return {"ok": True, "handed_over": ["codex-prepared"]}

    monkeypatch.setattr(system, "_drain_sessions", lambda: [codex, claude])
    monkeypatch.setattr(system, "_DRAIN_DEADLINE_S", 0.1)
    monkeypatch.setattr(system.os, "kill", kill)
    monkeypatch.setattr(app_main, "drain_mutating_requests", AsyncMock(return_value=True))
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 0)
    monkeypatch.setattr(manager, "prepare_restart_handover", prepare, raising=False)
    monkeypatch.setattr(
        manager, "rollback_restart_handover", rollback, raising=False
    )

    outcome = await asyncio.wait_for(system._restart_service_after_response(), timeout=2)

    assert kill.called is False, "a runtime that became busy after prepare must not be cut"
    assert outcome["ok"] is False and outcome["cut_ids"] == ["claude-late"]
    rollback.assert_awaited_once_with()


def test_t4_transient_rehearsal_is_versioned_and_cannot_target_production():
    """The destructive delivery check must be reviewable and hard-pinned to the mini stand."""
    root = Path(__file__).resolve().parents[1]
    runner = root / "scripts" / "rehearse-seamless-restart.py"
    assert runner.is_file(), (
        "T4 needs a versioned transient-unit runner; a scratch-only command cannot be reviewed")
    text = runner.read_text()
    assert "orchestra-237.service" in text
    assert "orchestra.service" not in text.replace("orchestra-237.service", ""), (
        "the rehearsal must have no code path that can restart the production unit")
    assert "uvloop" in text, "the runner must measure the production event-loop shape"
    assert "NFileDescriptorStore" in text
    assert "turn ended" in text
    assert "actual_cli_pid" in text and "cli_started_at" in text
    assert "sequence" in text and "count" in text, (
        "the runner must report exactly-once event evidence, not only a final marker")

    dry_run = subprocess.run(
        [sys.executable, str(runner), "--dry-run"],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert dry_run.returncode == 0, dry_run.stderr
    assert json.loads(dry_run.stdout) == {
        "restart_argv": ["sudo", "systemctl", "restart", "orchestra-237.service"]
    }, "dry-run must execute the same hard-pinned command builder used by the rehearsal"

    override = subprocess.run(
        [sys.executable, str(runner), "--dry-run", "--unit", "orchestra.service"],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert override.returncode != 0, (
        "the destructive runner must expose no CLI surface that can select production")

    module = runpy.run_path(str(runner), run_name="orchestra_237_rehearsal_test")
    execute = module.get("main")
    assert callable(execute), "the reviewed main() must own dry-run and destructive execution"
    run = MagicMock(return_value=SimpleNamespace(returncode=0))
    assert execute(["--execute"], run=run) == 0
    run.assert_called_once_with(
        ["sudo", "systemctl", "restart", "orchestra-237.service"],
        check=True,
    )


@pytest.mark.asyncio
async def test_guard_refused_quiesce_leaves_the_backend_untouched():
    """Охранник, добавленный ПОСЛЕ раунда 2 ревью #237 — не оракул тикета.

    Инвариант, сломанный в B1: `quiesce_for_handover() is False` ОБЯЗАН означать
    «не квиесцирован». Вызывающий вправе просто остановить агента по-старому и не
    должен гадать, не оставил ли отказ его наполовину поставленным на паузу.

    Проверяются оба отказных пути, и проверяется НАБЛЮДАЕМОЕ: доезжает ли до очереди
    кадр, отправленный CLI уже ПОСЛЕ отказа. Флаг для этого не годится — именно он и
    был снят в B1 при живом дефекте.
    """
    from app.backend_codex import CodexBackend

    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipe_pair()
    backend = CodexBackend(model="gpt-5.6-luna", cwd="/tmp")
    try:
        await backend.adopt(cli_in_w, cli_out_r, "thread-237", "turn-237")

        # путь 1: незавершённый JSON-RPC запрос — исход неизвестен, передача запрещена
        loop = asyncio.get_running_loop()
        backend._pending_requests[4242] = loop.create_future()
        assert await backend.quiesce_for_handover() is False
        backend._pending_requests.pop(4242)

        os.write(cli_out_w, (json.dumps({"method": "a", "params": {"seq": 1}}) + "\n").encode())
        await _wait_until(
            lambda: backend._notifications.qsize() == 1,
            message="после отказа по in-flight запросу агент оглох: читатель не вернулся",
        )
        assert backend._handover_quiescing is False

        # путь 2: перенесённые события не сериализуются — тоже отказ, тоже без последствий
        backend._notifications.put_nowait({"method": "b", "params": {"bad": object()}})
        assert await backend.quiesce_for_handover() is False

        while not backend._notifications.empty():
            backend._notifications.get_nowait()
        os.write(cli_out_w, (json.dumps({"method": "c", "params": {"seq": 2}}) + "\n").encode())
        await _wait_until(
            lambda: backend._notifications.qsize() == 1,
            message="после отказа по сериализации агент оглох: читатель не вернулся",
        )
        assert backend._handover_quiescing is False
    finally:
        backend._disconnecting = True
        await backend.teardown_adopted()
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass
