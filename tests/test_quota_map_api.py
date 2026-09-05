"""Живая карта квот: панель обязана получать вердикт правила, а не считать его сама (#343).

Числа в ожиданиях — литералы, посчитанные по спеке руками: тест обязан покраснеть,
когда правило поменяют, а не подстроиться под него.
"""

import pytest
import json
from datetime import datetime, timezone

import app.db as db
import app.routes.system as system
import importlib

import app.quota_gate as quota_gate

NOW = 2_000_000_000.0


_QUOTA_ENV_NAMES = (
    "QUOTA_TOLERANCE_START_PP",
    "QUOTA_TOLERANCE_END_PP",
    "QUOTA_HARD_STOP_PCT",
    "QUOTA_GATED_LANES",
    "QUOTA_CURVE_EXPONENT",
    "QUOTA_CURVED_LANES",
)


def _reload_quota_gate_with_env(monkeypatch, **overrides: str | None):
    for name in _QUOTA_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    for name, value in overrides.items():
        if value is None:
            continue
        monkeypatch.setenv(name, value)
    return importlib.reload(quota_gate)


@pytest.fixture
def reloaded_quota_gate(monkeypatch):
    """Перезагрузка `app.quota_gate` с откатом, который переживает ПАДЕНИЕ теста.

    Раньше откат стоял последней строкой тела теста. Тест падал раньше неё, модуль
    оставался с чужими константами, и следующие тесты файла краснели по чужой
    причине: `test_line_point_is_computed_server_side_for_every_pool` в одиночку
    зелёный, а после теста env-переопределений получал `tolerance_pp` 7.5 вместо
    5.5 — то есть `13 + (2 - 13) * 0.5` от QUOTA_TOLERANCE_*, утёкших сюда.
    Фикстура откатывает в teardown, поэтому утечка невозможна независимо от исхода.
    """
    yield lambda **overrides: _reload_quota_gate_with_env(monkeypatch, **overrides)
    for name in _QUOTA_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    importlib.reload(quota_gate)


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


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _providers_snapshot(*, codex_reset: float, spark_reset: float, claude_reset: float,
                       codex_util: float, spark_util: float, claude_util: float):
    return {
        "codex": {
            "label": "Codex",
            "windows": [
                {
                    "id": "primary",
                    "label": "5h",
                    "window_minutes": 300,
                    "utilization": codex_util,
                    "resets_at": _iso(codex_reset),
                },
            ],
        },
        "codex_spark": {
            "label": "Codex Spark",
            "windows": [
                {
                    "id": "primary",
                    "label": "5h",
                    "window_minutes": 300,
                    "utilization": spark_util,
                    "resets_at": _iso(spark_reset),
                },
            ],
        },
        "anthropic": {
            "label": "Claude",
            "windows": [
                {
                    "id": "seven_day",
                    "label": "7d",
                    "window_minutes": 10080,
                    "utilization": claude_util,
                    "resets_at": _iso(claude_reset),
                },
            ],
        },
    }


def _expected_release_status(
    utilization: float,
    progress: float,
    resets_at: str,
    lane: str = "sol",
) -> tuple[str, float | None]:
    """Момент открытия полосы по спеке — считается здесь, а не берётся у гейта.

    Константы продублированы намеренно (см. заголовок файла): тест обязан краснеть,
    когда правило поменяют. У кривой полосы обратной функции в замкнутом виде нет,
    поэтому корень ищется делением пополам — ровно как в `line_release_progress`.
    """
    hard_stop = 99.0
    start = 10.0
    end = 1.0
    exponent = 2.5
    curved_lanes = ("sol",)

    def limit_at(point: float) -> float:
        norm = point
        if lane in curved_lanes and point > 0.0:
            norm = point ** (1.0 / exponent)
        tolerance = start + (end - start) * point
        return min(hard_stop, norm * 100.0 + tolerance)

    if utilization >= hard_stop:
        return "at_reset", (datetime.fromisoformat(resets_at).timestamp() - NOW)

    if utilization <= limit_at(progress):
        return "open", None
    if utilization > limit_at(1.0):
        return "at_reset", datetime.fromisoformat(resets_at).timestamp() - NOW
    low, high = progress, 1.0
    for _ in range(60):
        middle = (low + high) / 2.0
        if limit_at(middle) < utilization:
            low = middle
        else:
            high = middle
    return "opens_in", (high - progress) * 300 * 60.0


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
        # Кривизна — такая же часть правила, как допуск: панель рисует порог сама и
        # без этих двух полей нарисует ПРЯМУЮ там, где гейт блокирует по параболе.
        "curve_exponent": 2.5,
        "curved_lanes": ["sol"],
    }
    assert payload["observation_max_age_seconds"] == 300.0


