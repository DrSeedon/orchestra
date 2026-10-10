"""V-678: доставка, отбитая гейтом квот, не теряется и не требует таймера у отправителя.

Проверяется ядро: сохранность (переживает «рестарт»), порядок к одному адресату, отсутствие
дублей, выпуск при открытии гейта и по снятию гейта владельцем, отмена, край «адресат
сменил задачу». Формулировки receipt'ов не проверяются.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.events import MessageProvenance
from app.quota_gate import QuotaGateError, evaluate_worker_admission, line_limit

SOURCE_ID, SOURCE_NAME = "src-678", "orch-678"
TARGET_ID, TARGET_NAME = "tgt-678", "worker-678"
SCOPE = "/scope-678"
MODEL = "claude-opus-5-5[1m]"
GENERATION = f"session={TARGET_ID}|task=678|branch=task-678/w|needs_switch=0"
IDS = [f"00000000-0000-4000-8000-00000000067{i}" for i in range(6)]
PROV = MessageProvenance(origin="agent", senders=(SOURCE_NAME,), subtype="direct_message")


def _record(session_id, name, role="worker"):
    return {
        "id": session_id, "name": name, "scope": SCOPE, "cwd": "/tmp", "model": MODEL,
        "system_prompt": "", "status": "idle", "session_id": None, "cost_usd": 0.0,
        "worktree_path": "/tmp", "branch": "task-678/w", "base_branch": "main",
        "needs_switch": 0, "task_id": "678", "role": role,
        "is_orchestrator": role == "orchestrator", "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "parent_name": "",
    }


def _decision(utilization_above_line: float):
    """Реальное решение гейта: выше линии на заданную величину → blocked (или available)."""
    now = time.time()
    window_minutes = 10080
    window_start = now - window_minutes * 60 * 0.1
    util = line_limit(
        0.1, "claude", window_minutes=window_minutes, window_start_at=window_start,
    ) + utilization_above_line
    window = {
        "id": "seven_day", "window_minutes": 10080, "utilization": util,
        "resets_at": datetime.fromtimestamp(now + 10080 * 60 * 0.9, timezone.utc).isoformat(),
    }
    return evaluate_worker_admission(
        MODEL, {"anthropic": {"label": "Claude", "windows": [window]}},
        {"anthropic": now}, now=now,
    )


class Gate:
    """Управляемый гейт: один источник истины и для приёмки, и для runner'а, и для релизера."""

    def __init__(self):
        self.above = 20.0

    def decision(self):
        return _decision(self.above)

    def open(self):
        self.above = -10.0


class FakeManager:
    def __init__(self, gate):
        self.gate = gate
        self.delivered: list[str] = []
        self.sent_to_sender: list[str] = []
        self.generation = GENERATION

    async def send_message_delivery(
        self, session_id, message, *, delivery, target_generation, provenance,
    ):
        decision = self.gate.decision()
        if decision.state == "blocked":
            raise QuotaGateError(decision)
        if target_generation != self.generation:
            from app.message_deliveries import TargetTaskChangedError

            raise TargetTaskChangedError("target task generation changed before delivery")
        await delivery.before_submit()
        self.delivered.append(message)
        await delivery.mark_submitted(provider_ref="turn")

    async def send_initial_delivery(self, session_id, message, *, delivery, provenance):
        decision = self.gate.decision()
        if decision.state == "blocked":
            raise QuotaGateError(decision)
        await delivery.before_submit()
        self.delivered.append(message)
        await delivery.mark_submitted(provider_ref="turn")

    async def send(self, session_id, text, *, provenance):
        self.sent_to_sender.append(text)


@pytest.fixture
def env(tmp_path, monkeypatch):
    from app import db, deps, message_deliveries, quota_gate

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "wait.db")
    db.init_db()
    db.save_session(_record(SOURCE_ID, SOURCE_NAME, "orchestrator"))
    db.save_session(_record(TARGET_ID, TARGET_NAME))
    gate = Gate()
    manager = FakeManager(gate)
    monkeypatch.setattr(deps, "manager", manager)

    async def admission(model, observation_loader=None):
        return gate.decision()

    monkeypatch.setattr(quota_gate, "get_worker_admission", admission)
    message_deliveries._target_runner_tasks.clear()
    message_deliveries._target_delivery_locks.clear()
    yield SimpleNamespace(gate=gate, manager=manager, db=db)
    quota_gate.clear_gate_override()


async def _accept(delivery_id, text, *, parked=False, source=SOURCE_ID, generation=GENERATION):
    from app import message_deliveries

    return await message_deliveries.accept_message_delivery(
        delivery_id=delivery_id, source_session_id=source, source_name=SOURCE_NAME,
        source_scope=SCOPE, source_task_id="678", target_session_id=TARGET_ID,
        target_name=TARGET_NAME, target_scope=SCOPE, target_task_id="678",
        target_generation=generation, message=text, rendered_message=f"[from:x] {text}",
        provenance=PROV, quota_wait=_decision(20.0) if parked else None,
    )


