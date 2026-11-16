"""Always-on behavioral contracts; isolated SQLite, fake transports, no provider calls."""
import asyncio
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app import approvals, db, dreaming, mailbox, message_deliveries, outbox, timers
from app.events import MessageProvenance
from app.session_state import AgentStatus

PROVENANCE = MessageProvenance("agent",("sender",),"direct_message")


@pytest.fixture
def store():
    db.init_db()
    return db


def event(body="body",**kwargs):
    return mailbox.enqueue_event("worker","/scope","sender",body,provenance=PROVENANCE,**kwargs)


def timer(**kwargs):
    return timers.set_timer("worker","/scope","alarm",**kwargs)


def outgoing(body="hello",**kwargs):
    return outbox.enqueue("worker","/scope","dashboard","worker",body,**kwargs)


def card(**kwargs):
    return approvals.request_approval("worker","/scope","deploy","Deploy reviewed diff",**kwargs)


def test_schema_online_upgrade_is_repeatable_and_preserves_data(store):
    event()
    with db._conn() as c:
        c.execute("DROP TRIGGER always_on_cancel_mailbox")
        c.execute("DROP TRIGGER always_on_cancel_message_deliveries")
        for table in ("timers","outbox_messages","outbox_said_ledger","deferred_approvals","dreaming_runs"):
            c.execute(f"DROP TABLE {table}")
        c.execute("DROP INDEX idx_mailbox_idempotency")
        c.execute("ALTER TABLE mailbox DROP COLUMN idempotency_key")
    db.init_db()
    db.init_db()
    assert mailbox.pending("worker","/scope")[0]["body"] == "body"
    with db._conn() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 3
        assert "idempotency_key" in {r[1] for r in c.execute("PRAGMA table_info(mailbox)")}
    assert timer(delay_seconds=5)["state"] == "active"


def test_inbox_idempotency_and_legacy_return(store):
    first = event(idempotency_key="one")
    assert event("retry",idempotency_key="one") == {"id":first["id"],"deduplicated":True}
    assert mailbox.enqueue("worker","/scope","sender","retry",provenance=PROVENANCE,
                           idempotency_key="one") == first["id"]
    assert event()["id"] != event()["id"]
    other = mailbox.enqueue("worker","/other","sender","other",provenance=PROVENANCE,idempotency_key="one")
    assert other != first["id"]


def test_concurrent_idempotency_and_claim(store):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _:event(idempotency_key="race"),range(12)))
    assert sum(not r["deduplicated"] for r in results) == 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _:mailbox.claim("worker","/scope"),range(4)))
    assert sum(len(c) for c in claims) == 1


def test_structured_batch_preserves_single_message_and_bodies(store):
    event("first")
    assert mailbox.format_event_batch(mailbox.pending("worker","/scope")) == "[from:sender] first"
    event("second")
    text = mailbox.format_event_batch(mailbox.pending("worker","/scope"))
    assert text.startswith('<event-inbox count="2">')
    assert "[event 1/2] [from:sender] first" in text
    assert "[event 2/2] [from:sender] second" in text
    assert text.endswith("</event-inbox>")


def fake_manager(status=AgentStatus.IDLE):
    received=[]
    async def deliver(items):
        received.append(items)
        await asyncio.sleep(0.01)
        mailbox.mark_delivered([m["id"] for m in items])
    session=SimpleNamespace(id="session",name="worker",scope="/scope",status=status,_compacting=False,
                            _turns=SimpleNamespace(_deliver_mailbox=deliver))
    manager=SimpleNamespace(sessions={"session":session},get_by_name=lambda *_:session,
                            ensure_loaded_by_id=AsyncMock(return_value=session))
    return manager,session,received


