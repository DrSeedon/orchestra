"""Панель истории обязана говорить, ЧЕГО не хватает.

Раньше все три исхода — «снимков нет», «запрос упал», «нет данных по этому
провайдеру» — рисовались одной и той же надписью «Collecting data...», которая
не менялась никогда. Молчаливая заглушка вместо причины и есть баг.
"""
import re
from pathlib import Path

import pytest
from playwright.sync_api import Browser, sync_playwright

ROOT = Path(__file__).parent.parent
UTILS_JS = ROOT / "app/static/js/utils.js"
USAGE_JS = ROOT / "app/static/js/usage.js"
APP_JS = ROOT / "app/static/js/app.js"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


def _page_with_api(browser: Browser):
    """Страница с РЕАЛЬНЫМ origin и полностью загруженным app.js.

    `set_content` даёт about:blank, где localStorage запрещён, и исполнение
    app.js обрывается на полпути — api() определён, а объявленные ниже него
    `_netFailPath`/`_API_TIMEOUT_MS` нет. Нужен настоящий origin.
    """
    page = browser.new_page()
    page.route(
        "http://harness.local/**",
        lambda route: route.fulfill(
            status=200, content_type="text/html",
            body="<body><div id='usage-bar'></div></body>",
        ),
    )
    page.goto("http://harness.local/")
    page.add_script_tag(path=str(UTILS_JS))
    page.add_script_tag(path=str(APP_JS))
    return page


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


