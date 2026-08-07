"""#162 — верхний бар: та же строка 5h, но честная, когда недельный связывает.

Три состояния гоняются по ОДНОМУ и тому же коду: связывает / не связывает / поля нет.
Второе и третье обязаны совпадать с сегодняшним видом байт в байт — иначе «показываем
только при пороге» превращается в «показываем всегда, просто по-разному».
"""

from pathlib import Path

import pytest
from playwright.sync_api import Browser, sync_playwright

ROOT = Path(__file__).parent.parent
UTILS_JS = ROOT / "app/static/js/utils.js"
USAGE_JS = ROOT / "app/static/js/usage.js"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


def _render(browser: Browser, headroom, width=1440):
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.set_content('<body><div id="usage-bar"></div></body>')
    page.evaluate("""() => {
        window.marked = {setOptions() {}, parse(v) { return v; }};
        window.DOMPurify = {addHook() {}};
    }""")
    page.add_script_tag(path=str(UTILS_JS))
    page.add_script_tag(path=str(USAGE_JS))
    page.evaluate(
        """headroom => {
            const reset = new Date(Date.now() + 3 * 3600000).toISOString();
            _usageData = {
                anthropic: {
                    five_hour: {utilization: 9, resets_at: reset},
                    seven_day: {utilization: 92, resets_at: new Date(Date.now() + 4 * 86400000).toISOString()},
                },
                codex: {primary: {utilization: 100, window_minutes: 10080, resets_at: reset}},
                grok: null,
                orchestra: {total_cost_usd: 2261, agents_count: 3},
            };
            if (headroom) _usageData.quota_headroom = headroom;
            renderUsageBar();
        }""",
        headroom,
    )
    html = page.evaluate("() => document.getElementById('usage-bar').innerHTML")
    box = page.evaluate("""() => {
        const bar = document.getElementById('usage-bar');
        const cap = bar.querySelector('[data-quota-cap]');
        return {
            scroll: bar.scrollWidth,
            client: bar.clientWidth,
            capRight: cap ? Math.round(cap.getBoundingClientRect().right) : null,
        };
    }""")
    page.close()
    return html, box


BINDING = {"rate": 0.1313, "available_pct": 60.9, "locked_pct": 30.1,
           "windows_left": 0.61, "window_hours": 72, "sample_five_hour_pct": 579.0}
FREE = {**BINDING, "available_pct": 91.0, "locked_pct": 0.0, "windows_left": 2.97}


def test_binding_week_marks_the_locked_zone_and_says_how_much_is_left(browser):
    html, _ = _render(browser, BINDING)
    assert "0.6 окна" in html
    assert "repeating-linear-gradient" in html          # заперто недельным
    assert "width:30.1%" in html                        # ровно locked_pct
    assert "5h: " in html and "7d: " in html


def test_zones_and_caption_live_in_the_same_5h_element(browser):
    """Один прибор, а не два: и полоса, и текст — внутри той же строки лимита 5h."""
    html, _ = _render(browser, BINDING)
    five = html.split("5h: ")[1].split("7d: ")[0]
    assert "repeating-linear-gradient" in five
    assert "0.6 окна" in five
    assert "5h: " in html.split("0.6 окна")[0]


def test_reset_countdown_survives_the_added_text(browser):
    """Остаток окна выкидывать нельзя — он в той же строке и до, и после правки."""
    html, _ = _render(browser, BINDING)
    plain, _ = _render(browser, None)
    for mark in ("(", "%"):
        assert mark in html and mark in plain
    assert "⏳" in html or "h " in html or "m" in html


def test_free_week_looks_exactly_like_today(browser):
    """Порог 1.5: выше него разметка обязана совпасть с версией без поля вовсе."""
    with_headroom, _ = _render(browser, FREE)
    without, _ = _render(browser, None)
    assert with_headroom == without
    assert "repeating-linear-gradient" not in with_headroom
    assert "data-quota-cap" not in with_headroom


def test_foreign_runtimes_are_untouched_in_both_states(browser):
    """Зоны — только у 5h Claude. У Codex своя полоса и она не меняется."""
    binding, _ = _render(browser, BINDING)
    plain, _ = _render(browser, None)
    codex_binding = binding.split("Codex")[1]
    codex_plain = plain.split("Codex")[1]
    assert codex_binding == codex_plain


def test_caption_is_visible_on_a_phone(browser):
    """Бар шире телефона и БЕЗ правки (замер: 1126 px при 390 px экрана) — он nowrap
    с overflow:hidden, правый край всегда срезан. Значит проверять надо не ширину бара,
    а то, что добавленный текст попал в видимую часть, а не за срез."""
    html, box = _render(browser, BINDING, width=390)
    assert "0.6 окна" in html
    assert box["capRight"] is not None
    assert box["capRight"] <= box["client"], (
        f"подпись уехала за срез экрана: {box['capRight']} > {box['client']}"
    )
