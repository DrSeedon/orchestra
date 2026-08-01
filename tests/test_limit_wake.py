import asyncio
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


def _candidate(
    session_id: str,
    name: str,
    *,
    provider: str = "anthropic",
    limit_kind: str = "timed",
    limit_turn_id: int = 10,
) -> dict:
    model = "claude-opus-5[1m]" if provider == "anthropic" else "gpt-5.6-sol"
    return {
        **_session(session_id, name, model),
        "limit_kind": limit_kind,
        "provider": provider,
        "limit_turn_id": limit_turn_id,
    }


def _envelope(provider_usage: dict, *, fresh: bool = True, error=None) -> dict:
    return {"fresh": fresh, "usage": provider_usage, "error": error}


def _anthropic_usage(
    five_hour: float,
    seven_day: float,
    *,
    five_reset: str | None = None,
    seven_reset: str | None = None,
    extra_usage: dict | None = None,
) -> dict:
    usage = {
        "windows": [
            {
                "id": "five_hour",
                "utilization": five_hour,
                "resets_at": five_reset,
            },
            {
                "id": "seven_day",
                "utilization": seven_day,
                "resets_at": seven_reset,
            },
        ]
    }
    if extra_usage is not None:
        usage["extra_usage"] = extra_usage
    return usage


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
        "anthropic": _envelope({
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
        }),
        "codex": _envelope({
            "windows": [
                {
                    "id": "primary",
                    "utilization": 100,
                    "resets_at": (NOW + timedelta(hours=3)).isoformat(),
                }
            ]
        }),
    }

    plan = build_wake_plan(agents, provider_usage, now=NOW)

    assert plan["manual_agents"] == []
    assert [(item["provider"], item["reset_at"]) for item in plan["schedules"]] == [
        ("anthropic", (NOW + timedelta(days=2)).isoformat()),
        ("codex", (NOW + timedelta(hours=3)).isoformat()),
    ]


def test_monthly_spend_limit_uses_known_base_reset():
    from app.limit_wake import build_wake_plan

    monthly = _candidate(
        "monthly",
        "monthly-worker",
        limit_kind="monthly",
    )
    provider_usage = {
        "anthropic": _envelope(_anthropic_usage(
            100,
            8,
            five_reset=(NOW + timedelta(hours=1)).isoformat(),
        )),
    }

    plan = build_wake_plan([monthly], provider_usage, now=NOW)

    assert plan["manual_agents"] == []
    assert plan["schedules"][0]["reason"] == "base_reset"
    assert plan["schedules"][0]["agents"][0]["name"] == "monthly-worker"


def test_monthly_spend_limit_wakes_now_when_complete_base_is_open():
    from app.limit_wake import build_wake_plan

    monthly = _candidate(
        "monthly",
        "monthly-worker",
        limit_kind="monthly",
    )
    provider_usage = {
        "anthropic": _envelope(_anthropic_usage(
            0,
            9,
            extra_usage={
                "spend_limit_reached": True,
                "is_enabled": False,
                "disabled_reason": "org_level_disabled_until",
            },
        )),
    }

    plan = build_wake_plan([monthly], provider_usage, now=NOW)

    assert plan["schedules"][0]["reason"] == "available_now"
    assert plan["manual_agents"] == []


def test_mixed_anthropic_limit_labels_share_one_base_reset_schedule():
    from app.limit_wake import build_wake_plan

    agents = [
        _candidate("monthly", "monthly-worker", limit_kind="monthly"),
        _candidate("timed", "timed-worker", limit_turn_id=20),
    ]
    provider_usage = {
        "anthropic": _envelope(_anthropic_usage(
            100,
            9,
            five_reset=(NOW + timedelta(hours=1)).isoformat(),
        )),
    }

    plan = build_wake_plan(agents, provider_usage, now=NOW)

    assert [agent["name"] for agent in plan["schedules"][0]["agents"]] == [
        "monthly-worker",
        "timed-worker",
    ]
    assert plan["manual_agents"] == []
    assert plan["unavailable_agents"] == []


