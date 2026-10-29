"""Local Codex pacing, real session admission and durable delivery; no provider I/O."""

import asyncio
import json
import shutil
import sqlite3
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import db, quota_gate as gate
from app.events import MessageProvenance
from app.manager import SessionManager
from app.session import AgentSession, AgentStatus
from app.routes import system

REAL_ADMISSION = gate.get_worker_admission
START = datetime(2026, 10, 20, 7, tzinfo=timezone.utc).timestamp()  # 14:00 Krasnoyarsk
WEEK = 10080 * 60
NOW = START + 0.1 * WEEK
MODEL = "gpt-6.1-sol"


def window(used, *, start=START, minutes=10080, name="primary"):
    return dict(id=name, window_minutes=minutes, utilization=used, resets_at=start + minutes * 60)


def decide(used, *, now=NOW, windows=None, stamp=None, policy=None):
    return gate.evaluate_worker_admission(
        MODEL, {"codex": {"windows": windows or [window(used)]}},
        {"codex": now if stamp is None else stamp}, now=now, policy=policy,
    )


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(gate.time, "time", lambda: NOW)
    db.init_db()


@pytest.mark.parametrize("model,bucket,lane", [
    (MODEL, "codex", "sol"), ("gpt-6-astra", "codex", "sol"),
    ("gpt-6-luna", "codex", "luna"), ("gpt-5.3-codex-spark", "codex_spark", "spark"),
])
def test_weekly_codex_uses_claude_day_night_boundary(clock, model, bucket, lane):
    policy = gate.quota_policy()
    limit = gate.line_limit(.1, "claude", policy, window_minutes=10080, window_start_at=START)
    for used, expected in [(limit, "available"), (limit + .01, "blocked"), (0, "available")]:
        decision = gate.evaluate_worker_admission(
            model, {bucket: {"windows": [window(used)]}}, {bucket: NOW}, now=NOW,
        )
        assert decision.state == expected
        assert decision.gated and decision.lane == lane
        assert decision.limit_pct == pytest.approx(limit)
        assert decision.hard_limit_pct == 99


def test_prolite_weekly_primary_null_secondary_normalizes_and_gates(clock):
    for plan in ["prolite", None]:
        raw = {"rateLimits": {"planType": plan, "primary": {
            "windowDurationMins": 10080, "usedPercent": 90, "resetsAt": START + WEEK,
        }, "secondary": None}}
        normalized = system._normalize_codex_usage(raw)
        providers = system._provider_usage_snapshot(None, normalized, None)
        decision = gate.evaluate_worker_admission(MODEL, providers, {"codex": NOW}, now=NOW)
        assert decision.state == "blocked" and decision.progress == pytest.approx(.1)
        assert decision.utilization == 90


@pytest.mark.parametrize("reverse", [False, True])
def test_dual_windows_follow_duration_and_exhaustion(clock, reverse):
    windows = [window(10, name="secondary"), window(100, start=NOW-3600, minutes=300)]
    if reverse:
        windows.reverse()
    decision = decide(10, windows=windows)
    assert decision.utilization == 10
    assert decision.state == "blocked" and decision.reason_key == "pool_exhausted"
    assert decision.release_in_seconds == 4 * 3600
    windows[0 if reverse else 1]["utilization"] = 99
    assert decide(10, windows=windows).state == "available"


def test_short_exhaustion_can_delay_a_weekly_line_release(clock):
    line = decide(0).limit_pct
    pacing = decide(line + .1)
    assert pacing.state == "blocked" and pacing.release_in_seconds < 4 * 3600
    combined = decide(line + .1, windows=[
        window(line + .1), window(100, start=NOW-3600, minutes=300, name="secondary"),
    ])
    assert combined.state == "blocked" and combined.release_in_seconds == 4 * 3600


def test_release_prediction_matches_time_and_new_window_reset(clock):
    held = decide(40)
    assert held.state == "blocked" and held.release_in_seconds > 0
    at = NOW + held.release_in_seconds
    assert decide(40, now=at - 1).state == "blocked"
    assert decide(40, now=at + 1).state == "available"
    # Fresh next-window usage starts near the floor, not at last week's allowance.
    new = decide(40, now=START + WEEK + 1, windows=[window(40, start=START + WEEK)])
    assert new.state == "blocked" and new.progress < .001


