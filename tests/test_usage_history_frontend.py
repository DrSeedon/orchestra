"""Панель истории обязана говорить, ЧЕГО не хватает.

Раньше все три исхода — «снимков нет», «запрос упал», «нет данных по этому
провайдеру» — рисовались одной и той же надписью «Collecting data...», которая
не менялась никогда. Молчаливая заглушка вместо причины и есть баг.
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


def _slot_text(browser: Browser, api_script: str) -> str:
    """Отдаём _loadSparkline подставной api() и возвращаем текст слота Claude."""
    page = browser.new_page()
    page.set_content('<body><div id="usage-bar"></div></body>')
    page.add_script_tag(path=str(UTILS_JS))
    page.add_script_tag(path=str(USAGE_JS))
    result = page.evaluate(
        """apiScript => {
            eval(apiScript);
            _sparkData = null; _sparkDataTs = 0; _sparkError = '';
            const tip = document.createElement('div');
            tip.innerHTML = '<div data-usage-history="anthropic"></div>'
                          + '<div data-usage-history="codex,codex_spark"></div>';
            document.body.appendChild(tip);
            return _loadSparkline(tip).then(() => ({
                anthropic: tip.children[0].innerHTML,
                codex: tip.children[1].innerHTML,
            }));
        }""",
        api_script,
    )
    page.close()
    return result


def _history(count: int, *, provider_usage=None, step: int = 30, skip: int = 0):
    """Ответ /api/usage/history: снимки в текущем 5h-окне с шагом step минут.

    skip — сколько шагов пропустить в середине (провал в данных).
    """
    js = []
    for i in range(count):
        age = step * (count - i) + (step * skip if i < count // 2 else 0)
        js.append(
            "{ts: new Date(Date.now() - %d * 60000).toISOString(),"
            " five_hour_pct: %d, five_hour_resets_at: resets,"
            " providers: %s}" % (age, 10 + i * 5, provider_usage or "null")
        )
    # Скобки обязательны: `() => {…}` читается как тело функции, а не объект.
    return "({step_minutes: %d, rows: [%s]})" % (step, ",".join(js))


def test_empty_history_says_what_is_missing(browser):
    out = _slot_text(browser, "window.api = async () => ({step_minutes: 5, rows: []});")

    assert "Снимков ещё нет" in out["anthropic"]
    assert "Collecting data" not in out["anthropic"]


def test_failed_request_surfaces_the_error(browser):
    """Пустой catch прятал причину — теперь класс исключения виден в панели."""
    out = _slot_text(
        browser,
        "window.api = async () => { const e = new Error('signal timed out');"
        " e.name = 'TimeoutError'; throw e; };",
    )

    assert "не загрузилась" in out["anthropic"]
    assert "TimeoutError" in out["anthropic"]
    assert "signal timed out" in out["anthropic"]


def test_real_data_draws_a_chart_not_a_stub(browser):
    """Главная жалоба: графика нет вовсе. При живых данных должен быть svg."""
    out = _slot_text(
        browser,
        "const resets = new Date(Date.now() + 3600000).toISOString();"
        f"window.api = async () => {_history(6)};",
    )

    assert "<svg" in out["anthropic"], out["anthropic"]
    assert "Collecting data" not in out["anthropic"]


def test_provider_absent_from_history_is_not_the_same_as_no_data(browser):
    """Данные есть, но Codex в них не встречается — это ДРУГОЕ сообщение."""
    out = _slot_text(
        browser,
        "const resets = new Date(Date.now() + 3600000).toISOString();"
        f"window.api = async () => {_history(6)};",
    )

    assert "провайдера в истории нет" in out["codex"], out["codex"]
    assert "Снимки ведутся с" in out["codex"]
    assert "<svg" not in out["codex"]


def test_hole_in_data_breaks_the_line_instead_of_bridging_it(browser):
    """Через провал в снимках линия не проводится: график врал бы формой."""
    prelude = "const resets = new Date(Date.now() + 3600000).toISOString();"
    solid = _slot_text(browser, prelude + f"window.api = async () => {_history(8, step=10)};")
    holed = _slot_text(browser, prelude + f"window.api = async () => {_history(8, step=10, skip=6)};")

    assert solid["anthropic"].count('stroke="#38bdf8"') == 1, solid["anthropic"]
    assert holed["anthropic"].count('stroke="#38bdf8"') == 2, holed["anthropic"]


def test_history_request_gets_its_own_timeout(browser):
    """4 МБ на общем 5-секундном таймауте api() обрывались раньше ответа."""
    source = USAGE_JS.read_text()
    block = source.split("async function _loadSparkline", 1)[1].split("_sparkPeriodIdx = {}", 1)[0]

    assert "AbortSignal.timeout(30000)" in block
