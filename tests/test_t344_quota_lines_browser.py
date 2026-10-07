"""Правило допуска по квоте на дашборде (#344).

Панель обязана рисовать ТО ЖЕ правило, что исполняет гейт, и не выдумывать
«работает» там, где сервер сказал `data_available=false`. Проверяется браузером,
а не чтением исходника: рассуждение о вёрстке ничего не доказывает.

Первым делом тесты ждут символ, которого в main НЕТ (`QuotaPanel`,
`#quota-lines`, `.ql-chart`), — иначе прогон зеленел бы на старом коде.
"""
import json
from pathlib import Path

import pytest
from playwright.sync_api import Browser, sync_playwright

ROOT = Path(__file__).parent.parent
I18N_JS = ROOT / "app/static/js/i18n.js"
UTILS_JS = ROOT / "app/static/js/utils.js"
QUOTA_JS = ROOT / "app/static/js/quota-lines.js"
CONNECTION_JS = ROOT / "app/static/js/connection.js"
APP_JS = ROOT / "app/static/js/app.js"
STYLE_CSS = ROOT / "app/static/css/style.css"
# Те же вендорные файлы, что грузит dashboard.html (строки 8-11). Без них app.js
# падает на `marked is not defined` / `DOMPurify is not defined`, и стенд приписал
# бы чужую ошибку панели квот — то есть соврал бы в сторону «панель сломана».
VENDOR_JS = [
    ROOT / "app/static/css/vendor/marked.min.js",
    ROOT / "app/static/css/vendor/purify.min.js",
    ROOT / "app/static/css/vendor/diff_match_patch.js",
    ROOT / "app/static/css/vendor/highlight.min.js",
]

HARD = 99.0
TOL_START = 10.0
TOL_END = 1.0


# Модульная фикстура, а не сессионная: сессионный sync-Playwright держит
# запущенный event loop и роняет любой asyncio-тест после этого файла.
@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


CURVE_EXPONENT = 2.5
CURVED_LANES = ("sol",)
GATED_LANES = ("claude", "sol")
LANE_HARD_STOP = {"sol": 95.0}
RESET_IN_SECONDS = 402000.0


def _limit(progress: float, lane: str | None = None) -> float:
    """Та же формула, что у гейта (#343, парабола #b757e834) — для ФИКСТУРЫ, не прода."""
    tolerance = TOL_START + (TOL_END - TOL_START) * progress
    norm = progress
    if lane in CURVED_LANES and progress > 0.0:
        norm = progress ** (1.0 / CURVE_EXPONENT)
    return min(HARD, norm * 100 + tolerance)


def _lane(lane: str, label: str, gated: bool, blocked: bool, reason: str = "",
          release_status: str | None = None, release_in_seconds: float | None = None) -> dict:
    """Полоса в том виде, в каком её отдаёт сервер (`app/routes/system.py:1581-1611`).

    `release_status` обязателен: слово на бейдже панель берёт ИМЕННО из него
    (`_qlReleaseText`, `app/static/js/quota-lines.js:71`), а не из `blocked`. Фикстура
    без этого поля заставляла панель писать «работает» про заблокированную полосу —
    то есть проверяла собственную неполноту, а не вёрстку.
    """
    if release_status is None:
        release_status = "at_reset" if blocked else "open"
    if blocked and release_in_seconds is None:
        release_in_seconds = RESET_IN_SECONDS
    return {"lane": lane, "label": label, "gated": gated, "blocked": blocked,
            "curved": lane in CURVED_LANES, "reason": reason,
            "release_status": release_status, "release_in_seconds": release_in_seconds,
            "models": []}


def _bucket(bucket: str, label: str, utilization, progress, lanes,
            data_available: bool = True, window_minutes: int = 10080, trace: list | None = None) -> dict:
    limit = None if progress is None else round(_limit(progress), 2)
    tolerance = None if progress is None else round(TOL_START + (TOL_END - TOL_START) * progress, 2)
    window = None
    if data_available:
        window = {"id": "primary", "label": "7d", "window_minutes": window_minutes,
                  "utilization": utilization, "resets_at": "2026-08-25T07:00:00+00:00",
                  "reset_in_seconds": 402000.0, "starts_at": "2026-08-18T07:00:00+00:00",
                  "progress": progress}
    return {"bucket": bucket, "label": label, "observed_at": 1755600000.0, "fresh": True,
            "data_available": data_available, "window": window, "reference_windows": [],
            "tolerance_pp": tolerance, "limit_pct": limit, "lanes": lanes, "models": [],
            "trace": trace}


