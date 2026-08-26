"""Терминальный отказ во главе очереди не должен глушить воркера навсегда.

26.08: у `pilot-surikov-style` во главе встал `FAILED_BEFORE_SUBMIT` (QuotaGateError
накануне). `_next_target_delivery` отбирал «первое не-SUBMITTED», поэтому головой
оставался мёртвый отказ, `ensure_target_runner` видел «голова не QUEUED» и выходил
молча. Шесть последующих заданий не ушли никогда, а отправитель на каждое получал
QUEUED. Воркер выглядел живым и глухим.
"""
import sqlite3

import pytest

from app import message_deliveries


def _make_db(tmp_path, rows):
    path = tmp_path / "deliveries.db"
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE message_deliveries (
               accept_seq INTEGER PRIMARY KEY,
               delivery_id TEXT,
               target_session_id TEXT,
               state TEXT
           )"""
    )
    connection.executemany(
        "INSERT INTO message_deliveries (accept_seq, delivery_id, target_session_id, state)"
        " VALUES (?,?,?,?)",
        rows,
    )
    connection.commit()
    return connection


@pytest.fixture
def patched_conn(monkeypatch):
    def _install(connection):
        class _Ctx:
            def __enter__(self):
                return connection

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(message_deliveries.db, "_conn", lambda: _Ctx())

    return _install


def test_terminal_failure_at_head_does_not_hide_later_queued_messages(
    tmp_path, patched_conn
):
    connection = _make_db(
        tmp_path,
        [
            (1, "dead", "sess", "FAILED_BEFORE_SUBMIT"),
            (2, "alive", "sess", "QUEUED"),
        ],
    )
    patched_conn(connection)

    head = message_deliveries._next_target_delivery("sess")

    assert head is not None, "очередь не должна выглядеть пустой при живом QUEUED"
    assert head["delivery_id"] == "alive"
    assert head["state"] == "QUEUED"


def test_queue_still_reports_empty_when_everything_is_terminal(tmp_path, patched_conn):
    connection = _make_db(
        tmp_path,
        [
            (1, "sent", "sess", "SUBMITTED"),
            (2, "dead", "sess", "FAILED_BEFORE_SUBMIT"),
        ],
    )
    patched_conn(connection)

    assert message_deliveries._next_target_delivery("sess") is None


def test_delivery_unknown_still_blocks_on_purpose(tmp_path, patched_conn):
    """DELIVERY_UNKNOWN — НАМЕРЕННЫЙ барьер (#380 R7), снимать его нельзя.

    «Неизвестно, ушло ли» ≠ «точно не ушло». Пропустив такую голову, мы можем доставить
    следующее сообщение раньше, чем выяснится судьба предыдущего: получим перестановку
    порядка или дубль. Отказ ДО отправки (FAILED_BEFORE_SUBMIT) такой неоднозначности
    не создаёт — вот его пропускать и нужно.
    """
    connection = _make_db(
        tmp_path,
        [
            (1, "ambiguous", "sess", "DELIVERY_UNKNOWN"),
            (2, "later", "sess", "QUEUED"),
        ],
    )
    patched_conn(connection)

    head = message_deliveries._next_target_delivery("sess")

    assert head["delivery_id"] == "ambiguous"
    assert "DELIVERY_UNKNOWN" not in message_deliveries._TERMINAL_DELIVERY_STATES


@pytest.mark.asyncio
async def test_delivery_unknown_head_does_not_send_later_message(tmp_path, patched_conn):
    connection = _make_db(
        tmp_path,
        [
            (1, "ambiguous", "sess", "DELIVERY_UNKNOWN"),
            (2, "later", "sess", "QUEUED"),
        ],
    )
    patched_conn(connection)
    calls = []

    class Manager:
        async def send_message_delivery(self, *args, **kwargs):
            calls.append((args, kwargs))

    drained = await message_deliveries.run_target_message_deliveries(
        "sess", manager=Manager(),
    )

    assert drained is False
    assert calls == []


def test_in_flight_states_are_not_skipped(tmp_path, patched_conn):
    """Обратное плечо: PREPARING/DISPATCHING — НЕ терминальные, их пропускать нельзя."""
    connection = _make_db(
        tmp_path,
        [
            (1, "busy", "sess", "DISPATCHING"),
            (2, "later", "sess", "QUEUED"),
        ],
    )
    patched_conn(connection)

    head = message_deliveries._next_target_delivery("sess")

    assert head["delivery_id"] == "busy", "идущая доставка не должна перепрыгиваться"


@pytest.mark.asyncio
async def test_runner_continues_after_delivery_failed_before_submit(monkeypatch):
    heads = iter([
        {"delivery_id": "dead", "state": "QUEUED"},
        {"delivery_id": "alive", "state": "QUEUED"},
        None,
    ])
    attempted = []

    monkeypatch.setattr(
        message_deliveries,
        "_next_target_delivery",
        lambda _target: next(heads),
    )

    async def run(delivery_id, manager=None):
        attempted.append(delivery_id)
        if delivery_id == "dead":
            raise KeyError("archived target is not loaded")

    monkeypatch.setattr(message_deliveries, "run_message_delivery", run)
    monkeypatch.setattr(
        message_deliveries,
        "_row",
        lambda delivery_id: {
            "state": "FAILED_BEFORE_SUBMIT" if delivery_id == "dead" else "SUBMITTED"
        },
    )

    assert await message_deliveries.run_target_message_deliveries("archived") is True
    assert attempted == ["dead", "alive"]


@pytest.mark.asyncio
async def test_runner_does_not_cross_delivery_unknown_barrier(monkeypatch):
    monkeypatch.setattr(
        message_deliveries,
        "_next_target_delivery",
        lambda _target: {"delivery_id": "unknown", "state": "QUEUED"},
    )

    async def run(_delivery_id, manager=None):
        raise RuntimeError("provider outcome unknown")

    monkeypatch.setattr(message_deliveries, "run_message_delivery", run)
    monkeypatch.setattr(
        message_deliveries,
        "_row",
        lambda _delivery_id: {"state": "DELIVERY_UNKNOWN"},
    )

    with pytest.raises(RuntimeError, match="provider outcome unknown"):
        await message_deliveries.run_target_message_deliveries("worker")