@pytest.mark.parametrize("missing_window", ["five_hour", "seven_day"])
def test_anthropic_readiness_fails_closed_when_base_window_is_missing(
    missing_window,
):
    from app.limit_wake import provider_readiness

    usage = _anthropic_usage(
        0,
        0,
        extra_usage={"spend_limit_reached": False, "is_enabled": True},
    )
    usage["windows"] = [
        window for window in usage["windows"] if window["id"] != missing_window
    ]

    readiness = provider_readiness(_envelope(usage), "anthropic", now=NOW)

    assert readiness["state"] == "unavailable"


def test_anthropic_extra_usage_cannot_authorize_exhausted_base():
    from app.limit_wake import provider_readiness

    readiness = provider_readiness(
        _envelope(_anthropic_usage(
            100,
            9,
            five_reset=(NOW + timedelta(hours=1)).isoformat(),
            extra_usage={
                "spend_limit_reached": False,
                "is_enabled": True,
                "balance": 1000,
            },
        )),
        "anthropic",
        now=NOW,
    )

    assert readiness["state"] == "reset"


def test_anthropic_reset_requires_every_exhausted_window_to_have_future_reset():
    from app.limit_wake import provider_readiness

    readiness = provider_readiness(
        _envelope(_anthropic_usage(
            100,
            100,
            five_reset=(NOW + timedelta(hours=1)).isoformat(),
        )),
        "anthropic",
        now=NOW,
    )

    assert readiness["state"] == "manual"


@pytest.mark.parametrize("provider", ["codex", "grok"])
def test_non_anthropic_keeps_valid_reset_when_another_exhausted_reset_is_missing(
    provider,
):
    from app.limit_wake import provider_readiness

    readiness = provider_readiness(
        _envelope({
            "windows": [
                {
                    "id": "primary",
                    "utilization": 100,
                    "resets_at": (NOW + timedelta(hours=2)).isoformat(),
                },
                {
                    "id": "secondary",
                    "utilization": 100,
                    "resets_at": None,
                },
            ]
        }),
        provider,
        now=NOW,
    )

    assert readiness["state"] == "reset"
    assert readiness["reset_at"] == (NOW + timedelta(hours=2)).isoformat()


@pytest.fixture
def wake_db(tmp_path, monkeypatch):
    db_path = tmp_path / "wake.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db

    init_db()
    return db_path


@pytest.mark.asyncio
async def test_schedule_wake_uses_fresh_base_capacity_and_returns_click_decision(
    monkeypatch,
):
    from app.limit_wake import schedule_wake_after_reset
    from app.routes import system

    monthly = _candidate(
        "monthly",
        "monthly-worker",
        limit_kind="monthly",
    )
    monkeypatch.setattr(
        "app.limit_wake._load_limit_stopped_agents",
        lambda: [monthly],
    )
    monkeypatch.setattr("app.limit_wake._active_wake_jobs", lambda: [])
    fresh = AsyncMock(return_value={
        "anthropic": _anthropic_usage(
            0,
            8,
            extra_usage={"spend_limit_reached": True, "is_enabled": False},
        ),
    })
    monkeypatch.setattr(system, "current_provider_usage", fresh)
    manager = MagicMock()
    manager.create = AsyncMock(return_value={"id": "wake-now"})
    manager.cancel = AsyncMock()
    monkeypatch.setattr("app.bg_jobs.bg_manager", manager)

    result = await schedule_wake_after_reset()

    fresh.assert_awaited_once_with(
        provider="anthropic",
        force_refresh=True,
    )
    config = manager.create.await_args.args[1]
    assert config["reason"] == "available_now"
    assert config["agents"][0]["limit_turn_id"] == monthly["limit_turn_id"]
    assert result["scheduled"] == [{
        "provider": "anthropic",
        "reason": "available_now",
        "reset_at": None,
        "agents": ["monthly-worker"],
        "preserved": False,
    }]
    assert result["manual"] == []
    assert result["unavailable"] == []


