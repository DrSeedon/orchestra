"""#V-741: accepted agent messages must report a terminal delivery failure."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.events import InjectedMessage, MessageProvenance


SOURCE_ID = "source-session-741"
TARGET_ID = "target-session-741"
SCOPE = "/scope-741"
SOURCE_NAME = "sender-741"
TARGET_NAME = "target-741"


def _session_record(session_id, name):
    return {
        "id": session_id,
        "name": name,
        "scope": SCOPE,
        "cwd": f"/tmp/{name}",
        "model": "gpt-6-luna",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": f"/tmp/{name}",
        "branch": "main",
        "base_branch": "main",
        "needs_switch": 0,
        "task_id": "741",
        "role": "worker",
        "is_orchestrator": False,
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "parent_name": "",
    }


@pytest.fixture
def delivery_db(tmp_path, monkeypatch):
    from app import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "message-delivery-741.db")
    db.init_db()
    db.save_session(_session_record(SOURCE_ID, SOURCE_NAME))
    db.save_session(_session_record(TARGET_ID, TARGET_NAME))
    return db


async def _accept(module, *, delivery_id=None):
    delivery_id = delivery_id or str(uuid.uuid4())
    await module.accept_message_delivery(
        delivery_id=delivery_id,
        source_session_id=SOURCE_ID,
        source_principal=f"mcp:{SOURCE_ID}",
        source_name=SOURCE_NAME,
        source_scope=SCOPE,
        source_task_id="741",
        target_session_id=TARGET_ID,
        target_name=TARGET_NAME,
        target_scope=SCOPE,
        target_task_id="741",
        target_generation=f"session={TARGET_ID}|task=741|branch=main|needs_switch=0",
        message="please do this",
        rendered_message=f"[from:{SOURCE_NAME}] please do this",
        message_kind=None,
        wake=True,
        provenance=MessageProvenance(
            origin="agent", senders=(SOURCE_NAME,), subtype="direct_message",
            ref=delivery_id,
        ),
    )
    return delivery_id


class _Manager:
    def __init__(self, db, *, fail_notice=False, fail_target=False, target_repository=""):
        self.db = db
        self.fail_notice = fail_notice
        self.fail_target = fail_target
        self.target_repository = target_repository
        self.notices = []

    async def send_message_delivery(
        self, _session_id, _message, *, delivery, target_generation, provenance,
    ):
        if self.fail_target:
            raise RuntimeError("target session rejected before submit")
        if self.target_repository:
            from app.prompting import load_worker_memory

            load_worker_memory(
                TARGET_NAME, "worker", SCOPE, self.target_repository,
                allow_missing_layout=True,
            )
        await delivery.before_submit()
        await delivery.mark_submitted(provider_ref="submitted-741")

    async def send(self, session_id, message, *, provenance):
        assert session_id == SOURCE_ID
        assert isinstance(message, InjectedMessage)
        assert message.provenance == provenance
        if self.fail_notice:
            raise RuntimeError("sender unavailable")
        self.notices.append(message)
        self.db.add_log(
            session_id,
            datetime.now(timezone.utc),
            "user_message",
            message.text,
            event_id=message.event_id,
            provenance=provenance,
        )


@pytest.mark.asyncio
async def test_failed_before_submit_wakes_agent_once_with_delivery_and_error(
    delivery_db, monkeypatch,
):
    from app import message_deliveries

    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _target: None)
    delivery_id = await _accept(message_deliveries)
    manager = _Manager(delivery_db, fail_target=True)

    with pytest.raises(RuntimeError, match="rejected before submit"):
        await message_deliveries.run_message_delivery(delivery_id, manager=manager)

    assert len(manager.notices) == 1
    notice = manager.notices[0]
    assert notice.provenance.origin == "platform"
    assert notice.provenance.ref == delivery_id
    assert notice.event_id == f"message-delivery-failed:{delivery_id}"
    assert f"to '{TARGET_NAME}'" in notice.text
    assert f"delivery_id={delivery_id}" in notice.text
    assert "code=DELIVERY_NOT_SUBMITTED" in notice.text
    assert "target session rejected before submit" in notice.text
    assert message_deliveries._failure_notice(delivery_id)["delivered_at"]


@pytest.mark.asyncio
async def test_success_and_waiting_quota_do_not_wake_sender(delivery_db, monkeypatch):
    from app import message_deliveries

    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _target: None)
    success_id = await _accept(message_deliveries)
    success_manager = _Manager(delivery_db)
    await message_deliveries.run_message_delivery(success_id, manager=success_manager)
    assert success_manager.notices == []
    assert message_deliveries._failure_notice(success_id) is None

    waiting_id = await _accept(message_deliveries)
    message_deliveries.mark_message_delivery_waiting_quota(
        waiting_id,
        SimpleNamespace(
            provider_label="provider", reason="gate closed", provider="provider",
            utilization=1.0, release_status="unknown", release_in_seconds=None,
            reset_at=None,
        ),
    )
    assert await message_deliveries.recover_message_delivery_failure_notices(
        success_manager,
    ) == 0
    assert success_manager.notices == []


@pytest.mark.asyncio
async def test_owner_delivery_failure_does_not_create_agent_wake(delivery_db):
    from app import message_deliveries

    delivery_id = str(uuid.uuid4())
    await message_deliveries.accept_message_delivery(
        delivery_id=delivery_id,
        source_session_id=None,
        source_principal="operator:owner",
        source_name="",
        source_scope=SCOPE,
        source_task_id="",
        target_session_id=TARGET_ID,
        target_name=TARGET_NAME,
        target_scope=SCOPE,
        target_task_id="741",
        target_generation=f"session={TARGET_ID}|task=741|branch=main|needs_switch=0",
        message="owner message",
        rendered_message="owner message",
        message_kind=None,
        wake=True,
        provenance=MessageProvenance(origin="user", senders=("user",)),
    )
    message_deliveries.mark_message_delivery_failed_before_submit(
        delivery_id, RuntimeError("target unavailable"),
    )

    assert message_deliveries._failure_notice(delivery_id) is None


@pytest.mark.asyncio
async def test_delivery_succeeds_when_target_worktree_has_no_layout_file(
    delivery_db, monkeypatch, tmp_path,
):
    from app import message_deliveries

    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _target: None)
    delivery_id = await _accept(message_deliveries)
    worktree = tmp_path / "worker-worktree"
    worktree.mkdir()
    manager = _Manager(delivery_db, target_repository=str(worktree))

    await message_deliveries.run_message_delivery(delivery_id, manager=manager)

    assert message_deliveries._row(delivery_id)["state"] == "SUBMITTED"
    assert manager.notices == []


@pytest.mark.asyncio
async def test_agent_session_send_skips_missing_layout_only_for_delivery_context(
    tmp_path, monkeypatch,
):
    from app import message_deliveries
    from app.events import MessageProvenance
    from app.orchestra_layout import LayoutMigrationError
    from app.session import AgentSession

    worktree = tmp_path / "worker-worktree"
    (worktree / ".orchestra" / "workers").mkdir(parents=True)
    provenance = MessageProvenance(
        origin="agent", senders=("sender-741",), subtype="direct_message",
    )
    backend = SimpleNamespace(send=AsyncMock(), active_turn_id="turn-741")
    monkeypatch.setattr(
        "app.session.get_runtime",
        lambda _backend: SimpleNamespace(
            capabilities=SimpleNamespace(mid_turn_inject=True, event_stream="none"),
        ),
    )
    monkeypatch.setattr(
        message_deliveries, "mark_message_delivery_dispatching", lambda _id: {},
    )
    monkeypatch.setattr(
        message_deliveries, "mark_message_delivery_submitted",
        lambda _id, provider_ref=None: {},
    )

    def session_for_send(name):
        target = AgentSession(
            id=f"{name}-session-741", name=name, scope=str(tmp_path),
            cwd=str(worktree), worktree_path=str(worktree),
        )
        target.session_id = "resumed-741"
        target._current_prompt = "ROLE: worker."
        target._prompt_injected = False
        target.prompt_overlay = None
        target._log = MagicMock()
        target._persist = MagicMock()
        target._notify_scope_running = AsyncMock()
        target._attach_pending_facts = lambda message: (message, [])
        target._ack_pending_facts = lambda _keys: None
        target._worker_admission = AsyncMock(
            return_value=SimpleNamespace(state="available", valid_until=None),
        )
        target._ensure_backend = AsyncMock(return_value=backend)
        return target

    delivery_session = session_for_send("delivery-worker-741")
    delivery = message_deliveries.MessageDeliveryContext(
        str(uuid.uuid4()),
        history_user_message="agent task",
        provenance=provenance,
    )
    await delivery_session.send(
        "agent task", provenance=provenance, delivery=delivery,
    )
    assert delivery_session.status.value == "running"
    backend.send.assert_awaited_once()
    assert delivery.dispatched is True

    plain_session = session_for_send("plain-worker-741")
    with pytest.raises(LayoutMigrationError) as error:
        await plain_session.send("ordinary send", provenance=provenance)
    assert error.value.code == "ORCHESTRA_LAYOUT_MISSING"
    backend.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_pending_failure_notice_replays_after_restart_without_duplicate(
    delivery_db, monkeypatch,
):
    from app import message_deliveries

    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _target: None)
    delivery_id = await _accept(message_deliveries)
    message_deliveries.mark_message_delivery_failed_before_submit(
        delivery_id, RuntimeError("worktree layout unavailable"),
    )
    first_process = _Manager(delivery_db, fail_notice=True)

    with pytest.raises(RuntimeError, match="sender unavailable"):
        await message_deliveries.notify_message_delivery_failure(
            delivery_id, manager=first_process,
        )
    assert message_deliveries._failure_notice(delivery_id)["delivered_at"] is None

    restarted_manager = _Manager(delivery_db)
    assert await message_deliveries.recover_message_delivery_failure_notices(
        restarted_manager,
    ) == 1
    assert await message_deliveries.recover_message_delivery_failure_notices(
        restarted_manager,
    ) == 0
    assert len(restarted_manager.notices) == 1