@pytest.mark.asyncio
async def test_rule_constants_reflect_environment_overrides(mapped, reloaded_quota_gate):
    gate = reloaded_quota_gate(
        QUOTA_HARD_STOP_PCT="92",
        QUOTA_TOLERANCE_START_PP="13",
        QUOTA_TOLERANCE_END_PP="2",
        QUOTA_GATED_LANES="",
    )
    payload = await mapped(_observation(
        codex=[_window(300, 98.0, window_id="primary", label="5h", progress=0.3)],
    ))

    assert payload["rule"] == {
        "hard_stop_pct": gate.HARD_STOP_PCT,
        "tolerance_start_pp": gate.TOLERANCE_START_PP,
        "tolerance_end_pp": gate.TOLERANCE_END_PP,
        "curve_exponent": gate.CURVE_EXPONENT,
        "curved_lanes": sorted(gate.CURVED_LANES),
    }
    codex = _pool(payload, "codex")
    assert all(not lane["gated"] for lane in codex["lanes"] if lane["lane"] in ("sol", "luna"))


@pytest.mark.asyncio
async def test_bucket_trace_points_use_usage_snapshot_history(mapped):
    db.init_db()
    codex_progress = 0.46
    spark_progress = 0.37
    claude_progress = 0.17
    codex_reset = NOW + 300 * 60 * (1.0 - codex_progress)
    spark_reset = NOW + 300 * 60 * (1.0 - spark_progress)
    claude_reset = NOW + 10080 * 60 * (1.0 - claude_progress)

    with db._conn() as conn:
        for idx, point in enumerate((21.0, 23.0, 25.0)):
            conn.execute(
                """INSERT INTO usage_snapshots
                   (ts, five_hour_pct, seven_day_pct, five_hour_resets_at,
                    seven_day_resets_at, total_cost_usd, active_agents, provider_usage)
                   VALUES (?, 0, 0, '', '', 0, 0, ?)""",
                (
                    _iso(NOW - (idx + 1) * 2000),
                    json.dumps(
                        _providers_snapshot(
                            codex_reset=codex_reset,
                            spark_reset=spark_reset,
                            claude_reset=claude_reset,
                            codex_util=point,
                            spark_util=point + 0.5,
                            claude_util=point + 1.0,
                        ),
                        ensure_ascii=False,
                    ),
                ),
            )

    payload = await mapped(_observation(
        codex=[_window(300, 30.0, window_id="primary", label="5h", progress=codex_progress)],
        codex_spark=[_window(300, 19.0, window_id="primary", label="5h", progress=spark_progress)],
        anthropic=[_window(10080, 5.0, window_id="seven_day", label="7d", progress=claude_progress)],
    ))

    codex = _pool(payload, "codex")
    spark = _pool(payload, "codex_spark")
    claude = _pool(payload, "anthropic")

    assert "trace" in codex and isinstance(codex["trace"], dict)
    assert list(codex["trace"].keys()) == ["points"]
    assert len(codex["trace"]["points"]) == 3
    assert len(spark["trace"]["points"]) == 3
    assert len(claude["trace"]["points"]) == 3
    assert all(
        0.0 <= point["progress"] <= 1.0
        for point in codex["trace"]["points"]
    )
    assert codex["trace"]["points"][0]["utilization"] != codex["trace"]["points"][-1]["utilization"]