@pytest.mark.asyncio
async def test_burst_has_one_wake_and_one_batch(store):
    manager,session,received=fake_manager()
    async def arrive(i):
        event(str(i))
        return await mailbox.wake_recipient("worker","/scope",manager=manager)
    await asyncio.gather(*(arrive(i) for i in range(20)))
    assert len(received) == 1 and len(received[0]) == 20
    assert not mailbox.pending("worker","/scope")
    assert mailbox._wake_tasks == {}


@pytest.mark.asyncio
async def test_busy_inbox_recovers_and_does_not_compete(store):
    manager,session,received=fake_manager(AgentStatus.RUNNING)
    event(idempotency_key="busy")
    assert not await mailbox.wake_recipient("worker","/scope",manager=manager,coalesce_delay_s=0)
    assert not received
    session.status=AgentStatus.IDLE
    assert await mailbox.wake_recipient("worker","/scope",manager=manager,coalesce_delay_s=0)
    assert len(received) == 1


@pytest.mark.asyncio
async def test_wake_caller_cancellation_does_not_cancel_shared_delivery(store):
    manager,session,received=fake_manager()
    event()
    waiter=asyncio.create_task(mailbox.wake_recipient("worker","/scope",manager=manager))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await asyncio.sleep(0.08)
    assert len(received) == 1


@pytest.mark.parametrize("kwargs",[
    {},{"delay_seconds":-1},{"delay_seconds":float("nan")},
    {"kind":"invalid","delay_seconds":1},{"kind":"schedule","interval_seconds":9},
    {"kind":"schedule"},{"kind":"schedule","cron_expr":"bad"},
    {"kind":"schedule","cron_expr":"60 * * * *"},
    {"kind":"schedule","cron_expr":"* * * * *","interval_seconds":10},
    {"delay_seconds":1,"due_at":20},{"delay_seconds":1,"max_fires":0},
])
def test_timer_validation(store,kwargs):
    with pytest.raises(ValueError):
        timer(**kwargs)


@pytest.mark.asyncio
async def test_one_shot_atomic_idempotent_fire_and_restart_wake(store):
    row=timer(delay_seconds=0,idempotency_key="alarm")
    assert timer(delay_seconds=5,idempotency_key="alarm")["id"] == row["id"]
    assert await timers.tick_timers(now=time.time()+1) == 1
    assert await timers.tick_timers(now=time.time()+2) == 0
    pending=mailbox.pending("worker","/scope")
    assert len(pending) == 1 and pending[0]["provenance"].subtype == "timer"
    assert pending[0]["provenance"].ref == row["id"]
    manager,_,received=fake_manager()
    await mailbox.recover_event_wakes(manager)
    assert len(received) == 1


@pytest.mark.asyncio
async def test_timer_transaction_rolls_back_when_event_cannot_persist(store,monkeypatch):
    row=timer(delay_seconds=0)
    def fail(*a,**k):
        raise sqlite3.OperationalError("injected failure")
    monkeypatch.setattr(mailbox,"enqueue_event",fail)
    with pytest.raises(sqlite3.OperationalError):
        await timers.tick_timers(now=time.time()+1)
    assert timers.list_timers()[0]["fire_count"] == 0


@pytest.mark.asyncio
async def test_interval_downtime_skips_missed_slots_and_max_fires(store):
    row=timer(kind="schedule",interval_seconds=10,max_fires=2)
    now=row["next_due_at"]+1000
    assert await timers.tick_timers(now=now) == 1
    current=timers.list_timers()[0]
    assert current["fire_count"] == 1 and now < current["next_due_at"] <= now+10
    assert await timers.tick_timers(now=current["next_due_at"]) == 1
    assert timers.list_timers()[0]["state"] == "completed"
    assert len(mailbox.pending("worker","/scope")) == 2