def _trace(*points):
    return {"points": [{"ts": f"2026-08-19T12:3{i}:00+00:00", "progress": p[0], "utilization": p[1]} for i, p in enumerate(points)]}


def _payload(codex_util=30.0, codex_progress=0.5, spark_util=39.0, spark_progress=0.5,
             claude_util=30.0, claude_progress=0.5, **overrides) -> dict:
    """Ответ /api/usage/quota-map. Вердикты считает сервер — фикстура их и задаёт."""
    codex_blocked = codex_util > _limit(codex_progress, "sol") if codex_progress is not None else codex_util >= HARD
    codex_hard = codex_util >= HARD
    spark_hard = spark_util >= HARD
    claude_blocked = claude_util > _limit(claude_progress, "claude") if claude_progress is not None else claude_util >= HARD
    hard_reason = f"utilization is at or above the hard stop {HARD}%"
    data = {
        "generated_at": "2026-08-19T12:00:00+00:00",
        "observation_max_age_seconds": 300.0,
        "rule": {"hard_stop_pct": HARD, "tolerance_start_pp": TOL_START,
                 "tolerance_end_pp": TOL_END, "curve_exponent": CURVE_EXPONENT,
                 "curved_lanes": list(CURVED_LANES),
                 "lane_hard_stop_pct": dict(LANE_HARD_STOP),
                 "gated_lanes": list(GATED_LANES)},
        "buckets": [
            _bucket("codex", "Codex", codex_util, codex_progress, [
                _lane("sol", "Sol", True, codex_blocked or codex_hard,
                      hard_reason if codex_hard
                      else f"utilization {codex_util}% is above the line limit"),
                _lane("luna", "Luna", False, codex_hard, hard_reason if codex_hard else ""),
            ]),
            _bucket("codex_spark", "Codex Spark", spark_util, spark_progress, [
                _lane("spark", "Spark", False, spark_hard, hard_reason if spark_hard else ""),
            ]),
            _bucket("anthropic", "Claude", claude_util, claude_progress, [
                _lane("claude", "Claude-воркеры", True, claude_blocked or claude_util >= HARD,
                      hard_reason if claude_util >= HARD else ""),
            ]),
        ],
        "outside_policy": [],
    }
    data.update(overrides)
    return data


def _render(browser: Browser, payload, as_json: bool = False, language: str = "en") -> "tuple":
    """Открыть страницу, подменить api() и отрисовать панель РАСКРЫТОЙ."""
    errors: list = []
    page = browser.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.route("http://harness.local/**", lambda route: route.fulfill(
        status=200, content_type="text/html", body="<body><div id='usage-bar'></div></body>"))
    # Набор писался под английские подписи; с V-584 локаль по умолчанию русская,
    # а английская локаль — это те же исходные строки в коде.
    page.add_init_script(f"window.__ORCH_LANG__ = {json.dumps(language)};")
    page.goto("http://harness.local/")
    page.add_style_tag(path=str(STYLE_CSS))
    for vendor in VENDOR_JS:
        page.add_script_tag(path=str(vendor))
    page.add_script_tag(path=str(I18N_JS))
    page.add_script_tag(path=str(UTILS_JS))
    page.add_script_tag(path=str(QUOTA_JS))
    page.add_script_tag(path=str(CONNECTION_JS))
    page.add_script_tag(path=str(APP_JS))
    # Символа нет в main: зелень на старом коде исключена.
    assert page.evaluate("typeof QuotaPanel?.init") == "function"
    if payload is None:
        page_payload = None
    elif as_json:
        page_payload = json.dumps(payload)
    else:
        page_payload = payload
    page.evaluate(
        """async raw => {
            api = async () => (raw === null ? Promise.reject(new Error('boom')) : raw);
            QuotaPanel.init();
            await QuotaPanel.fetch();
        }""",
        page_payload,
    )
    page.click("#quota-lines-toggle")
    return page, errors


def test_claude_lane_label_follows_dashboard_language(browser):
    payload = _payload()
    claude = next(lane for lane in payload["buckets"][2]["lanes"] if lane["lane"] == "claude")
    claude["label"] = "Claude workers"
    page, errors = _render(browser, payload, language="ru")

    assert "гейт ВКЛЮЧЁН: Claude-воркеры" in page.locator("[data-ql-gate='on']").inner_text()
    assert page.locator("[data-ql-lane='claude']").inner_text().startswith("Claude-воркеры")
    assert errors == [], errors
    page.close()


