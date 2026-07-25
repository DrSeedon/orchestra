import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def _session(session_id: str, name: str, model: str, status: str = "idle") -> dict:
    return {
        "id": session_id,
        "name": name,
        "scope": "/project",
        "model": model,
        "status": status,
    }


def _log(log_id: int, kind: str, content: str) -> dict:
    return {"id": log_id, "type": kind, "content": content}


def test_find_limit_stopped_agents_only_returns_latest_limited_turn():
    from app.limit_wake import find_limit_stopped_agents

    sessions = [
        _session("limited", "limited-worker", "claude-opus-5[1m]"),
        _session("recovered", "recovered-worker", "claude-opus-5[1m]"),
        _session("ordinary", "ordinary-worker", "gpt-5.6-sol"),
        _session("running", "running-worker", "claude-opus-5[1m]", "running"),
    ]
    logs = {
        "limited": [
            _log(1, "status", "turn ended (end_turn, 2 turns)"),
            _log(2, "text", "You've hit your weekly usage limit"),
            _log(3, "error", "subscription limit — ждём сброса квоты. НЕ ретраим"),
            _log(4, "status", "turn ended (stop_sequence, 1 turns)"),
        ],
        "recovered": [
            _log(5, "text", "You've hit your weekly usage limit"),
            _log(6, "error", "subscription limit — ждём сброса квоты. НЕ ретраим"),
            _log(7, "status", "turn ended (stop_sequence, 1 turns)"),
            _log(8, "user_message", "continue"),
            _log(9, "status", "turn ended (end_turn, 2 turns)"),
        ],
        "ordinary": [
            _log(10, "text", "done"),
            _log(11, "status", "turn ended (end_turn, 1 turns)"),
        ],
        "running": [
            _log(12, "text", "You've hit your usage limit"),
            _log(13, "error", "subscription limit — ждём сброса квоты. НЕ ретраим"),
            _log(14, "status", "turn ended (stop_sequence, 1 turns)"),
        ],
    }

    assert find_limit_stopped_agents(sessions, logs) == [
        {
            **sessions[0],
            "limit_kind": "timed",
            "provider": "anthropic",
            "limit_turn_id": 4,
        }
    ]


def test_find_limit_stopped_agents_preserves_monthly_limit_over_generic_status():
    from app.limit_wake import find_limit_stopped_agents

    session = _session("monthly", "monthly-worker", "claude-opus-5[1m]")
    logs = {
        "monthly": [
            _log(
                1,
                "text",
                "You've hit your monthly spend limit · raise it at "
                "claude.ai/settings/usage",
            ),
            _log(2, "error", "subscription limit — ждём сброса квоты. НЕ ретраим"),
            _log(3, "status", "turn ended (stop_sequence, 1 turns)"),
        ]
    }

    agents = find_limit_stopped_agents([session], logs)

    assert agents[0]["limit_kind"] == "monthly"


def test_limit_phrase_in_normal_assistant_text_is_not_terminal_evidence():
    from app.limit_wake import find_limit_stopped_agents

    session = _session("normal", "normal-worker", "claude-opus-5[1m]")
    logs = {
        "normal": [
            _log(1, "text", "The weekly usage limit is documented here."),
            _log(2, "status", "turn ended (end_turn, 1 turns)"),
        ]
    }

    assert find_limit_stopped_agents([session], logs) == []


def test_limit_detection_uses_event_timestamp_when_log_ids_commit_out_of_order():
    from app.limit_wake import find_limit_stopped_agents

    session = _session("limited", "limited-worker", "claude-opus-5[1m]")
    logs = {
        "limited": [
            {
                **_log(12, "text", "You've hit your weekly usage limit"),
                "ts": "2026-07-25T12:00:00.100000+00:00",
            },
            {
                **_log(11, "error", "subscription limit — ждём сброса квоты. НЕ ретраим"),
                "ts": "2026-07-25T12:00:00.200000+00:00",
            },
            {
                **_log(10, "status", "turn ended (stop_sequence, 1 turns)"),
                "ts": "2026-07-25T12:00:00.300000+00:00",
            },
        ]
    }

    agents = find_limit_stopped_agents([session], logs)

    assert agents[0]["limit_turn_id"] == 10


