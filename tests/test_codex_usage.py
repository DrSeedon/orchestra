import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.routes import system


@pytest.fixture(autouse=True)
def _no_live_grok_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(system, "_GROK_CREDENTIALS_PATH", tmp_path / "missing-grok-auth.json")
    monkeypatch.setattr(system, "_grok_usage_cache", {"data": None, "ts": 0.0})


def test_normalize_codex_usage_prefers_codex_bucket():
    result = {
        "rateLimits": {"planType": "plus", "primary": None},
        "rateLimitsByLimitId": {
            "codex": {
                "planType": "prolite",
                "primary": {
                    "usedPercent": 6,
                    "windowDurationMins": 10080,
                    "resetsAt": 1784957081,
                },
                "secondary": None,
                "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
            },
        },
        "rateLimitResetCredits": {"availableCount": 2},
    }

    usage = system._normalize_codex_usage(result)

    assert usage == {
        "plan_type": "prolite",
        "primary": {
            "utilization": 6,
            "window_minutes": 10080,
            "resets_at": "2026-07-25T05:24:41Z",
        },
        "secondary": None,
        "credits": {"has_credits": False, "unlimited": False, "balance": "0"},
        "reset_credits": 2,
    }


def test_normalize_codex_usage_exposes_separate_spark_bucket():
    result = {
        "rateLimitsByLimitId": {
            "codex": {
                "planType": "prolite",
                "primary": {
                    "usedPercent": 39,
                    "windowDurationMins": 10080,
                    "resetsAt": 1784957080,
                },
                "secondary": None,
            },
            "codex_bengalfox": {
                "planType": "prolite",
                "primary": {
                    "usedPercent": 8,
                    "windowDurationMins": 10080,
                    "resetsAt": 1784964042,
                },
                "secondary": None,
            },
        },
    }

    usage = system._normalize_codex_usage(result)

    assert usage["primary"]["utilization"] == 39
    assert usage["spark"] == {
        "limit_id": "codex_bengalfox",
        "plan_type": "prolite",
        "primary": {
            "utilization": 8,
            "window_minutes": 10080,
            "resets_at": "2026-07-25T07:20:42Z",
        },
        "secondary": None,
    }


def test_provider_usage_snapshot_unifies_provider_windows():
    anthropic = {
        "five_hour": {"utilization": 9, "resets_at": "2026-07-18T11:20:00Z"},
        "seven_day": {"utilization": 67, "resets_at": "2026-07-21T07:00:00Z"},
    }
    codex = {
        "plan_type": "prolite",
        "primary": {
            "utilization": 34,
            "window_minutes": 10080,
            "resets_at": "2026-07-25T05:24:41Z",
        },
        "secondary": None,
        "spark": {
            "limit_id": "codex_bengalfox",
            "plan_type": "prolite",
            "primary": {
                "utilization": 8,
                "window_minutes": 10080,
                "resets_at": "2026-07-25T07:20:42Z",
            },
            "secondary": None,
        },
    }
    grok = {
        "plan_type": "X Premium+",
        "primary": {
            "utilization": 10,
            "window_minutes": 10080,
            "resets_at": "2026-08-01T18:49:05.891405Z",
        },
        "secondary": None,
    }

    providers = system._provider_usage_snapshot(anthropic, codex, grok)

    assert providers == {
        "anthropic": {
            "label": "Claude",
            "windows": [
                {
                    "id": "five_hour",
                    "label": "5h",
                    "utilization": 9,
                    "window_minutes": 300,
                    "resets_at": "2026-07-18T11:20:00Z",
                },
                {
                    "id": "seven_day",
                    "label": "7d",
                    "utilization": 67,
                    "window_minutes": 10080,
                    "resets_at": "2026-07-21T07:00:00Z",
                },
            ],
        },
        "codex": {
            "label": "Codex",
            "plan_type": "prolite",
            "windows": [
                {
                    "id": "primary",
                    "label": "7d",
                    "utilization": 34,
                    "window_minutes": 10080,
                    "resets_at": "2026-07-25T05:24:41Z",
                },
            ],
        },
        "codex_spark": {
            "label": "Codex Spark",
            "plan_type": "prolite",
            "windows": [
                {
                    "id": "primary",
                    "label": "7d",
                    "utilization": 8,
                    "window_minutes": 10080,
                    "resets_at": "2026-07-25T07:20:42Z",
                },
            ],
        },
        "grok": {
            "label": "Grok",
            "plan_type": "X Premium+",
            "windows": [
                {
                    "id": "primary",
                    "label": "7d",
                    "utilization": 10,
                    "window_minutes": 10080,
                    "resets_at": "2026-08-01T18:49:05.891405Z",
                },
            ],
        },
    }


