"""Живая карта квот и полоса Claude в горячей политике (#318).

Пороги в ожиданиях — литералы: тест обязан покраснеть, когда политику поменяют,
а не подстроиться под неё.
"""

import sqlite3

import pytest

import app.db as db
import app.routes.system as system

NOW = 2_000_000_000.0


def _window(minutes, utilization, *, window_id="w", label="w"):
    return {
        "id": window_id, "label": label, "window_minutes": minutes,
        "utilization": utilization, "resets_at": "2033-05-18T04:33:20+00:00",
    }


def _observation(**providers):
    return {
        "providers": {
            name: {"label": name, "windows": windows}
            for name, windows in providers.items()
        },
        "observed_at_by_provider": {name: NOW - 10 for name in providers},
    }


@pytest.fixture
def mapped(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "quota-map.db")
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)

    async def no_refresh(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(system, "_get_usage_data", no_refresh)
    monkeypatch.setattr(system.time, "time", lambda: NOW)

    async def run(observation):
        monkeypatch.setattr(system, "_quota_observation_from_cache", lambda: observation)
        return await system.quota_map()

    return run


def _pool(payload, bucket):
    found = [item for item in payload["buckets"] if item["bucket"] == bucket]
    assert found, f"bucket {bucket} is missing from {[b['bucket'] for b in payload['buckets']]}"
    return found[0]


def _model(pool, model):
    found = [item for item in pool["models"] if item["model"] == model]
    assert found, f"model {model} is missing from {[m['model'] for m in pool['models']]}"
    return found[0]


@pytest.mark.asyncio
async def test_every_pool_reports_its_own_threshold_and_verdict(mapped):
    payload = await mapped(_observation(
        anthropic=[_window(10080, 4, window_id="seven_day", label="7d")],
        codex=[_window(10080, 99, window_id="primary", label="7d")],
        codex_spark=[_window(10080, 1, window_id="primary", label="7d")],
    ))

    claude = _pool(payload, "anthropic")
    assert [(lane["lane"], lane["threshold"]) for lane in claude["lanes"]] == [("claude", 90.0)]
    assert _model(claude, "claude-opus-5[1m]")["state"] == "available"

    codex = _pool(payload, "codex")
    assert [(lane["lane"], lane["threshold"]) for lane in codex["lanes"]] == [
        ("sol", 95.0), ("luna", 98.0),
    ]
    assert _model(codex, "gpt-5.6-sol")["state"] == "blocked"
    assert _model(codex, "gpt-5.6-luna")["state"] == "blocked"

    spark = _pool(payload, "codex_spark")
    assert _model(spark, "gpt-5.3-codex-spark")["state"] == "available"
    assert payload["mode"]["deciding"] == "static_thresholds"
    assert payload["mode"]["source"] == "temporary_static_override"


@pytest.mark.asyncio
async def test_claude_five_hour_window_is_reference_and_never_gates(mapped):
    payload = await mapped(_observation(anthropic=[
        _window(300, 99, window_id="five_hour", label="5h"),
        _window(10080, 4, window_id="seven_day", label="7d"),
    ]))

    claude = _pool(payload, "anthropic")
    assert claude["window"]["id"] == "seven_day"
    assert claude["window"]["utilization"] == 4
    assert [item["id"] for item in claude["reference_windows"]] == ["five_hour"]
    assert _model(claude, "claude-opus-5[1m]")["state"] == "available"


@pytest.mark.asyncio
async def test_pool_without_weekly_telemetry_is_no_data_not_zero(mapped):
    payload = await mapped(_observation(
        anthropic=[_window(300, 26, window_id="five_hour", label="5h")],
        codex=[_window(10080, 10, window_id="primary", label="7d")],
    ))

    claude = _pool(payload, "anthropic")
    assert claude["data_available"] is False
    assert claude["window"] is None
    assert _model(claude, "claude-opus-5[1m]")["state"] == "unknown"
    assert _pool(payload, "codex")["data_available"] is True


@pytest.mark.asyncio
async def test_grok_has_no_threshold_at_all(mapped):
    payload = await mapped(_observation(
        anthropic=[_window(10080, 4, window_id="seven_day", label="7d")],
    ))

    outside = {item["model"]: item for item in payload["outside_policy"]}
    assert "grok-4.5" in outside
    assert outside["grok-4.5"]["threshold"] is None
    assert outside["grok-4.5"]["lane"] is None
    assert outside["grok-4.5"]["state"] == "not_applicable"


@pytest.mark.asyncio
async def test_hot_claude_lane_moves_both_the_gate_and_the_map(mapped):
    observation = _observation(
        anthropic=[_window(10080, 60, window_id="seven_day", label="7d")],
    )
    before = await mapped(observation)
    assert _model(_pool(before, "anthropic"), "claude-opus-5[1m]")["state"] == "available"

    db.replace_quota_policy({"claude": 55}, actor="test", reason="tighten claude")

    after = await mapped(observation)
    claude = _pool(after, "anthropic")
    assert [(lane["lane"], lane["threshold"]) for lane in claude["lanes"]] == [("claude", 55.0)]
    assert _model(claude, "claude-opus-5[1m]")["state"] == "blocked"
    assert _model(claude, "claude-opus-5[1m]")["threshold"] == 55.0


def test_existing_three_lane_database_migrates_without_losing_revisions(tmp_path, monkeypatch):
    """Живая БД создана со старым CHECK на три полосы — её нельзя ни уронить,
    ни обнулить: пороги, ревизии и причины операторских правок обязаны выжить."""
    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(str(path))
    legacy.execute("""
        CREATE TABLE IF NOT EXISTS quota_controller_policy (
            lane TEXT PRIMARY KEY CHECK (lane IN ('sol','luna','spark')),
            threshold REAL NOT NULL CHECK (threshold >= 0 AND threshold <= 100),
            revision INTEGER NOT NULL CHECK (revision >= 1),
            source TEXT NOT NULL,
            reason TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    legacy.executemany(
        "INSERT INTO quota_controller_policy VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("sol", 93.0, 7, "temporary_static_override", "operator runway", "2026-08-17T10:00:00+00:00"),
            ("luna", 97.0, 7, "temporary_static_override", "operator runway", "2026-08-17T10:00:00+00:00"),
            ("spark", 95.0, 7, "temporary_static_override", "operator runway", "2026-08-17T10:00:00+00:00"),
        ],
    )
    legacy.commit()
    legacy.close()

    monkeypatch.setattr(db, "DB_PATH", path)
    snapshot = db.quota_policy_snapshot()

    lanes = snapshot["lanes"]
    assert lanes["sol"]["threshold"] == 93.0
    assert lanes["luna"]["threshold"] == 97.0
    assert lanes["spark"]["threshold"] == 95.0
    assert lanes["sol"]["revision"] == 7
    assert lanes["sol"]["reason"] == "operator runway"
    assert lanes["claude"]["threshold"] == 90.0
    assert lanes["claude"]["revision"] == 7
    assert snapshot["revision"] == 7

    # После миграции политика остаётся операторски изменяемой, включая новую полосу.
    changed = db.replace_quota_policy(
        {"claude": 88}, actor="test", reason="post-migration edit",
        expected_revision=snapshot["revision"],
    )
    assert changed["lanes"]["claude"]["threshold"] == 88.0
    assert changed["lanes"]["sol"]["threshold"] == 93.0
    assert changed["revision"] == 8
    assert db.quota_policy_audit()[0]["new"]["claude"] == 88.0


@pytest.mark.asyncio
async def test_analytics_snapshot_carries_the_map_in_one_request(mapped, monkeypatch):
    """Модалка держит контракт «один запрос на открытие»: карта едет тем же снимком."""
    db.init_db()
    monkeypatch.setattr(
        system, "_quota_observation_from_cache",
        lambda: _observation(anthropic=[_window(10080, 4, window_id="seven_day", label="7d")]),
    )

    async def usage():
        return {"anthropic": {"seven_day": {"utilization": 4}}}

    monkeypatch.setattr(system, "get_usage", usage)
    import app.usage_analytics as usage_analytics

    monkeypatch.setattr(
        usage_analytics, "build_usage_analytics",
        lambda **_kwargs: {"summary": {}, "capacity": {}},
    )
    payload = await system.usage_analytics_endpoint(days=1)

    assert "quota_map" in payload
    assert _pool(payload["quota_map"], "anthropic")["window"]["utilization"] == 4
    assert payload["quota_map"]["mode"]["deciding"] == "static_thresholds"


@pytest.mark.asyncio
async def test_non_owner_dashboard_gets_no_subscription_percentages(mapped, monkeypatch):
    """Проценты подписки owner-only — как у /api/usage; карта не обходит эти ворота."""
    monkeypatch.setattr(system, "is_owner_mode", lambda: False)

    payload = await mapped(_observation(
        anthropic=[_window(10080, 4, window_id="seven_day", label="7d")],
    ))

    assert payload == {"data_available": False, "error": "owner_mode_only"}