def test_codex_day_and_night_rates_are_the_existing_claude_rates(clock):
    def limit(hours):
        return gate.line_limit(hours / 168, "sol", window_minutes=10080,
                               window_start_at=START, policy_history=[])
    assert limit(1) - limit(0) == pytest.approx(89 * .943 / 112)
    assert limit(11) - limit(10) == pytest.approx(89 * .057 / 56)
    assert limit(0) == pytest.approx(10 + 91 * 8 / 168)


def test_unversioned_policy_preserves_the_actual_old_codex_curve(clock):
    snapshot = gate.quota_policy_snapshot(gate.quota_policy())
    snapshot.pop("codex_claude_pacing")
    snapshot.update(curved_lanes=["sol"], lane_hard_stop_pct={"sol": 95})
    historical = gate._policy_from_snapshot(snapshot)
    assert not historical.codex_claude_pacing
    assert gate.line_limit(.5, "sol", historical) == pytest.approx(81.2858283255199)


def test_short_only_codex_retains_window_and_general_hard_stop(clock):
    for used, state in [(98.9, "available"), (99, "blocked")]:
        decision = decide(used, windows=[window(used, start=NOW-9000, minutes=300)])
        assert decision.state == state
        assert decision.progress == .5


def test_history_envelope_matches_claude_and_resets(clock):
    current = gate.quota_policy()
    old = replace(current, tolerance_start_pp=65)
    db.append_quota_policy_history(gate.quota_policy_snapshot(old), START, source="test")
    db.append_quota_policy_history(gate.quota_policy_snapshot(current), NOW - 1, source="test")
    held = decide(60)
    assert held.state == "available" and held.limit_pct > 65
    assert held.limit_pct == gate.line_limit(.1, "claude", current,
                                           window_minutes=10080, window_start_at=START)
    next_window = decide(60, now=START + WEEK + 1, windows=[window(60, start=START + WEEK)])
    assert next_window.state == "blocked" and next_window.limit_pct < 20


@pytest.mark.parametrize("stamp", [0, NOW - 300, NOW + 1, "bad"])
def test_stale_missing_unknown_fail_open_without_fabricated_usage(clock, stamp):
    decision = decide(90, stamp=stamp)
    assert decision.state == "unknown" and decision.allowed
    assert decision.utilization is None and decision.limit_pct is None


@pytest.mark.parametrize("used", [None, True, float("nan"), float("inf"), -1])
def test_malformed_usage_is_not_zero_or_full(clock, used):
    normalized = system._normalize_codex_usage({"rateLimits": {"primary": {
        "windowDurationMins": 10080, "usedPercent": used,
    }}})
    assert normalized["primary"] is None
    assert decide(0, windows=[window(used)]).state == "unknown"


def test_optional_reset_does_not_prevent_below_hard_stop_work(clock):
    win = window(45)
    win.pop("resets_at")
    assert decide(45, windows=[win]).state == "available"
    win["utilization"] = 99
    assert decide(99, windows=[win]).state == "blocked"


@pytest.mark.asyncio
async def test_observation_failure_remains_unknown(clock):
    async def failed(**kwargs):
        raise RuntimeError("offline quota source")
    decision = await REAL_ADMISSION(MODEL, failed)
    assert decision.state == "unknown" and decision.allowed


def test_optional_policy_history_failure_keeps_current_formula(clock, monkeypatch):
    monkeypatch.setattr(db, "quota_policy_history_for_window", Mock(side_effect=sqlite3.OperationalError("offline")))
    assert decide(0).state == "available"
    assert decide(90).state == "blocked"