def test_normalize_grok_usage_requires_verified_weekly_shape():
    result = {
        "config": {
            "currentPeriod": {
                "type": "USAGE_PERIOD_TYPE_WEEKLY",
                "start": "2026-07-25T18:49:05.891405+00:00",
                "end": "2026-08-01T18:49:05.891405+00:00",
            },
            "creditUsagePercent": 10.0,
        },
        "subscription_tier": "X Premium+",
    }

    assert system._normalize_grok_usage(result) == {
        "plan_type": "X Premium+",
        "primary": {
            "utilization": 10,
            "window_minutes": 10080,
            "resets_at": "2026-08-01T18:49:05.891405Z",
        },
        "secondary": None,
    }

    result["config"]["currentPeriod"]["type"] = "USAGE_PERIOD_TYPE_MONTHLY"
    assert system._normalize_grok_usage(result) is None
    result["config"]["currentPeriod"]["type"] = "USAGE_PERIOD_TYPE_WEEKLY"
    result["config"]["creditUsagePercent"] = None
    assert system._normalize_grok_usage(result) is None


def test_read_grok_token_prefers_latest_credential(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({
        "https://auth.x.ai::old": {
            "key": "old-token",
            "expires_at": "2026-07-28T01:00:00Z",
        },
        "https://auth.x.ai::fresh": {
            "key": "fresh-token",
            "expires_at": "2026-07-29T01:00:00Z",
        },
    }))
    monkeypatch.setattr(system, "_GROK_CREDENTIALS_PATH", auth)

    assert system._read_grok_token() == "fresh-token"


@pytest.mark.asyncio
async def test_fetch_grok_usage_uses_credit_format_and_treats_401_as_missing(monkeypatch):
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "config": {
                    "currentPeriod": {
                        "type": "USAGE_PERIOD_TYPE_WEEKLY",
                        "start": "2026-07-25T18:49:05.891405+00:00",
                        "end": "2026-08-01T18:49:05.891405+00:00",
                    },
                    "creditUsagePercent": 10,
                },
            }

    class FakeClient:
        request = None

        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def get(self, url, **kwargs):
            FakeClient.request = (url, kwargs)
            return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)

    usage = await system._fetch_grok_usage("secret")

    url, kwargs = FakeClient.request
    assert url == "https://cli-chat-proxy.grok.com/v1/billing"
    assert kwargs["params"] == {"format": "credits"}
    assert kwargs["headers"]["Authorization"] == "Bearer secret"
    assert usage["primary"]["utilization"] == 10

    FakeResponse.status_code = 401
    with pytest.raises(PermissionError, match="token_expired"):
        await system._fetch_grok_usage("expired")


@pytest.mark.asyncio
async def test_grok_401_returns_no_data_instead_of_zero_or_stale(monkeypatch):
    monkeypatch.setattr(system, "_read_grok_token", lambda: "expired")
    monkeypatch.setattr(
        system,
        "_grok_usage_cache",
        {"data": {"primary": {"utilization": 73}}, "ts": 0.0},
    )
    monkeypatch.setattr(
        system,
        "_fetch_grok_usage",
        AsyncMock(side_effect=PermissionError("token_expired")),
    )
    monkeypatch.setattr(system, "_usage_cache", {"data": None, "ts": 0.0, "token": None})
    monkeypatch.setattr(system, "_codex_usage_cache", {"data": None, "ts": 0.0})
    monkeypatch.setattr(system, "_fetch_codex_usage", AsyncMock(side_effect=RuntimeError("offline")))
    monkeypatch.setattr(system, "_get_agents_cost", lambda: {})
    monkeypatch.setattr(system, "_get_voice_cost_usd", lambda: 0.0)

    response = await system._get_usage_data()

    assert response["grok"] is None
    assert system._grok_usage_cache["data"] is None


def test_usage_history_round_trips_universal_provider_windows(tmp_path, monkeypatch):
    db_path = tmp_path / "usage.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db, usage_get_history, usage_save_snapshot

    init_db()
    providers = {
        "codex": {
            "label": "Codex",
            "windows": [{
                "id": "primary",
                "label": "7d",
                "utilization": 34,
                "window_minutes": 10080,
                "resets_at": "2026-07-25T05:24:41Z",
            }],
        },
    }
    usage_save_snapshot(9, 67, "a", "b", 1.0, 0, providers=providers)

    history = usage_get_history(hours=1)

    assert history
    assert history[-1]["providers"] == providers
    assert "provider_usage" not in history[-1]


