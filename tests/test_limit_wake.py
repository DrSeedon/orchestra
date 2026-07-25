import json
from datetime import datetime, timedelta, timezone

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
            _log(3, "status", "turn ended (stop_sequence, 1 turns)"),
        ],
        "recovered": [
            _log(4, "text", "You've hit your weekly usage limit"),
            _log(5, "status", "turn ended (stop_sequence, 1 turns)"),
            _log(6, "user_message", "continue"),
            _log(7, "status", "turn ended (end_turn, 2 turns)"),
        ],
        "ordinary": [
            _log(8, "text", "done"),
            _log(9, "status", "turn ended (end_turn, 1 turns)"),
        ],
        "running": [
            _log(10, "text", "You've hit your usage limit"),
            _log(11, "status", "turn ended (stop_sequence, 1 turns)"),
        ],
    }

    assert find_limit_stopped_agents(sessions, logs) == [
        {
            **sessions[0],
            "limit_kind": "timed",
            "provider": "anthropic",
            "limit_turn_id": 3,
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
    assert first["id"] == second["id"]
    assert len(active) == 1
    assert json.loads(active[0]["config"])["delay_seconds"] == 1200
