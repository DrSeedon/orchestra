"""#V-748: terminal file delivery failures wake the agent sender durably."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from aiogram.exceptions import TelegramBadRequest
from app.events import InjectedMessage


SOURCE_ID = "source-session-748"
SCOPE = "/scope-748"
PRIMARY_CHAT = -100748001
PRIMARY_THREAD = 7481


def _session_record():
    return {
        "id": SOURCE_ID,
        "name": "sender-748",
        "scope": SCOPE,
        "cwd": "/tmp/sender-748",
        "model": "gpt-6-luna",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": "/tmp/sender-748",
        "branch": "main",
        "base_branch": "main",
        "needs_switch": 0,
        "task_id": "748",
        "role": "worker",
        "is_orchestrator": False,
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "parent_name": "",
    }


class _SenderManager:
    def __init__(self, db):
        self.db = db
        self.fail_once = True
        self.notices = []

    async def send(self, session_id, message, *, provenance):
        assert session_id == SOURCE_ID
        assert isinstance(message, InjectedMessage)
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("sender session is temporarily unavailable")
        self.notices.append(message)
        self.db.add_log(
            session_id, datetime.now(timezone.utc), "user_message", message.text,
            event_id=message.event_id, provenance=provenance,
        )


@pytest.fixture
def file_world(tmp_path, monkeypatch):
    from app import db
    import app.deps as deps
    import app.tg_bridge as bridge
    import app.tg_file_deliveries as deliveries

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "file-notices-748.db")
    db.init_db()
    db.save_session(_session_record())
    monkeypatch.setattr(deliveries, "SPOOL_ROOT", tmp_path / "outbox")
    monkeypatch.setattr(deliveries, "ensure_chat_runner", lambda _chat_id: None)

    class _Bot:
        async def send_document(self, chat_id, document, caption=None, message_thread_id=None):
            return SimpleNamespace(
                message_id=74801,
                chat=SimpleNamespace(id=chat_id),
            )

    monkeypatch.setattr(bridge, "bot", _Bot())
    manager = _SenderManager(db)
    monkeypatch.setattr(deps, "manager", manager)
    return SimpleNamespace(db=db, deliveries=deliveries, manager=manager, root=tmp_path)


async def _accept(world, name, *, event_id=None):
    path = world.root / name
    path.write_bytes(b"file payload")
    event_id = event_id or str(uuid.uuid4())
    receipt, status, _headers = await world.deliveries.accept_file_delivery(
        event_id=event_id,
        source_session_id=SOURCE_ID,
        source_name="sender-748",
        source_scope=SCOPE,
        source_path=str(path),
        caption="",
        as_document=True,
        orch_name="orch-748",
        targets=[{
            "target_kind": "primary",
            "chat_id": PRIMARY_CHAT,
            "thread_id": PRIMARY_THREAD,
        }],
    )
    assert status == 202
    assert receipt["event_id"] == event_id
    return event_id


@pytest.mark.asyncio
async def test_terminal_file_failures_wake_sender_once_and_recover_pending_notice(
    file_world, monkeypatch,
):
    from app import tg_file_deliveries

    snapshot_event = await _accept(file_world, "snapshot.pdf")
    rejected_event = await _accept(file_world, "rejected.pdf")
    success_event = await _accept(file_world, "success.pdf")

    async def snapshot_failure(row):
        if row["event_id"] == snapshot_event:
            return {
                "code": "SNAPSHOT_MISSING",
                "message": "queued snapshot is missing",
                "retryable": False,
                "outcome_unknown": False,
            }
        return None

    monkeypatch.setattr(tg_file_deliveries, "_snapshot_failure", snapshot_failure)
    from app import tg_bridge

    submit_file = tg_bridge._submit_file_snapshot_once

    async def reject_provider(chat_id, snapshot_path, *args, **kwargs):
        if snapshot_path.endswith("rejected.pdf"):
            raise TelegramBadRequest(method=SimpleNamespace(), message="bad file")
        return await submit_file(chat_id, snapshot_path, *args, **kwargs)

    monkeypatch.setattr(
        tg_file_deliveries, "_submit_file_snapshot_once", reject_provider,
    )
    await tg_file_deliveries.run_chat_deliveries(PRIMARY_CHAT)

    assert tg_file_deliveries._failure_notice(snapshot_event)["delivered_at"] is None
    rejected_notice = tg_file_deliveries._failure_notice(rejected_event)
    assert rejected_notice["delivered_at"]
    assert "code=PROVIDER_REJECTED" in file_world.manager.notices[0].text
    assert rejected_event in file_world.manager.notices[0].text
    assert tg_file_deliveries._failure_notice(success_event) is None

    file_world.manager.fail_once = False
    assert await tg_file_deliveries.recover_file_delivery_failure_notices(
        file_world.manager,
    ) == 1
    assert len(file_world.manager.notices) == 2
    assert file_world.manager.notices[1].event_id == f"file-delivery-failed:{snapshot_event}"
    assert "queued snapshot is missing" in file_world.manager.notices[1].text
    assert await tg_file_deliveries.recover_file_delivery_failure_notices(
        file_world.manager,
    ) == 0
    assert len(file_world.manager.notices) == 2