@pytest.mark.asyncio
async def test_refresh_failure_preserves_job_but_not_same_agent_new_turn(
    monkeypatch,
):
    from app.limit_wake import schedule_wake_after_reset
    from app.routes import system

    current = _candidate(
        "agent-a",
        "worker-a",
        limit_kind="monthly",
        limit_turn_id=20,
    )
    old_config = {
        "action": "wake_subscription_limited",
        "provider": "anthropic",
        "reason": "base_reset",
        "agents": [{
            "id": "agent-a",
            "name": "worker-a",
            "scope": "/project",
            "limit_turn_id": 10,
        }],
        "replace_key": "wake-limit-anthropic",
    }
    old_job = {
        "id": "old-job",
        "trigger_at": "2026-07-29T12:00:00+00:00",
        "config": old_config,
    }
    monkeypatch.setattr(
        "app.limit_wake._load_limit_stopped_agents",
        lambda: [current],
    )
    monkeypatch.setattr(
        "app.limit_wake._active_wake_jobs",
        lambda: [old_job],
    )
    monkeypatch.setattr(
        system,
        "current_provider_usage",
        AsyncMock(side_effect=RuntimeError("usage refresh failed")),
    )
    manager = MagicMock()
    manager.create = AsyncMock()
    manager.cancel = AsyncMock()
    monkeypatch.setattr("app.bg_jobs.bg_manager", manager)

    result = await schedule_wake_after_reset()

    manager.create.assert_not_awaited()
    manager.cancel.assert_not_awaited()
    assert old_job["config"] == old_config
    assert result["scheduled"][0]["preserved"] is True
    assert result["scheduled"][0]["agents"] == []
    assert result["unavailable"][0]["agents"] == ["worker-a"]
    assert result["warnings"][0]["agents"] == ["worker-a"]


@pytest.mark.asyncio
async def test_refresh_failure_preserved_coverage_matches_turn_pair(monkeypatch):
    from app.limit_wake import schedule_wake_after_reset
    from app.routes import system

    current = _candidate(
        "agent-a",
        "worker-a",
        limit_kind="monthly",
        limit_turn_id=10,
    )
    old_job = {
        "id": "old-job",
        "trigger_at": "2026-07-29T12:00:00+00:00",
        "config": {
            "action": "wake_subscription_limited",
            "provider": "anthropic",
            "reason": "base_reset",
            "agents": [{
                "id": "agent-a",
                "name": "worker-a",
                "scope": "/project",
                "limit_turn_id": 10,
            }],
            "replace_key": "wake-limit-anthropic",
        },
    }
    monkeypatch.setattr(
        "app.limit_wake._load_limit_stopped_agents",
        lambda: [current],
    )
    monkeypatch.setattr(
        "app.limit_wake._active_wake_jobs",
        lambda: [old_job],
    )
    monkeypatch.setattr(
        system,
        "current_provider_usage",
        AsyncMock(side_effect=RuntimeError("usage refresh failed")),
    )
    manager = MagicMock()
    manager.create = AsyncMock()
    manager.cancel = AsyncMock()
    monkeypatch.setattr("app.bg_jobs.bg_manager", manager)

    result = await schedule_wake_after_reset()

    assert result["scheduled"][0]["agents"] == ["worker-a"]
    assert result["unavailable"] == []
    assert result["warnings"] == []


@pytest.mark.asyncio
async def test_refresh_failure_does_not_report_timer_that_finished_while_awaiting(
    monkeypatch,
):
    from app.limit_wake import schedule_wake_after_reset
    from app.routes import system

    current = _candidate(
        "agent-a",
        "worker-a",
        limit_kind="monthly",
        limit_turn_id=10,
    )
    old_job = {
        "id": "old-job",
        "trigger_at": "2026-07-29T12:00:00+00:00",
        "config": {
            "action": "wake_subscription_limited",
            "provider": "anthropic",
            "reason": "base_reset",
            "agents": [current],
            "replace_key": "wake-limit-anthropic",
        },
    }
    active_reads = 0

    def active_jobs():
        nonlocal active_reads
        active_reads += 1
        return [old_job] if active_reads == 1 else []

    monkeypatch.setattr(
        "app.limit_wake._load_limit_stopped_agents",
        lambda: [current],
    )
    monkeypatch.setattr("app.limit_wake._active_wake_jobs", active_jobs)
    monkeypatch.setattr(
        system,
        "current_provider_usage",
        AsyncMock(side_effect=RuntimeError("usage refresh failed")),
    )
    manager = MagicMock()
    manager.create = AsyncMock()
    manager.cancel = AsyncMock()
    monkeypatch.setattr("app.bg_jobs.bg_manager", manager)

    result = await schedule_wake_after_reset()

    assert result["scheduled"] == []
    assert result["unavailable"][0]["agents"] == ["worker-a"]
    assert result["state"]["scheduled"] == []