def test_unified_panel_has_four_points_without_console_errors(browser):
    page, errors = _render(browser, _payload())
    assert page.locator("#quota-lines").count() == 1
    assert page.locator("[data-ql-chart='all']").count() == 1
    assert page.locator(".ql-chart").count() == 2
    assert page.locator("[data-ql-timeline='all'] + [data-ql-chart='all']").count() == 1
    for lane in ("sol", "luna", "spark", "claude"):
        assert page.locator(f"[data-ql-point='{lane}']").count() == 1
    assert errors == [], errors
    page.close()


def test_panel_renders_when_api_returns_object_payload(browser):
    """Баг-орда #353: `/api/usage/quota-map` уже отдаёт объект, повторный JSON.parse ломал всё."""
    payload = _payload()
    page, errors = _render(browser, payload, as_json=False)
    assert page.locator("[data-ql-chart='all']").count() == 1
    assert "not valid JSON" not in page.locator("#quota-lines").inner_text()
    assert errors == [], errors
    page.close()


def test_timeline_centers_now_repeats_thresholds_and_shades_nights(browser):
    payload = _payload()
    payload["generated_at"] = "2026-08-19T12:00:00+00:00"
    bucket = payload["buckets"][0]
    bucket["timeline"] = {"points": [
        {"ts": 1787130000, "utilization": 25.0, "resets_at": 1787745600, "window_minutes": 10080},
        {"ts": 1787133600, "utilization": 26.0, "resets_at": 1787745600, "window_minutes": 10080},
    ]}
    page, errors = _render(browser, payload)
    timeline = page.locator("[data-ql-timeline='all']")
    now_x = timeline.locator(".ql-now").get_attribute("x1")
    assert float(now_x) == pytest.approx(497.0)
    current_points = timeline.locator("[data-ql-timeline-point]")
    assert current_points.count() == 4
    assert all(float(current_points.nth(i).get_attribute("cx")) == pytest.approx(float(now_x)) for i in range(4))
    nights = timeline.locator(".ql-night")
    assert nights.count() >= 7
    day_ms, offset_ms = 86400000, 7 * 3600000
    from_ms = 1787140800000 - 84 * 3600000
    first_midnight = (int((from_ms + offset_ms) // day_ms) + 1) * day_ms - offset_ms
    expected_night_x = 54 + (first_midnight - from_ms) / (168 * 3600000) * 886
    expected_full_width = 8 * 3600000 / (168 * 3600000) * 886
    assert float(nights.first.get_attribute("x")) == pytest.approx(54.0)
    assert float(nights.first.get_attribute("width")) == pytest.approx(3600000 / (168 * 3600000) * 886)
    assert float(nights.nth(1).get_attribute("x")) == pytest.approx(expected_night_x)
    assert float(nights.nth(1).get_attribute("width")) == pytest.approx(expected_full_width)
    assert timeline.locator("[data-ql-timeline-threshold='sol']").count() >= 2
    assert timeline.locator("[data-ql-timeline-history='codex']").count() == 1
    assert errors == [], errors
    page.evaluate("""() => {
        const body = document.querySelector('.ql-body');
        body.style.maxHeight = 'none';
        body.style.height = 'auto';
        body.style.overflow = 'visible';
    }""")
    page.add_style_tag(content=".ql-body { max-height: none !important; overflow: visible !important; }")
    screenshot = ROOT / ".orchestra/tasks/V-652/quota-timeline.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({"width": 1280, "height": 1600})
    page.screenshot(path=str(screenshot), full_page=True)
    page.close()


def test_timeline_keeps_old_claude_rule_until_v732_effective_time(browser):
    payload = _payload(claude_progress=0.5, claude_util=50.0)
    old_start = 1790665200.0  # 2026-09-29 07:00 UTC
    reset = 1791874800.0  # 2026-10-13 07:00 UTC
    old_reset = reset - 604800.0
    effective = 1791261780.0  # 2026-10-06 04:43 UTC
    payload["generated_at"] = "2026-10-07T05:00:00+00:00"
    payload["rule"]["claude_weekly_shift_hours"] = 8.0
    payload["rule_history"] = [
        {"effective_from": 1790640000.0, "policy": {
            **payload["rule"], "claude_weekly_shift_hours": 0.0,
        }},
        {"effective_from": effective, "policy": payload["rule"]},
    ]
    bucket = next(item for item in payload["buckets"] if item["bucket"] == "anthropic")
    bucket["window"] = {
        "id": "seven_day", "window_minutes": 10080, "utilization": 50.0,
        "resets_at": "2026-10-13T07:00:00+00:00", "progress": 8 / 168,
    }
    page, errors = _render(browser, payload)
    old_line = page.locator(
        f"[data-ql-timeline='all'] [data-ql-timeline-threshold='claude'][data-ql-policy-from='1790640000'][data-ql-window-end='{int(old_reset)}']"
    )
    v732_tail = page.locator(
        f"[data-ql-timeline='all'] [data-ql-timeline-threshold='claude'][data-ql-policy-from='{int(effective)}'][data-ql-window-end='{int(old_reset)}']"
    )
    current_line = page.locator(
        f"[data-ql-timeline='all'] [data-ql-timeline-threshold='claude'][data-ql-policy-from='current'][data-ql-window-end='{int(reset)}']"
    )
    assert old_line.count() >= 1
    assert v732_tail.count() >= 1
    assert current_line.count() >= 1

    chart_from = 1791349200.0 - 84 * 3600.0
    def chart_point_near(line, ts):
        target_x = 54.0 + (ts - chart_from) / (168 * 3600.0) * 886.0
        points = [tuple(map(float, point.split(",")))
                  for point in line.get_attribute("points").split()]
        return min(points, key=lambda point: abs(point[0] - target_x))[1]

    old_sample = 1791201600.0  # 2026-10-05 12:00 UTC, before V-732 restart
    old_progress = (old_sample - old_start) / 604800.0
    old_expected = 10.0 + 91.0 * old_progress
    old_y = chart_point_near(old_line.first, old_sample)
    expected_old_y = 18.0 + (1.0 - old_expected / 100.0) * 408.0

    current_sample = 1791349200.0  # 2026-10-07 05:00 UTC
    current_progress = (current_sample - old_reset) / 604800.0
    shifted_expected = 10.0 + 91.0 * (current_progress + 8.0 / 168.0)
    shifted_y = chart_point_near(current_line.first, current_sample)
    expected_shifted_y = 18.0 + (1.0 - shifted_expected / 100.0) * 408.0
    assert old_y == pytest.approx(expected_old_y, abs=2.0)
    assert shifted_y == pytest.approx(expected_shifted_y, abs=2.0)
    assert errors == []
    page.close()


def test_current_claude_chart_uses_day_night_profile_and_headroom(browser):
    payload = _payload(claude_progress=0.06, claude_util=20.0)
    now = 1791349200.0  # 2026-10-07 05:00 UTC
    start = 1791270000.0  # 2026-10-06 07:00 UTC, Tuesday 14:00 Krasnoyarsk
    reset = start + 604800.0
    payload["generated_at"] = "2026-10-07T05:00:00+00:00"
    payload["rule"].update({
        "claude_weekly_shift_hours": 8.0,
        "claude_day_start_hour": 8.0,
        "claude_night_quota_share": 0.057,
    })
    payload["rule_history"] = [
        {"effective_from": 1790640000.0, "policy": {
            **payload["rule"], "claude_weekly_shift_hours": 0.0,
            "claude_night_quota_share": None,
        }},
        {"effective_from": 1791261780.0, "policy": {
            **payload["rule"], "claude_night_quota_share": None,
        }},
        {"effective_from": now - 3600.0, "policy": payload["rule"]},
    ]
    bucket = next(item for item in payload["buckets"] if item["bucket"] == "anthropic")
    bucket["window"] = {
        "id": "seven_day", "window_minutes": 10080, "utilization": 20.0,
        "resets_at": "2026-10-13T07:00:00+00:00", "progress": 0.06,
    }
    page, errors = _render(browser, payload)
    points = page.locator("[data-ql-chart='all'] [data-ql-threshold='claude']")
    assert points.count() == 1
    sample = tuple(map(float, points.first.get_attribute("points").split()[6].split(",")))
    drawn_limit = (1.0 - (sample[1] - 18.0) / 408.0) * 100.0
    day_rate = 89.0 * 0.943 / 112.0
    night_rate = 89.0 * 0.057 / 56.0
    expected = 10.0 + day_rate * 10.0 + night_rate * 0.08 + 91.0 * 8.0 / 168.0

    assert drawn_limit == pytest.approx(expected, abs=0.01)
    assert errors == []
    page.close()


def test_live_quota_map_history_and_two_hour_labels(browser):
    payload = json.loads((ROOT / "tests/fixtures/v654_quota_map_live_shape.json").read_text())
    page, errors = _render(browser, payload)
    timeline = page.locator("[data-ql-timeline='all']")
    histories = {el.get_attribute("data-ql-timeline-history"): el for el in timeline.locator("[data-ql-timeline-history]").all()}
    assert set(histories) == {"codex", "anthropic"}
    for bucket, expected_points in (("codex", 171), ("anthropic", 169)):
        coords = histories[bucket].get_attribute("points").split()
        assert len(coords) == expected_points + 1  # historical samples plus the current sample at now
        assert len(set(coords)) > expected_points // 2
    assert timeline.locator(".ql-timeline-burn").count() <= 6
    now_x = float(timeline.locator(".ql-now").get_attribute("x1"))
    assert now_x == pytest.approx(497.0)
    current = timeline.locator("[data-ql-timeline-point]")
    assert {current.nth(i).get_attribute("data-ql-timeline-point") for i in range(current.count())} == {"sol", "luna", "claude"}
    codex_radii = [float(current.nth(i).get_attribute("r")) for i in range(2)]
    assert len(set(codex_radii)) == 2
    ticks = timeline.locator("[data-ql-time-tick]")
    assert ticks.count() == 84
    tick_x = [float(ticks.nth(i).get_attribute("x1")) for i in range(ticks.count())]
    assert all(b - a == pytest.approx(886 / 84) for a, b in zip(tick_x, tick_x[1:]))
    boundaries = timeline.locator("[data-ql-time-boundary]")
    assert boundaries.count() == 14
    assert {boundaries.nth(i).get_attribute("data-ql-time-boundary") for i in range(boundaries.count())} == {"0", "8"}
    labels = timeline.locator("[data-ql-time-label]")
    assert labels.count() > 0
    label_boxes = timeline.locator("[data-ql-time-label], [data-ql-time-boundary]").evaluate_all(
        "els => els.map(el => { const b = el.getBBox(); return [b.x, b.y, b.width, b.height]; })"
    )
    for i, (x1, y1, w1, h1) in enumerate(label_boxes):
        for x2, y2, w2, h2 in label_boxes[i + 1:]:
            assert x1 + w1 <= x2 or x2 + w2 <= x1 or y1 + h1 <= y2 or y2 + h2 <= y1
    assert errors == [], errors
    page.evaluate("""() => {
        const body = document.querySelector('.ql-body');
        body.style.maxHeight = 'none';
        body.style.height = 'auto';
        body.style.overflow = 'visible';
    }""")
    page.add_style_tag(content=".ql-body { max-height: none !important; overflow: visible !important; }")
    screenshot = ROOT / ".orchestra/tasks/V-654/quota-timeline-live-fixture.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({"width": 1280, "height": 1600})
    page.screenshot(path=str(screenshot), full_page=True)
    page.close()


def test_panel_curve_matches_the_limit_the_server_computed(browser):
    """Кривая панели и порог гейта — одно число, а не две копии.

    Если фронт заведёт свою арифметику, эта проверка разойдётся первой.
    """
    payload = _payload(codex_progress=0.37, codex_util=20.0)
    page, _ = _render(browser, payload)
    server_limit = next(b for b in payload["buckets"] if b["bucket"] == "codex")["limit_pct"]
    drawn = page.evaluate(
        "p => QuotaPanel.limitAt(p, {hard_stop_pct: 99, tolerance_start_pp: 10, tolerance_end_pp: 1}, 'claude')", 0.37
    )
    assert abs(drawn - server_limit) < 0.01, (drawn, server_limit)
    page.close()


def test_claude_shift_matches_lane_limit_and_legacy_rule_falls_back(browser):
    payload = _payload(claude_progress=0.5, claude_util=30.0)
    rule = {**payload["rule"], "claude_weekly_shift_hours": 8.0}
    payload["rule"] = rule
    lane = next(bucket for bucket in payload["buckets"] if bucket["bucket"] == "anthropic")["lanes"][0]
    lane["limit_pct"] = 55.5 + 91.0 * 8.0 / 168.0
    page, errors = _render(browser, payload)
    values = page.evaluate(
        """({rule, legacy}) => [
            QuotaPanel.limitAt(0.5, rule, 'claude'),
            QuotaPanel.limitAt(0.5, legacy, 'claude'),
            QuotaPanel.limitAt(0.5, rule, 'sol'),
        ]""",
        {"rule": rule, "legacy": {k: v for k, v in rule.items() if k != "claude_weekly_shift_hours"}},
    )

    assert abs(values[0] - lane["limit_pct"]) < 0.01
    assert values[1] == pytest.approx(55.5)
    assert values[2] == pytest.approx(_limit(0.5, "sol"))
    assert errors == []
    page.close()


def test_lane_ceiling_is_drawn_and_capped_like_the_gate(browser):
    """Потолок полосы обязан доехать до картинки: Sol стоит на 95%, Luna живёт до 99%.

    Иначе панель рисует дорогой полосе чужие 99% ровно там, где гейт её уже не пускает.
    """
    payload = _payload(codex_util=96.0, codex_progress=0.9)
    page, errors = _render(browser, payload)
    drawn = page.evaluate(
        """rule => [
            QuotaPanel.limitAt(1.0, rule, 'sol'),
            QuotaPanel.limitAt(1.0, rule, 'claude'),
        ]""",
        payload["rule"],
    )
    assert drawn == [95.0, HARD]
    assert page.locator("[data-ql-hard-lane='sol']").count() == 1
    assert page.locator("[data-ql-hard-lane='luna']").count() == 0
    assert errors == [], errors
    page.close()


def _gate_node(page) -> tuple:
    node = page.locator("#quota-lines [data-ql-gate]")
    return node.get_attribute("data-ql-gate"), node.get_attribute("class")


def test_gate_state_names_the_lanes_the_diagonal_holds(browser):
    """Состав гейта виден сразу: кто под диагональю, кто вне её и на чём стоп.

    До #V-547 фронт вообще не получал `gated_lanes`, и состав правила был ему неизвестен.
    """
    page, errors = _render(browser, _payload())
    state, css = _gate_node(page)
    assert state == "on" and "ql-gate-on" in css
    for lane in ("sol", "luna", "spark", "claude", "orchestrator"):
        assert page.locator(f"[data-ql-panel='all'] [data-ql-lane='{lane}']").count() == 1
    assert page.locator("[data-ql-threshold='sol'].ql-gated-off").count() == 0
    assert page.locator("[data-ql-threshold='claude'].ql-gated-off").count() == 0
    assert errors == [], errors
    page.close()


def test_gate_lifted_from_every_lane_does_not_look_like_a_working_gate(browser):
    """Живое состояние с `QUOTA_GATED_LANES=`: диагональ снята со ВСЕХ полос.

    Именно здесь панель была неотличима от работающего правила, поэтому проверяется
    не наличие слова, а расхождение с включённым гейтом: состояние, оформление и текст.
    """
    lifted = _payload(codex_util=20.0, claude_util=20.0)
    lifted["rule"]["gated_lanes"] = []
    for bucket in lifted["buckets"]:
        for lane in bucket["lanes"]:
            lane["gated"] = False
    off_page, errors = _render(browser, lifted)
    off = _gate_node(off_page)
    # Снятая диагональ рисуется призраком: сплошная линия означала бы живой порог.
    assert off_page.locator("[data-ql-threshold='sol'].ql-gated-off").count() == 1
    assert off_page.locator("[data-ql-threshold='claude'].ql-gated-off").count() == 1
    assert errors == [], errors
    off_page.close()

    on_page, _ = _render(browser, _payload(codex_util=20.0, claude_util=20.0))
    on = _gate_node(on_page)
    on_page.close()

    assert off[0] == "off" and "ql-gate-off" in off[1]
    assert off[0] != on[0] and off[1] != on[1]


def test_point_moves_with_utilization(browser):
    """Точка «где мы сейчас» обязана ехать за фактом, а не стоять картинкой."""
    low, _ = _render(browser, _payload(codex_util=20.0))
    y_low = float(low.get_attribute("[data-ql-point='sol']", "cy"))
    low.close()
    high, _ = _render(browser, _payload(codex_util=80.0))
    y_high = float(high.get_attribute("[data-ql-point='sol']", "cy"))
    high.close()
    # Ось перевёрнута: больший процент — меньший y.
    assert y_high < y_low, (y_high, y_low)


def test_calm_window_says_everyone_works(browser):
    page, _ = _render(browser, _payload(codex_util=20.0, claude_util=20.0))
    verdict = page.locator("[data-ql-panel='all'] [data-ql-verdict]")
    assert "ql-verdict-open" in (verdict.get_attribute("class") or "")
    assert page.locator("[data-ql-panel='all'] .ql-badge-blocked").count() == 0
    page.close()


def _badge_is_blocked(page, lane: str) -> bool:
    """Состояние полосы читается по КЛАССУ бейджа, а не по слову.

    Слово панель берёт из `release_status` и пишет «откроется через …», а не «блок»
    (`app/static/js/quota-lines.js:71-88`). Ассерт на слово ломался бы от любой правки
    формулировки, притом что проверять надо ровно одно: панель не выдаёт
    заблокированную полосу за работающую.
    """
    css = page.get_attribute(f"[data-ql-panel='all'] [data-ql-lane='{lane}']", "class")
    return "ql-badge-blocked" in (css or "")


def test_above_the_curve_stops_sol_but_not_luna_and_spark(browser):
    """Порог гейтит Sol; Luna и Spark живут до жёстких 99%.

    90% в середине окна: порог Sol там 81.3% (парабола), то есть выше порога. Прежние
    80% лежали НИЖЕ кривой и после #b757e834 перестали блокировать хоть кого-нибудь —
    тест проверял бы пустоту.
    """
    payload = _payload(codex_util=90.0, codex_progress=0.5, spark_util=39.0)
    page, _ = _render(browser, payload)
    verdict = page.locator("[data-ql-panel='all'] [data-ql-verdict]")
    assert "ql-verdict-blocked" in (verdict.get_attribute("class") or "")
    assert _badge_is_blocked(page, "sol")
    assert not _badge_is_blocked(page, "luna")
    assert not _badge_is_blocked(page, "spark")
    page.close()


def test_hard_99_stops_everyone_and_orchestrator_still_works(browser):
    page, _ = _render(browser, _payload(codex_util=99.5, spark_util=99.5))
    assert _badge_is_blocked(page, "sol")
    assert _badge_is_blocked(page, "luna")
    assert _badge_is_blocked(page, "spark")
    # Причина жёсткого стопа обязана дойти до юзера: сам бейдж говорит только «когда
    # откроется», поэтому число 99 ищется в списке причин панели.
    reasons = page.locator("[data-ql-panel='all'] .ql-reasons").inner_text()
    assert "99" in reasons and "Luna" in reasons and "Spark" in reasons, reasons
    assert "ql-badge-always" in page.get_attribute(
        "[data-ql-panel='all'] [data-ql-lane='orchestrator']", "class"
    )
    page.close()


def test_spark_is_drawn_by_its_own_counter_not_together_with_sol(browser):
    """Spark считается по СВОЕМУ счётчику — своя точка, своя доля окна."""
    page, _ = _render(browser, _payload(codex_util=100.0, codex_progress=0.6,
                                        spark_util=39.0, spark_progress=0.3))
    sol_x = float(page.get_attribute("[data-ql-point='sol']", "cx"))
    spark_x = float(page.get_attribute("[data-ql-point='spark']", "cx"))
    sol_y = float(page.get_attribute("[data-ql-point='sol']", "cy"))
    spark_y = float(page.get_attribute("[data-ql-point='spark']", "cy"))
    assert sol_x != spark_x, "Spark стоит на своей доле окна, а не на доле Codex"
    assert sol_y != spark_y, "Spark считается по своему счётчику, а не по общему Codex"
    page.close()


def test_spark_point_does_not_advertise_a_threshold_that_does_not_bind_it(browser):
    """У Spark диагонали нет — печатать ей «порог N%» значит выдумать ограничение.

    Найдено на скриншоте: подпись Spark показывала «допуск 4.4 п.п. · порог 66.4%»,
    хотя единственный стоп Spark — жёсткие 99%.
    """
    page, _ = _render(browser, _payload(spark_util=39.0, spark_progress=0.62))
    assert page.locator("[data-ql-threshold='spark']").count() == 0
    assert page.locator("[data-ql-threshold='sol']").count() == 1
    page.close()


def test_missing_telemetry_says_no_data_not_works(browser):
    """`data_available=false` — это «данных нет», а не «всё хорошо».

    Гейт на неизвестной квоте пропускает (fail-open), поэтому тихое «работает»
    здесь было бы прямой ложью оператору.
    """
    payload = _payload()
    for bucket in payload["buckets"]:
        if bucket["bucket"] in ("codex", "codex_spark"):
            bucket["data_available"] = False
            bucket["window"] = None
            bucket["limit_pct"] = None
            bucket["tolerance_pp"] = None
    page, _ = _render(browser, payload)
    verdict = page.locator("[data-ql-panel='all'] [data-ql-verdict]")
    assert "ql-nodata" in (verdict.get_attribute("class") or "")
    assert page.locator("[data-ql-panel='all'] .ql-badge-nodata").count() > 0
    assert page.locator("[data-ql-point='sol']").count() == 0
    page.close()


def test_unknown_reset_time_drops_the_diagonal_and_keeps_hard_stop(browser):
    """`progress=null` при известном utilization: диагонали нет, 99% остаются."""
    page, _ = _render(browser, _payload(codex_progress=None, codex_util=40.0))
    assert page.locator("[data-ql-flat='codex']").count() == 1
    assert page.locator("[data-ql-point='sol']").count() == 0
    # SVG-узел не HTMLElement — inner_text() на нём падает, нужен text_content().
    assert page.locator("[data-ql-threshold='sol']").count() == 1
    page.close()


def test_old_payload_without_rule_block_says_no_data(browser):
    """Реальное состояние до мержа #343: роут `/api/usage/quota-map` уже есть,
    а блока `rule` в нём ещё нет. Панель обязана честно сказать «нет данных»,
    а не нарисовать линию по выдуманным константам."""
    payload = _payload()
    del payload["rule"]
    page, _ = _render(browser, payload)
    assert page.locator("#quota-lines [data-ql-gate='nodata']").count() == 1
    assert page.locator("#quota-lines .ql-sum .ql-nodata").count() == 1
    assert page.locator("#quota-lines [data-ql-verdict].ql-nodata").count() == 1
    assert page.locator(".ql-chart").count() == 0
    page.close()


def test_summary_without_rule_block_says_no_data_not_works(browser):
    """Свёрнутая сводка на живом ответе без `rule` (сейчас так отвечает прод).

    Ловится именно расхождение сводки с телом: тело говорило «нет данных», а
    сводка при Codex 100% печатала «Sol, Luna Fast, Spark — работают», потому что
    считала вердикт своей веткой. Вердикт один — источник один.
    """
    payload = _payload(codex_util=100.0, spark_util=100.0, claude_util=20.0)
    del payload["rule"]
    page, _ = _render(browser, payload)
    assert page.locator("#quota-lines .ql-sum .ql-nodata").count() == 1
    page.close()


def test_summary_repeats_the_body_verdict_when_the_rule_arrives(browser):
    """Обратная сторона того же: `rule` пришёл (состояние после мержа #343) —
    сводка обязана печатать ДОСЛОВНО вердикт тела, а не свой пересчёт."""
    # 90%, а не 80%: после #b757e834 порог Sol в середине окна 81.3%, и на 80%
    # вердикт «стоят» не появился бы вовсе — сводке было бы нечего повторять.
    page, _ = _render(browser, _payload(codex_util=90.0, codex_progress=0.5, claude_util=20.0))
    summary = page.locator("#quota-lines .ql-sum .ql-verdict-blocked")
    body = page.locator("[data-ql-panel='all'] [data-ql-verdict]")
    assert "ql-verdict-blocked" in (summary.get_attribute("class") or "")
    assert "ql-verdict-blocked" in (body.get_attribute("class") or "")
    page.close()


def test_unified_panel_renders_trace_and_history_empty_notice(browser):
    payload = _payload(codex_progress=0.46, spark_progress=0.37, claude_progress=0.17)
    page, _ = _render(browser, payload)
    assert page.locator("[data-ql-panel='all'] [data-ql-trace-msg]").count() == 3
    assert page.locator(".ql-trace-codex").count() == 0
    assert page.locator(".ql-trace-codex-spark").count() == 0
    assert page.locator(".ql-trace-anthropic").count() == 0
    page.close()


def test_unified_panel_renders_trace_when_present(browser):
    payload = _payload(codex_progress=0.46, spark_progress=0.37, claude_progress=0.17)
    payload["buckets"][0]["trace"] = _trace((0.2, 46.0), (0.3, 47.0))
    payload["buckets"][1]["trace"] = _trace((0.1, 18.0), (0.2, 24.0))
    payload["buckets"][2]["trace"] = _trace((0.05, 80.0), (0.07, 82.0))
    page, _ = _render(browser, payload)
    panel = page.locator("[data-ql-panel='all']")
    assert panel.locator(".ql-trace-codex").count() == 1
    assert panel.locator(".ql-trace-codex-spark").count() == 1
    assert panel.locator(".ql-trace-anthropic").count() == 1
    assert panel.locator("[data-ql-trace-msg]").count() == 0
    page.close()


def test_failed_request_says_no_data_and_does_not_pretend_to_work(browser):
    page, _ = _render(browser, None)
    assert page.locator("#quota-lines [data-ql-gate='nodata']").count() == 1
    assert page.locator("#quota-lines .ql-sum .ql-nodata").count() == 1
    assert page.locator("#quota-lines [data-ql-verdict].ql-nodata").count() == 1
    assert page.locator(".ql-chart").count() == 0
    page.close()


def test_panel_is_absent_outside_owner_mode(browser):
    """V-636: вне owner mode сервер квоты не отдаёт; «нет данных — owner_mode_only»
    на стенде для внешнего эксперта читалось как неисправность."""
    page = browser.new_page()
    page.route("http://harness.local/**", lambda route: route.fulfill(
        status=200, content_type="text/html", body="<body><div id='usage-bar'></div></body>"))
    page.goto("http://harness.local/")
    page.add_style_tag(path=str(STYLE_CSS))
    for script in [*VENDOR_JS, I18N_JS, UTILS_JS, QUOTA_JS, CONNECTION_JS, APP_JS]:
        page.add_script_tag(path=str(script))
    page.evaluate("""async () => {
        api = async () => ({data_available: false, error: 'owner_mode_only'});
        QuotaPanel.init();
        await QuotaPanel.fetch();
    }""")
    assert page.locator("#quota-lines").count() == 1
    assert not page.locator("#quota-lines").is_visible()
    page.close()
