"""#407: explicit, silent, and failed child turns share one fan release."""

import uuid
from datetime import datetime, timezone

import pytest


SCOPE = "/fan-modes-407"
PARENT_ID = "parent-modes-407"
PARENT_NAME = "parent-modes-407"


def _parent_record():
    return {
        "id": PARENT_ID,
        "name": PARENT_NAME,
        "scope": SCOPE,
        "cwd": "/tmp/parent-modes-407",
        "model": "gpt-5.6-sol",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": "/tmp/parent-modes-407",
        "branch": "task-407/parent-modes",
        "base_branch": "main",
        "needs_switch": 0,
        "task_id": "407",
        "role": "orchestrator",
        "is_orchestrator": True,
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "parent_name": "",
    }


@pytest.fixture
def fan_db(tmp_path, monkeypatch):
    from app import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "fan-modes-407.db")
    db.init_db()
    db.save_session(_parent_record())
    return db


class _WakeRecorder:
    def __init__(self):
        self.records = []

    async def ensure_loaded(self, name, scope=None):
        return type("Parent", (), {"id": PARENT_ID})()

    async def send(self, session_id, message):
        self.records.append({"path": "auto-report", "message": message})

    async def send_message_delivery(
        self, session_id, message, *, delivery, target_generation,
    ):
        self.records.append({"path": "explicit", "message": message})
        await delivery.before_submit()
        await delivery.mark_submitted(provider_ref="fan-wake")


async def _explicit_report(module, child, delivery_id=None):
    delivery_id = delivery_id or str(uuid.uuid4())
    await module.accept_message_delivery(
        delivery_id=delivery_id,
        source_session_id=f"sid-{child}",
        source_principal=f"mcp:sid-{child}",
        source_name=child,
        source_scope=SCOPE,
        source_task_id="407",
        target_session_id=PARENT_ID,
        target_name=PARENT_NAME,
        target_scope=SCOPE,
        target_task_id="407",
        target_generation=(
            f"session={PARENT_ID}|task=407|branch=task-407/parent-modes|needs_switch=0"
        ),
        message=f"explicit report from {child}",
        rendered_message=f"[from:{child}] explicit report from {child}",
        message_kind=None,
        wake=True,
    )
    return delivery_id


class _FinishedChild:
    is_orchestrator = False
    _did_report = False
    _manually_interrupted = False
    _pending_messages = False
    _compacting = False
    _last_stop_reason = "end_turn"
    _auto_report_task = None
    parent_name = PARENT_NAME
    last_task_sender = PARENT_NAME

    def __init__(self, name, *, ok, text):
        self.name = name
        self.scope = SCOPE
        self._last_turn_ok = ok
        self._turn_logs = [text]
        self._last_text_output = text
        self.idle_calls = []

    async def on_idle(self, *args):
        self.idle_calls.append(args)


async def _finish(child):
    from app.session_turns import TurnManager

    TurnManager(child).fire_auto_report()
    if child._auto_report_task is not None:
        await child._auto_report_task


@pytest.mark.asyncio
async def test_t2_mixed_explicit_silent_and_failed_turns_wake_parent_once(
    fan_db, monkeypatch,
):
    from app import fan_barrier, message_deliveries

    children = ["explicit-407", "silent-407", "failed-407"]
    fan_barrier.open_fan(
        fan_id="fan-modes-407",
        parent_name=PARENT_NAME,
        scope=SCOPE,
        children=children,
        deadline_seconds=3600,
    )
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _target: None)
    recorder = _WakeRecorder()
    monkeypatch.setattr("app.deps.manager", recorder)

    delivery_id = await _explicit_report(message_deliveries, children[0])
    await message_deliveries.run_message_delivery(delivery_id, manager=recorder)
    silent = _FinishedChild(children[1], ok=True, text="[[ORCHESTRA:SILENT_TURN]]")
    failed = _FinishedChild(children[2], ok=False, text="provider crashed")
    await _finish(silent)
    assert recorder.records == [], (
        f"silent child woke parent separately: {recorder.records!r}"
    )
    await _finish(failed)

    manifest = fan_barrier.manifest("fan-modes-407")
    assert [member["state"] for member in manifest["members"]] == [
        "done", "done", "failed",
    ]
    assert silent.idle_calls == [] and failed.idle_calls == []
    assert len(recorder.records) == 1, (
        f"actual parent wake records={recorder.records!r}; expected exactly one"
    )
    assert recorder.records[0]["path"] == "auto-report"
    assert "complete=true" in recorder.records[0]["message"]


