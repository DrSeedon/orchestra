"""Frozen fake-only behavioral RED oracles for #333 C1 + C5.

The tests enter through the production TG HTTP route or MCP wrapper.  Every
Telegram/provider boundary is replaced before the route is called; this file
must never contact Telegram, start Orchestra, or mutate the live database.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI


SOURCE_ID = "source-session-333"
SOURCE_NAME = "source-333"
SCOPE = "/scope-333"
PRIMARY_CHAT = -100333001
PRIMARY_THREAD = 3331
MIRROR_CHAT = -100333002
MIRROR_THREAD = 3332

EVENT_1 = "00000000-0000-4000-8000-000000000331"
EVENT_2 = "00000000-0000-4000-8000-000000000332"
EVENT_3 = "00000000-0000-4000-8000-000000000333"
EVENT_4 = "00000000-0000-4000-8000-000000000334"


def _session_record(*, session_id: str, name: str, scope: str, role: str = "worker"):
    return {
        "id": session_id,
        "name": name,
        "scope": scope,
        "cwd": f"/tmp/{name}",
        "model": "gpt-5.6-sol",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": f"/tmp/{name}",
        "branch": f"task-333/{name}",
        "base_branch": "main",
        "needs_switch": 0,
        "task_id": "333",
        "role": role,
        "is_orchestrator": role in {"orchestrator", "sub-orchestrator"},
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "parent_name": "",
    }


def _optional_delivery_module():
    if importlib.util.find_spec("app.tg_file_deliveries") is None:
        return None
    return importlib.import_module("app.tg_file_deliveries")


def _delivery_module():
    module = _optional_delivery_module()
    assert module is not None, (
        "#333 missing behavior: durable TG route has no tg_file_deliveries owner"
    )
    return module


def _required_callable(owner, name: str):
    value = getattr(owner, name, None)
    assert callable(value), f"#333 missing behavior: {owner!r}.{name} is not callable"
    return value


async def _spin_until(predicate, *, ticks: int = 400) -> bool:
    """Yield deterministic scheduler ticks; correctness is not a wall-clock budget."""
    for _ in range(ticks):
        if predicate():
            return True
        await asyncio.sleep(0)
    return bool(predicate())


class _ExplodingBot:
    def __getattr__(self, name):
        raise AssertionError(f"live/direct bot seam was reached: {name}")


class _ProviderDouble:
    """One injected provider boundary with an observable call count and snapshot path."""

    def __init__(self):
        self.calls: list[dict] = []
        self.behavior = None

    async def __call__(
        self,
        chat_id: int,
        snapshot_path: str,
        caption: str,
        thread_id: int | None,
        *,
        is_photo: bool,
    ):
        call = {
            "chat_id": chat_id,
            "snapshot_path": str(snapshot_path),
            "caption": caption,
            "thread_id": thread_id,
            "is_photo": is_photo,
        }
        self.calls.append(call)
        if self.behavior is not None:
            return await self.behavior(call)
        call["bytes"] = Path(snapshot_path).read_bytes()
        return SimpleNamespace(
            message_id=33300 + len(self.calls),
            chat=SimpleNamespace(id=chat_id),
            message_thread_id=thread_id,
        )


@pytest.fixture
def delivery_world(tmp_path, monkeypatch):
    from app import db
    from app.mcp_proof import issue_mcp_proof
    from app.routes import system as system_routes
    from app.routes import tg as tg_routes
    import app.tg_bridge as bridge

    db_path = tmp_path / "tg-file-delivery-333.db"
    spool_root = tmp_path / "tg-file-outbox"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    db.save_session(_session_record(
        session_id=SOURCE_ID,
        name=SOURCE_NAME,
        scope=SCOPE,
        role="orchestrator",
    ))

    monkeypatch.setattr(system_routes, "_is_safe_path", lambda _path: True)
    monkeypatch.setattr(bridge, "bot", _ExplodingBot())
    monkeypatch.setattr(
        bridge,
        "config",
        {
            "group_id": PRIMARY_CHAT,
            "topics": {SOURCE_NAME: PRIMARY_THREAD},
            "topic_names": {SOURCE_NAME: SOURCE_NAME},
            "mirrors": {},
        },
    )
    monkeypatch.setattr(
        bridge,
        "_resolve_topic",
        lambda scope, sender: (SOURCE_NAME, PRIMARY_THREAD),
    )

    legacy_calls = []

    async def legacy_send(path, caption, scope, sender, as_document=False):
        legacy_calls.append((path, caption, scope, sender, as_document))
        return {"ok": True, "message_id": 999, "chat_id": PRIMARY_CHAT}

    # Current code reaches this synchronous path.  C1 must bypass it; returning a
    # harmless 200 makes the RED an assertion about 202 semantics, not a network error.
    monkeypatch.setattr(bridge, "send_file_to_tg", legacy_send)

    provider = _ProviderDouble()
    monkeypatch.setattr(
        bridge, "_submit_file_snapshot_once", provider, raising=False,
    )
    module = _optional_delivery_module()
    if module is not None:
        monkeypatch.setattr(module, "SPOOL_ROOT", spool_root, raising=False)
        monkeypatch.setattr(
            module, "_submit_file_snapshot_once", provider, raising=False,
        )

    app = FastAPI()
    app.include_router(tg_routes.router)
    proof = issue_mcp_proof(SOURCE_ID)
    headers = {
        "X-Orchestra-Session-Id": SOURCE_ID,
        "X-Orchestra-Mcp-Proof": proof,
    }
    return SimpleNamespace(
        app=app,
        bridge=bridge,
        db=db,
        db_path=db_path,
        spool_root=spool_root,
        provider=provider,
        legacy_calls=legacy_calls,
        headers=headers,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )


async def _post_file(
    world,
    source: Path,
    event_id: str,
    *,
    caption: str = "artifact 333",
    as_document: bool = False,
):
    transport = httpx.ASGITransport(app=world.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/api/tg/send_file",
            headers=world.headers,
            json={
                "path": str(source),
                "caption": caption,
                "scope": SCOPE,
                "sender": SOURCE_NAME,
                "as_document": as_document,
                "event_id": event_id,
            },
        )


async def _get_status(world, event_id: str, *, headers=None):
    transport = httpx.ASGITransport(app=world.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(
            f"/api/tg/file-deliveries/{event_id}",
            headers=world.headers if headers is None else headers,
        )


async def _wait_status(world, event_id: str, state: str):
    seen = None
    for _ in range(400):
        response = await _get_status(world, event_id)
        if response.status_code == 200:
            seen = response.json()
            if seen["delivery_state"] == state:
                return seen
        await asyncio.sleep(0)
    pytest.fail(f"#333 status did not become {state}; last={seen!r}")


def _event_row(world, event_id: str):
    with world.db._conn() as connection:
        row = connection.execute(
            "SELECT * FROM tg_file_deliveries WHERE event_id=?", (event_id,),
        ).fetchone()
    return dict(row) if row else None


def _target_rows(world, event_id: str):
    with world.db._conn() as connection:
        rows = connection.execute(
            "SELECT * FROM tg_file_delivery_targets "
            "WHERE event_id=? ORDER BY target_kind",
            (event_id,),
        ).fetchall()
    return [dict(row) for row in rows]


# Positive controls: if either fails, a RED below is a broken harness rather than
# evidence about missing production behavior.
@pytest.mark.asyncio
async def test_t333_control_provider_double_reads_only_the_supplied_snapshot(tmp_path):
    snapshot = tmp_path / "snapshot.bin"
    snapshot.write_bytes(b"snapshot-control-333")
    os.chmod(snapshot, 0o600)
    provider = _ProviderDouble()

    result = await provider(
        PRIMARY_CHAT, str(snapshot), "caption", PRIMARY_THREAD, is_photo=False,
    )

    assert result.message_id == 33301
    assert provider.calls == [{
        "chat_id": PRIMARY_CHAT,
        "snapshot_path": str(snapshot),
        "caption": "caption",
        "thread_id": PRIMARY_THREAD,
        "is_photo": False,
        "bytes": b"snapshot-control-333",
    }]


@pytest.mark.asyncio
async def test_t333_control_timeout_double_crosses_boundary_exactly_once(tmp_path):
    snapshot = tmp_path / "timeout.bin"
    snapshot.write_bytes(b"timeout-control-333")
    provider = _ProviderDouble()

    async def timeout(_call):
        raise TimeoutError("synthetic provider timeout")

    provider.behavior = timeout
    with pytest.raises(TimeoutError, match="synthetic provider timeout"):
        await provider(
            PRIMARY_CHAT, str(snapshot), "caption", PRIMARY_THREAD, is_photo=True,
        )
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_t333_t1_accepts_0600_snapshot_before_provider_and_source_can_disappear(
    delivery_world,
):
    world = delivery_world
    source = world.tmp_path / "source.png"
    source.write_bytes(b"immutable-image-333")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked(call):
        entered.set()
        await release.wait()
        call["bytes"] = Path(call["snapshot_path"]).read_bytes()
        return SimpleNamespace(
            message_id=33301,
            chat=SimpleNamespace(id=call["chat_id"]),
            message_thread_id=call["thread_id"],
        )

    world.provider.behavior = blocked
    response = await _post_file(world, source, EVENT_1)

    assert response.status_code == 202, (
        "#333 RED: /api/tg/send_file still reports synchronous provider success"
    )
    receipt = response.json()
    assert receipt["acceptance"] == "ACCEPTED"
    assert receipt["event_id"] == EVENT_1
    assert receipt["delivery_state"] == "QUEUED"
    assert len(receipt["payload_hash"]) == 64
    assert receipt["status_url"] == f"/api/tg/file-deliveries/{EVENT_1}"
    assert world.legacy_calls == []

    assert await _spin_until(entered.is_set), "#333 provider runner never reached fake seam"
    submitting = (await _get_status(world, EVENT_1)).json()
    assert submitting["children"]["primary"]["state"] == "SUBMITTING"
    snapshot = Path(world.provider.calls[0]["snapshot_path"])
    assert snapshot != source
    assert snapshot.is_file()
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o600
    assert snapshot.read_bytes() == b"immutable-image-333"

    source.unlink()
    release.set()
    sent = await _wait_status(world, EVENT_1, "SENT")
    assert world.provider.calls[0]["bytes"] == b"immutable-image-333"
    assert sent["children"]["primary"]["message_id"] == 33301
    assert len(world.provider.calls) == 1


@pytest.mark.asyncio
async def test_t333_t1_same_event_hash_is_one_acceptance_and_changed_hash_conflicts(
    delivery_world,
):
    world = delivery_world
    source = world.tmp_path / "same.bin"
    source.write_bytes(b"same-payload-333")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked(call):
        entered.set()
        await release.wait()
        call["bytes"] = Path(call["snapshot_path"]).read_bytes()
        return SimpleNamespace(message_id=33302, chat=SimpleNamespace(id=call["chat_id"]))

    world.provider.behavior = blocked
    first, second = await asyncio.gather(
        _post_file(world, source, EVENT_1),
        _post_file(world, source, EVENT_1),
    )
    assert [first.status_code, second.status_code] == [202, 202]
    receipts = [first.json(), second.json()]
    assert {item["acceptance"] for item in receipts} == {
        "ACCEPTED", "ALREADY_ACCEPTED",
    }
    assert len({item["payload_hash"] for item in receipts}) == 1
    assert len({item["accept_seq"] for item in receipts}) == 1
    assert await _spin_until(entered.is_set)
    assert len(world.provider.calls) == 1

    source.write_bytes(b"DIFFERENT-payload-333")
    conflict = await _post_file(world, source, EVENT_1)
    assert conflict.status_code == 409
    error = conflict.json()["error"]
    assert error["code"] == "IDEMPOTENCY_CONFLICT"
    assert error["outcome_unknown"] is False
    with world.db._conn() as connection:
        assert connection.execute(
            "SELECT count(*) FROM tg_file_deliveries WHERE event_id=?", (EVENT_1,),
        ).fetchone()[0] == 1

    release.set()
    await _wait_status(world, EVENT_1, "SENT")
    assert len(world.provider.calls) == 1


@pytest.mark.asyncio
async def test_t333_t1_timeout_after_boundary_calls_provider_once_and_stays_unknown(
    delivery_world,
):
    world = delivery_world
    source = world.tmp_path / "timeout.jpg"
    source.write_bytes(b"timeout-payload-333")

    async def timeout(_call):
        raise TimeoutError("timeout after provider boundary")

    world.provider.behavior = timeout
    accepted = await _post_file(world, source, EVENT_1)
    assert accepted.status_code == 202
    unknown = await _wait_status(world, EVENT_1, "UNKNOWN")
    child = unknown["children"]["primary"]
    assert child["state"] == "UNKNOWN"
    assert child["error"]["outcome_unknown"] is True
    assert child["error"]["retryable"] is False
    assert unknown["next_action"]["tool"] == "file_delivery_status"
    assert len(world.provider.calls) == 1

    repeated = await _post_file(world, source, EVENT_1)
    assert repeated.status_code == 202
    assert repeated.json()["acceptance"] == "ALREADY_ACCEPTED"
    assert repeated.json()["delivery_state"] == "UNKNOWN"
    for _ in range(50):
        await asyncio.sleep(0)
    assert len(world.provider.calls) == 1, (
        "#333 UNKNOWN was blindly replayed after same-id reconciliation"
    )


@pytest.mark.asyncio
async def test_t333_t1_restart_replays_queued_but_converts_submitting_to_unknown(
    delivery_world,
):
    world = delivery_world
    module = _optional_delivery_module()
    if module is not None:
        original_runner = _required_callable(module, "ensure_chat_runner")
        world.monkeypatch.setattr(module, "ensure_chat_runner", lambda _chat_id: None)
    else:
        original_runner = None

    queued_source = world.tmp_path / "queued.bin"
    in_flight_source = world.tmp_path / "in-flight.bin"
    queued_source.write_bytes(b"queued-after-restart-333")
    in_flight_source.write_bytes(b"submitting-at-restart-333")
    queued = await _post_file(world, queued_source, EVENT_1)
    in_flight = await _post_file(world, in_flight_source, EVENT_2)
    assert [queued.status_code, in_flight.status_code] == [202, 202]

    module = _delivery_module()
    assert original_runner is not None
    with world.db._conn() as connection:
        connection.execute(
            "UPDATE tg_file_delivery_targets SET state='SUBMITTING' "
            "WHERE event_id=? AND target_kind='primary'",
            (EVENT_2,),
        )
    world.monkeypatch.setattr(module, "ensure_chat_runner", original_runner)

    recover = _required_callable(module, "recover_file_deliveries")
    await recover()
    sent = await _wait_status(world, EVENT_1, "SENT")
    unknown = await _wait_status(world, EVENT_2, "UNKNOWN")
    assert sent["children"]["primary"]["state"] == "SENT"
    assert unknown["children"]["primary"]["state"] == "UNKNOWN"
    assert world.provider.calls[0]["bytes"] == b"queued-after-restart-333"
    assert len(world.provider.calls) == 1

    await recover()
    for _ in range(50):
        await asyncio.sleep(0)
    assert len(world.provider.calls) == 1


@pytest.mark.asyncio
async def test_t333_t1_pre_submit_snapshot_failure_is_retryable_with_same_event_only(
    delivery_world,
):
    world = delivery_world
    module = _optional_delivery_module()
    if module is not None:
        original_runner = _required_callable(module, "ensure_chat_runner")
        world.monkeypatch.setattr(module, "ensure_chat_runner", lambda _chat_id: None)
    else:
        original_runner = None
    source = world.tmp_path / "pre-submit.bin"
    source.write_bytes(b"pre-submit-333")

    accepted = await _post_file(world, source, EVENT_1)
    assert accepted.status_code == 202
    module = _delivery_module()
    assert original_runner is not None
    row = _event_row(world, EVENT_1)
    Path(row["snapshot_path"]).unlink()
    run_chat = _required_callable(module, "run_chat_deliveries")
    await run_chat(PRIMARY_CHAT)
    failed = await _wait_status(world, EVENT_1, "FAILED_BEFORE_SUBMIT")
    failure = failed["children"]["primary"]["error"]
    assert failure["outcome_unknown"] is False
    assert failure["retryable"] is True
    assert world.provider.calls == []

    world.monkeypatch.setattr(module, "ensure_chat_runner", original_runner)
    retried = await _post_file(world, source, EVENT_1)
    assert retried.status_code == 202
    assert retried.json()["acceptance"] == "ALREADY_ACCEPTED"
    assert retried.json()["accept_seq"] == accepted.json()["accept_seq"]
    await _wait_status(world, EVENT_1, "SENT")
    assert len(world.provider.calls) == 1


@pytest.mark.asyncio
async def test_t333_t2_two_runners_keep_per_chat_fifo_and_one_lease_generation(
    delivery_world,
):
    world = delivery_world
    module = _optional_delivery_module()
    if module is not None:
        original_runner = _required_callable(module, "ensure_chat_runner")
        world.monkeypatch.setattr(module, "ensure_chat_runner", lambda _chat_id: None)
    else:
        original_runner = None
    first_source = world.tmp_path / "first.bin"
    second_source = world.tmp_path / "second.bin"
    first_source.write_bytes(b"first-fifo-333")
    second_source.write_bytes(b"second-fifo-333")
    first_entered = asyncio.Event()
    first_release = asyncio.Event()

    async def ordered(call):
        call["bytes"] = Path(call["snapshot_path"]).read_bytes()
        if call["bytes"] == b"first-fifo-333":
            first_entered.set()
            await first_release.wait()
            message_id = 33321
        else:
            message_id = 33322
        return SimpleNamespace(message_id=message_id, chat=SimpleNamespace(id=call["chat_id"]))

    world.provider.behavior = ordered
    first = await _post_file(world, first_source, EVENT_1)
    second = await _post_file(world, second_source, EVENT_2)
    assert [first.status_code, second.status_code] == [202, 202]
    module = _delivery_module()
    assert original_runner is not None
    run_chat = _required_callable(module, "run_chat_deliveries")

    runner_a = asyncio.create_task(run_chat(PRIMARY_CHAT))
    runner_b = asyncio.create_task(run_chat(PRIMARY_CHAT))
    assert await _spin_until(first_entered.is_set)
    for _ in range(50):
        await asyncio.sleep(0)
    assert [call["bytes"] for call in world.provider.calls] == [b"first-fifo-333"]
    first_release.set()
    await asyncio.gather(runner_a, runner_b)
    assert [call["bytes"] for call in world.provider.calls] == [
        b"first-fifo-333", b"second-fifo-333",
    ]
    assert (await _get_status(world, EVENT_1)).json()["delivery_state"] == "SENT"
    assert (await _get_status(world, EVENT_2)).json()["delivery_state"] == "SENT"
    with world.db._conn() as connection:
        lease = connection.execute(
            "SELECT generation FROM tg_file_chat_leases WHERE chat_id=?",
            (PRIMARY_CHAT,),
        ).fetchone()
        generations = {
            row[0] for row in connection.execute(
                "SELECT lease_generation FROM tg_file_delivery_targets "
                "WHERE event_id IN (?, ?)", (EVENT_1, EVENT_2),
            ).fetchall()
        }
    assert lease is not None and lease[0] > 0
    assert generations == {lease[0]}


@pytest.mark.asyncio
async def test_t333_t2_queue_full_returns_retry_after_without_snapshot_or_submit(
    delivery_world,
):
    world = delivery_world
    module = _optional_delivery_module()
    if module is not None:
        world.monkeypatch.setattr(module, "MAX_PENDING_PER_CHAT", 1, raising=False)
        world.monkeypatch.setattr(module, "MAX_PENDING_TOTAL", 8, raising=False)
        world.monkeypatch.setattr(module, "ensure_chat_runner", lambda _chat_id: None)
    first_source = world.tmp_path / "capacity-1.bin"
    second_source = world.tmp_path / "capacity-2.bin"
    first_source.write_bytes(b"capacity-one-333")
    second_source.write_bytes(b"capacity-two-333")

    first = await _post_file(world, first_source, EVENT_1)
    assert first.status_code == 202
    full = await _post_file(world, second_source, EVENT_2)
    assert full.status_code == 429
    error = full.json()["error"]
    assert error["code"] == "TG_FILE_QUEUE_FULL"
    assert error["retryable"] is True
    assert error["outcome_unknown"] is False
    assert int(full.headers["Retry-After"]) >= 1
    assert _event_row(world, EVENT_2) is None
    first_snapshot = Path(_event_row(world, EVENT_1)["snapshot_path"])
    assert {
        path for path in world.spool_root.rglob("*") if path.is_file()
    } == {first_snapshot}, "#333 full admission left an orphan snapshot"
    assert world.provider.calls == []

    repeated = await _post_file(world, first_source, EVENT_1)
    assert repeated.status_code == 202
    assert repeated.json()["acceptance"] == "ALREADY_ACCEPTED"


@pytest.mark.asyncio
async def test_t333_t2_mirror_failure_never_rewrites_primary_sent(
    delivery_world,
):
    world = delivery_world
    world.bridge.config["mirrors"] = {
        SOURCE_NAME: {"chat_id": MIRROR_CHAT, "topic_id": MIRROR_THREAD},
    }
    source = world.tmp_path / "mirrored.png"
    source.write_bytes(b"mirrored-image-333")

    async def split_outcome(call):
        call["bytes"] = Path(call["snapshot_path"]).read_bytes()
        if call["chat_id"] == MIRROR_CHAT:
            raise TimeoutError("synthetic mirror timeout")
        return SimpleNamespace(message_id=33331, chat=SimpleNamespace(id=PRIMARY_CHAT))

    world.provider.behavior = split_outcome
    accepted = await _post_file(world, source, EVENT_1)
    assert accepted.status_code == 202
    status = None
    for _ in range(400):
        response = await _get_status(world, EVENT_1)
        if response.status_code == 200:
            status = response.json()
            children = status["children"]
            if (
                children.get("primary", {}).get("state") == "SENT"
                and children.get("mirror", {}).get("state") == "UNKNOWN"
            ):
                break
        await asyncio.sleep(0)
    assert status is not None
    assert status["delivery_state"] == "SENT"
    assert status["children"]["primary"]["message_id"] == 33331
    assert status["children"]["mirror"]["state"] == "UNKNOWN"
    assert status["children"]["mirror"]["error"]["outcome_unknown"] is True
    assert sorted(call["chat_id"] for call in world.provider.calls) == sorted(
        [PRIMARY_CHAT, MIRROR_CHAT]
    )
    assert len(world.provider.calls) == 2


@pytest.mark.asyncio
async def test_t333_t3_status_is_owner_scoped_and_legacy_tool_returns_durable_id(
    delivery_world,
    monkeypatch,
):
    world = delivery_world
    source = world.tmp_path / "owner.bin"
    source.write_bytes(b"owner-status-333")
    accepted = await _post_file(world, source, EVENT_1)
    assert accepted.status_code == 202
    owner = await _get_status(world, EVENT_1)
    assert owner.status_code == 200
    assert owner.json()["event_id"] == EVENT_1

    other_id = "other-source-session-333"
    world.db.save_session(_session_record(
        session_id=other_id,
        name="other-source-333",
        scope="/other-333",
        role="orchestrator",
    ))
    from app.mcp_proof import issue_mcp_proof
    denied = await _get_status(
        world,
        EVENT_1,
        headers={
            "X-Orchestra-Session-Id": other_id,
            "X-Orchestra-Mcp-Proof": issue_mcp_proof(other_id),
        },
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["outcome_unknown"] is False

    import app.mcp_stdio as mcp

    fixed_id = EVENT_3

    class FixedUUID:
        def __str__(self):
            return fixed_id

    monkeypatch.setattr(mcp.uuid, "uuid4", lambda: FixedUUID())
    monkeypatch.setattr(mcp, "SCOPE", SCOPE)
    monkeypatch.setattr(mcp, "WORKER_NAME", SOURCE_NAME)
    calls = []
    receipt = {
        "ok": True,
        "acceptance": "ACCEPTED",
        "event_id": fixed_id,
        "delivery_state": "QUEUED",
        "payload_hash": "a" * 64,
        "accept_seq": 7,
        "status_url": f"/api/tg/file-deliveries/{fixed_id}",
        "children": {"primary": {"state": "QUEUED"}},
        "next_action": {},
    }

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return receipt

    monkeypatch.setattr(mcp, "_api", fake_api)
    output = await mcp.send_file(str(source), "legacy caption")
    assert isinstance(output, str)
    assert "accepted" in output.lower()
    assert fixed_id in output
    assert "QUEUED" in output
    assert calls[0][0:2] == ("POST", "/api/tg/send_file")
    assert calls[0][2]["json"]["event_id"] == fixed_id
    assert "event_id" in inspect.signature(mcp.send_file).parameters

    status_tool = _required_callable(mcp, "file_delivery_status")
    status = await status_tool(fixed_id)
    assert status == receipt
    assert calls[-1][0:2] == (
        "GET", f"/api/tg/file-deliveries/{fixed_id}",
    )
    assert "file_delivery_status" in mcp.READ_ONLY_MCP_TOOLS


@pytest.mark.asyncio
async def test_t333_t3_legacy_timeout_reconciles_same_generated_id_before_return(
    delivery_world,
    monkeypatch,
):
    world = delivery_world
    source = world.tmp_path / "legacy-timeout.bin"
    source.write_bytes(b"legacy-timeout-333")
    import app.mcp_stdio as mcp

    class FixedUUID:
        def __str__(self):
            return EVENT_4

    monkeypatch.setattr(mcp.uuid, "uuid4", lambda: FixedUUID())
    monkeypatch.setattr(mcp, "SCOPE", SCOPE)
    monkeypatch.setattr(mcp, "WORKER_NAME", SOURCE_NAME)
    calls = []
    receipt = {
        "ok": True,
        "acceptance": "ALREADY_ACCEPTED",
        "event_id": EVENT_4,
        "delivery_state": "UNKNOWN",
        "payload_hash": "b" * 64,
        "accept_seq": 8,
        "status_url": f"/api/tg/file-deliveries/{EVENT_4}",
        "children": {"primary": {"state": "UNKNOWN"}},
        "next_action": {
            "tool": "file_delivery_status",
            "arguments": {"event_id": EVENT_4},
        },
    }

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "POST":
            assert kwargs["json"].get("event_id") == EVENT_4, (
                "#333 RED: legacy send_file did not mint one durable id before POST"
            )
            raise mcp.ApiToolError(
                code="transport_timeout",
                message="synthetic HTTP timeout",
                outcome_unknown=True,
                details={"request_not_sent": False},
            )
        return receipt

    monkeypatch.setattr(mcp, "_api", fake_api)
    output = await mcp.send_file(str(source), "legacy timeout")
    assert EVENT_4 in output
    assert "UNKNOWN" in output
    assert [(method, path) for method, path, _kwargs in calls] == [
        ("POST", "/api/tg/send_file"),
        ("GET", f"/api/tg/file-deliveries/{EVENT_4}"),
    ]


@pytest.mark.asyncio
async def test_t333_t3_cleanup_keeps_unknown_quarantine_and_rollback_never_replays(
    delivery_world,
):
    world = delivery_world
    sent_source = world.tmp_path / "sent-cleanup.bin"
    unknown_source = world.tmp_path / "unknown-cleanup.bin"
    sent_source.write_bytes(b"sent-cleanup-333")
    unknown_source.write_bytes(b"unknown-cleanup-333")

    async def terminal(call):
        call["bytes"] = Path(call["snapshot_path"]).read_bytes()
        if call["bytes"] == b"unknown-cleanup-333":
            raise TimeoutError("unknown remains quarantined")
        return SimpleNamespace(message_id=33341, chat=SimpleNamespace(id=call["chat_id"]))

    world.provider.behavior = terminal
    sent_accept = await _post_file(world, sent_source, EVENT_1)
    unknown_accept = await _post_file(world, unknown_source, EVENT_2)
    assert [sent_accept.status_code, unknown_accept.status_code] == [202, 202]
    await _wait_status(world, EVENT_1, "SENT")
    await _wait_status(world, EVENT_2, "UNKNOWN")
    module = _delivery_module()
    cleanup = _required_callable(module, "cleanup_file_deliveries")

    await cleanup(now=datetime(2100, 1, 1, tzinfo=timezone.utc))
    sent_row = _event_row(world, EVENT_1)
    unknown_row = _event_row(world, EVENT_2)
    assert sent_row is not None and unknown_row is not None, (
        "#333 cleanup deleted idempotency receipts"
    )
    assert not sent_row["snapshot_path"] or not Path(sent_row["snapshot_path"]).exists()
    assert unknown_row["quarantined_at"]
    unknown_snapshot = Path(unknown_row["snapshot_path"])
    assert unknown_snapshot.is_file()
    assert "quarantine" in unknown_snapshot.parts
    assert stat.S_IMODE(unknown_snapshot.stat().st_mode) == 0o600
    calls_before_rollback = len(world.provider.calls)

    world.monkeypatch.setattr(module, "ADMISSION_ENABLED", False, raising=False)
    fresh = world.tmp_path / "after-rollback.bin"
    fresh.write_bytes(b"new-after-rollback-333")
    disabled = await _post_file(world, fresh, EVENT_3)
    assert disabled.status_code == 503
    disabled_error = disabled.json()["error"]
    assert disabled_error["code"] == "TG_FILE_OUTBOX_DISABLED"
    assert disabled_error["outcome_unknown"] is False

    existing = await _post_file(world, unknown_source, EVENT_2)
    assert existing.status_code == 202
    assert existing.json()["delivery_state"] == "UNKNOWN"
    recover = _required_callable(module, "recover_file_deliveries")
    await recover()
    for _ in range(50):
        await asyncio.sleep(0)
    assert len(world.provider.calls) == calls_before_rollback
    status = await _get_status(world, EVENT_2)
    assert status.status_code == 200
    assert status.json()["delivery_state"] == "UNKNOWN"