def _states(db):
    with db._conn() as connection:
        return {
            row["delivery_id"]: row["state"]
            for row in connection.execute("SELECT delivery_id, state FROM message_deliveries")
        }


async def _drain():
    from app import message_deliveries

    for _ in range(50):
        tasks = [t for t in message_deliveries._target_runner_tasks.values() if not t.done()]
        if not tasks:
            return
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_blocked_messages_wait_then_leave_in_accept_order_without_duplicates(env):
    from app import quota_queue

    # Первое отбито на приёмке (preflight), второе принято, пока гейт ещё закрыт и голова
    # уже ждёт: обогнать её оно не вправе.
    await _accept(IDS[0], "first", parked=True)
    await _accept(IDS[1], "second")
    # Повтор отправителя тем же delivery_id — не новое сообщение.
    resource, _ = await _accept(IDS[0], "first", parked=True)
    assert resource["acceptance"] == "ALREADY_ACCEPTED"

    await _drain()
    assert env.manager.delivered == []
    assert _states(env.db) == {IDS[0]: "WAITING_QUOTA", IDS[1]: "QUEUED"}

    assert await quota_queue.release_waiting() == 0  # гейт закрыт: ничего не уходит
    env.gate.open()
    assert await quota_queue.release_waiting() == 1
    await _drain()

    assert env.manager.delivered == ["[from:x] first", "[from:x] second"]
    assert set(_states(env.db).values()) == {"SUBMITTED"}
    assert await quota_queue.release_waiting() == 0  # повторный проход ничего не шлёт заново
    assert len(env.manager.delivered) == 2


@pytest.mark.asyncio
async def test_runtime_refusal_parks_instead_of_failing(env):
    """Гейт закрылся уже ПОСЛЕ приёмки: отказ runner'а — это ожидание, а не потеря."""
    await _accept(IDS[0], "late")
    await _drain()

    assert _states(env.db) == {IDS[0]: "WAITING_QUOTA"}
    with env.db._conn() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM logs WHERE session_id=? AND type='user_message'", (TARGET_ID,),
        ).fetchone()[0] == 0  # панель не показывает недоставленное доставленным


@pytest.mark.asyncio
async def test_waiting_delivery_survives_restart_and_is_released_afterwards(env):
    from app import message_deliveries, quota_queue

    await _accept(IDS[0], "survive", parked=True)
    # «Рестарт»: память процесса пуста, стартовое восстановление не должно её тронуть.
    message_deliveries._target_runner_tasks.clear()
    await message_deliveries.recover_message_deliveries()
    assert _states(env.db) == {IDS[0]: "WAITING_QUOTA"}

    env.gate.open()
    await quota_queue.release_waiting()
    await _drain()
    assert env.manager.delivered == ["[from:x] survive"]


@pytest.mark.asyncio
async def test_owner_override_releases_the_queue_immediately(env):
    from app import quota_gate
    from app.routes.system import quota_override

    await _accept(IDS[0], "override", parked=True)
    assert _decision(20.0).state == "blocked"

    response = await quota_override({"minutes": 5})
    await _drain()

    assert response["released_deliveries"] == 1
    assert quota_gate.gate_override_remaining() > 0
    assert env.manager.delivered == ["[from:x] override"]


@pytest.mark.asyncio
async def test_cancel_removes_waiting_message_and_unblocks_the_ones_behind(env):
    from app import message_deliveries, quota_queue

    await _accept(IDS[0], "cancel-me", parked=True)
    await _accept(IDS[1], "keep")

    body, status = message_deliveries.cancel_message_delivery(IDS[0], "someone-else")
    assert status == 404  # чужую доставку отменить нельзя
    body, status = message_deliveries.cancel_message_delivery(IDS[0], SOURCE_ID)
    assert status == 200 and body["delivery_state"] == "CANCELLED"

    env.gate.open()
    await quota_queue.release_waiting()
    await _drain()
    assert env.manager.delivered == ["[from:x] keep"]

    body, status = message_deliveries.cancel_message_delivery(IDS[1], SOURCE_ID)
    assert status == 409  # уже ушло: отменять поздно


@pytest.mark.asyncio
async def test_target_changed_task_fails_loudly_and_sender_is_told(env):
    from app import quota_queue

    await _accept(IDS[0], "stale", parked=True)
    env.manager.generation = "session=other|task=999|branch=x|needs_switch=0"
    env.gate.open()
    await quota_queue.release_waiting()
    await _drain()

    assert _states(env.db) == {IDS[0]: "FAILED_BEFORE_SUBMIT"}
    assert env.manager.delivered == []
    assert len(env.manager.sent_to_sender) == 1 and IDS[0] in env.manager.sent_to_sender[0]


@pytest.mark.asyncio
async def test_closed_gate_keeps_waiting_and_long_queue_goes_out_in_order(env):
    from app import quota_queue

    for i in range(5):
        await _accept(IDS[i], f"m{i}", parked=(i == 0))
    await _drain()
    assert env.manager.delivered == []
    for _ in range(3):  # много проходов при закрытом гейте — ничего не уходит и не меняется
        assert await quota_queue.release_waiting() == 0

    env.gate.open()
    await quota_queue.release_waiting()
    await _drain()
    assert env.manager.delivered == [f"[from:x] m{i}" for i in range(5)]