@pytest.mark.asyncio
async def test_t2_releasing_report_replays_as_manifest_after_preparation_crash(
    fan_db, monkeypatch,
):
    from app import fan_barrier, message_deliveries

    child = "crash-window-407"
    fan_barrier.open_fan(
        fan_id="fan-crash-window-407",
        parent_name=PARENT_NAME,
        scope=SCOPE,
        children=[child],
        deadline_seconds=3600,
    )
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _target: None)
    delivery_id = await _explicit_report(message_deliveries, child)
    real_prepare = message_deliveries.prepare_message_delivery

    def crash_after_intercept(_delivery_id):
        raise RuntimeError("simulated crash after fan release")

    monkeypatch.setattr(message_deliveries, "prepare_message_delivery", crash_after_intercept)
    with pytest.raises(RuntimeError, match="simulated crash"):
        await message_deliveries.run_message_delivery(delivery_id, manager=_WakeRecorder())

    with fan_db._conn() as connection:
        stored = connection.execute(
            "SELECT state, message FROM message_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
    assert stored["state"] == "QUEUED"
    assert stored["message"].startswith("fan=fan-crash-window-407 complete=true")

    monkeypatch.setattr(message_deliveries, "prepare_message_delivery", real_prepare)
    recorder = _WakeRecorder()
    await message_deliveries.run_message_delivery(delivery_id, manager=recorder)
    assert len(recorder.records) == 1
    assert "complete=true" in recorder.records[0]["message"]
    assert "explicit report from" not in recorder.records[0]["message"]


@pytest.mark.asyncio
async def test_t2_known_pre_submit_failure_rearms_fan_and_same_receipt_retries(
    fan_db, monkeypatch,
):
    from app import fan_barrier, message_deliveries

    child = "pre-submit-failure-407"
    fan_barrier.open_fan(
        fan_id="fan-pre-submit-407",
        parent_name=PARENT_NAME,
        scope=SCOPE,
        children=[child],
        deadline_seconds=3600,
    )
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _target: None)
    delivery_id = await _explicit_report(message_deliveries, child)

    class FailingManager:
        async def send_message_delivery(self, *args, **kwargs):
            raise RuntimeError("provider was not called")

    with pytest.raises(RuntimeError, match="provider was not called"):
        await message_deliveries.run_message_delivery(
            delivery_id, manager=FailingManager(),
        )
    assert fan_barrier.is_released("fan-pre-submit-407") is False
    with fan_db._conn() as connection:
        state = connection.execute(
            "SELECT state FROM message_deliveries WHERE delivery_id=?", (delivery_id,),
        ).fetchone()[0]
    assert state == "FAILED_BEFORE_SUBMIT"

    await _explicit_report(message_deliveries, child, delivery_id=delivery_id)
    recorder = _WakeRecorder()
    await message_deliveries.run_message_delivery(delivery_id, manager=recorder)
    assert fan_barrier.is_released("fan-pre-submit-407") is True
    assert len(recorder.records) == 1
    assert "fan=fan-pre-submit-407 complete=true" in recorder.records[0]["message"]


@pytest.mark.asyncio
async def test_t2_buffered_receipt_never_enters_dispatching_state(
    fan_db, monkeypatch,
):
    from app import fan_barrier, message_deliveries

    fan_barrier.open_fan(
        fan_id="fan-atomic-buffer-407",
        parent_name=PARENT_NAME,
        scope=SCOPE,
        children=["buffered-407", "pending-407"],
        deadline_seconds=3600,
    )
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _target: None)
    monkeypatch.setattr(
        message_deliveries,
        "mark_message_delivery_dispatching",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fan buffer entered provider-dispatch state")
        ),
    )
    delivery_id = await _explicit_report(message_deliveries, "buffered-407")
    await message_deliveries.run_message_delivery(
        delivery_id, manager=_WakeRecorder(),
    )

    with fan_db._conn() as connection:
        state = connection.execute(
            "SELECT state FROM message_deliveries WHERE delivery_id=?", (delivery_id,),
        ).fetchone()[0]
    assert state == "SUBMITTED"