@pytest.mark.parametrize("reset", [None, True, float("nan"), float("inf"), 1e300])
def test_invalid_optional_reset_preserves_known_usage(clock, reset):
    raw = {"rateLimits": {"primary": {
        "windowDurationMins": 10080, "usedPercent": 45, "resetsAt": reset,
    }}}
    normalized = system._normalize_codex_usage(raw)
    assert normalized["primary"]["utilization"] == 45
    providers = system._provider_usage_snapshot(None, normalized, None)
    decision = gate.evaluate_worker_admission(MODEL, providers, {"codex": NOW}, now=NOW)
    assert decision.state == "available" and decision.limit_pct is None


def test_dashboard_js_matches_shared_server_formula_and_history(clock):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run the dashboard formula")
    policy = gate.quota_policy()
    old = replace(policy, tolerance_start_pp=65)
    history = [{"effective_from": START, "policy": gate.quota_policy_snapshot(old)}]
    samples = []
    for minutes in [300, 10080]:
        for lane in ["claude", "sol", "luna", "spark"]:
            for progress in [0, .1, .5, .9, 1]:
                samples.append(dict(lane=lane, progress=progress, minutes=minutes))
    source = Path(__file__).parents[1] / "app/static/js/quota-lines.js"
    sample_start = START + 17  # Provider reset timestamps need not land on a minute.
    script = """
const fs = require('fs'), vm = require('vm');
global.window = {}; global.orchLocale = () => 'en'; global.T = x => x;
global.cssToken = () => '#fff'; global._formatPercent = x => String(x); global._escHtml = String;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const src = fs.readFileSync(input.source, 'utf8').replace('init: initQuotaLines,',
    'chartForTest(data) { _quotaLinesData=data; return _qlChartSvg({buckets: data.buckets.map(b=>b.bucket)}, data.rule); }, init: initQuotaLines,');
vm.runInThisContext(src);
const values = input.samples.map(s => window.QuotaPanel.monotoneLimitAt(
    s.progress, input.policy, s.lane, s.minutes, input.start * 1000,
    input.history, (input.start + s.progress * s.minutes * 60) * 1000));
const buckets = [['codex',['sol','luna']], ['codex_spark',['spark']], ['anthropic',['claude']]]
    .map(([bucket,lanes]) => ({bucket, data_available:true, fresh:true,
        window:{window_minutes:10080, utilization:0, progress:.1,
            resets_at:new Date((input.start + 10080*60)*1000).toISOString()},
        lanes:lanes.map(lane=>({lane, label:lane, gated:true, limit_pct:20})), trace:{points:[]}}));
const chart = window.QuotaPanel.chartForTest({rule:input.policy, buckets}).svg;
const legacy = {...input.policy, codex_claude_pacing:false, curved_lanes:['sol'], lane_hard_stop_pct:{sol:95}};
const oldSol = window.QuotaPanel.limitAt(.5, legacy, 'sol');
process.stdout.write(JSON.stringify({values, chart, oldSol}));
"""
    result = subprocess.run([node, "-e", script], input=json.dumps(dict(
        source=str(source), samples=samples, policy=gate.quota_policy_snapshot(policy),
        start=sample_start, history=history,
    )), text=True, capture_output=True, timeout=10, check=True)
    expected = [gate.line_limit(s["progress"], s["lane"], policy,
                               window_minutes=s["minutes"], window_start_at=sample_start,
                               policy_history=history) for s in samples]
    output = json.loads(result.stdout)
    assert output["values"] == pytest.approx(expected)
    for lane in ["sol", "luna", "spark", "claude"]:
        assert f'data-ql-threshold="{lane}"' in output["chart"]
    assert output["oldSol"] == pytest.approx(81.2858283255199)