@pytest.mark.asyncio
async def test_initial_task_waits_for_the_gate_and_precedes_direct_messages(env):
    from app import initial_deliveries, quota_queue

    initial_id = "00000000-0000-4000-8000-000000000679"
    await initial_deliveries.accept_initial_delivery(
        delivery_id=initial_id, session_id=TARGET_ID, worker_name=TARGET_NAME, scope=SCOPE,
        sender=SOURCE_NAME, message="first task",
        provenance=MessageProvenance(
            origin="agent", senders=(SOURCE_NAME,), subtype="initial_delivery",
            ref=initial_id,
        ),
    )
    for _ in range(50):
        await asyncio.sleep(0)
        row = initial_deliveries._delivery_payload(initial_id)
        if row["state"] != "QUEUED":
            break
    assert initial_deliveries._delivery_payload(initial_id)["state"] == "WAITING_QUOTA"
    assert quota_queue.waiting_scopes() == {SCOPE}

    await _accept(IDS[0], "direct", parked=True)  # адресату пишут, пока его задание ждёт
    assert quota_queue.waiting_scopes() == {SCOPE}
    env.gate.open()
    await quota_queue.release_waiting()
    assert quota_queue.waiting_scopes() == set()
    for _ in range(50):
        await asyncio.sleep(0)
    await quota_queue.release_waiting()  # следующий проход цикла (если первый не успел)
    await _drain()

    assert env.manager.delivered == ["first task", "[from:x] direct"]
    assert initial_deliveries._delivery_payload(initial_id)["state"] == "SUBMITTED"


@pytest.mark.asyncio
async def test_initial_wait_rechecks_current_model_after_change_races_gate_sweep(
    env, monkeypatch,
):
    from app import initial_deliveries, quota_queue

    initial_id = "00000000-0000-4000-8000-000000000680"
    decision = _decision(20.0)
    await initial_deliveries.accept_initial_delivery(
        delivery_id=initial_id, session_id=TARGET_ID, worker_name=TARGET_NAME, scope=SCOPE,
        sender=SOURCE_NAME, message="first task",
        provenance=MessageProvenance(
            origin="agent", senders=(SOURCE_NAME,), subtype="initial_delivery",
            ref=initial_id,
        ),
        quota_wait=decision,
    )
    seen_models = []

    async def admission(model):
        seen_models.append(model)
        if len(seen_models) == 1:
            env.db.save_session(_record(TARGET_ID, TARGET_NAME, role="worker") | {
                "model": "gpt-6-luna",
            })
            return False, decision
        return model == "gpt-6-luna", None

    monkeypatch.setattr(quota_queue, "_admission_allows", admission)
    assert await quota_queue.release_waiting() == 0
    assert initial_deliveries._delivery_payload(initial_id)["state"] == "WAITING_QUOTA"

    env.gate.open()
    assert await quota_queue.release_waiting() == 1
    await _drain()

    assert seen_models == [MODEL, "gpt-6-luna"]
    assert env.manager.delivered == ["first task"]
    assert initial_deliveries._delivery_payload(initial_id)["state"] == "SUBMITTED"


@pytest.mark.asyncio
async def test_model_change_immediately_releases_waiting_initial_task(env, monkeypatch):
    from app import initial_deliveries, quota_queue
    from app.routes import sessions as session_routes

    initial_id = "00000000-0000-4000-8000-000000000681"
    await initial_deliveries.accept_initial_delivery(
        delivery_id=initial_id, session_id=TARGET_ID, worker_name=TARGET_NAME, scope=SCOPE,
        sender=SOURCE_NAME, message="first task",
        provenance=MessageProvenance(
            origin="agent", senders=(SOURCE_NAME,), subtype="initial_delivery",
            ref=initial_id,
        ),
        quota_wait=env.gate.decision(),
    )
    env.gate.open()
    checked_models = []

    async def admission(model):
        checked_models.append(model)
        return model == "gpt-6-luna", None

    monkeypatch.setattr(quota_queue, "_admission_allows", admission)

    class Worker:
        async def change_model(self, model):
            env.db.save_session(_record(TARGET_ID, TARGET_NAME) | {"model": model})
            return {"ok": True, "changed": True, "model": model}

    async def ensure_loaded(_name, _scope):
        return Worker()

    monkeypatch.setattr(
        session_routes.manager, "ensure_loaded", ensure_loaded, raising=False,
    )
    response = await session_routes.change_model(
        TARGET_NAME, {"scope": SCOPE, "model": "gpt-6-luna"},
    )
    await _drain()

    assert response["ok"] is True
    assert checked_models == ["gpt-6-luna"]
    assert env.manager.delivered == ["first task"]
    assert initial_deliveries._delivery_payload(initial_id)["state"] == "SUBMITTED"
