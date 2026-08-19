"""Живая карта квот: панель обязана получать вердикт правила, а не считать его сама (#343).

Числа в ожиданиях — литералы, посчитанные по спеке руками: тест обязан покраснеть,
когда правило поменяют, а не подстроиться под него.
"""

import pytest

import app.db as db
import app.routes.system as system

NOW = 2_000_000_000.0


def _window(minutes, utilization, *, window_id="w", label="w", progress=0.5):
    """Окно с заданной долей пройденного: `resets_at` = NOW + остаток окна."""
    from datetime import datetime, timezone

    return {
        "id": window_id, "label": label, "window_minutes": minutes,
        "utilization": utilization,
        "resets_at": datetime.fromtimestamp(
            NOW + minutes * 60 * (1.0 - progress), timezone.utc,
        ).isoformat(),
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


def _lane(pool, lane):
    found = [item for item in pool["lanes"] if item["lane"] == lane]
    assert found, f"lane {lane} is missing from {[item['lane'] for item in pool['lanes']]}"
    return found[0]


@pytest.mark.asyncio
async def test_rule_constants_travel_with_the_payload(mapped):
    """Панель не хардкодит числа правила — иначе она разойдётся с гейтом молча."""
    payload = await mapped(_observation(
        anthropic=[_window(10080, 4, window_id="seven_day", label="7d")],
    ))

    assert payload["rule"] == {
        "hard_stop_pct": 99.0,
        "tolerance_start_pp": 10.0,
        "tolerance_end_pp": 1.0,
    }
    assert payload["observation_max_age_seconds"] == 300.0


@pytest.mark.asyncio
async def test_line_point_is_computed_server_side_for_every_pool(mapped):
    payload = await mapped(_observation(
        anthropic=[_window(10080, 4, window_id="seven_day", label="7d", progress=0.5)],
        codex=[_window(300, 4, window_id="primary", label="5h", progress=0.25)],
    ))

    claude = _pool(payload, "anthropic")
    assert claude["window"]["progress"] == pytest.approx(0.5)
    assert claude["tolerance_pp"] == pytest.approx(5.5)
    assert claude["limit_pct"] == pytest.approx(55.5)

    codex = _pool(payload, "codex")
    assert codex["window"]["progress"] == pytest.approx(0.25)
    assert codex["tolerance_pp"] == pytest.approx(7.75)
    assert codex["limit_pct"] == pytest.approx(32.75)


@pytest.mark.asyncio
async def test_gated_and_free_lanes_split_on_the_same_number(mapped):
    """90% в 10% окна: Sol и Claude стоят, Luna и Spark работают."""
    payload = await mapped(_observation(
        anthropic=[_window(10080, 90, window_id="seven_day", label="7d", progress=0.1)],
        codex=[_window(300, 90, window_id="primary", label="5h", progress=0.1)],
        codex_spark=[_window(300, 90, window_id="primary", label="5h", progress=0.1)],
    ))

    claude = _pool(payload, "anthropic")
    assert _lane(claude, "claude")["gated"] is True
    assert _lane(claude, "claude")["blocked"] is True
    assert _model(claude, "claude-opus-5[1m]")["state"] == "blocked"

    codex = _pool(payload, "codex")
    assert _lane(codex, "sol")["blocked"] is True
    assert _lane(codex, "luna")["gated"] is False
    assert _lane(codex, "luna")["blocked"] is False
    assert _model(codex, "gpt-5.6-luna")["state"] == "available"

    spark = _pool(payload, "codex_spark")
    assert _lane(spark, "spark")["gated"] is False
    assert _model(spark, "gpt-5.3-codex-spark")["state"] == "available"


@pytest.mark.asyncio
async def test_hard_stop_closes_every_lane_including_the_free_ones(mapped):
    payload = await mapped(_observation(
        codex=[_window(300, 99, window_id="primary", label="5h", progress=0.9)],
        codex_spark=[_window(300, 99, window_id="primary", label="5h", progress=0.9)],
    ))

    codex = _pool(payload, "codex")
    assert _lane(codex, "sol")["blocked"] is True
    assert _lane(codex, "luna")["blocked"] is True
    assert _lane(_pool(payload, "codex_spark"), "spark")["blocked"] is True


@pytest.mark.asyncio
async def test_spark_carries_its_own_counter_next_to_a_burnt_codex(mapped):
    """Живой случай: Codex 100%, Spark 39% — в карте это два разных пула."""
    payload = await mapped(_observation(
        codex=[_window(300, 100, window_id="primary", label="5h")],
        codex_spark=[_window(300, 39, window_id="primary", label="5h")],
    ))

    assert _pool(payload, "codex")["window"]["utilization"] == 100
    assert _pool(payload, "codex_spark")["window"]["utilization"] == 39
    assert _lane(_pool(payload, "codex_spark"), "spark")["blocked"] is False


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
async def test_pool_without_its_window_is_no_data_not_zero(mapped):
    """`utilization=0` и «телеметрии нет» обязаны различаться — иначе подпись соврёт."""
    payload = await mapped(_observation(
        anthropic=[_window(300, 26, window_id="five_hour", label="5h")],
        codex=[_window(300, 10, window_id="primary", label="5h")],
    ))

    claude = _pool(payload, "anthropic")
    assert claude["data_available"] is False
    assert claude["window"] is None
    assert claude["limit_pct"] is None and claude["tolerance_pp"] is None
    assert _model(claude, "claude-opus-5[1m]")["state"] == "unknown"
    assert _pool(payload, "codex")["data_available"] is True


@pytest.mark.asyncio
async def test_stale_observation_is_marked_not_silently_trusted(mapped):
    observation = _observation(
        codex=[_window(300, 10, window_id="primary", label="5h")],
    )
    observation["observed_at_by_provider"]["codex"] = NOW - 400

    codex = _pool(await mapped(observation), "codex")

    assert codex["fresh"] is False
    assert _model(codex, "gpt-5.6-sol")["state"] == "unknown"


@pytest.mark.asyncio
async def test_grok_is_outside_the_policy_entirely(mapped):
    payload = await mapped(_observation(
        anthropic=[_window(10080, 4, window_id="seven_day", label="7d")],
    ))

    outside = {item["model"]: item for item in payload["outside_policy"]}
    assert "grok-4.5" in outside
    assert outside["grok-4.5"]["lane"] is None
    assert outside["grok-4.5"]["gated"] is False
    assert outside["grok-4.5"]["limit_pct"] is None
    assert outside["grok-4.5"]["state"] == "not_applicable"


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
    # Снятые системы не должны воскреснуть в снимке аналитики.
    assert "quota_controller" not in payload


@pytest.mark.asyncio
async def test_non_owner_dashboard_gets_no_subscription_percentages(mapped, monkeypatch):
    """Проценты подписки owner-only — как у /api/usage; карта не обходит эти ворота."""
    monkeypatch.setattr(system, "is_owner_mode", lambda: False)

    payload = await mapped(_observation(
        anthropic=[_window(10080, 4, window_id="seven_day", label="7d")],
    ))

    assert payload == {"data_available": False, "error": "owner_mode_only"}