@pytest.mark.asyncio
async def test_provider_refresh_cannot_borrow_another_provider_snapshot(
    monkeypatch,
):
    from app.limit_wake import schedule_wake_after_reset
    from app.routes import system

    candidate = _candidate("agent-a", "worker-a")
    monkeypatch.setattr(
        "app.limit_wake._load_limit_stopped_agents",
        lambda: [candidate],
    )
    monkeypatch.setattr("app.limit_wake._active_wake_jobs", lambda: [])
    monkeypatch.setattr(
        system,
        "current_provider_usage",
        AsyncMock(return_value={
            "codex": {
                "windows": [{
                    "id": "primary",
                    "utilization": 0,
                    "resets_at": None,
                }]
            }
        }),
    )
    manager = MagicMock()
    manager.create = AsyncMock()
    manager.cancel = AsyncMock()
    monkeypatch.setattr("app.bg_jobs.bg_manager", manager)

    result = await schedule_wake_after_reset()

    manager.create.assert_not_awaited()
    assert result["unavailable"][0]["agents"] == ["worker-a"]
    assert "missing" in result["unavailable"][0]["reason"]


@pytest.mark.asyncio
async def test_missing_requested_provider_preserves_existing_timer(monkeypatch):
    from app.limit_wake import schedule_wake_after_reset
    from app.routes import system

    candidate = _candidate("agent-a", "worker-a")
    old_job = {
        "id": "old-job",
        "trigger_at": "2026-07-29T12:00:00+00:00",
        "config": {
            "provider": "anthropic",
            "reason": "base_reset",
            "replace_key": "wake-limit-anthropic",
            "agents": [candidate],
        },
    }
    monkeypatch.setattr(
        "app.limit_wake._load_limit_stopped_agents",
        lambda: [candidate],
    )
    monkeypatch.setattr(
        "app.limit_wake._active_wake_jobs",
        lambda: [old_job],
    )
    monkeypatch.setattr(
        system,
        "current_provider_usage",
        AsyncMock(return_value={
            "codex": {
                "windows": [{
                    "id": "primary",
                    "utilization": 0,
                    "resets_at": None,
                }]
            }
        }),
    )
    manager = MagicMock()
    manager.create = AsyncMock()
    manager.cancel = AsyncMock()
    monkeypatch.setattr("app.bg_jobs.bg_manager", manager)

    result = await schedule_wake_after_reset()

    manager.create.assert_not_awaited()
    manager.cancel.assert_not_awaited()
    assert result["scheduled"][0]["preserved"] is True
    assert result["scheduled"][0]["agents"] == ["worker-a"]
    assert result["unavailable"] == []


@pytest.mark.asyncio
async def test_successful_manual_decision_cancels_obsolete_timer(monkeypatch):
    from app.limit_wake import schedule_wake_after_reset
    from app.routes import system

    candidate = _candidate(
        "agent-a",
        "worker-a",
        limit_kind="monthly",
    )
    old_job = {
        "id": "old-job",
        "trigger_at": "2026-07-29T12:00:00+00:00",
        "config": {
            "provider": "anthropic",
            "replace_key": "wake-limit-anthropic",
            "agents": [candidate],
        },
    }
    monkeypatch.setattr(
        "app.limit_wake._load_limit_stopped_agents",
        lambda: [candidate],
    )
    monkeypatch.setattr(
        "app.limit_wake._active_wake_jobs",
        lambda: [old_job],
    )
    monkeypatch.setattr(
        system,
        "current_provider_usage",
        AsyncMock(return_value={
            "anthropic": _anthropic_usage(100, 100),
        }),
    )
    manager = MagicMock()
    manager.create = AsyncMock()
    manager.cancel = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr("app.bg_jobs.bg_manager", manager)

    result = await schedule_wake_after_reset()

    manager.create.assert_not_awaited()
    manager.cancel.assert_awaited_once_with("old-job")
    assert result["manual"][0]["agents"] == ["worker-a"]