@pytest.mark.parametrize("sender_filter,scope_filter,sender,expected",[
    ("*","","sender",True),("any","","sender",True),("one, sender","","sender",True),
    ("other","","sender",False),("","/scope","sender",True),("","/other","sender",False),
    ("","","sender",False),("other","*","sender",False),
])
def test_timer_inbound_cancellation_filters(store,sender_filter,scope_filter,sender,expected):
    row=timer(delay_seconds=100,cancel_on_sender=sender_filter,cancel_on_scope=scope_filter)
    mailbox.enqueue("worker","/scope",sender,"reply",provenance=PROVENANCE)
    current=timers.list_timers()[0]
    assert (current["state"] == "cancelled") is expected
    if expected:
        assert current["cancelled_reason"] == f"auto_cancelled_by_inbound:{sender}"


@pytest.mark.asyncio
async def test_timer_event_does_not_cancel_another_timer(store):
    waiting=timer(delay_seconds=100,cancel_on_sender="*")
    timer(delay_seconds=0)
    await timers.tick_timers(now=time.time()+1)
    assert next(r for r in timers.list_timers() if r["id"] == waiting["id"])["state"] == "active"
    assert timers.cancel_timer(waiting["id"])
    assert not timers.cancel_timer(waiting["id"])


@pytest.mark.parametrize("expression,tz,start,expected",[
    ("*/15 * * * *","UTC","2026-11-16T09:01:00+00:00","2026-11-16T09:15:00+00:00"),
    ("0 9 * * 1-5","Europe/Moscow","2026-11-16T05:59:00+00:00","2026-11-16T06:00:00+00:00"),
    ("30 2 * * *","America/New_York","2026-03-08T06:00:00+00:00","2026-03-09T06:30:00+00:00"),
    ("30 1 * * *","America/New_York","2026-11-01T05:31:00+00:00","2026-11-01T06:30:00+00:00"),
    ("0 0 1 * 1","UTC","2026-11-02T00:01:00+00:00","2026-11-09T00:00:00+00:00"),
])
def test_cron_timezone_dst_and_calendar(expression,tz,start,expected):
    assert timers.next_cron_due(expression,tz,datetime.fromisoformat(start).timestamp()) == datetime.fromisoformat(expected).timestamp()


@pytest.mark.asyncio
async def test_outbox_ledger_pacing_and_content_deduplication(store,monkeypatch):
    transport=AsyncMock()
    monkeypatch.setattr(outbox,"_send",transport)
    first=outgoing(dedupe_key="first")
    duplicate=outgoing("  hello  ")
    third=outgoing("different")
    now=time.time()+1
    assert await outbox.dispatch_outbox(now=now) == 1
    states={r["id"]:r["state"] for r in outbox.list_messages()}
    assert states[first["id"]] == "sent"
    assert states[duplicate["id"]] == "suppressed_duplicate"
    assert states[third["id"]] == "pending"
    assert await outbox.dispatch_outbox(now=now+3) == 1
    assert transport.await_count == 2


@pytest.mark.asyncio
async def test_outbox_key_dedupe_window_and_target_isolation(store,monkeypatch):
    transport=AsyncMock()
    monkeypatch.setattr(outbox,"_send",transport)
    outgoing(dedupe_key="same",min_interval_seconds=0,dedupe_window_seconds=10)
    outgoing("new content",dedupe_key="same",min_interval_seconds=0,dedupe_window_seconds=10)
    now=time.time()+1
    assert await outbox.dispatch_outbox(now=now) == 1
    outgoing("new content",dedupe_key="same",min_interval_seconds=0,dedupe_window_seconds=10)
    assert await outbox.dispatch_outbox(now=now+11) == 1
    outbox.enqueue("worker","/scope","dashboard","other","new content",min_interval_seconds=0)
    assert await outbox.dispatch_outbox(now=now+12) == 1


@pytest.mark.parametrize("hour,urgent,expected_hour",[(23,False,7),(3,False,7),(12,False,12),(23,True,23)])
def test_quiet_hours_cross_midnight(store,hour,urgent,expected_hour):
    row=outgoing(urgent=urgent,quiet_start_hour=22,quiet_end_hour=7)
    now=datetime(2026,11,16,hour,tzinfo=timezone.utc).timestamp()
    due=outbox.quiet_until(row,now)
    assert datetime.fromtimestamp(due,timezone.utc).hour == expected_hour
    assert due >= now