def make_session(tmp_path, monkeypatch, *, model=MODEL, is_orch=True):
    session = AgentSession(
        id="local-quota-1121", name="local-quota", scope=str(tmp_path), cwd=str(tmp_path),
        model=model, backend_type="codex" if model.startswith("gpt") else "claude",
        system_prompt="", branch="", created_at=datetime.now(timezone.utc),
        role="orchestrator" if is_orch else "worker", is_orchestrator=is_orch,
    )
    backend = SimpleNamespace(send=AsyncMock(), active_turn_id="fake-turn")
    monkeypatch.setattr(session, "_ensure_backend", AsyncMock(return_value=backend))
    monkeypatch.setattr(session, "_persist", Mock())
    monkeypatch.setattr(session, "_log", Mock())
    monkeypatch.setattr(session, "_turn_event_loop", AsyncMock())
    return session, backend


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["user", "agent", "background_task", "platform", "system"])
async def test_codex_orchestrator_checks_new_turn_from_every_origin(clock, tmp_path, monkeypatch, origin):
    session, backend = make_session(tmp_path, monkeypatch)
    session._admission_service = AsyncMock(return_value=decide(90))
    with pytest.raises(gate.QuotaGateError):
        await session.send("held", provenance=MessageProvenance(origin=origin, senders=("test",)))
    backend.send.assert_not_awaited()
    assert session.status == AgentStatus.IDLE
    session._admission_service.return_value = decide(0)
    await session.send("allowed", provenance=MessageProvenance(origin=origin, senders=("test",)))
    backend.send.assert_awaited_once()
    if session._listen_task:
        await session._listen_task


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["retired-codex-model", "claude-sonnet-5-5[1m]"])
async def test_actual_codex_runtime_cannot_bypass_quota_by_model_name(clock, tmp_path, monkeypatch, model):
    session, backend = make_session(tmp_path, monkeypatch, model=model)
    session.backend_type = "codex"
    session._admission_service = AsyncMock(return_value=decide(90))

    with pytest.raises(gate.QuotaGateError):
        await session.preflight_delivery_admission()
    with pytest.raises(gate.QuotaGateError):
        await session.send("held recovery", provenance=MessageProvenance(
            origin="system", senders=("system",), subtype="runtime_reconnect",
        ))

    assert session._admission_service.await_count == 2
    assert all(call.args == (model,) for call in session._admission_service.await_args_list)
    backend.send.assert_not_awaited()
    assert not session._lifecycle_lock.locked()


@pytest.mark.asyncio
async def test_pending_codex_batch_is_durable_and_equal_later_batch_is_distinct(clock, tmp_path, monkeypatch):
    from app import message_deliveries as deliveries, report_holds

    session, backend = make_session(tmp_path, monkeypatch)
    db.save_session(session._to_db_dict())
    session._admission_service = AsyncMock(return_value=decide(90))
    monkeypatch.setattr(report_holds, "ensure_runner", lambda *_: None)
    for _ in range(2):
        session._pending_messages.append("same later message")
        session._pending_owner_initiated_turn = True
        await session._flush_pending()
        assert not session._pending_messages
    backend.send.assert_not_awaited()
    with db._conn() as connection:
        rows = connection.execute("SELECT * FROM message_deliveries").fetchall()
    assert len(rows) == 2 and all(row["state"] == "WAITING_QUOTA" for row in rows)
    assert all(row["origin"] == "user" for row in rows)
    await deliveries.recover_message_deliveries()
    with db._conn() as connection:
        assert connection.execute("SELECT COUNT(*) FROM message_deliveries").fetchone()[0] == 2


@pytest.mark.asyncio
async def test_pending_transfer_write_failure_retains_messages_and_unlocks(clock, tmp_path, monkeypatch):
    from app import message_deliveries as deliveries

    session, backend = make_session(tmp_path, monkeypatch)
    session._pending_messages.append("retain on failed write")
    session._admission_service = AsyncMock(return_value=decide(90))
    monkeypatch.setattr(deliveries, "accept_message_delivery", AsyncMock(side_effect=RuntimeError("write failed")))
    with pytest.raises(RuntimeError, match="write failed"):
        await session._flush_pending()
    assert session._pending_messages == ["retain on failed write"]
    assert not session._lifecycle_lock.locked()
    backend.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_claude_orchestrator_keeps_its_authorized_bypass(clock, tmp_path, monkeypatch):
    session, backend = make_session(tmp_path, monkeypatch, model="claude-opus-5-5[1m]")
    session._admission_service = AsyncMock(side_effect=AssertionError("unexpected quota read"))
    await session.preflight_delivery_admission()
    await session.send("allowed", provenance=MessageProvenance(origin="user", senders=("test",)))
    backend.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_hub_never_reads_local_codex_quota(clock):
    loader = AsyncMock(side_effect=AssertionError("local quota read by hub"))
    decision = await REAL_ADMISSION("hubsol", loader)
    assert decision.allowed
    loader.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("used", [0, 90])
