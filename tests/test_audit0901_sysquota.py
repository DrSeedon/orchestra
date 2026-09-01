"""Аудит 01.09: рестарт-preflight и порог, который печатает панель.

Два независимых дефекта, два разных шва:

* кнопка рестарта отменялась любой живой мутацией при нулевом бюджете дренажа;
* подпись у точки Sol печатала ПРЯМОЙ порог бакета, хотя блокируют по кривой.

Числа в ожиданиях — литералы, посчитанные по спеке руками: тест обязан покраснеть,
когда правило поменяют, а не подстроиться под него.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from playwright.sync_api import sync_playwright

import app.quota_gate as quota_gate
import app.routes.system as system

ROOT = Path(__file__).parent.parent
VENDOR_JS = [
    ROOT / "app/static/css/vendor/marked.min.js",
    ROOT / "app/static/css/vendor/purify.min.js",
    ROOT / "app/static/css/vendor/diff_match_patch.js",
    ROOT / "app/static/css/vendor/highlight.min.js",
]
UTILS_JS = ROOT / "app/static/js/utils.js"
CONNECTION_JS = ROOT / "app/static/js/connection.js"
QUOTA_JS = ROOT / "app/static/js/quota-lines.js"



# ── дефект: рестарт отменяется живой мутацией ────────────────────────────────


@pytest.mark.asyncio
async def test_inflight_mutating_call_cannot_cancel_the_restart(monkeypatch):
    """Кнопка рестарта — абсолютная команда (решение юзера 28.08.2026).

    `_do_restart_service` мутаций уже не боится, а `restart_preflight` остался на старом
    гейте: при бюджете 0 с дренаж возвращает False мгновенно, и `restart_server` отвечает
    409 «still in flight after 0s» — то самое «нажатие не делало ничего».
    """
    from app import main as app_main

    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 1, raising=False)
    # Ни один настоящий сигнал рестарта из теста уйти не может.
    monkeypatch.setattr(
        system, "_restart_service_after_response",
        AsyncMock(return_value={
            "ok": True, "prepared": True, "cut_turns": 0, "cut_names": [], "cut_ids": [],
        }),
    )
    monkeypatch.setattr(system, "_signal_restart_and_disarm_on_failure", AsyncMock())
    monkeypatch.setattr(system, "_signal_restart_after_response", AsyncMock())

    try:
        response = await system.restart_server()
    finally:
        pending = list(system._restart_tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        app_main.open_mutating_admission()
        system.manager.end_drain()

    assert response["scheduled"] is True
    assert response["ok"] is True


@pytest.mark.asyncio
async def test_preflight_drain_waits_for_nothing_at_the_current_budget(monkeypatch):
    """Оставленный дренаж — барьер на будущее, а не ожидание: сегодня он не ждёт вовсе.

    Мерим не секунды (wall-clock врёт под нагрузкой), а число опросов счётчика: при
    `MUTATING_DRAIN_BUDGET_S = 0.0` цикл не выполняется ни разу и счётчик спрашивают
    ровно один раз. Вернут ненулевой бюджет — опросов станет много, и восстановленное
    ожидание, которого никто не заказывал, назовёт этот тест, а не следующий рестарт.
    """
    from app import main as app_main

    polls = []

    def counted() -> int:
        polls.append(1)
        return 1  # мутация висит и не кончится сама

    monkeypatch.setattr(app_main, "inflight_mutating_count", counted, raising=False)
    try:
        verdict = await system.restart_preflight()
    finally:
        app_main.open_mutating_admission()
        system.manager.end_drain()

    assert verdict == {"ok": True}
    assert len(polls) == 1, (
        f"дренаж опросил счётчик {len(polls)} раз(а): бюджет снова не нулевой, "
        "и preflight опять ждёт живую мутацию"
    )


# ── дефект: подпись печатает прямой порог у кривой полосы ────────────────────
# Браузерный тест держится ПОСЛЕДНИМ в файле: sync-Playwright удерживает запущенный
# event loop, и asyncio-тесты после него падают (см. tests/conftest.py).


HARD = 99.0
TOL_START = 10.0
TOL_END = 1.0
CURVE_EXPONENT = 2.5
# progress=0.5, utilization=70: допуск 5.5 п.п.
# прямая (бакет)  = 0.5*100 + 5.5           = 55.5%
# кривая (Sol)    = 0.5**(1/2.5)*100 + 5.5  = 81.3% — по ней Sol и блокируют
BUCKET_STRAIGHT_LIMIT = 55.5
SOL_CURVED_LIMIT = 81.29


def _quota_map_payload() -> dict:
    return {
        "generated_at": "2026-09-01T12:00:00+00:00",
        "observation_max_age_seconds": 300.0,
        "rule": {
            "hard_stop_pct": HARD,
            "tolerance_start_pp": TOL_START,
            "tolerance_end_pp": TOL_END,
            "curve_exponent": CURVE_EXPONENT,
            "curved_lanes": ["sol"],
        },
        "buckets": [{
            "bucket": "codex", "label": "Codex", "observed_at": 1756728000.0,
            "fresh": True, "data_available": True,
            "window": {
                "id": "primary", "label": "5h", "window_minutes": 300,
                "utilization": 70.0, "resets_at": "2026-09-01T15:00:00+00:00",
                "reset_in_seconds": 9000.0, "starts_at": "2026-09-01T10:00:00+00:00",
                "progress": 0.5,
            },
            "reference_windows": [],
            "tolerance_pp": 5.5,
            "limit_pct": BUCKET_STRAIGHT_LIMIT,
            "trace": {"points": []},
            "lanes": [
                {"lane": "luna", "label": "Luna", "gated": False, "curved": False,
                 "limit_pct": None, "blocked": False, "release_status": "open",
                 "release_in_seconds": None, "reason": "", "models": []},
                {"lane": "sol", "label": "Sol", "gated": True, "curved": True,
                 "limit_pct": SOL_CURVED_LIMIT, "blocked": False, "release_status": "open",
                 "release_in_seconds": None, "reason": "", "models": []},
            ],
            "models": [],
        }],
        "outside_policy": [],
    }


def test_lane_label_prints_the_threshold_that_actually_gates_it():
    """Подпись у точки обязана называть порог ПОЛОСЫ, а не прямую бакета.

    Sol идёт по параболе (81.3% при половине окна), а панель печатала бакетные 55.5% —
    то есть юзер читал бы «Sol на 14.5 п.п. выше порога» у полосы, которая работает, и
    видел бы на том же SVG розовую кривую, проходящую выше точки.
    """
    payload = _quota_map_payload()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        errors: list = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.route("http://harness.local/**", lambda route: route.fulfill(
            status=200, content_type="text/html",
            body="<body><div id='usage-bar'></div></body>"))
        page.goto("http://harness.local/")
        for vendor in VENDOR_JS:
            page.add_script_tag(path=str(vendor))
        page.add_script_tag(path=str(UTILS_JS))
        page.add_script_tag(path=str(CONNECTION_JS))
        page.add_script_tag(path=str(QUOTA_JS))
        # Символ, которого нет в пустой странице: зелень на неподгруженном коде исключена.
        assert page.evaluate("typeof QuotaPanel?.init") == "function"
        page.evaluate(
            """async raw => {
                const data = JSON.parse(raw);
                window._fetchQuotaMapShared = async () => data;
                QuotaPanel.init();
                await QuotaPanel.fetch();
            }""",
            json.dumps(payload),
        )
        page.click("#quota-lines-toggle")

        sol_detail = page.locator("[data-ql-detail='sol']").text_content()
        luna_detail = page.locator("[data-ql-detail='luna']").text_content()
        panel_text = page.locator("#quota-lines").text_content()
        browser_errors = list(errors)
        browser.close()

    assert browser_errors == [], browser_errors
    assert "порог 81.3%" in sol_detail, sol_detail
    assert "55.5" not in sol_detail, sol_detail
    # Luna не гейтится вовсе — печатать ей чужой порог значит выдумать ограничение.
    assert "диагональ не применяется" in luna_detail, luna_detail
    assert "порог" not in luna_detail, luna_detail
    # `buckets[].limit_pct` остаётся в ответе как справочная прямая пула, и в панели ему
    # места нет НИГДЕ: всплывёт снова — вернулось расхождение «показываем не тот порог».
    assert str(BUCKET_STRAIGHT_LIMIT) not in panel_text, panel_text