@pytest.mark.asyncio
async def test_trace_filters_rows_from_iso_and_numeric_timestamps(mapped):
    db.init_db()
    progress = 0.5
    codex_reset = NOW + 300 * 60 * (1.0 - progress)

    with db._conn() as conn:
        # Один row в ISO, второй row в UNIX-времени: оба в окне текущего 5h-времени.
        conn.execute(
            """INSERT INTO usage_snapshots
               (ts, five_hour_pct, seven_day_pct, five_hour_resets_at,
                seven_day_resets_at, total_cost_usd, active_agents, provider_usage)
               VALUES (?, 0, 0, '', '', 0, 0, ?)""",
            (
                _iso(NOW - 1000),
                json.dumps(
                    _providers_snapshot(
                        codex_reset=codex_reset,
                        spark_reset=codex_reset,
                        claude_reset=NOW + 10080 * 60,
                        codex_util=21.0,
                        spark_util=10.0,
                        claude_util=2.0,
                    ),
                    ensure_ascii=False,
                ),
            ),
        )
        conn.execute(
            """INSERT INTO usage_snapshots
               (ts, five_hour_pct, seven_day_pct, five_hour_resets_at,
                seven_day_resets_at, total_cost_usd, active_agents, provider_usage)
               VALUES (?, 0, 0, '', '', 0, 0, ?)""",
            (
                float(NOW - 800),
                json.dumps(
                    _providers_snapshot(
                        codex_reset=codex_reset,
                        spark_reset=codex_reset,
                        claude_reset=NOW + 10080 * 60,
                        codex_util=22.0,
                        spark_util=10.0,
                        claude_util=2.0,
                    ),
                    ensure_ascii=False,
                ),
            ),
        )
        # Старые/будущие snapshot'ы не должны попадать в trace.
        conn.execute(
            """INSERT INTO usage_snapshots
               (ts, five_hour_pct, seven_day_pct, five_hour_resets_at,
                seven_day_resets_at, total_cost_usd, active_agents, provider_usage)
               VALUES (?, 0, 0, '', '', 0, 0, ?)""",
            (
                _iso(NOW - 36000),
                json.dumps(
                    _providers_snapshot(
                        codex_reset=codex_reset,
                        spark_reset=codex_reset,
                        claude_reset=NOW + 10080 * 60,
                        codex_util=23.0,
                        spark_util=10.0,
                        claude_util=2.0,
                    ),
                    ensure_ascii=False,
                ),
            ),
        )
        conn.execute(
            """INSERT INTO usage_snapshots
               (ts, five_hour_pct, seven_day_pct, five_hour_resets_at,
                seven_day_resets_at, total_cost_usd, active_agents, provider_usage)
               VALUES (?, 0, 0, '', '', 0, 0, ?)""",
            (
                float(NOW + 50),
                json.dumps(
                    _providers_snapshot(
                        codex_reset=codex_reset,
                        spark_reset=codex_reset,
                        claude_reset=NOW + 10080 * 60,
                        codex_util=99.0,
                        spark_util=10.0,
                        claude_util=2.0,
                    ),
                    ensure_ascii=False,
                ),
            ),
        )

    payload = await mapped(_observation(
        codex=[_window(300, 21.0, window_id="primary", label="5h", progress=progress)],
    ))

    codex = _pool(payload, "codex")
    assert codex["data_available"] is True
    assert len(codex["trace"]["points"]) == 2
    assert codex["trace"]["points"][0]["utilization"] == 21.0
    assert codex["trace"]["points"][1]["utilization"] == 22.0


@pytest.mark.asyncio
async def test_trace_is_downsampled(mapped):
    db.init_db()
    progress = 0.5
    reset = NOW + 300 * 60 * (1.0 - progress)

    with db._conn() as conn:
        for idx in range(520):
            conn.execute(
                """INSERT INTO usage_snapshots
                   (ts, five_hour_pct, seven_day_pct, five_hour_resets_at,
                    seven_day_resets_at, total_cost_usd, active_agents, provider_usage)
                   VALUES (?, 0, 0, '', '', 0, 0, ?)""",
                (
                    _iso(NOW - idx * 10),
                    json.dumps(
                        {
                            "codex": {
                                "label": "Codex",
                                "windows": [
                                    {
                                        "id": "primary",
                                        "label": "5h",
                                        "window_minutes": 300,
                                        "utilization": 10.0 + idx / 20,
                                        "resets_at": _iso(reset),
                                    }
                                ],
                            },
                        },
                        ensure_ascii=False,
                    ),
                ),
            )

    payload = await mapped(_observation(
        codex=[_window(300, 5.0, window_id="primary", label="5h", progress=progress)],
    ))

    points = _pool(payload, "codex")["trace"]["points"]
    assert 1 <= len(points) <= 200


@pytest.mark.asyncio
async def test_release_fields_arrive_for_each_gating_status(mapped):
    progress = 0.5
    resets_at = _iso(NOW + 300 * 60 * (1.0 - progress))

    payload_open = await mapped(_observation(
        codex=[_window(300, 55.5, window_id="primary", label="5h", progress=progress)],
    ))
    lane_open = _lane(_pool(payload_open, "codex"), "sol")
    assert lane_open["release_status"] == "open"
    assert lane_open["release_in_seconds"] is None

    # 60% при кривой полосе уже ОТКРЫТО (порог Sol в середине окна 81.3%), поэтому
    # прежнее число перестало проверять статус `opens_in` вовсе. 90% лежит между
    # порогом середины окна и жёстким стопом — то есть проверяет именно его.
    payload_opens_in = await mapped(_observation(
        codex=[_window(300, 90.0, window_id="primary", label="5h", progress=progress)],
    ))
    lane_opens_in = _lane(_pool(payload_opens_in, "codex"), "sol")
    expected_status, expected_seconds = _expected_release_status(90.0, progress, resets_at)
    assert expected_status == "opens_in", "фикстура обязана проверять именно статус opens_in"
    assert lane_opens_in["release_status"] == expected_status
    assert lane_opens_in["release_in_seconds"] == pytest.approx(expected_seconds)

    payload_at_reset = await mapped(_observation(
        codex=[_window(300, 99.0, window_id="primary", label="5h", progress=progress)],
    ))
    lane_at_reset = _lane(_pool(payload_at_reset, "codex"), "sol")
    expected_status, expected_seconds = _expected_release_status(99.0, progress, resets_at)
    assert lane_at_reset["release_status"] == expected_status
    assert lane_at_reset["release_in_seconds"] == pytest.approx(expected_seconds)


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