def test_build_wake_plan_uses_latest_blocking_provider_window():
    from app.limit_wake import build_wake_plan

    agents = [
        {
            **_session("a", "claude-worker", "claude-opus-5[1m]"),
            "limit_kind": "timed",
            "provider": "anthropic",
            "limit_turn_id": 10,
        },
        {
            **_session("b", "codex-worker", "gpt-5.6-sol"),
            "limit_kind": "timed",
            "provider": "codex",
            "limit_turn_id": 20,
        },
    ]
    provider_usage = {
        "anthropic": {
            "windows": [
                {
                    "id": "five_hour",
                    "utilization": 100,
                    "resets_at": (NOW + timedelta(hours=2)).isoformat(),
                },
                {
                    "id": "seven_day",
                    "utilization": 100,
                    "resets_at": (NOW + timedelta(days=2)).isoformat(),
                },
            ]
        },
        "codex": {
            "windows": [
                {
                    "id": "primary",
                    "utilization": 100,
                    "resets_at": (NOW + timedelta(hours=3)).isoformat(),
                }
            ]
        },
    }

    plan = build_wake_plan(agents, provider_usage, now=NOW)

    assert plan["manual_agents"] == []
    assert [(item["provider"], item["reset_at"]) for item in plan["schedules"]] == [
        ("anthropic", (NOW + timedelta(days=2)).isoformat()),
        ("codex", (NOW + timedelta(hours=3)).isoformat()),
    ]


def test_monthly_spend_limit_never_gets_an_automatic_reset():
    from app.limit_wake import build_wake_plan

    monthly = {
        **_session("monthly", "monthly-worker", "claude-opus-5[1m]"),
        "limit_kind": "monthly",
        "provider": "anthropic",
        "limit_turn_id": 10,
    }
    provider_usage = {
        "anthropic": {
            "windows": [
                {
                    "id": "five_hour",
                    "utilization": 100,
                    "resets_at": (NOW + timedelta(hours=1)).isoformat(),
                }
            ]
        }
    }

    plan = build_wake_plan([monthly], provider_usage, now=NOW)

    assert plan["schedules"] == []
    assert plan["manual_agents"] == ["monthly-worker"]
    assert plan["manual_action_url"] == "https://claude.ai/settings/usage"


@pytest.fixture
def wake_db(tmp_path, monkeypatch):
    db_path = tmp_path / "wake.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db

    init_db()
    return db_path


@pytest.mark.asyncio
async def test_replaceable_timer_is_idempotent(wake_db, monkeypatch):
    from app.bg_jobs import BgJobManager
    from app.db import bg_get_active_all

    manager = BgJobManager()
    monkeypatch.setattr(manager, "_start_task", lambda *args, **kwargs: None)

    first = await manager.create(
        "timer",
        {"delay_seconds": 600, "action": "wake_subscription_limited"},
        "",
        "__system__",
        "__system__",
        "__global__",
        "dashboard",
        replace_key="wake-anthropic",
    )
    second = await manager.create(
        "timer",
        {"delay_seconds": 1200, "action": "wake_subscription_limited"},
        "",
        "__system__",
        "__system__",
        "__global__",
        "dashboard",
        replace_key="wake-anthropic",
    )

    active = bg_get_active_all()
    assert first["id"] != second["id"]
    assert len(active) == 1
    assert json.loads(active[0]["config"])["delay_seconds"] == 1200


@pytest.mark.asyncio
async def test_wake_job_stops_before_second_agent_when_limit_closes(
    wake_db, monkeypatch
):
    from app.db import bg_get_jobs, bg_save_job
    from app.limit_wake import run_wake_job
    from app.session_state import AgentStatus
    from app.routes import system

    targets = [
        {
            "id": "a",
            "name": "worker-a",
            "scope": "/project",
            "limit_turn_id": 10,
        },
        {
            "id": "b",
            "name": "worker-b",
            "scope": "/project",
            "limit_turn_id": 20,
        },
    ]
    now = datetime.now(timezone.utc)
    bg_save_job({
        "id": "wake-job",
        "type": "timer",
        "config": json.dumps({
            "action": "wake_subscription_limited",
            "provider": "anthropic",
            "agents": targets,
        }),
        "message": "",
        "target_session_id": "__system__",
        "target_name": "__system__",
        "target_scope": "__global__",
        "created_by_name": "dashboard",
        "status": "active",
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "trigger_at": now.isoformat(),
        "created_at": now.isoformat(),
        "last_output": "",
    })
    candidates = [
        {
            **_session("a", "worker-a", "claude-opus-5[1m]"),
            "limit_kind": "timed",
            "provider": "anthropic",
            "limit_turn_id": 10,
        },
        {
            **_session("b", "worker-b", "claude-opus-5[1m]"),
            "limit_kind": "timed",
            "provider": "anthropic",
            "limit_turn_id": 20,
        },
    ]
    monkeypatch.setattr(
        "app.limit_wake._load_limit_stopped_agents",
        lambda: candidates,
    )
    monkeypatch.setattr(
        system,
        "current_provider_usage",
        AsyncMock(side_effect=[
            {"anthropic": {"windows": [{"utilization": 0}]}},
            {"anthropic": {"windows": [{"utilization": 100}]}},
        ]),
    )
    session = MagicMock(status=AgentStatus.IDLE)
    session.send = AsyncMock()
    manager = MagicMock()
    manager.ensure_loaded = AsyncMock(return_value=session)

    await run_wake_job(
        "wake-job",
        {
            "provider": "anthropic",
            "agents": targets,
        },
        manager,
        stagger_seconds=0,
    )

    session.send.assert_awaited_once()
    row = next(job for job in bg_get_jobs() if job["id"] == "wake-job")
    assert row["status"] == "triggered"
    assert "limit is still active" in row["last_output"]
    config = json.loads(row["config"])
    assert config["deliveries"]["a"]["state"] == "delivered"


