"""Механика русской локали дашборда: словарь доезжает до экрана, выбор переживает
перезагрузку, переключатель доступен до входа.

Проверяется МЕХАНИЗМ, а не формулировки. Ни один тест здесь не знает, как именно
переведена конкретная надпись: перевод — решение владельца продукта, и он будет
меняться. Ломаться эти тесты обязаны на другом: словарь не доехал до разметки,
язык не сохранился, переключателя нет на первом экране, `T` не определена к моменту
разбора остальных сценариев. Приёмка по отрисованным экранам — отдельный прогон,
`.orchestra/tasks/V-584/audit_screens.py`.
"""

import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from tests.test_frontend import _free_port, _seed_dashboard_db, _stop_dashboard_server

USER = "i18n-user"
PASSWORD = "i18n-pass"

# Атрибуты, которые переводятся по разметке, и соответствующие им data-метки.
ATTRS = [
    ("data-i18n-title", "title"),
    ("data-i18n-placeholder", "placeholder"),
    ("data-i18n-aria-label", "aria-label"),
]


def _start_auth_dashboard(db_path: Path):
    """Сервер С включённым логином: страница входа — первый экран пользователя."""
    env = os.environ.copy()
    env["ORCHESTRA_DB_PATH"] = str(db_path)
    # Сервер поднимается ОТДЕЛЬНЫМ процессом, где `pytest` в sys.modules нет, а
    # `load_dotenv()` в lifespan читает `.env` чекаута с БОЕВЫМИ путями. Не передав
    # хранилище задач явно, мы отдаём подпроцессу живое: 22.09.2026 так было
    # переписано 1863 записи боевого хранилища.
    env["ORCHESTRA_TASK_REPOSITORY"] = str(db_path.parent / "tasks")
    env["DASHBOARD_USER"] = USER
    env["DASHBOARD_PASSWORD"] = PASSWORD
    env["OWNER_MODE"] = "1"
    env["SSH_TUNNELS"] = ""
    port = _free_port()
    root = Path(__file__).resolve().parent.parent
    output = tempfile.TemporaryFile(dir=db_path.parent)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(root), env=env, stdout=output, stderr=subprocess.STDOUT,
    )
    proc.stdout = output
    origin = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output.seek(0)
            raise RuntimeError(
                f"сервер локали упал ({proc.returncode}):\n"
                + output.read().decode("utf-8", "replace")[-2000:]
            )
        try:
            with urllib.request.urlopen(f"{origin}/login", timeout=1) as response:
                if response.status == 200:
                    return proc, origin
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.1)
    proc.kill()
    raise RuntimeError(f"сервер локали не поднялся на {origin}")