def _history(count: int, *, provider_usage=None, step: int = 30, skip: int = 0,
             nulls: tuple = (), drop: tuple = ()):
    """Ответ /api/usage/history: снимки в текущем 5h-окне с шагом step минут.

    skip — сколько шагов пропустить в середине (провал в данных);
    nulls — индексы снимков, где источник не ответил (`five_hour_pct: null`);
    drop — индексы снимков, которых в ответе нет вовсе.
    """
    js = []
    for i in range(count):
        if i in drop:
            continue
        age = step * (count - i) + (step * skip if i < count // 2 else 0)
        pct = "null" if i in nulls else str(10 + i * 5)
        js.append(
            "{ts: new Date(Date.now() - %d * 60000).toISOString(),"
            " five_hour_pct: %s, five_hour_resets_at: resets,"
            " providers: %s}" % (age, pct, provider_usage or "null")
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


def test_null_pct_is_a_hole_not_a_zero(browser):
    """#150: источник не ответил → в колонке null. Ноль нарисовал бы провал в пол.

    Сравниваем с тем же рядом, где серединных снимков просто НЕТ: картинка обязана
    совпасть — оба случая означают «данных за этот период не было».
    """
    prelude = "const resets = new Date(Date.now() + 3600000).toISOString();"
    nulled = _slot_text(browser, prelude + f"window.api = async () => {_history(8, step=10, nulls=(3, 4))};")
    missing = _slot_text(browser, prelude + f"window.api = async () => {_history(8, step=10, drop=(3, 4))};")

    # Сравниваем сами линии расхода: разметку целиком нельзя — метка сброса
    # считается от Date.now() и уезжает на доли пикселя между двумя прогонами
    line = lambda html: re.findall(r'points="([^"]+)" fill="none" stroke="#38bdf8"', html)

    assert len(line(nulled["anthropic"])) == 2, nulled["anthropic"]
    assert line(nulled["anthropic"]) == line(missing["anthropic"])


def _weekly(count: int, *, first_age_min: int, reset_in_h: int):
    """Снимки недельного окна: шаг 30 мин, самый старый — first_age_min минут назад."""
    rows = []
    for i in range(count):
        rows.append(
            "{ts: new Date(Date.now() - %d * 60000).toISOString(), seven_day_pct: %d,"
            " seven_day_resets_at: new Date(Date.now() + %d * 3600000).toISOString(),"
            " providers: null}" % (first_age_min - 30 * i, 20 + i, reset_in_h)
        )
    return ",".join(rows)


def test_older_period_is_fetched_on_demand(browser):
    """Фронт грузит один период; предыдущий приезжает по клику ◀, а не лежит в первом ответе."""
    page = browser.new_page()
    page.set_content("<body><div id='usage-bar'></div></body>")
    page.add_script_tag(path=str(UTILS_JS))
    page.add_script_tag(path=str(USAGE_JS))
    result = page.evaluate(
        """() => {
            const calls = [];
            window.api = async (url) => {
                calls.push(url);
                const rows = url.includes('until=')
                    ? [%s]
                    : [%s];
                return {step_minutes: 30, rows,
                        oldest_ts: new Date(Date.now() - 30 * 86400000).toISOString()};
            };
            _sparkData = null; _sparkDataTs = 0; _sparkError = ''; _sparkOldestTs = '';
            const tip = document.createElement('div');
            tip.innerHTML = '<div data-usage-history="anthropic"></div>';
            document.body.appendChild(tip);
            return _loadSparkline(tip).then(async () => {
                const first = tip.children[0].innerHTML;
                const older = tip.children[0].querySelector('[data-spark-nav="older"]');
                if (!older) return {calls, first, after: '', clicked: false};
                older.click();
                await new Promise(resolve => setTimeout(resolve, 100));
                return {calls, first, after: tip.children[0].innerHTML, clicked: true};
            });
        }"""
        % (_weekly(6, first_age_min=900, reset_in_h=-140), _weekly(6, first_age_min=300, reset_in_h=4)),
    )
    page.close()

    assert result["clicked"], "стрелка ◀ недоступна, хотя сервер сообщил более старые снимки"
    assert len(result["calls"]) == 2, result["calls"]
    assert "until=" not in result["calls"][0], result["calls"][0]
    assert "until=" in result["calls"][1], result["calls"][1]
    assert "current" in result["first"]
    assert "1w ago" in result["after"], result["after"]


def test_series_order_does_not_depend_on_which_chunk_loaded_first(browser):
    """Подгрузили старый кусок без 5h — и 5h с 7d менялись местами и цветами."""
    rows = []
    for i in range(6):
        five = "" if i == 0 else " five_hour_pct: %d, five_hour_resets_at: r5," % (10 + i)
        rows.append(
            "{ts: new Date(Date.now() - %d * 60000).toISOString(),%s"
            " seven_day_pct: %d, seven_day_resets_at: r7, providers: null}"
            % (30 * (6 - i), five, 20 + i)
        )
    out = _slot_text(
        browser,
        "const r5 = new Date(Date.now() + 3600000).toISOString();"
        "const r7 = new Date(Date.now() + 86400000).toISOString();"
        "window.api = async () => ({step_minutes: 30, rows: [%s], oldest_ts: ''});" % ",".join(rows),
    )

    order = [chunk.split('"')[0] for chunk in out["anthropic"].split('data-usage-series="')[1:]]
    assert order == ["anthropic:five_hour", "anthropic:seven_day"], order


def test_history_request_gets_its_own_timeout(browser):
    """4 МБ на общем таймауте api() обрывались раньше ответа.

    Проверяется ПОВЕДЕНИЕ, а не текст вызова: запрошенный бюджет и то, что свой
    signal вызывающего его не отменяет. Прошлая версия искала дословное
    `AbortSignal.timeout(30000)` внутри `_sparkFetch` и покраснела, когда #58
    перевёл бюджет в параметр `api(url, {timeoutMs})` — поведение при этом
    сохранилось. Никакого wall-clock: бюджет снимается с самого AbortSignal.
    """
    page = _page_with_api(browser)
    page.add_script_tag(path=str(USAGE_JS))
    result = page.evaluate(
        """() => {
            const asked = [];
            const realTimeout = AbortSignal.timeout.bind(AbortSignal);
            AbortSignal.timeout = ms => { asked.push(ms); return realTimeout(ms); };
            let sawAbort = null;
            window.fetch = (url, opts) => {
                sawAbort = opts.signal.aborted;
                return Promise.resolve({
                    ok: true,
                    json: async () => ({rows: [], step_minutes: 5, oldest_ts: ''}),
                });
            };
            return _sparkFetch('').then(() => ({asked, sawAbort}));
        }"""
    )
    page.close()

    assert result["asked"], "api() больше не ставит таймаут на запрос истории"
    assert max(result["asked"]) >= 30000, (
        f"бюджет истории просел до {result['asked']}; годовой ответ (4.36 МБ) "
        f"снова оборвётся раньше, чем доедет"
    )
    assert result["sawAbort"] is False, "запрос ушёл уже отменённым"


def test_history_timeout_survives_a_caller_signal(browser):
    """`opts.signal || AbortSignal.timeout(...)` молча съедал бы таймаут.

    Если вызывающий передал свой signal, комбинировать надо через
    `AbortSignal.any`, иначе зависший ответ висит вечно.
    """
    page = _page_with_api(browser)
    result = page.evaluate(
        """() => {
            window.fetch = (url, opts) => new Promise((_, reject) => {
                opts.signal.addEventListener('abort', () => reject(opts.signal.reason));
            });
            const caller = new AbortController();  // жив и не срабатывает
            // Свой потолок: со съеденным таймаутом запрос висит ВЕЧНО, и без него
            // тест умирал бы на разрушении контекста вместо внятного диагноза.
            const hung = new Promise(r => setTimeout(() => r({name: 'HUNG'}), 3000));
            const call = api('/api/usage/history?hours=1',
                             {signal: caller.signal, timeoutMs: 40})
                .then(() => ({name: 'resolved'}), e => ({name: e.name}));
            return Promise.race([call, hung]);
        }"""
    )
    page.close()

    assert result["name"] == "TimeoutError", (
        f"свой signal вызывающего отменил таймаут: {result}"
    )