@pytest.mark.asyncio
async def test_outbox_retry_backoff_and_permanent_failure(store,monkeypatch):
    monkeypatch.setattr(outbox,"_send",AsyncMock(side_effect=httpx.ConnectError("offline")))
    outgoing(max_attempts=2)
    now=time.time()+1
    assert await outbox.dispatch_outbox(now=now) == 0
    row=outbox.list_messages()[0]
    assert row["state"] == "pending" and row["attempts"] == 1 and row["next_attempt_at"] == now+2
    assert await outbox.dispatch_outbox(now=now+1) == 0
    assert outbox.list_messages()[0]["attempts"] == 1
    await outbox.dispatch_outbox(now=now+2)
    assert outbox.list_messages()[0]["state"] == "failed"


@pytest.mark.asyncio
async def test_outbox_concurrent_dispatch_is_single_flight_per_target(store,monkeypatch):
    transport=AsyncMock()
    monkeypatch.setattr(outbox,"_send",transport)
    outgoing(min_interval_seconds=0)
    await asyncio.gather(outbox.dispatch_outbox(),outbox.dispatch_outbox())
    assert transport.await_count == 1


@pytest.mark.asyncio
async def test_outbox_reclaims_expired_lease(store,monkeypatch):
    monkeypatch.setattr(outbox,"_send",AsyncMock())
    row=outgoing()
    with db._conn() as c:
        c.execute("UPDATE outbox_messages SET state='dispatching',lease_until=? WHERE id=?",(time.time()-1,row["id"]))
    assert await outbox.dispatch_outbox(now=time.time()+1) == 1