@pytest.fixture(scope="module")
def dashboard_browser(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("i18n-dash") / "orchestra.db"
    _seed_dashboard_db(db_path)
    proc, origin = _start_auth_dashboard(db_path)
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch()
            except Exception as exc:
                pytest.fail(
                    f"chromium недоступен ({type(exc).__name__}: {exc}); "
                    "установка: playwright install --with-deps chromium"
                )
            yield browser, origin
            browser.close()
    finally:
        _stop_dashboard_server(proc)


def _login(page, origin):
    page.goto(f"{origin}/login", wait_until="domcontentloaded")
    page.fill('input[name="username"]', USER)
    page.fill('input[name="password"]', PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_selector("#agent-list", timeout=30000)


def _open_dashboard(dashboard_browser, lang=None):
    browser, origin = dashboard_browser
    context = browser.new_context()
    if lang:
        context.add_init_script(
            f"try {{ localStorage.setItem('orch_lang', '{lang}'); }} catch (e) {{}}"
        )
    page = context.new_page()
    _login(page, origin)
    return context, page


def test_dictionary_reaches_static_markup(dashboard_browser):
    """Разметка с data-i18n обязана прийти на экран уже переведённой."""
    context, page = _open_dashboard(dashboard_browser, "ru")
    try:
        state = page.evaluate("""() => {
            const rows = [];
            document.querySelectorAll('[data-i18n]').forEach((el) => {
                el.childNodes.forEach((node) => {
                    if (node.nodeType !== Node.TEXT_NODE) return;
                    const shown = node.nodeValue.trim();
                    if (!shown) return;
                    rows.push({shown, translated: Object.values(window.orchDict).includes(shown)});
                });
            });
            return {rows, keys: Object.keys(window.orchDict).length};
        }""")
    finally:
        context.close()

    assert state["keys"] > 0, "словарь пуст — переводить нечем"
    assert state["rows"], "в разметке нет ни одного узла с data-i18n"
    untranslated = [row["shown"] for row in state["rows"] if not row["translated"]]
    assert untranslated == [], (
        "эти узлы разметки не получили значение из словаря: " + repr(untranslated)
    )


def test_dictionary_reaches_marked_attributes(dashboard_browser):
    """Подписи title/placeholder/aria-label переводятся тем же словарём."""
    context, page = _open_dashboard(dashboard_browser, "ru")
    try:
        state = page.evaluate("""(attrs) => {
            const rows = [];
            for (const [marker, attr] of attrs) {
                document.querySelectorAll('[' + marker + ']').forEach((el) => {
                    const shown = (el.getAttribute(attr) || '').trim();
                    if (!shown) return;
                    rows.push({attr, shown,
                               translated: Object.values(window.orchDict).includes(shown)});
                });
            }
            return rows;
        }""", ATTRS)
    finally:
        context.close()

    assert state, "ни один атрибут не помечен для перевода"
    untranslated = [f'{row["attr"]}={row["shown"]!r}' for row in state if not row["translated"]]
    assert untranslated == [], (
        "эти подписи не получили значение из словаря: " + repr(untranslated)
    )


def test_language_choice_survives_reload(dashboard_browser):
    """Выбор языка хранится у клиента и переживает перезагрузку страницы.

    Начальный язык здесь НЕ навязывается извне: init-скрипт выполняется на каждой
    навигации и переписывал бы сделанный в тесте выбор при перезагрузке — то есть
    проверял бы себя, а не сохранение.
    """
    context, page = _open_dashboard(dashboard_browser)
    try:
        assert page.evaluate("() => orchLang()") == "ru"
        before = page.evaluate(_FIRST_MARKED_TEXT)

        with page.expect_navigation():
            page.click('#lang-switch button[data-lang="en"]')
        page.wait_for_selector("#agent-list")
        assert page.evaluate("() => orchLang()") == "en"
        english = page.evaluate(_FIRST_MARKED_TEXT)
        assert english != before, "переключение на английский ничего не изменило"

        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector("#agent-list")
        assert page.evaluate("() => orchLang()") == "en"
        assert page.evaluate(_FIRST_MARKED_TEXT) == english

        with page.expect_navigation():
            page.click('#lang-switch button[data-lang="ru"]')
        page.wait_for_selector("#agent-list")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector("#agent-list")
        assert page.evaluate("() => orchLang()") == "ru"
        assert page.evaluate(_FIRST_MARKED_TEXT) == before
    finally:
        context.close()


# Текст первого помеченного узла — «что видно на экране» без привязки к формулировке.
_FIRST_MARKED_TEXT = """() => {
    const el = document.querySelector('[data-i18n]');
    return el ? el.textContent.trim() : null;
}"""


def test_language_switch_works_before_login(dashboard_browser):
    """Русский доступен с первого экрана: переключатель есть на странице входа."""
    browser, origin = dashboard_browser
    context = browser.new_context()
    page = context.new_page()
    try:
        page.goto(f"{origin}/login", wait_until="domcontentloaded")
        page.wait_for_selector("#lang-switch button")
        assert page.locator("#lang-switch button").count() == 2
        assert not context.cookies(), "страница входа не должна требовать сессии"

        russian = page.evaluate(_FIRST_MARKED_TEXT)
        assert page.evaluate("() => orchLang()") == "ru"
        assert page.evaluate("() => document.documentElement.lang") == "ru"

        with page.expect_navigation():
            page.click('#lang-switch button[data-lang="en"]')
        page.wait_for_selector("#lang-switch button")
        assert page.evaluate("() => orchLang()") == "en"
        assert page.evaluate(_FIRST_MARKED_TEXT) != russian
        assert page.locator('input[name="username"]').count() == 1
    finally:
        context.close()


def test_missing_key_falls_back_to_source_string(dashboard_browser):
    """Английская локаль работает без словаря, подстановка значений — по именам."""
    context, page = _open_dashboard(dashboard_browser, "ru")
    try:
        result = page.evaluate("""() => ({
            unknown: T('строка, которой нет в словаре'),
            params: T('нет такого ключа {a}/{b}', {a: 1, b: 2}),
            missingParam: T('{нетзначения}', {}),
            notAString: T(null),
        })""")
    finally:
        context.close()

    assert result["unknown"] == "строка, которой нет в словаре"
    assert result["params"] == "нет такого ключа 1/2"
    assert result["missingParam"] == "{нетзначения}"
    assert result["notAString"] is None


def test_dashboard_loads_without_script_errors(dashboard_browser):
    """`T` объявлена раньше остальных сценариев — иначе разбор их файлов падает."""
    browser, origin = dashboard_browser
    context = browser.new_context()
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        _login(page, origin)
        page.wait_for_timeout(1500)
        assert page.evaluate("() => typeof T") == "function"
        assert errors == [], "ошибки при загрузке страницы: " + repr(errors)
    finally:
        context.close()
