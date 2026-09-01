"""Аудит 01.09: два дефекта доставки — замороженный agent_status и глухая очередь.

1. `stream_session_logs` разрешает живую сессию ОДИН раз на коннект. У НЕ загруженного
   воркера `manager.get` отдаёт None, и каждое событие стрима штампуется статусом из
   строки БД, снятой на коннекте ('idle'), — даже когда сессия уже загрузилась и идёт
   ход. Клиент верит `agent_status` каждого события, поэтому верный 'running' от опроса
   затирается по несколько раз в секунду.
2. `DELIVERY_UNKNOWN` во главе FIFO — НАМЕРЕННЫЙ барьер (#380 R7), снимать его нельзя.
   Но отправитель получал бодрый `state=QUEUED` без единого слова о блокировке, а
   штатного разбора головы (по аналогии с `resolve_merge_operation`) не было вовсе:
   доставка `c39339bd` простояла 25 часов, три следующих — `QUEUED`, воркер выглядел
   живым и глухим.
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import message_deliveries


SCOPE = "/audit-0901"
SOURCE_ID = "audit-0901-source"
SOURCE_NAME = "audit-0901-sender"
TARGET_ID = "audit-0901-target"
TARGET_NAME = "audit-0901-worker"
TARGET_GENERATION = f"session={TARGET_ID}|task=|branch=|needs_switch=0"
HEAD_ID = "00000000-0000-4000-8000-000000000901"
TAIL_ID = "00000000-0000-4000-8000-000000000902"


def _session_record(*, session_id, name, status="idle", role="worker"):
    return {
        "id": session_id,
        "name": name,
        "scope": SCOPE,
        "cwd": f"/tmp/{name}",
        "model": "claude-opus-5[1m]",
        "system_prompt": "",
        "status": status,
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": f"/tmp/{name}",
        "branch": "",
        "base_branch": "main",
        "needs_switch": 0,
        "task_id": "",
        "role": role,
        "is_orchestrator": role == "orchestrator",
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "parent_name": "",
    }


@pytest.fixture
def delivery_db(tmp_path, monkeypatch):
    from app import db

    db_path = tmp_path / "audit-0901.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    db.save_session(_session_record(
        session_id=SOURCE_ID, name=SOURCE_NAME, role="orchestrator",
    ))
    db.save_session(_session_record(session_id=TARGET_ID, name=TARGET_NAME))
    return db


async def _accept(*, delivery_id, message):
    return await message_deliveries.accept_message_delivery(
        delivery_id=delivery_id,
        source_session_id=SOURCE_ID,
        source_name=SOURCE_NAME,
        source_scope=SCOPE,
        target_session_id=TARGET_ID,
        target_name=TARGET_NAME,
        target_scope=SCOPE,
        target_generation=TARGET_GENERATION,
        message=message,
        rendered_message=f"[from:{SOURCE_NAME}] {message}",
        wake=True,
    )


class _FakeRequest:
    def __init__(self):
        self.disconnected = False

    async def is_disconnected(self):
        return self.disconnected


async def _next_event(events):
    raw = await events.__anext__()
    return json.loads(raw.removeprefix("data: ").strip())


@pytest.mark.asyncio
async def test_stream_reports_the_live_status_after_the_session_loads(
    delivery_db, monkeypatch,
):
    """Стрим, открытый на НЕ загруженной сессии, обязан догнать её реальный статус."""
    from app.deps import manager
    from app.live_broker import broker
    from app.routes.sessions import stream_session_logs

    assert manager.get(TARGET_ID) is None, "сессия не должна быть загружена на коннекте"
    response = await stream_session_logs(TARGET_NAME, SCOPE, _FakeRequest())
    events = response.body_iterator
    try:
        opened = await _next_event(events)
        assert opened["type"] == "__session"
        assert opened["agent_status"] == "idle"

        # Воркеру пришло сообщение: сессию загрузили, пошёл ход, логи идут в ТОТ ЖЕ стрим.
        monkeypatch.setitem(
            manager.sessions, TARGET_ID,
            SimpleNamespace(status=SimpleNamespace(value="running")),
        )
        broker.publish(TARGET_ID, {"type": "stream", "content": "работаю"})

        live = await _next_event(events)
        assert live["type"] == "stream"
        assert live["agent_status"] == "running", (
            "статус заморожен на коннекте: событие идущего хода штампуется 'idle', "
            "и клиент затирает им верный статус из опроса"
        )
    finally:
        await events.aclose()


@pytest.mark.asyncio
async def test_blocked_queue_is_named_to_the_sender_and_a_restart_clears_it(
    delivery_db, monkeypatch,
):
    """За неразобранной головой очереди отправитель обязан узнать о блокировке.

    И барьер обязан сниматься САМ: после рестарта процесс, который мог дослать голову,
    мёртв, переставить порядок она уже не может — держать за ней очередь незачем.
    """
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _target: None)
    await _accept(delivery_id=HEAD_ID, message="ambiguous head")
    message_deliveries.prepare_message_delivery(HEAD_ID)
    message_deliveries.mark_message_delivery_dispatching(HEAD_ID)
    message_deliveries.mark_message_delivery_unknown(
        HEAD_ID, RuntimeError("provider outcome lost"),
    )

    receipt, status_code = await _accept(delivery_id=TAIL_ID, message="must not vanish")
    assert status_code == 202
    blocked = receipt.get("next_action") or {}
    assert blocked.get("code") == "TARGET_QUEUE_BLOCKED", (
        "приняли сообщение за головой DELIVERY_UNKNOWN и ответили отправителю одним "
        "QUEUED с пустым next_action: про блокировку очереди он не узнаёт вовсе"
    )
    assert blocked["arguments"] == {"delivery_id": HEAD_ID}
    assert blocked["blocked_since"], "не сказано, с КАКИХ ПОР очередь стоит"

    await message_deliveries.recover_message_deliveries()

    head = message_deliveries._next_target_delivery(TARGET_ID)
    assert head is not None and head["delivery_id"] == TAIL_ID, (
        "осиротевшая голова обязана перестать держать очередь после рестарта"
    )
    tail_receipt = message_deliveries.get_message_delivery(TAIL_ID, SOURCE_ID)
    assert not tail_receipt.get("next_action")