async def test_codex_orchestrator_creation_checks_planned_first_turn(clock, tmp_path, monkeypatch, used):
    manager = SessionManager()
    monkeypatch.setattr(gate, "get_worker_admission", AsyncMock(return_value=decide(used)))

    async def create():
        return await manager.create_session(
            name="blocked-orch", scope=str(tmp_path), cwd=str(tmp_path), model=MODEL,
            role="orchestrator", is_orchestrator=True, planned_initial_turn=True,
        )

    if used == 90:
        with pytest.raises(gate.QuotaGateError):
            await create()
        assert manager.get_by_name("blocked-orch", str(tmp_path)) is None
    else:
        session = await create()
        assert session.is_orchestrator and session.backend_type == "codex"


@pytest.mark.asyncio
@pytest.mark.parametrize("preflight_hold", [True, False])
async def test_real_codex_orchestrator_delivery_wait_restart_release_exactly_once(clock, tmp_path, monkeypatch, preflight_hold):
    from app import deps, message_deliveries as deliveries, quota_queue, report_holds
    from app.routes import sessions as routes

    # Each parameter has a new event loop; production has one loop per process.
    monkeypatch.setattr(quota_queue, "_release_lock", asyncio.Lock())
    session, backend = make_session(tmp_path, monkeypatch)
    db.save_session(session._to_db_dict())
    manager = SessionManager()
    manager.sessions[session.id] = session
    monkeypatch.setattr(manager, "_auto_switch_before_delivery", AsyncMock())
    monkeypatch.setattr(deps, "manager", manager)
    monkeypatch.setattr(routes, "manager", manager)
    monkeypatch.setattr(report_holds, "ensure_runner", lambda *_: None)
    admission = AsyncMock(return_value=decide(90 if preflight_hold else 0))
    monkeypatch.setattr(gate, "get_worker_admission", admission)
    monkeypatch.setattr(deliveries, "ensure_target_runner", lambda *_: None)
    delivery_id = "00000000-0000-4000-8000-000000001121"
    provenance = MessageProvenance(origin="user", senders=("owner",), subtype="direct_message")
    held = await routes._preflight_or_quota_wait(session.id)
    assert held.state == "blocked" if preflight_hold else held is None
    generation = f"session={session.id}|task=|branch=|needs_switch=0"
    args = dict(
        delivery_id=delivery_id, source_session_id="", source_name="", source_scope=str(tmp_path),
        source_task_id="", target_session_id=session.id, target_name=session.name,
        target_scope=str(tmp_path), target_task_id="", target_generation=generation,
        message="survives", rendered_message="survives", provenance=provenance, quota_wait=held,
    )
    await deliveries.accept_message_delivery(**args)
    await deliveries.accept_message_delivery(**args)
    if not preflight_hold:
        # The gate can close after durable acceptance but before submission.
        admission.return_value = decide(90)
        await deliveries.run_target_message_deliveries(session.id, manager)
        backend.send.assert_not_awaited()
    assert deliveries._row(delivery_id)["state"] == "WAITING_QUOTA"
    # Reconstruct the session and manager as on restart, keeping only SQLite receipts.
    session, backend = make_session(tmp_path, monkeypatch)
    manager.sessions[session.id] = session
    await deliveries.recover_message_deliveries()
    assert await quota_queue.release_waiting() == 0
    admission.return_value = decide(0)
    assert sum(await asyncio.gather(quota_queue.release_waiting(), quota_queue.release_waiting())) == 1
    await deliveries.run_target_message_deliveries(session.id, manager)
    assert deliveries._row(delivery_id)["state"] == "SUBMITTED"
    backend.send.assert_awaited_once()
    assert await quota_queue.release_waiting() == 0
    await deliveries.run_target_message_deliveries(session.id, manager)
    backend.send.assert_awaited_once()
    if session._listen_task:
        await session._listen_task