@pytest.mark.asyncio
async def test_concurrent_clicks_cannot_restore_an_older_capacity_decision(
    monkeypatch,
):
    from app import limit_wake
    from app.routes import system

    candidate = _candidate("agent-a", "worker-a")
    active_jobs = [{
        "id": "initial-job",
        "trigger_at": "2026-07-29T12:00:00+00:00",
        "config": {
            "provider": "anthropic",
            "replace_key": "wake-limit-anthropic",
            "agents": [candidate],
        },
    }]
    monkeypatch.setattr(
        limit_wake,
        "_load_limit_stopped_agents",
        lambda: [candidate],
    )
    monkeypatch.setattr(
        limit_wake,
        "_active_wake_jobs",
        lambda: list(active_jobs),
    )
    monkeypatch.setattr(limit_wake, "_schedule_lock", asyncio.Lock())

    first_started = asyncio.Event()
    release_first = asyncio.Event()
    fetch_calls = 0

    async def fresh_usage(**_kwargs):
        nonlocal fetch_calls
        fetch_calls += 1
        if fetch_calls == 1:
            first_started.set()
            await release_first.wait()
            return {"anthropic": _anthropic_usage(0, 0)}
        return {"anthropic": _anthropic_usage(100, 100)}

    async def create(_kind, config, *_args, **kwargs):
        active_jobs[:] = [{
            "id": "new-job",
            "trigger_at": config.get("reset_at"),
            "config": {
                **config,
                "replace_key": kwargs["replace_key"],
            },
        }]
        return {"id": "new-job"}

    async def cancel(job_id):
        active_jobs[:] = [job for job in active_jobs if job["id"] != job_id]
        return {"ok": True}

    monkeypatch.setattr(system, "current_provider_usage", fresh_usage)
    manager = MagicMock()
    manager.create = AsyncMock(side_effect=create)
    manager.cancel = AsyncMock(side_effect=cancel)
    monkeypatch.setattr("app.bg_jobs.bg_manager", manager)

    older = asyncio.create_task(limit_wake.schedule_wake_after_reset())
    await asyncio.wait_for(first_started.wait(), timeout=1)
    newer = asyncio.create_task(limit_wake.schedule_wake_after_reset())
    await asyncio.sleep(0)
    assert fetch_calls == 1
    release_first.set()
    await asyncio.gather(older, newer)

    assert fetch_calls == 2
    assert active_jobs == []
    manager.cancel.assert_awaited_once_with("new-job")


def test_wake_status_exposes_active_job_names_and_reason(monkeypatch):
    from app.limit_wake import wake_status

    monkeypatch.setattr(
        "app.limit_wake._load_limit_stopped_agents",
        lambda: [_candidate("agent-a", "worker-a", limit_kind="monthly")],
    )
    monkeypatch.setattr(
        "app.limit_wake._active_wake_jobs",
        lambda: [{
            "id": "wake-job",
            "trigger_at": "2026-07-29T12:00:00+00:00",
            "config": {
                "provider": "anthropic",
                "reason": "base_reset",
                "agents": [{
                    "id": "agent-a",
                    "name": "worker-a",
                    "scope": "/project",
                    "limit_turn_id": 10,
                }],
            },
        }],
    )

    status = wake_status()

    assert status["scheduled"][0]["agents"] == ["worker-a"]
    assert status["scheduled"][0]["reason"] == "base_reset"
    assert status["manual"] == []
    assert status["unavailable"] == []


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
            {"anthropic": _anthropic_usage(0, 0)},
            {"anthropic": _anthropic_usage(100, 0)},
        ]),
    )
    session = MagicMock(status=AgentStatus.IDLE)
    session.id = "a"
    session.send = AsyncMock()
    manager = MagicMock()
    manager.ensure_loaded = AsyncMock(return_value=session)

    async def deliver(_session_id, message):
        await session.send(message)

    manager.send = AsyncMock(side_effect=deliver)

    await run_wake_job(
        "wake-job",
        {
            "provider": "anthropic",
            "agents": targets,
        },
        manager,
        stagger_seconds=0,
    )

    manager.send.assert_awaited_once()
    session.send.assert_awaited_once()
    row = next(job for job in bg_get_jobs() if job["id"] == "wake-job")
    assert row["status"] == "triggered"
    assert "base capacity has no timed reset" in row["last_output"]
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
            "anthropic": _anthropic_usage(0, 0),
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