@pytest.mark.asyncio
async def test_wake_job_reconciles_claimed_delivery_without_duplicate_send(
    wake_db, monkeypatch
):
    from app.db import bg_get_jobs, bg_save_job
    from app.limit_wake import run_wake_job
    from app.routes import system

    target = {
        "id": "a",
        "name": "worker-a",
        "scope": "/project",
        "limit_turn_id": 10,
    }
    config = {
        "action": "wake_subscription_limited",
        "provider": "anthropic",
        "agents": [target],
        "deliveries": {
            "a": {"state": "claimed", "token": "durable-token"},
        },
    }
    now = datetime.now(timezone.utc)
    bg_save_job({
        "id": "replayed-wake",
        "type": "timer",
        "config": json.dumps(config),
        "message": "",
        "target_session_id": "__system__",
        "target_name": "__system__",
        "target_scope": "__global__",
        "created_by_name": "dashboard",
        "status": "active",
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "trigger_at": now.isoformat(),
        "created_at": now.isoformat(),
        "last_output": "",
    })
    monkeypatch.setattr(
        "app.limit_wake._load_limit_stopped_agents",
        lambda: [{
            **_session("a", "worker-a", "claude-opus-5[1m]"),
            "limit_kind": "timed",
            "provider": "anthropic",
            "limit_turn_id": 10,
        }],
    )
    monkeypatch.setattr(
        "app.limit_wake._wake_token_seen",
        lambda session_id, token: token == "durable-token",
    )
    monkeypatch.setattr(
        system,
        "current_provider_usage",
        AsyncMock(return_value={
            "anthropic": {"windows": [{"utilization": 0}]},
        }),
    )
    manager = MagicMock()
    manager.ensure_loaded = AsyncMock()

    await run_wake_job(
        "replayed-wake",
        config,
        manager,
        stagger_seconds=0,
    )

    manager.ensure_loaded.assert_not_awaited()
    row = next(job for job in bg_get_jobs() if job["id"] == "replayed-wake")
    assert json.loads(row["config"])["deliveries"]["a"]["state"] == "delivered"


@pytest.mark.asyncio
async def test_wake_timer_restores_from_database(wake_db, monkeypatch):
    from app.bg_jobs import BgJobManager

    creator = BgJobManager()
    monkeypatch.setattr(creator, "_start_task", lambda *args, **kwargs: None)
    result = await creator.create(
        "timer",
        {
            "delay_seconds": 3600,
            "action": "wake_subscription_limited",
            "provider": "anthropic",
            "agents": [],
        },
        "",
        "__system__",
        "__system__",
        "__global__",
        "dashboard",
        replace_key="wake-limit-anthropic",
    )

    restored = []
    replacement = BgJobManager()
    monkeypatch.setattr(
        replacement,
        "_start_task",
        lambda *args, **kwargs: restored.append((args, kwargs)),
    )
    await replacement.restore_from_db()

    assert len(restored) == 1
    assert restored[0][0][0] == result["id"]
    assert restored[0][0][2]["action"] == "wake_subscription_limited"


@pytest.mark.asyncio
async def test_interrupted_triggering_wake_timer_replays_after_restart(
    wake_db, monkeypatch
):
    from app.bg_jobs import BgJobManager
    from app.db import bg_save_job

    now = datetime.now(timezone.utc)
    bg_save_job({
        "id": "interrupted-wake",
        "type": "timer",
        "config": json.dumps({
            "delay_seconds": 1,
            "action": "wake_subscription_limited",
            "provider": "anthropic",
            "agents": [],
        }),
        "message": "",
        "target_session_id": "__system__",
        "target_name": "__system__",
        "target_scope": "__global__",
        "created_by_name": "dashboard",
        "status": "triggering",
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "trigger_at": (now - timedelta(seconds=30)).isoformat(),
        "created_at": (now - timedelta(minutes=1)).isoformat(),
        "last_output": "woke 1 agents",
    })
    restored = []
    manager = BgJobManager()
    monkeypatch.setattr(
        manager,
        "_start_task",
        lambda *args, **kwargs: restored.append((args, kwargs)),
    )

    await manager.restore_from_db()

    assert len(restored) == 1
    assert restored[0][0][0] == "interrupted-wake"
