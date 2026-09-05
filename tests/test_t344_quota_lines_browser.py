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
                 "curved_lanes": list(CURVED_LANES)},
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


def _render(browser: Browser, payload, as_json: bool = False) -> "tuple":
    """Открыть страницу, подменить api() и отрисовать панель РАСКРЫТОЙ."""
    errors: list = []
    page = browser.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.route("http://harness.local/**", lambda route: route.fulfill(
        status=200, content_type="text/html", body="<body><div id='usage-bar'></div></body>"))
    page.goto("http://harness.local/")
    page.add_style_tag(path=str(STYLE_CSS))
    for vendor in VENDOR_JS:
        page.add_script_tag(path=str(vendor))
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


def test_unified_panel_has_four_points_without_console_errors(browser):
    page, errors = _render(browser, _payload())
    assert page.locator("#quota-lines").count() == 1
    assert page.locator("[data-ql-chart='all']").count() == 1
    assert page.locator(".ql-chart").count() == 1
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
    verdict = page.locator("[data-ql-panel='all'] [data-ql-verdict]").inner_text()
    assert "работают" in verdict
    assert "стоят" not in verdict
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
    verdict = page.locator("[data-ql-panel='all'] [data-ql-verdict]").inner_text()
    assert "Sol" in verdict and "стоят" in verdict
    luna = page.locator("[data-ql-panel='all'] [data-ql-lane='luna']").inner_text()
    spark = page.locator("[data-ql-panel='all'] [data-ql-lane='spark']").inner_text()
    assert _badge_is_blocked(page, "sol")
    assert not _badge_is_blocked(page, "luna") and "работает" in luna and "без диагонали" in luna
    assert not _badge_is_blocked(page, "spark") and "работает" in spark and "без диагонали" in spark
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
    orch = page.locator("[data-ql-panel='all'] [data-ql-lane='orchestrator']").inner_text()
    assert "всегда работает" in orch
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
    chart = page.locator("[data-ql-chart='all']").text_content()
    assert "диагональ не применяется" in chart
    # У Sol порог печатается — иначе проверка была бы вакуумной.
    assert "порог" in chart
    spark_detail = page.locator("[data-ql-detail='spark']").text_content()
    assert "порог" not in spark_detail
    sol_detail = page.locator("[data-ql-detail='sol']").text_content()
    assert "порог" in sol_detail
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
    verdict = page.locator("[data-ql-panel='all'] [data-ql-verdict]").inner_text()
    assert "нет данных" in verdict
    assert "работают" not in verdict
    assert page.locator("[data-ql-point='sol']").count() == 0
    page.close()


def test_unknown_reset_time_drops_the_diagonal_and_keeps_hard_stop(browser):
    """`progress=null` при известном utilization: диагонали нет, 99% остаются."""
    page, _ = _render(browser, _payload(codex_progress=None, codex_util=40.0))
    assert page.locator("[data-ql-flat='codex']").count() == 1
    assert page.locator("[data-ql-point='sol']").count() == 0
    # SVG-узел не HTMLElement — inner_text() на нём падает, нужен text_content().
    chart = page.locator("[data-ql-chart='all']").text_content()
    assert "срок сброса неизвестен" in chart
    page.close()


def test_old_payload_without_rule_block_says_no_data(browser):
    """Реальное состояние до мержа #343: роут `/api/usage/quota-map` уже есть,
    а блока `rule` в нём ещё нет. Панель обязана честно сказать «нет данных»,
    а не нарисовать линию по выдуманным константам."""
    payload = _payload()
    del payload["rule"]
    page, _ = _render(browser, payload)
    text = page.locator("#quota-lines").inner_text()
    assert "нет данных" in text
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
    summary = page.locator("#quota-lines .ql-sum").inner_text()
    assert "нет данных" in summary, summary
    assert "работают" not in summary, summary
    assert "стоят" not in summary, summary
    page.close()


def test_summary_repeats_the_body_verdict_when_the_rule_arrives(browser):
    """Обратная сторона того же: `rule` пришёл (состояние после мержа #343) —
    сводка обязана печатать ДОСЛОВНО вердикт тела, а не свой пересчёт."""
    # 90%, а не 80%: после #b757e834 порог Sol в середине окна 81.3%, и на 80%
    # вердикт «стоят» не появился бы вовсе — сводке было бы нечего повторять.
    page, _ = _render(browser, _payload(codex_util=90.0, codex_progress=0.5, claude_util=20.0))
    summary = page.locator("#quota-lines .ql-sum").inner_text()
    body = page.locator("[data-ql-panel='all'] [data-ql-verdict]").inner_text()
    assert body and body in summary, (body, summary)
    assert "Sol" in summary and "стоят" in summary, summary
    page.close()


def test_unified_panel_renders_trace_and_history_empty_notice(browser):
    payload = _payload(codex_progress=0.46, spark_progress=0.37, claude_progress=0.17)
    page, _ = _render(browser, payload)
    body_text = page.locator("[data-ql-panel='all']").inner_text()
    assert isinstance(body_text, str) and "истории за это окно нет" in body_text
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
    assert "истории за это окно нет" not in panel.inner_text()
    page.close()


def test_failed_request_says_no_data_and_does_not_pretend_to_work(browser):
    page, _ = _render(browser, None)
    text = page.locator("#quota-lines").inner_text()
    assert "нет данных" in text
    assert page.locator(".ql-chart").count() == 0
    page.close()