def test_usage_history_includes_latest_snapshot_before_next_grid_point(tmp_path, monkeypatch):
    db_path = tmp_path / "usage.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db, usage_get_history

    init_db()
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    latest_ts = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    old_providers = {"anthropic": {"label": "Claude", "windows": []}}
    latest_providers = {
        "codex": {"label": "Codex", "windows": []},
        "codex_spark": {"label": "Codex Spark", "windows": []},
    }
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """INSERT INTO usage_snapshots
               (ts, five_hour_pct, seven_day_pct, provider_usage)
               VALUES (?, 0, 0, ?)""",
            [
                (old_ts, json.dumps(old_providers)),
                (latest_ts, json.dumps(latest_providers)),
            ],
        )

    history = usage_get_history(hours=1, step_minutes=5)

    assert history[-1]["ts"] == latest_ts
    assert history[-1]["providers"] == latest_providers


def test_usage_snapshot_migrates_old_history_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "old-usage.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE usage_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                five_hour_pct REAL DEFAULT 0,
                seven_day_pct REAL DEFAULT 0,
                five_hour_resets_at TEXT,
                seven_day_resets_at TEXT,
                total_cost_usd REAL DEFAULT 0,
                active_agents INTEGER DEFAULT 0
            )
        """)
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db

    init_db()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(usage_snapshots)")}
    assert "provider_usage" in columns


@pytest.mark.asyncio
async def test_snapshot_collector_persists_codex_without_anthropic_oauth(monkeypatch):
    codex = {
        "plan_type": "prolite",
        "primary": {
            "utilization": 34,
            "window_minutes": 10080,
            "resets_at": "2026-07-25T05:24:41Z",
        },
        "secondary": None,
    }
    save_snapshot = MagicMock()
    monkeypatch.setattr(system, "_read_oauth_credentials", lambda: (None, None, None))
    monkeypatch.setattr(system, "_fetch_codex_usage", AsyncMock(return_value=codex))
    monkeypatch.setattr(system, "_usage_cache", {"data": None, "ts": 0.0, "token": None})
    monkeypatch.setattr(system, "_codex_usage_cache", {"data": None, "ts": 0.0})
    monkeypatch.setattr(system.manager, "sessions", {})
    monkeypatch.setattr("app.db.usage_save_snapshot", save_snapshot)

    await system._collect_usage_snapshot()

    save_snapshot.assert_called_once()
    assert save_snapshot.call_args.kwargs["providers"]["codex"]["windows"][0]["utilization"] == 34
    assert system._codex_usage_cache["data"] is codex


@pytest.mark.asyncio
async def test_usage_endpoint_adds_codex_without_changing_anthropic(monkeypatch):
    anthropic = {"five_hour": {"utilization": 12}, "seven_day": {"utilization": 34}}
    codex = {
        "plan_type": "prolite",
        "primary": {"utilization": 6, "window_minutes": 10080, "resets_at": None},
        "secondary": None,
    }
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)
    monkeypatch.setattr(system, "_usage_cache", {"data": anthropic, "ts": time.time(), "token": None})
    monkeypatch.setattr(system, "_codex_usage_cache", {"data": None, "ts": 0.0})
    monkeypatch.setattr(system, "_fetch_codex_usage", AsyncMock(return_value=codex))
    monkeypatch.setattr(system, "_get_agents_cost", lambda: {"agents_count": 0})
    monkeypatch.setattr(system, "_get_voice_cost_usd", lambda: 0.42)

    response = await system.get_usage()

    assert response["anthropic"] is anthropic
    assert response["codex"] is codex
    assert response["orchestra"] == {"agents_count": 0}
    assert response["voice_cost_usd"] == 0.42


@pytest.mark.asyncio
async def test_codex_failure_does_not_break_anthropic_usage(monkeypatch):
    anthropic = {"five_hour": {"utilization": 12}}
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)
    monkeypatch.setattr(system, "_usage_cache", {"data": anthropic, "ts": time.time(), "token": None})
    monkeypatch.setattr(system, "_codex_usage_cache", {"data": None, "ts": 0.0})
    monkeypatch.setattr(system, "_fetch_codex_usage", AsyncMock(side_effect=RuntimeError("not logged in")))
    monkeypatch.setattr(system, "_get_agents_cost", lambda: {})
    monkeypatch.setattr(system, "_get_voice_cost_usd", lambda: 0.0)

    response = await system.get_usage()

    assert response["anthropic"] is anthropic
    assert response["codex"] is None


@pytest.mark.asyncio
async def test_missing_anthropic_credentials_preserves_codex_capacity(monkeypatch):
    codex = {
        "plan_type": "pro",
        "primary": {"utilization": 22, "window_minutes": 10080},
    }
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)
    monkeypatch.setattr(
        system,
        "_usage_cache",
        {"data": None, "ts": 0.0, "token": None},
    )
    monkeypatch.setattr(
        system,
        "_codex_usage_cache",
        {"data": None, "ts": 0.0},
    )
    monkeypatch.setattr(
        system,
        "_read_oauth_credentials",
        lambda: (None, None, None),
    )
    monkeypatch.setattr(
        system,
        "_fetch_codex_usage",
        AsyncMock(return_value=codex),
    )
    monkeypatch.setattr(system, "_get_agents_cost", lambda: {})
    monkeypatch.setattr(system, "_get_voice_cost_usd", lambda: 0.0)

    response = await system.get_usage()

    assert response["anthropic"] is None
    assert response["codex"] is codex


@pytest.mark.asyncio
async def test_forced_provider_refresh_never_authorizes_stale_capacity(monkeypatch):
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)
    monkeypatch.setattr(
        system,
        "_usage_cache",
        {
            "data": {
                "five_hour": {
                    "utilization": 20,
                    "resets_at": "2026-07-25T15:00:00Z",
                }
            },
            "ts": time.time(),
            "token": None,
        },
    )
    monkeypatch.setattr(
        system,
        "_read_oauth_credentials",
        lambda: ("token", None, None),
    )
    monkeypatch.setattr(
        system,
        "_fetch_anthropic_usage",
        AsyncMock(side_effect=RuntimeError("offline")),
    )

    with pytest.raises(RuntimeError, match="fresh Anthropic usage"):
        await system.current_provider_usage(
            provider="anthropic",
            force_refresh=True,
        )


@pytest.mark.asyncio
async def test_internal_provider_refresh_works_when_not_owner_mode(
    monkeypatch,
):
    anthropic = {
        "five_hour": {
            "utilization": 0,
            "resets_at": "2026-07-25T15:00:00Z",
        }
    }
    monkeypatch.setattr(system, "is_owner_mode", lambda: False)
    monkeypatch.setattr(
        system,
        "_read_oauth_credentials",
        lambda: ("token", None, None),
    )
    monkeypatch.setattr(
        system,
        "_fetch_anthropic_usage",
        AsyncMock(return_value=anthropic),
    )
    monkeypatch.setattr(
        system,
        "_fetch_codex_usage",
        AsyncMock(side_effect=RuntimeError("unused provider offline")),
    )
    monkeypatch.setattr(system, "_get_agents_cost", lambda: {})
    monkeypatch.setattr(system, "_get_voice_cost_usd", lambda: 0.0)

    providers = await system.current_provider_usage(
        provider="anthropic",
        force_refresh=True,
    )

    assert providers["anthropic"]["windows"][0]["utilization"] == 0


@pytest.mark.asyncio
async def test_fetch_codex_usage_uses_app_server_protocol(monkeypatch):
    class FakeStdin:
        def __init__(self):
            self.messages = []

        def write(self, data):
            self.messages.append(json.loads(data))

        async def drain(self):
            pass

        def close(self):
            pass

    class FakeStdout:
        def __init__(self):
            self.lines = iter([
                b'{"id":1,"result":{"userAgent":"test"}}\n',
                b'{"id":2,"result":{"rateLimits":{"planType":"pro","primary":{"usedPercent":9,"windowDurationMins":300,"resetsAt":1784957081},"secondary":null}}}\n',
            ])

        async def readline(self):
            return next(self.lines, b"")

    class FakeProcess:
        def __init__(self):
            self.stdin = FakeStdin()
            self.stdout = FakeStdout()
            self.returncode = None

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

    proc = FakeProcess()
    monkeypatch.setattr(system.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))

    usage = await system._fetch_codex_usage()

    assert usage["primary"]["window_minutes"] == 300
    assert [message["method"] for message in proc.stdin.messages] == [
        "initialize", "initialized", "account/rateLimits/read",
    ]