@pytest.mark.parametrize("kwargs",[
    {"quiet_start_hour":22},{"quiet_start_hour":24,"quiet_end_hour":7},
    {"min_interval_seconds":-1},{"max_attempts":0},{"dedupe_window_seconds":float("inf")},
])
def test_outbox_validation(store,kwargs):
    with pytest.raises(ValueError):
        outgoing(**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("decision",["approved","rejected"])
async def test_approval_atomic_resolve_idempotency_and_context(store,decision):
    row=card(payload={"sha":"reviewed"},context_note="resume release",idempotency_key="card")
    assert card(idempotency_key="card")["id"] == row["id"]
    resolved=await approvals.resolve_approval(row["id"],decision,note="decision")
    assert resolved["state"] == decision
    await approvals.resolve_approval(row["id"],"rejected")
    messages=mailbox.pending("worker","/scope")
    assert len(messages) == 1 and f"[APPROVAL {decision.upper()}]" in messages[0]["body"]
    data=json.loads(messages[0]["body"].split("] ",1)[1])
    assert data["payload"] == {"sha":"reviewed"}
    assert data["context_note"] == "resume release" and data["decision_note"] == "decision"


@pytest.mark.asyncio
async def test_approval_expiry_cancel_and_late_decision(store):
    row=card(expires_in_seconds=1)
    assert await approvals.sweep_expired_approvals(now=time.time()+2) == 1
    assert await approvals.sweep_expired_approvals(now=time.time()+3) == 0
    assert (await approvals.resolve_approval(row["id"],"approved"))["state"] == "expired"
    assert "[APPROVAL EXPIRED]" in mailbox.pending("worker","/scope")[0]["body"]
    second=card()
    assert approvals.cancel_approval(second["id"])
    assert (await approvals.resolve_approval(second["id"],"approved"))["state"] == "cancelled"


def register_project(tmp_path):
    scope=str(tmp_path/"project")
    root=Path(scope)/".orchestra"/"workers"
    root.mkdir(parents=True)
    with db._conn() as c:
        c.execute("INSERT INTO tm_projects(id,name,prefix,scope,created_at) VALUES ('project','project','AO',?,?)",
                  (scope,datetime.now(timezone.utc).isoformat()))
    return scope,root


def test_dreaming_archives_full_memory_compacts_and_refreshes_pointers(store,tmp_path):
    scope,root=register_project(tmp_path)
    path=root/"worker.md"
    raw="# Worker\n## Findings\n"+"".join(f"- finding {i} "+("x"*70)+"\n" for i in range(100))
    path.write_text(raw)
    with db._conn() as c:
        c.execute("""INSERT INTO tm_tasks(par_number,project_id,title,status,assignee,created_at,updated_at)
                     VALUES (1,'project','Finish feature','in_progress','worker','now','now')""")
    result=dreaming.run_dreaming_pass()
    assert result["worker_memories"] == 1
    compacted=path.read_text()
    assert len(compacted) <= dreaming.WORKER_MEMORY_L1_BUDGET_CHARS
    assert "## Findings" in compacted and "finding 99" in compacted and "tm_tasks:1" in compacted
    assert list((root/"archive").glob("*.md"))[0].read_text() == raw
    assert dreaming.run_dreaming_pass()["worker_memories"] == 0
    with db._conn() as c:
        c.execute("UPDATE tm_tasks SET status='done'")
    assert dreaming.run_dreaming_pass()["worker_memories"] == 1
    assert "tm_tasks:1" not in path.read_text()


def test_dreaming_busy_is_zero_work_and_symlinks_are_ignored(store,tmp_path):
    scope,root=register_project(tmp_path)
    path=root/"worker.md"
    path.write_text("large"*2000)
    manager=SimpleNamespace(sessions={"s":SimpleNamespace(status=AgentStatus.RUNNING)})
    assert dreaming.run_dreaming_pass(manager)["skipped_busy"]
    assert not (root/"archive").exists()
    outside=Path(scope)/"outside.md"
    outside.write_text("do not touch")
    (root/"link.md").symlink_to(outside)
    dreaming.run_dreaming_pass()
    assert outside.read_text() == "do not touch"


def test_dreaming_archived_session_digest_bounded_and_recorded_once(store,tmp_path):
    scope,root=register_project(tmp_path)
    with db._conn() as c:
        for i in range(6):
            c.execute("""INSERT INTO sessions(id,name,scope,cwd,model,status,created_at,total_turns,last_summary,branch,task_id)
                         VALUES (?,?,?,?,?,'archived',?,12,?,'feature','task')""",
                      (f"id-{i}",f"worker-{i}",scope,scope,"fake",datetime.now(timezone.utc).isoformat(),"summary "*400))
    assert dreaming.run_dreaming_pass()["session_digests"] == 6
    digest=list((root/"digests").glob("*.md"))[0]
    assert digest.stat().st_size <= 8192
    assert "worker-5" in digest.read_text()
    assert dreaming.run_dreaming_pass()["session_digests"] == 0


def client_for_routes():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes import timers as timer_routes, approvals as approval_routes, dreaming as dream_routes, outbox as outbox_routes, inbox as inbox_routes
    app=FastAPI()
    for module in (timer_routes,approval_routes,dream_routes,outbox_routes,inbox_routes):
        app.include_router(module.router)
    return TestClient(app)


def test_rest_round_trip_and_operator_approval_gate(store,monkeypatch):
    monkeypatch.delenv("DASHBOARD_USER",raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD",raising=False)
    from app.routes import approvals as routes
    manager,_,_=fake_manager()
    monkeypatch.setattr(routes,"manager",manager)
    with client_for_routes() as client:
        response=client.post("/api/timers",json={"recipient":"worker","scope":"/scope","body":"wake","delay_seconds":60})
        assert response.status_code == 200
        assert client.get("/api/timers").json()[0]["id"] == response.json()["id"]
        assert client.post(f"/api/timers/{response.json()['id']}/cancel").json()["cancelled"]
        response=client.post("/api/approvals",json={"recipient":"worker","scope":"/scope","action":"release","summary":"review"})
        approval_id=response.json()["id"]
        assert client.post(f"/api/approvals/{approval_id}/resolve",json={"decision":"approved"},
                           headers={"x-orchestra-session-id":"agent"}).status_code == 403
        assert client.post(f"/api/approvals/{approval_id}/resolve",json={"decision":"approved"}).json()["state"] == "approved"
        assert client.post("/api/timers",json={"recipient":"worker","scope":"/scope","body":"wake","delay_seconds":-1}).status_code == 422


def test_mcp_tools_and_read_only_profile():
    from app import mcp_stdio
    names={tool.name for tool in mcp_stdio.mcp._tool_manager.list_tools()}
    assert {"set_timer","list_timers","cancel_timer","request_approval","list_approvals","cancel_approval",
            "outbox_enqueue","outbox_list"} <= names
    assert {"list_timers","list_approvals","outbox_list"} <= mcp_stdio.READ_ONLY_MCP_TOOLS


# Reuse the pre-existing recovery fixture/receipt writer; its frozen assertions stay intact.
from tests.test_v966_stuck_deliveries import stuck_db, _insert, TARGET, SCOPE


def recovery_manager(status):
    from app.session_turns import TurnManager
    received=[]
    class Session:
        id=TARGET
        name=TARGET
        scope=SCOPE
        backend_type="codex"
        _compacting=False
        _manually_interrupted=True
        _mailbox_held_after_stop=True
        def __init__(self):
            self.status=status
            self._turns=TurnManager(self)
        def _log(self,*a,**k):
            pass
        def _spawn_bg(self,coro):
            return asyncio.create_task(coro)
        async def send(self,text,**kwargs):
            received.append(str(text))
    session=Session()
    manager=SimpleNamespace(sessions={TARGET:session},ensure_loaded_by_id=AsyncMock(return_value=session))
    return manager,session,received


@pytest.mark.asyncio
@pytest.mark.parametrize("entry",["runner","sweep","ensure"])
@pytest.mark.parametrize("status",[AgentStatus.IDLE,AgentStatus.WAITING])
async def test_fresh_queued_input_unblocks_orphaned_waiting_head_even_after_stop(stuck_db,monkeypatch,entry,status):
    _insert("head",1,"WAITING_NEXT_TURN",age_s=1)
    _insert("tail",2,"QUEUED",age_s=0)
    manager,session,received=recovery_manager(status)
    calls=[]
    async def deliver(delivery_id,manager=None):
        calls.append(delivery_id)
        with db._conn() as c:
            c.execute("UPDATE message_deliveries SET state='SUBMITTED' WHERE delivery_id=?",(delivery_id,))
    monkeypatch.setattr(message_deliveries,"run_message_delivery",deliver)
    if entry == "runner":
        assert await message_deliveries.run_target_message_deliveries(TARGET,manager)
    elif entry == "sweep":
        assert (await message_deliveries.sweep_stuck_deliveries(manager))["woken"] == 1
        task=message_deliveries._target_runner_tasks.get(TARGET)
        if task:
            await task
    else:
        message_deliveries.ensure_target_runner(TARGET,manager)
        await message_deliveries._target_runner_tasks[TARGET]
    assert received and "body-head" in received[0]
    assert calls == ["tail"]
    assert message_deliveries._row("head")["state"] == "SUBMITTED"
    assert not session._mailbox_held_after_stop


@pytest.mark.asyncio
@pytest.mark.parametrize("status,compacting",[(AgentStatus.RUNNING,False),(AgentStatus.IDLE,True)])
async def test_recovery_does_not_race_running_or_compacting_session(stuck_db,status,compacting):
    _insert("head",1,"WAITING_NEXT_TURN",age_s=1)
    _insert("tail",2,"QUEUED",age_s=0)
    manager,session,received=recovery_manager(status)
    session._compacting=compacting
    assert not await message_deliveries.run_target_message_deliveries(TARGET,manager)
    assert not received


@pytest.mark.asyncio
async def test_stale_orphaned_waiting_head_is_rebuilt_without_new_input(stuck_db):
    _insert("orphan",1,"WAITING_NEXT_TURN",age_s=121)
    manager,session,received=recovery_manager(AgentStatus.IDLE)
    session._manually_interrupted=False
    session._mailbox_held_after_stop=False
    assert (await message_deliveries.sweep_stuck_deliveries(manager))["woken"] == 1
    await asyncio.sleep(0.02)
    assert "body-orphan" in received[0]
    assert message_deliveries._row("orphan")["state"] == "SUBMITTED"


def test_direct_delivery_auto_cancels_follow_up_in_same_transaction(stuck_db):
    row=timers.set_timer(TARGET,SCOPE,"follow up",delay_seconds=60,cancel_on_sender="sender-966")
    _insert("new-message",1,"QUEUED",age_s=0)
    current=next(r for r in timers.list_timers() if r["id"] == row["id"])
    assert current["state"] == "cancelled"
    assert current["cancelled_reason"] == "auto_cancelled_by_inbound:sender-966"


def test_operator_cannot_be_impersonated_with_agent_bearer_token(store,monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER","operator")
    monkeypatch.setenv("DASHBOARD_PASSWORD","test-password")
    row=card()
    with client_for_routes() as client:
        result=client.post(f"/api/approvals/{row['id']}/resolve",json={"decision":"approved"},
                           headers={"Authorization":"Bearer orchestra-pytest-only-token"})
        assert result.status_code == 403
    assert approvals.list_approvals()[0]["state"] == "pending"


def test_rest_agent_resource_ownership_is_enforced(store,monkeypatch):
    from app.routes import always_on
    monkeypatch.setattr(always_on,"check_mcp_proof",lambda *_:True)
    monkeypatch.setattr(always_on.db,"get_session",lambda _:{"name":"worker","scope":"/scope"})
    monkeypatch.delenv("DASHBOARD_USER",raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD",raising=False)
    foreign=timers.set_timer("other","/scope","private",delay_seconds=5)
    headers={"x-orchestra-session-id":"worker-id"}
    with client_for_routes() as client:
        assert client.get("/api/timers",headers=headers).json() == []
        assert client.post(f"/api/timers/{foreign['id']}/cancel",headers=headers).status_code == 403
        assert client.post("/api/timers",headers=headers,json={
            "recipient":"other","scope":"/scope","body":"spoof","delay_seconds":5}).status_code == 403


@pytest.mark.asyncio
async def test_approval_resolve_rolls_back_if_mailbox_fails(store,monkeypatch):
    row=card()
    def fail(*args,**kwargs):
        raise sqlite3.OperationalError("injected")
    monkeypatch.setattr(mailbox,"enqueue_event",fail)
    with pytest.raises(sqlite3.OperationalError):
        await approvals.resolve_approval(row["id"],"approved")
    assert approvals.list_approvals()[0]["state"] == "pending"


@pytest.mark.asyncio
async def test_telegram_bridge_success_and_disabled_retry(store,monkeypatch):
    import sys
    bridge=SimpleNamespace(bot=object(),send_text_to_tg=AsyncMock(return_value={"ok":True}))
    monkeypatch.setitem(sys.modules,"app.tg_bridge",bridge)
    outbox.enqueue("worker","/scope","telegram","/scope","hello")
    now=time.time()+1
    assert await outbox.dispatch_outbox(now=now) == 1
    bridge.send_text_to_tg.assert_awaited_once()
    bridge.bot=None
    outbox.enqueue("worker","/scope","telegram","/scope","next")
    assert await outbox.dispatch_outbox(now=now+3) == 0
    assert outbox.list_messages()[0]["state"] == "pending"


@pytest.mark.asyncio
async def test_dashboard_outbox_logs_and_publishes_durably(store,monkeypatch):
    from app.live_broker import broker
    with db._conn() as c:
        c.execute("""INSERT INTO sessions(id,name,scope,cwd,model,created_at)
                     VALUES ('session','worker','/scope','/scope','fake','now')""")
    manager,_,_=fake_manager()
    messages=[]
    monkeypatch.setattr(broker,"publish",lambda sid,payload:messages.append(payload))
    outgoing()
    assert await outbox.dispatch_outbox(manager,now=time.time()+1) == 1
    with db._conn() as c:
        row=c.execute("SELECT content,event_id FROM logs WHERE session_id='session'").fetchone()
    assert row["content"] == "hello" and row["event_id"].startswith("outbox:")
    assert messages[0]["content"] == "hello"


@pytest.mark.asyncio
async def test_webhook_pins_public_dns_and_uses_explicit_transport(store,monkeypatch):
    calls=[]
    class Client:
        def __init__(self,**kwargs):
            assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        async def __aenter__(self):
            return self
        async def __aexit__(self,*args):
            pass
        async def post(self,url,**kwargs):
            calls.append((url,kwargs))
            return httpx.Response(200,request=httpx.Request("POST",url))
    monkeypatch.setattr(httpx,"AsyncClient",Client)
    monkeypatch.setattr(asyncio.get_running_loop(),"getaddrinfo",AsyncMock(
        return_value=[(2,1,6,"",("8.8.8.8",443))]))
    outbox.enqueue("worker","/scope","webhook","https://example.test/hook","hello")
    assert await outbox.dispatch_outbox(now=time.time()+1) == 1
    url,kwargs=calls[0]
    assert url == "https://8.8.8.8:443/hook"
    assert kwargs["headers"]["Host"] == "example.test"
    assert kwargs["extensions"]["sni_hostname"] == "example.test"
    assert kwargs["headers"]["Idempotency-Key"]


@pytest.mark.asyncio
async def test_webhook_rejects_internal_destinations_without_network_call(store,monkeypatch):
    monkeypatch.setattr(asyncio.get_running_loop(),"getaddrinfo",AsyncMock(
        return_value=[(2,1,6,"",("127.0.0.1",443))]))
    transport=AsyncMock()
    monkeypatch.setattr(httpx,"AsyncClient",transport)
    outbox.enqueue("worker","/scope","webhook","https://internal.test/hook","hello")
    assert await outbox.dispatch_outbox(now=time.time()+1) == 0
    assert outbox.list_messages()[0]["state"] == "failed"
    transport.assert_not_called()


@pytest.mark.asyncio
async def test_expired_outbox_lease_does_not_exceed_max_attempts(store,monkeypatch):
    transport=AsyncMock()
    monkeypatch.setattr(outbox,"_send",transport)
    row=outgoing(max_attempts=1)
    with db._conn() as c:
        c.execute("""UPDATE outbox_messages SET state='dispatching',attempts=1,lease_until=?
                     WHERE id=?""",(time.time()-1,row["id"]))
    assert await outbox.dispatch_outbox(now=time.time()+1) == 0
    assert outbox.list_messages()[0]["state"] == "failed"
    transport.assert_not_awaited()


def test_dreaming_leaves_short_clean_worker_memory_untouched_when_no_open_tasks(store,tmp_path):
    scope,root=register_project(tmp_path)
    path=root/"clean.md"
    path.write_text("# Clean Worker Notes\n- concise note\n")
    res=dreaming.run_dreaming_pass()
    assert res["worker_memories"] == 0
    assert path.read_text() == "# Clean Worker Notes\n- concise note\n"
    assert not (root/"archive").exists()
