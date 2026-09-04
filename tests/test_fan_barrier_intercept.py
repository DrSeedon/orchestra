"""#407: durable child reports must enter the fan barrier before delivery."""

import uuid
from datetime import datetime, timezone

import pytest

from app.events import MessageProvenance


SCOPE = "/fan-407"
PARENT_ID = "parent-session-407"
PARENT_NAME = "parent-407"


def _session_record():
    return {
        "id": PARENT_ID,
        "name": PARENT_NAME,
        "scope": SCOPE,
        "cwd": "/tmp/parent-407",
        "model": "gpt-5.6-sol",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": "/tmp/parent-407",
        "branch": "task-407/parent",
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

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "fan-407.db")
    db.init_db()
    db.save_session(_session_record())
    return db


class _WakeRecorder:
    def __init__(self):
        self.records = []

    async def send_message_delivery(
        self, session_id, message, *, delivery, target_generation, provenance,
    ):
        assert provenance.origin == "agent"
        self.records.append({"session_id": session_id, "message": message})
        await delivery.before_submit()
        await delivery.mark_submitted(provider_ref=f"wake-{len(self.records)}")


async def _accepted_report(module, child, body):
    delivery_id = str(uuid.uuid4())
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
            f"session={PARENT_ID}|task=407|branch=task-407/parent|needs_switch=0"
        ),
        message=body,
        rendered_message=f"[from:{child}] {body}",
        message_kind="done",
        wake=True,
        provenance=MessageProvenance(origin="agent", senders=(child,)),
    )
    return delivery_id


@pytest.mark.asyncio
async def test_t1_three_durable_reports_create_exactly_one_parent_wake(
    fan_db, monkeypatch,
):
    from app import fan_barrier, message_deliveries

    children = ["child-407-a", "child-407-b", "child-407-c"]
    fan_barrier.open_fan(
        fan_id="fan-407-red",
        parent_name=PARENT_NAME,
        scope=SCOPE,
        children=children,
        deadline_seconds=3600,
    )
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _target: None)
    recorder = _WakeRecorder()

    for child in children:
        delivery_id = await _accepted_report(
            message_deliveries, child, f"report from {child}",
        )
        await message_deliveries.run_message_delivery(delivery_id, manager=recorder)

    manifest = fan_barrier.manifest("fan-407-red")
    assert manifest["complete"] is True, (
        "durable send_message bypassed fan_barrier; all members stayed pending"
    )
    assert [member["state"] for member in manifest["members"]] == [
        "done", "done", "done",
    ]
    assert len(recorder.records) == 1, (
        f"actual parent wake records={recorder.records!r}; expected exactly one"
    )
    assert "fan=fan-407-red complete=true" in recorder.records[0]["message"]
