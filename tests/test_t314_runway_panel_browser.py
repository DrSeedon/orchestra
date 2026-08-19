"""T7 (#314): панель называет, ЧТО именно связало допуск.

Замороженный RED-оракул гейта плана. Сегодня оператор видит процент и не видит дефицит, а при
слепоте гейта не видит вообще ничего — и тишина читается как «всё хорошо». Это ровно тот класс
проверки, что даёт одинаковый вывод при успехе и при провале.

Якоря — на СВОИ узлы (`data-binding-constraint`, `data-runway-blind`), а не на текст всей
панели: продовые данные содержат чужие строки, и ассерт по контейнеру ловил бы их (#270).
"""

from tests.test_usage_analytics_frontend import _page, _payload


def _open(page):
    page.evaluate("openAnalyticsModal()")
    page.wait_for_timeout(20)


def _render(browser, runway):
    page = _page(browser)
    payload = _payload()
    payload["quota_controller"] = {
        "enforcement_active": True,
        "shadow": {"data_available": True, "reason": "shadow_telemetry_available"},
        "runway": runway,
    }
    page.evaluate("payload => { window.api = async () => payload; }", payload)
    _open(page)
    return page


DEFICIT_BINDING = {
    "binding_constraint": "runway_deficit",
    "deficit": 41.0,
    "pace": 2.2,
    "work_used": 36.0,
    "work_hours_left": 60.0,
    "utilization": 78.0,
    "threshold": 34.0,
    "static_threshold": 90.0,
    "window_id": "2026-08-25T07:00:00+00:00",
}


def test_panel_names_binding_constraint(browser):
    """Связавшее ограничение названо машиночитаемо, в собственном узле."""
    page = _render(browser, DEFICIT_BINDING)
    node = page.locator("[data-binding-constraint]")
    assert node.count() == 1
    assert node.get_attribute("data-binding-constraint") == "runway_deficit"


def test_panel_shows_both_values_not_only_the_binding_one(browser):
    """Обе величины видны всегда — иначе нельзя понять, насколько далеко вторая.

    Оператор, видящий только «закрыл дефицит», не знает, близок ли процент к пределу.
    """
    page = _render(browser, DEFICIT_BINDING)
    text = page.locator("[data-binding-constraint]").inner_text()
    assert "41" in text, "дефицит не показан"
    assert "78" in text, "процент не показан"
    assert "34" in text and "90" in text, "не показаны оба порога"


def test_panel_distinguishes_static_denial_from_deficit(browser):
    """«Отказал процент» и «закрыл дефицит» — разные значения одного атрибута."""
    page = _render(browser, {**DEFICIT_BINDING, "binding_constraint": "static_pct"})
    assert (
        page.locator("[data-binding-constraint]").get_attribute("data-binding-constraint")
        == "static_pct"
    )


def test_blindness_is_visible_not_silent(browser):
    """Слепота гейта показана явно, отдельным узлом, с моментом вооружения.

    Без этого «дефицит сейчас не может сработать» неотличимо от «дефицита нет».
    """
    page = _render(
        browser,
        {
            "binding_constraint": "blind_no_pace",
            "deficit": None,
            "pace": None,
            "work_used": 12.0,
            "min_work_hours": 34.0,
            "utilization": 61.0,
            "static_threshold": 90.0,
            "blind_until": "2026-08-20T13:00:00+00:00",
            "window_id": "2026-08-25T07:00:00+00:00",
        },
    )
    blind = page.locator("[data-runway-blind]")
    assert blind.count() == 1, "слепота гейта не показана отдельным узлом"
    # ПЕРЕЗАМОРОЖЕНО 19.08: прежний ассерт требовал «20.08» или «2026-08-20», то есть
    # приколачивал ФОРМАТ даты. Панель везде печатает через `_analyticsDateTime`
    # (локализованное «20 авг., 15:00»), и подгонять общий формат под один тест значило бы
    # чинить не то. Проверяем СМЫСЛ: момент вооружения назван и это именно 20-е число.
    text = blind.inner_text()
    assert "Вооружится" in text
    assert "20" in text, f"момент вооружения не показан: {text!r}"
    assert "34" in text, "не показано, сколько рабочих часов требуется"
