"""Playwright smoke tests for Orchestra dashboard.

The dashboard is started in-process by ``dashboard_browser`` (isolated DB,
no auth). A missing :8888 must not skip these tests — that printed green
while 12 checks never ran (#145, #242).
"""

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

_DASHBOARD_ORIGIN = ""
HTML_ARTIFACT_CSP = (
    "sandbox allow-scripts; "
    "default-src 'unsafe-inline' 'unsafe-eval' data: blob:; "
    "connect-src 'none'"
)


def test_html_preview_uses_protected_raw_url_and_opaque_origin_sandbox():
    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
    html_branch = source.split("if (/\\.html?$/i.test(path)) {", 1)[1].split(
        "return;", 1,
    )[0]
    match = re.search(r'<iframe[^`]+sandbox="([^"]+)"', html_branch)

    assert match
    assert "openBtn.href = rawUrl;" in html_branch
    assert set(match.group(1).split()) == {"allow-scripts"}
    assert "allow-same-origin" not in match.group(1)


def test_model_picker_surfaces_native_history_result_and_fallback():
    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
    helper = source.split("function _historyTransferMessage", 1)[1].split(
        "async function _showModelPicker", 1,
    )[0]
    picker = source.split("async function _showModelPicker", 1)[1].split(
        "function updateAgentInfo", 1,
    )[0]

    assert "reasoning omitted=${transfer.reasoning_omitted}" in helper
    assert "summary fallback active" in helper
    assert "_showHistoryTransfer(resp.history_transfer);" in picker


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", [".html", ".HTM"])
async def test_raw_html_response_has_sandbox_csp(tmp_path, monkeypatch, suffix):
    from app.routes import system

    target = tmp_path / f"artifact{suffix}"
    target.write_text("<script>document.body.textContent = 'works'</script>")
    monkeypatch.setattr(system, "_ALLOWED_ROOTS", [str(tmp_path)])

    response = await system.get_file_raw(str(target))

    assert response.headers["content-security-policy"] == HTML_ARTIFACT_CSP


@pytest.mark.asyncio
async def test_raw_non_html_response_has_no_artifact_csp(tmp_path, monkeypatch):
    from app.routes import system

    target = tmp_path / "notes.txt"
    target.write_text("safe text")
    monkeypatch.setattr(system, "_ALLOWED_ROOTS", [str(tmp_path)])

    response = await system.get_file_raw(str(target))

    assert "content-security-policy" not in response.headers


def _dashboard_base() -> str:
    if not _DASHBOARD_ORIGIN:
        pytest.fail("dashboard fixture did not start — dashboard_browser is required")
    return _DASHBOARD_ORIGIN


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _seed_dashboard_db(db_path: Path) -> None:
    """One orchestrator + the notify probe so selectAgent/waiters have a name."""
    from app import db as dbmod
    from app.db import init_db, save_session

    previous = dbmod.DB_PATH
    dbmod.DB_PATH = db_path
    try:
        init_db()
        now = datetime.now(timezone.utc).isoformat()
        save_session({
            "id": "fe-orch-id", "name": "fe-orch", "scope": "/tmp/fe-scope",
            "cwd": "/tmp/fe-scope", "model": "claude-opus-5[1m]",
            "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "", "created_at": now,
            "finished_at": None, "role": "orchestrator",
        })
        save_session({
            "id": "fe-notify-id", "name": "notify-268-probe",
            "scope": "/tmp/fe-scope", "cwd": "/tmp/fe-scope",
            "model": "claude-sonnet-5[1m]", "system_prompt": "",
            "status": "idle", "session_id": None, "cost_usd": 0.0,
            "worktree_path": None, "branch": None,
            "is_orchestrator": False, "color": "", "created_at": now,
            "finished_at": None, "role": "worker",
            "parent_id": "fe-orch-id", "parent_name": "fe-orch",
        })
    finally:
        dbmod.DB_PATH = previous


def _start_dashboard_server(db_path: Path) -> tuple[subprocess.Popen, str]:
    # Empty strings beat load_dotenv(): existing keys are not overwritten, so
    # the subprocess cannot pick up the machine unit's DASHBOARD_* / tunnels.
    env = os.environ.copy()
    env["ORCHESTRA_DB_PATH"] = str(db_path)
    env["DASHBOARD_USER"] = ""
    env["DASHBOARD_PASSWORD"] = ""
    env["OWNER_MODE"] = ""
    env["SSH_TUNNELS"] = ""
    port = _free_port()
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", str(port),
            "--log-level", "warning",
        ],
        cwd=str(root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    origin = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    last = "no attempt"
    while time.time() < deadline:
        if proc.poll() is not None:
            log = (proc.stdout.read() or b"").decode("utf-8", "replace")[-2000:]
            raise RuntimeError(
                f"dashboard fixture exited {proc.returncode}: {log}"
            )
        try:
            urllib.request.urlopen(origin, timeout=1)
            return proc, origin
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError(f"dashboard fixture did not accept HTTP at {origin}: {last}")


def _stop_dashboard_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def _goto_dashboard(page: Page):
    """Open the fixture dashboard. Missing HTML is a failure, not a skip (#242)."""
    origin = _dashboard_base()
    try:
        resp = page.goto(origin, wait_until="domcontentloaded")
    except Exception as exc:
        pytest.fail(
            f"dashboard at {origin} unreachable ({type(exc).__name__}: {exc})"
        )
    if resp is None or resp.status != 200:
        status = "no response" if resp is None else f"HTTP {resp.status}"
        pytest.fail(f"dashboard at {origin} returned {status}")
    if page.locator("#agent-list").count() == 0:
        pytest.fail(f"dashboard at {origin} has no #agent-list")
    return resp


@pytest.fixture(scope="module")
def dashboard_browser(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("fe-dash") / "orchestra.db"
    _seed_dashboard_db(db_path)
    proc, origin = _start_dashboard_server(db_path)
    global _DASHBOARD_ORIGIN
    _DASHBOARD_ORIGIN = origin
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch()
            except Exception as exc:
                pytest.fail(
                    f"chromium unavailable ({type(exc).__name__}: {exc}); "
                    "install: playwright install --with-deps chromium"
                )
            yield browser
            browser.close()
    finally:
        _DASHBOARD_ORIGIN = ""
        _stop_dashboard_server(proc)


@pytest.fixture(scope="module")
def dashboard_page(dashboard_browser: Browser):
    page = dashboard_browser.new_page()
    _goto_dashboard(page)
    expect(page.locator("#agent-list")).to_be_visible()
    yield page
    page.close()


def _repo_scope():
    """Scope сервера — путь РЕПОЗИТОРИЯ, а не рабочей копии: из worktree они разные."""
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=Path(__file__).parent, capture_output=True, text=True, check=True,
    ).stdout.strip()
    return str(Path(common).parent)


def test_dashboard_loads(dashboard_page: Page):
    expect(dashboard_page).to_have_title("🎼 Orchestra")


def test_sidebar_agents_visible(dashboard_page: Page):
    agent_list = dashboard_page.locator("#agent-list")
    expect(agent_list).to_be_visible()


def test_chat_input_exists(dashboard_page: Page):
    chat_input = dashboard_page.locator("#chat-input")
    expect(chat_input).to_be_visible()
    expect(chat_input).to_be_enabled()


def test_send_button_exists(dashboard_page: Page):
    send_btn = dashboard_page.locator("#send-btn")
    expect(send_btn).to_be_visible()
    expect(send_btn).to_have_text("Send")


def test_usage_bar_visible(dashboard_page: Page):
    usage_bar = dashboard_page.locator("#usage-bar")
    expect(usage_bar).to_be_attached()


def test_stream_updates_preserve_chat_selection(dashboard_browser: Browser):
    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
    stream_code = source.split("let streamBubble = null;", 1)[1].split(
        "function _renderJsonGrid", 1,
    )[0]
    page = dashboard_browser.new_page()
    page.set_content(
        '<div id="chat"><div id="stream"><p>Streaming text to copy</p>'
        '<span class="typing-cursor">▍</span></div></div>'
    )
    page.add_script_tag(
        content=f"""
            const $ = selector => document.querySelector(selector);
            const DOMPurify = {{sanitize: value => value}};
            const marked = {{parse: value => `<p>${{value}}</p>`}};
            function addCopyBtn() {{}}
            function addTimestamp() {{}}
            function _chatAtBottom() {{ return true; }}
            function _markChatHasNewBelow() {{}}
            let streamBubble = null;
            {stream_code}
        """
    )

    page.evaluate(
        """() => {
            streamBubble = document.querySelector('#stream');
            streamContent = 'Streaming text to copy';
            streamPending = ' plus update';
        }"""
    )
    page.locator("#stream p").dblclick(position={"x": 25, "y": 8})
    selected = page.evaluate("() => window.getSelection().toString()")
    assert selected

    before = page.evaluate(
        """() => {
            const selection = window.getSelection();
            _streamRenderTick();
            return {
                selectedAfterUpdate: selection.toString(),
                pending: streamPending,
            };
        }"""
    )

    assert before == {
        "selectedAfterUpdate": selected,
        "pending": " plus update",
    }

    page.evaluate(
        """() => {
            window.getSelection().removeAllRanges();
            document.dispatchEvent(new Event('selectionchange'));
        }"""
    )
    page.wait_for_function("() => streamPending === ''")
    expect(page.locator("#stream")).to_contain_text("plus update")

    deferred = page.evaluate(
        """() => {
            const chat = document.querySelector('#chat');
            chat.innerHTML = '<div id="stream"><p>Final text to copy</p></div>';
            streamBubble = document.querySelector('#stream');
            streamContent = 'Final text to copy';
            streamPending = ' plus buffered';
            const node = streamBubble.querySelector('p').firstChild;
            const range = document.createRange();
            range.setStart(node, 0);
            range.setEnd(node, 10);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            _completeStreamBubble('', '2026-07-30T00:00:00Z');
            return {
                selected: selection.toString(),
                deferred: _streamDeferredFinal !== null,
                bubbleStillLive: streamBubble !== null,
            };
        }"""
    )

    assert deferred == {
        "selected": "Final text",
        "deferred": True,
        "bubbleStillLive": True,
    }
    page.evaluate(
        """() => {
            window.getSelection().removeAllRanges();
            document.dispatchEvent(new Event('selectionchange'));
        }"""
    )
    page.wait_for_function("() => streamBubble === null")
    expect(page.locator("#chat")).to_contain_text("Final text to copy plus buffered")
    page.close()


def test_unexecuted_tool_call_marker_detects_structure_without_prose_false_alarms(
    dashboard_browser: Browser,
):
    from app.tool_call_guard import looks_like_unexecuted_tool_call

    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
    guard_code = (
        "const _UNEXECUTED_TOOL_CALL_WARNING"
        + source.split("const _UNEXECUTED_TOOL_CALL_WARNING", 1)[1].split(
            "function _selectionTouchesStream", 1,
        )[0]
    )
    cases = [
        (
            '<function_calls><invoke name="Bash"><parameter name="cmd">'
            "pwd</parameter></invoke>",
            True,
        ),
        ('câ{"cmd":"pwd"}</parameter>\n</invoke>', True),
        ("The invoke helper receives a parameter and returns normally.", False),
        ("The malformed output contained one </invoke> tag.", False),
        (
            "The docs use `<invoke name=\"Bash\">` and `</invoke>` as examples.",
            False,
        ),
        (
            "Documentation example:\n```xml\n<function_calls>\n"
            '<invoke name="Bash"><parameter name="cmd">pwd</parameter></invoke>\n'
            "```",
            False,
        ),
    ]

    page = dashboard_browser.new_page()
    page.set_content('<div id="message"></div>')
    page.add_style_tag(
        path=str(
            Path(__file__).parent.parent / "app/static/css/style.css"
        )
    )
    page.add_script_tag(content=guard_code)
    transcript_code = (
        "function _saCollapsible"
        + source.split("function _saCollapsible", 1)[1].split(
            "function renderTasksPanel", 1,
        )[0]
    )
    page.add_script_tag(
        content="""
            function _escHtml(text) {
                const node = document.createElement('div');
                node.textContent = text;
                return node.innerHTML;
            }
        """ + transcript_code
    )
    browser_results = page.evaluate(
        "(cases) => cases.map(([text]) => _looksLikeUnexecutedToolCall(text))",
        cases,
    )

    assert browser_results == [expected for _, expected in cases]
    assert browser_results == [
        looks_like_unexecuted_tool_call(text) for text, _ in cases
    ]

    page.evaluate(
        """text => {
            const message = document.querySelector('#message');
            message.textContent = text;
            _markUnexecutedToolCall(message, text);
            _markUnexecutedToolCall(message, text);
        }""",
        cases[1][0],
    )
    warning = page.locator(".unexecuted-tool-call-warning")
    expect(warning).to_have_count(1)
    expect(warning).to_contain_text("НЕ ВЫПОЛНЕНО")
    expect(warning).to_contain_text("напечатанный текстом")
    assert warning.evaluate(
        "(el) => getComputedStyle(el).borderLeftWidth"
    ) == "3px"

    page.evaluate(
        """text => {
            const message = document.querySelector('#message');
            _markUnexecutedToolCall(message, text);
        }""",
        cases[2][0],
    )
    expect(warning).to_have_count(0)

    page.evaluate(
        """() => {
            document.querySelector('#message').innerHTML = _renderTranscriptMsg({
                type: 'assistant',
                content: [
                    {type: 'text', text: 'câ</parameter>'},
                    {type: 'text', text: '</invoke>'},
                ],
            });
        }"""
    )
    expect(warning).to_have_count(1)

    assert "_markUnexecutedToolCall(streamBubble, streamContent);" in source
    assert "_markUnexecutedToolCall(streamBubble, finalText);" in source
    assert "_markUnexecutedToolCall(div, content);" in source
    assert "c.filter(block => block?.type === 'text')" in source
    page.close()


_PINNED_ORCH_TAB = "task197-pinned-orch"


def test_header_has_orch_tabs(dashboard_browser: Browser):
    """Вкладки шапки рисуются из /api/orchestrators, не из шаблона.

    Пустой ``#orch-tabs`` — flex без padding, bounding box 0×0, и Playwright
    считает его невидимым. ``to_be_visible()`` на контейнере поэтому зеленеет
    только когда живой сервер уже успел прислать оркестраторов — в полном
    прогоне тот же запрос тормозит или падает в пустой ``catch {}``, и тест
    краснеет (#185, #187, #197). Пиним ответ: живая БД больше не участвует.
    """
    page = dashboard_browser.new_page()
    pinned = [{
        "id": "sess-task197",
        "name": _PINNED_ORCH_TAB,
        "scope": "/tmp/task197-pinned",
        "status": "idle",
        "any_running": False,
        "any_waiting": False,
    }]

    def orch_list(route):
        url = route.request.url.split("?", 1)[0].rstrip("/")
        if route.request.method == "GET" and url.endswith("/api/orchestrators"):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(pinned),
            )
            return
        route.fallback()

    page.route(re.compile(r"/api/orchestrators(?:\?|$)"), orch_list)
    try:
        _goto_dashboard(page)
        tab = page.locator(f'#orch-tabs .orch-tab[data-orch-name="{_PINNED_ORCH_TAB}"]')
        expect(tab).to_be_visible()
        expect(tab).to_contain_text(_PINNED_ORCH_TAB)
    finally:
        page.close()


def test_orchestrator_unread_tracks_own_turn_only(dashboard_browser: Browser):
    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
    assert source.count("_unreadTabs.add(") == 1
    assert source.count("className = 'tab-unread'") == 1
    assert "_orchestratorTurnFinished(existing, fo)" in source

    def function_source(name):
        marker = f"function {name}"
        return marker + source.split(marker, 1)[1].split("\n}\n", 1)[0] + "\n}"

    page = dashboard_browser.new_page()
    page.set_content("<div id='tab'></div>")
    page.add_script_tag(content="\n".join([
        "const _unreadTabs = new Set();",
        function_source("_orchestratorTurnFinished"),
        function_source("_syncUnreadDot"),
    ]))

    result = page.evaluate("""() => {
        const workerFinished = _orchestratorTurnFinished(
            {status: 'idle', any_running: true},
            {status: 'idle', any_running: false},
        );
        const orchestratorFinished = _orchestratorTurnFinished(
            {status: 'running', any_running: true},
            {status: 'idle', any_running: true},
        );
        const tab = document.getElementById('tab');
        _syncUnreadDot(tab, '/foreign');
        const before = tab.querySelectorAll('.tab-unread').length;
        _unreadTabs.add('/foreign');
        _syncUnreadDot(tab, '/foreign');
        _syncUnreadDot(tab, '/foreign');
        const afterAdd = tab.querySelectorAll('.tab-unread').length;
        _unreadTabs.delete('/foreign');
        _syncUnreadDot(tab, '/foreign');
        const afterDelete = tab.querySelectorAll('.tab-unread').length;
        return {workerFinished, orchestratorFinished, before, afterAdd, afterDelete};
    }""")
    page.close()

    assert result == {
        "workerFinished": False,
        "orchestratorFinished": True,
        "before": 0,
        "afterAdd": 1,
        "afterDelete": 0,
    }


def test_json_preview_keeps_long_numbers_verbatim(dashboard_browser: Browser):
    """#136: просмотр .json не должен округлять целые больше 2^53."""
    utils = (Path(__file__).parent.parent / "app/static/js/utils.js").read_text()
    pretty = "function _prettyJsonText" + utils.split(
        "function _prettyJsonText", 1,
    )[1].split("\nmarked.setOptions", 1)[0]
    app = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
    # просмотрщик обязан звать форматтер текста, а не пересобирать разобранный объект
    assert "pretty = _prettyJsonText(raw)" in app
    assert "JSON.stringify(JSON.parse(raw)" not in app

    raw = '{"id": 1917704623170653147, "a": [1.0, {}, []], "s": "\\"x\\""}'
    page = dashboard_browser.new_page()
    page.set_content("<div></div>")
    page.add_script_tag(content=pretty)
    shown = page.evaluate("raw => _prettyJsonText(raw)", raw)
    page.close()

    assert "1917704623170653147" in shown
    assert shown == (
        '{\n  "id": 1917704623170653147,\n  "a": [\n    1.0,\n    {},\n    []\n  ],'
        '\n  "s": "\\"x\\""\n}'
    )


def test_dropped_path_lands_at_caret_not_at_end(dashboard_browser: Browser):
    """#94: юзер печатал в середине — путь обязан встать туда, а не в конец."""
    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
    insert_code = "function _insertPathAtCaret" + source.split(
        "function _insertPathAtCaret", 1,
    )[1].split("\nasync function _handleChatDrop", 1)[0]

    page = dashboard_browser.new_page()
    page.set_content('<textarea id="chat-input"></textarea>')
    page.add_script_tag(content=f"""
        let pastedImages = [];
        function showImagePreview() {{}}
        {insert_code}
        window.insert = (text, start, end) => {{
            const i = document.querySelector('#chat-input');
            i.value = text; i.focus(); i.setSelectionRange(start, end ?? start);
            _insertPathAtCaret(i, '/tmp/pic.png', '/tmp/pic.png');
            return {{value: i.value, start: i.selectionStart, end: i.selectionEnd}};
        }};
    """)
    middle = page.evaluate("() => insert('посмотри сюда', 9)")
    selection = page.evaluate("() => insert('убери это слово', 6, 9)")
    empty = page.evaluate("() => insert('', 0)")
    tail = page.evaluate("() => insert('хвост', 5)")
    page.close()

    assert middle["value"] == "посмотри \n/tmp/pic.png\nсюда"
    # каретка сразу после пути — юзер дописывает ПОСЛЕ него, а не перед
    assert middle["start"] == middle["end"] == len("посмотри \n/tmp/pic.png")
    assert selection["value"] == "убери \n/tmp/pic.png\n слово"
    assert empty["value"] == "/tmp/pic.png"
    assert tail["value"] == "хвост\n/tmp/pic.png"


def test_chat_drop_handles_files_tree_paths_and_upload_errors(
    dashboard_browser: Browser,
):
    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
    assert "function initChatDrop()" in source
    assert source.index("initChatDrop();") < source.index("loadOrchestrators();")
    assert "fileDropReady" not in source
    drop_code = "let _dropDragCounter = 0;" + source.split(
        "let _dropDragCounter = 0;", 1,
    )[1].split("function initTabContextMenu", 1)[0]
    # Срез содержит ВЫЗОВЫ _trackUpload/_uploadToChat, а их определения лежат
    # ниже по файлу — страница падала на "_trackUpload is not defined".
    # Берём настоящий блок загрузки, а не заглушки: заглушка спрятала бы
    # регрессию внутри него.
    upload_helpers = "const _pendingUploads = new Set();" + source.split(
        "const _pendingUploads = new Set();", 1,
    )[1].split("const _COMPRESS_MIN_BYTES", 1)[0]
    drop_code = upload_helpers + drop_code

    page = dashboard_browser.new_page()
    page.set_content("""
        <base href="http://orchestra.test/">
        <div id="input-shell">
            <div id="input-row">
                <textarea id="chat-input" placeholder="Message..."></textarea>
            </div>
        </div>
    """)

    def upload(route):
        body = route.request.post_data or ""
        match = re.search(r'filename="([^"]+)"', body)
        name = match.group(1) if match else "unknown"
        if name == "blocked.py":
            route.fulfill(
                status=400,
                content_type="application/json",
                body='{"error":"file type .py not allowed"}',
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=f'{{"path":"/tmp/{name}","url":"/uploads/{name}"}}',
        )

    page.route("**/api/upload", upload)
    page.add_script_tag(content=f"""
        const $ = selector => document.querySelector(selector);
        let pastedImages = [];
        const previewPaths = [];
        function showImagePreview(url, path) {{ previewPaths.push({{url, path}}); }}
        {drop_code}
        initChatDrop();
        window.testDrop = async (names, path = '') => {{
            const input = $('#chat-input');
            input.value = '';
            const dt = new DataTransfer();
            for (const name of names) {{
                dt.items.add(new File([`body:${{name}}`], name, {{type: 'text/plain'}}));
            }}
            if (path) dt.setData('text/plain', path);
            input.dispatchEvent(new DragEvent(
                'dragenter',
                {{bubbles: true, cancelable: true, dataTransfer: dt}},
            ));
            const hinted = input.placeholder;
            const over = new DragEvent(
                'dragover',
                {{bubbles: true, cancelable: true, dataTransfer: dt}},
            );
            input.dispatchEvent(over);
            const drop = new DragEvent(
                'drop',
                {{bubbles: true, cancelable: true, dataTransfer: dt}},
            );
            input.dispatchEvent(drop);
            // Аплоады идут ПОСЛЕДОВАТЕЛЬНО, и фиксированные 100 мс под нагрузкой
            // не покрывали поздний — тест терял его путь (#105: 3 красных из 9 ещё
            // до #94). Ждём УСЛОВИЕ: каждый файл либо дал путь, либо назван в ошибке.
            // Дедлайн — только страховка от зависания, не мерка скорости.
            const settled = () => names.every(name =>
                input.value.includes(`/tmp/${{name}}`)
                || ($('#chat-drop-error')?.textContent || '').includes(name));
            const deadline = Date.now() + 10000;
            while (!settled() && Date.now() < deadline) {{
                await new Promise(resolve => setTimeout(resolve, 10));
            }}
            return {{
                value: input.value,
                hinted,
                overPrevented: over.defaultPrevented,
                dropPrevented: drop.defaultPrevented,
                error: document.querySelector('#chat-drop-error')?.textContent || '',
            }};
        }};
    """)

    outside = page.evaluate("""() => {
        const dt = new DataTransfer();
        dt.items.add(new File(['body'], 'outside.txt', {type: 'text/plain'}));
        document.body.dispatchEvent(new DragEvent(
            'dragenter',
            {bubbles: true, cancelable: true, dataTransfer: dt},
        ));
        const over = new DragEvent(
            'dragover',
            {bubbles: true, cancelable: true, dataTransfer: dt},
        );
        document.body.dispatchEvent(over);
        const drop = new DragEvent(
            'drop',
            {bubbles: true, cancelable: true, dataTransfer: dt},
        );
        document.body.dispatchEvent(drop);
        return {
            placeholder: document.querySelector('#chat-input').placeholder,
            overPrevented: over.defaultPrevented,
            dropPrevented: drop.defaultPrevented,
        };
    }""")
    single = page.evaluate("() => testDrop(['one.txt'])")
    multi = page.evaluate("() => testDrop(['first.txt', 'second.txt'])")
    tree = page.evaluate("() => testDrop([], '/project/from-tree.md')")
    partial_failure = page.evaluate(
        "() => testDrop(['ok.txt', 'blocked.py', 'tail.txt'])",
    )
    page.close()

    assert outside == {
        "placeholder": "Message...",
        "overPrevented": True,
        "dropPrevented": True,
    }
    assert single == {
        "value": "/tmp/one.txt",
        "hinted": "📎 Drop files here",
        "overPrevented": True,
        "dropPrevented": True,
        "error": "",
    }
    assert multi["value"] == "/tmp/first.txt\n/tmp/second.txt"
    assert tree["value"] == "/project/from-tree.md"
    assert partial_failure["value"] == "/tmp/ok.txt\n/tmp/tail.txt"
    # Интент — юзеру названы ФАЙЛ и ПРИЧИНА. Дословная склейка не проверяется:
    # сообщение обросло классом исключения ("Error:"), что как раз соответствует
    # нашему правилу «показывать класс ошибки», и смысл не поменялся.
    assert "blocked.py" in partial_failure["error"]
    assert "file type .py not allowed" in partial_failure["error"]


def test_left_panel_has_tabs(dashboard_page: Page):
    files_tab = dashboard_page.locator('[data-left-tab="files"]')
    tasks_tab = dashboard_page.locator('[data-left-tab="tasks"]')
    jobs_tab = dashboard_page.locator('[data-left-tab="jobs"]')
    expect(files_tab).to_be_visible()
    expect(tasks_tab).to_be_visible()
    expect(jobs_tab).to_be_visible()


def test_agent_info_panel_exists(dashboard_page: Page):
    info = dashboard_page.locator("#agent-info")
    expect(info).to_be_visible()


def test_no_js_errors(dashboard_browser: Browser):
    errors = []
    page = dashboard_browser.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    _goto_dashboard(page)
    expect(page.locator("#agent-list")).to_be_visible()
    page.wait_for_timeout(2000)
    page.close()
    assert len(errors) == 0, f"JS errors on page: {errors}"


def _load_cache_pill_code(page: Page):
    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
    block = "function _cachePillState" + source.split(
        "function _cachePillState", 1,
    )[1].split("// Client-side countdown", 1)[0]
    page.set_content("<body></body>")
    page.add_script_tag(content=block)


def test_codex_cache_pill_is_approximate_and_expires_to_unknown(
    dashboard_browser: Browser,
):
    page = dashboard_browser.new_page()
    _load_cache_pill_code(page)
    states = page.evaluate("""() => {
        const snapshot = (pill) => pill && ({
            text: pill.textContent,
            tier: pill.dataset.tier,
            title: pill.title,
            approximate: pill.dataset.cacheApproximate,
        });
        const recent = new Date(Date.now() - 5 * 60000).toISOString();
        const expired = new Date(Date.now() - 37 * 60000).toISOString();
        return {
            running: snapshot(_cachePill({
                status: 'running',
                cache_ttl_seconds: 1800,
                cache_ttl_approximate: true,
            })),
            recent: snapshot(_cachePill({
                status: 'idle',
                last_turn_ts: recent,
                cache_ttl_seconds: 1800,
                cache_ttl_approximate: true,
            })),
            expired: snapshot(_cachePill({
                status: 'idle',
                last_turn_ts: expired,
                cache_ttl_seconds: 1800,
                cache_ttl_approximate: true,
            })),
            invalidTtl: _cachePill({
                status: 'idle',
                last_turn_ts: recent,
                cache_ttl_seconds: 0,
                cache_ttl_approximate: true,
            }),
            missingTurn: _cachePill({
                status: 'idle',
                cache_ttl_seconds: 1800,
                cache_ttl_approximate: true,
            }),
            malformedTurn: _cachePill({
                status: 'idle',
                last_turn_ts: 'not-a-date',
                cache_ttl_seconds: 1800,
                cache_ttl_approximate: true,
            }),
        };
    }""")
    page.close()

    assert states["running"]["text"] == "🔥≈"
    assert states["recent"]["text"].startswith("🔥≈")
    assert states["recent"]["approximate"] == "1"
    assert states["expired"]["text"] == "🧊? +7m"
    assert states["expired"]["tier"] == "unknown"
    assert "7m past" in states["expired"]["title"]
    assert "not guaranteed" in states["expired"]["title"]
    assert states["invalidTtl"] is None
    assert states["missingTurn"] is None
    assert states["malformedTurn"] is None


def test_claude_cache_pill_keeps_exact_thresholds(dashboard_browser: Browser):
    page = dashboard_browser.new_page()
    _load_cache_pill_code(page)
    states = page.evaluate("""() => {
        const stateAt = (minutesAgo) => {
            const pill = _cachePill({
                status: 'idle',
                last_turn_ts: new Date(Date.now() - minutesAgo * 60000).toISOString(),
                cache_ttl_seconds: 3600,
                cache_ttl_approximate: false,
            });
            return {text: pill.textContent, tier: pill.dataset.tier, title: pill.title};
        };
        return {
            hot: stateAt(20),
            warm: stateAt(45),
            cooling: stateAt(49),
            cold: stateAt(61),
        };
    }""")
    page.close()

    assert states["hot"]["tier"] == "hot"
    assert states["warm"]["tier"] == "warm"
    assert states["cooling"]["tier"] == "cooling"
    assert states["cold"] == {
        "text": "🧊",
        "tier": "cold",
        "title": "Cache cold — next turn ~20× дороже",
    }


def _open_tool_fixture_page(browser: Browser) -> Page:
    page = browser.new_page()
    _goto_dashboard(page)
    expect(page.locator("#chat")).to_be_visible()
    page.wait_for_function(
        "() => typeof selectedAgent !== 'undefined' && selectedAgent !== null"
    )
    page.evaluate("""() => {
        selectedAgent = null;
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
        window.compactMode = false;
        document.querySelector('#chat').innerHTML = '';
    }""")
    return page


def _route_frontend_sources(page: Page, source_path: Path | None = None) -> None:
    """Живой сервер отдаёт статику из ГЛАВНОГО чекаута — подменяем её своей.

    Стиль подменяем НАРАВНЕ со скриптом: иначе проверка внешнего вида зеленела бы
    на main, а не на ветке.
    """
    source = (
        source_path or Path(__file__).parent.parent / "app/static/js/app.js"
    ).read_text()
    page.route(
        "**/static/js/app.js*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/javascript",
            body=source,
        ),
    )
    style = (Path(__file__).parent.parent / "app/static/css/style.css").read_text()
    page.route(
        "**/static/css/style.css*",
        lambda route: route.fulfill(status=200, content_type="text/css", body=style),
    )


def _open_tool_correlation_page(
    browser: Browser,
    compact_mode: bool,
    source_path: Path | None = None,
) -> Page:
    page = browser.new_page()
    _route_frontend_sources(page, source_path)
    _goto_dashboard(page)
    page.wait_for_function("() => typeof addChatEntry === 'function'")
    page.evaluate("""compactMode => {
        selectedAgent = null;
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
        window.compactMode = compactMode;
        document.querySelector('#chat').innerHTML = '';
    }""", compact_mode)
    return page


@pytest.mark.parametrize("compact_mode", [False, True], ids=["normal", "compact"])
def test_parallel_tool_results_follow_tool_use_id_in_both_renderers(
    dashboard_browser: Browser,
    compact_mode: bool,
):
    source_override = os.environ.get("ORCHESTRA_TOOL_CORRELATION_SOURCE")
    source_path = Path(source_override) if source_override else None
    page = _open_tool_correlation_page(dashboard_browser, compact_mode, source_path)
    result_by_id = page.evaluate("""() => {
        const calls = [
            ['mcp__orchestra__task_create', {title:'CALL-A'} , 'parallel-a', 26001],
            ['mcp__orchestra__list_agents', {}, 'parallel-b', 26002],
            ['mcp__orchestra__worker_wip', {name:'CALL-C'}, 'parallel-c', 26003],
        ];
        for (const [name, args, toolUseId, id] of calls) {
            addChatEntry('tool', `${name}: ${JSON.stringify(args)}`, null, null,
                {id, tool_use_id:toolUseId});
        }

        // A real parallel block logs every call before any result. Results may
        // then finish in a different order; each marker deliberately differs.
        for (const [toolUseId, marker, id] of [
            ['parallel-c', 'RESULT-ONLY-C', 26006],
            ['parallel-a', 'RESULT-ONLY-A', 26004],
            ['parallel-b', 'RESULT-ONLY-B', 26005],
        ]) {
            addChatEntry('tool_result', marker, null, null, {id, tool_use_id:toolUseId});
        }
        const selector = window.compactMode ? '[data-compact-tool]' : '[data-tool-use-id]:not([data-compact-tool])';
        return Object.fromEntries([...document.querySelectorAll(`#chat ${selector}`)]
            .map(card => [
                card.dataset.toolUseId,
                window.compactMode ? card.dataset.resultContent || '' : card.innerText,
            ]));
    }""")
    page.close()

    assert set(result_by_id) == {"parallel-a", "parallel-b", "parallel-c"}
    for tool_use_id, marker in {
        "parallel-a": "RESULT-ONLY-A",
        "parallel-b": "RESULT-ONLY-B",
        "parallel-c": "RESULT-ONLY-C",
    }.items():
        assert marker in result_by_id[tool_use_id]
        assert not any(
            other in result_by_id[tool_use_id]
            for other in {"RESULT-ONLY-A", "RESULT-ONLY-B", "RESULT-ONLY-C"}
            if other != marker
        )


# Формы идентификатора, реально встречающиеся в журнале: Claude/MCP пишет `toolu_*`,
# Codex и Luna — `exec-<uuid>`, а у нативных Codex-событий он приходит только внутри
# тела вызова как `_codex_item_id`.
_TOOL_ID_FORMS = [
    ("claude", "toolu_01G5brx7JCG8nwANkQmhc6eF", False),
    ("codex_column", "exec-58a05905-8ec3-4b60-8ef8-b62fd6da3f42", False),
    ("codex_item_id_in_body", "exec-f47f37ef-c04d-44af-ac6a-2e5a3ebcc0ef", True),
]


@pytest.mark.parametrize("compact_mode", [False, True], ids=["normal", "compact"])
@pytest.mark.parametrize(
    ("id_form", "base_id", "id_only_in_body"),
    _TOOL_ID_FORMS,
    ids=[form[0] for form in _TOOL_ID_FORMS],
)
def test_split_history_page_pairs_results_with_calls_that_arrive_later(
    dashboard_browser: Browser,
    compact_mode: bool,
    id_form: str,
    base_id: str,
    id_only_in_body: bool,
):
    """История приезжает страницами и разрезает параллельный блок.

    Результаты нарисованы более новой страницей, а их вызовы приходят следующей,
    более старой — то есть ПОЗЖЕ и с якорем. Живой замер #260: `cardInDom: false`,
    `hasAnchor: true` — вызова в DOM ещё нет, и exact-only оставлял вечную сироту.
    """
    page = _open_tool_correlation_page(dashboard_browser, compact_mode)
    rendered = page.evaluate(
        """({baseId, idOnlyInBody}) => {
        const chat = document.querySelector('#chat');
        const idA = baseId + '-a';
        const idB = baseId + '-b';

        // Новая страница: два результата параллельного блока, вызовов ещё нет.
        addChatEntry('tool_result', 'SPLIT-RESULT-A', null, null, {id:31003, tool_use_id:idA});
        addChatEntry('tool_result', 'SPLIT-RESULT-B', null, null, {id:31004, tool_use_id:idB});
        const orphansBefore = chat.querySelectorAll('[data-unmatched-tool-result]').length;

        // Следующая, более СТАРАЯ страница дорисовывается НАД показанным.
        const anchor = chat.firstElementChild;
        for (const [name, marker, id, logId] of [
            ['mcp__orchestra__worker_wip', 'CALL-A', idA, 31001],
            ['mcp__orchestra__worker_wip', 'CALL-B', idB, 31002],
        ]) {
            const args = idOnlyInBody
                ? {name: marker, _codex_item_id: id}
                : {name: marker};
            const payload = idOnlyInBody ? {id: logId} : {id: logId, tool_use_id: id};
            addChatEntry('tool', `${name}: ${JSON.stringify(args)}`, null, anchor, payload);
        }

        const sel = window.compactMode
            ? '[data-compact-tool]'
            : '[data-tool-use-id]:not([data-compact-tool])';
        const cards = Object.fromEntries([...chat.querySelectorAll(sel)].map(card => [
            card.dataset.toolUseId,
            window.compactMode ? (card.dataset.resultContent || '') : card.innerText,
        ]));
        return {
            orphansBefore,
            orphansAfter: chat.querySelectorAll('[data-unmatched-tool-result]').length,
            cards,
            idA,
            idB,
        };
    }""",
        {"baseId": base_id, "idOnlyInBody": id_only_in_body},
    )
    page.close()

    assert rendered["orphansBefore"] == 2, "результаты без вызова обязаны быть видны сразу"
    assert rendered["orphansAfter"] == 0, "приехавший вызов обязан забрать свою сироту"
    cards = rendered["cards"]
    assert set(cards) == {rendered["idA"], rendered["idB"]}
    assert "SPLIT-RESULT-A" in cards[rendered["idA"]]
    assert "SPLIT-RESULT-B" not in cards[rendered["idA"]]
    assert "SPLIT-RESULT-B" in cards[rendered["idB"]]
    assert "SPLIT-RESULT-A" not in cards[rendered["idB"]]


@pytest.mark.parametrize("compact_mode", [False, True], ids=["normal", "compact"])
def test_notify_user_call_is_highlighted_and_navigable_from_the_timeline(
    dashboard_browser: Browser,
    compact_mode: bool,
):
    """#241: оркестратор зовёт юзера только `notify_user`, и это надо находить глазами.

    Форма строки — контракт `back`: обычный вызов тула, без новых полей и без нового API.
    """
    page = _open_tool_correlation_page(dashboard_browser, compact_mode)
    reason = "кеш падает 93.6% → 15%"
    page.evaluate(
        """reason => {
        // Рядом идёт обычная пара вызов/результат: подсветка не должна её задеть.
        addChatEntry('tool', 'Bash: {"command":"echo NEIGHBOUR"}', null, null,
            {id:33001, tool_use_id:'toolu_neighbour'});
        addChatEntry('tool_result', 'NEIGHBOUR-RESULT', null, null,
            {id:33002, tool_use_id:'toolu_neighbour'});
        addChatEntry(
            'tool',
            `mcp__orchestra__notify_user: ${JSON.stringify({reason})}`,
            '2026-08-13T12:00:00+00:00',
            null,
            {id:33003, tool_use_id:'toolu_notify241'},
        );
    }""",
        reason,
    )
    # Свой потолок с диагнозом: без него пропажа зова из списка падает молчаливым
    # 30-секундным таймаутом и не говорит, ЧТО именно сломалось.
    try:
        page.wait_for_function(
            "() => document.querySelector('#chat-notify-count')?.textContent === '🔔 1'",
            timeout=5000,
        )
    except PlaywrightTimeout:
        actual = page.evaluate(
            "() => [document.querySelector('#chat-notify-count')?.textContent,"
            " document.querySelectorAll('#chat-timeline-track .is-notify').length]"
        )
        page.close()
        pytest.fail(f"зов не попал в список: счётчик={actual[0]!r}, меток={actual[1]}")

    state = page.evaluate("""() => {
        const chat = document.querySelector('#chat');
        const card = chat.querySelector('[data-tool-use-id="toolu_notify241"]');
        const neighbour = chat.querySelector('[data-tool-use-id="toolu_neighbour"]');
        const marker = document.querySelector('#chat-timeline-track .is-notify');
        const nav = document.querySelector('#chat-notify-nav');
        const styles = getComputedStyle(card);
        return {
            cardHighlighted: card.classList.contains('chat-notify-user'),
            cardBorder: styles.borderLeftColor,
            cardText: card.innerText,
            navKind: card.dataset.chatNavKind,
            navLabel: card.dataset.chatNavLabel,
            markers: document.querySelectorAll('#chat-timeline-track .is-notify').length,
            markerTitle: marker?.title || '',
            navHidden: nav.classList.contains('hidden'),
            navDisabled: document.querySelector('#chat-notify-next').disabled,
            neighbourText: neighbour.innerText,
            neighbourHighlighted: neighbour.classList.contains('chat-notify-user'),
            orphans: chat.querySelectorAll('[data-unmatched-tool-result]').length,
        };
    }""")

    assert state["cardHighlighted"], "зов обязан быть выделен в потоке"
    assert state["cardBorder"] == "rgb(239, 68, 68)", state["cardBorder"]
    assert reason in state["cardText"], state["cardText"]
    assert '{"reason"' not in state["cardText"], "сырой JSON юзеру не нужен"
    if compact_mode:
        assert "🔔" in state["cardText"], state["cardText"]
    else:
        # В обычном режиме сырое имя тула заменено человеческой подписью.
        assert "Оркестратор зовёт" in state["cardText"], state["cardText"]
        assert "notify_user" not in state["cardText"], state["cardText"]

    # Список: своя метка на дорожке, счётчик и работающая навигация.
    assert state["navKind"] == "notify"
    assert state["markers"] == 1
    assert reason in state["navLabel"] and reason in state["markerTitle"]
    assert state["navHidden"] is False
    assert state["navDisabled"] is False

    # Соседняя пара цела — корреляция важнее подсветки.
    assert "NEIGHBOUR-RESULT" in state["neighbourText"]
    assert state["neighbourHighlighted"] is False
    assert state["orphans"] == 0

    page.click("#chat-notify-next")
    jumped = page.evaluate("""() => {
        const marker = document.querySelector('#chat-timeline-track .is-notify');
        const card = document.querySelector('#chat [data-tool-use-id="toolu_notify241"]');
        const box = card.getBoundingClientRect();
        const chatBox = document.querySelector('#chat').getBoundingClientRect();
        return {
            active: marker.classList.contains('is-active'),
            inView: box.top < chatBox.bottom && box.bottom > chatBox.top,
        };
    }""")
    page.close()
    assert jumped["active"], "клик по навигации обязан подсветить метку"
    assert jumped["inView"], "клик обязан привести зов во вьюпорт"


@pytest.mark.parametrize("compact_mode", [False, True], ids=["normal", "compact"])
def test_notify_nav_hides_itself_when_no_calls_are_present(dashboard_browser: Browser, compact_mode: bool):
    page = _open_tool_correlation_page(dashboard_browser, compact_mode)
    page.evaluate("""() => {
        addChatEntry('tool', 'Bash: {"command":"echo PLAIN"}', null, null, {id:34001, tool_use_id:'toolu_plain'});
    }""")
    page.wait_for_function("() => document.querySelector('#chat-timeline-track')?.children.length >= 1")
    state = page.evaluate("""() => ({
        navHidden: document.querySelector('#chat-notify-nav').classList.contains('hidden'),
        count: document.querySelector('#chat-notify-count').textContent,
        markers: document.querySelectorAll('#chat-timeline-track .is-notify').length,
    })""")
    page.close()
    assert state["navHidden"] is True, "без зовов полоса навигации занимала бы место впустую"
    assert state["count"] == "🔔 0"
    assert state["markers"] == 0


# Дословный отказ сервера на время перезапуска: `mutating_admission_verdict`, app/main.py:138.
_RESTART_REFUSAL = {
    "error": {
        "allowed": False,
        "retryable": True,
        "outcome_unknown": False,
        "code": "restart_pending",
        "message": "Orchestra is restarting; this call was refused before any side effect.",
    }
}


def _open_restart_page(browser: Browser) -> tuple[Page, dict]:
    """Дашборд с управляемыми ответами API.

    `send_refused` — отказ `restart_pending` на отправку; `server_down` — сервис ушёл
    (это делает перезапуск, и уходит он для ВСЕХ запросов сразу, а не только для одного
    маршрута: `_onServerOk` из соседнего успешного ответа обнуляет счётчик отказов и
    оверлей не появляется вовсе — поймано первым прогоном); `restart_header` — заголовок
    серверной части #269.
    """
    page = browser.new_page()
    _route_frontend_sources(page)
    state = {"send_refused": True, "server_down": False, "restart_header": None}

    def api_route(route):
        url = route.request.url
        if state["server_down"]:
            route.fulfill(status=502, content_type="text/plain", body="bad gateway")
            return
        if re.search(r"/api/sessions/[^/]+/send", url):
            if state["send_refused"]:
                route.fulfill(status=503, content_type="application/json",
                              body=json.dumps(_RESTART_REFUSAL))
            else:
                route.fulfill(status=200, content_type="application/json",
                              body='{"ok": true}')
            return
        if url.split("?")[0].endswith("/api/models") and state["restart_header"] is not None:
            response = route.fetch()
            headers = dict(response.headers)
            headers["X-Orchestra-Restarting"] = state["restart_header"]
            route.fulfill(response=response, headers=headers)
            return
        route.continue_()

    page.route(re.compile(r"/api/"), api_route)
    _goto_dashboard(page)
    page.wait_for_function("() => typeof sendChat === 'function' && selectedAgent")
    return page, state


def test_restart_refusal_pauses_sending_and_lifts_itself_when_service_returns(
    dashboard_browser: Browser,
):
    """#270: перезапуск — штатная операция, а выглядел он сырым JSON в чате.

    Юзер написал «ау» и получил `503: {"error":{...,"code":"restart_pending",...}}`.
    Сервер во время перезапуска ЖИВ и отвечает на чтения, поэтому оверлея не было вовсе,
    а страница молча немела.
    """
    page, state = _open_restart_page(dashboard_browser)
    page.fill("#chat-input", "ау")
    page.click("#send-btn")
    page.wait_for_selector("#restart-banner:not(.hidden)", timeout=10000)
    paused = page.evaluate("""() => ({
        banner: document.querySelector('#restart-banner').textContent,
        btnDisabled: document.querySelector('#send-btn').disabled,
        inputDisabled: document.querySelector('#chat-input').disabled,
        placeholder: document.querySelector('#chat-input').placeholder,
        // Только СВОЙ узел: в живой истории агента уже лежит сырой JSON того самого
        // инцидента, ради которого задача и заведена — по всему чату проверка врала бы.
        refusal: [...document.querySelectorAll('#chat > *')].reverse()
            .find(node => node.innerText.includes('Orchestra перезапускается'))?.innerText || '',
        overlay: !!_rebootOverlay,
    })""")

    # Перезапуск идёт: сервис ушёл, затем вернулся. Ничего руками не делаем.
    state["send_refused"] = False
    state["server_down"] = True
    page.wait_for_function("() => !!_rebootOverlay", timeout=20000)
    state["server_down"] = False
    page.wait_for_function(
        "() => document.querySelector('#restart-banner').classList.contains('hidden')",
        timeout=20000,
    )
    # Поток поднимается ПОСЛЕ дозагрузки истории, то есть позже снятия полосы: ждём
    # положительный признак, а не отсутствие незавершённой работы.
    page.wait_for_function("() => !!eventSource", timeout=20000)
    back = page.evaluate("""() => ({
        overlay: !!_rebootOverlay,
        btnDisabled: document.querySelector('#send-btn').disabled,
        inputDisabled: document.querySelector('#chat-input').disabled,
        streamOpen: !!eventSource,
    })""")
    page.close()

    assert "перезапускается" in paused["banner"], paused["banner"]
    assert paused["btnDisabled"] is True, "отправка всё равно будет отклонена"
    assert paused["inputDisabled"] is True
    assert "перезапуск" in paused["placeholder"].lower(), paused["placeholder"]
    assert paused["refusal"], "отказ обязан быть виден в чате человеческим текстом"
    assert "restart_pending" not in paused["refusal"], paused["refusal"]
    assert '{"error"' not in paused["refusal"], paused["refusal"]
    assert "503" not in paused["refusal"], paused["refusal"]
    assert paused["overlay"] is False, "сервер ещё отвечает — оверлей «сервер ушёл» тут врал бы"

    assert back["overlay"] is False, "сервис вернулся — оверлей обязан сняться сам"
    assert back["btnDisabled"] is False, "после возврата отправка обязана ожить без перезагрузки"
    assert back["inputDisabled"] is False
    assert back["streamOpen"] is True, "поток событий обязан быть переподключён"


def test_restart_header_raises_and_lowers_the_pause_without_any_user_action(
    dashboard_browser: Browser,
):
    """Заголовок серверной части #269 (`X-Orchestra-Restarting`) — признак в обе стороны.

    Он приезжает на существующем heartbeat, своего опроса не заводим. Пока его нет,
    признаком остаётся 503 из первого теста.
    """
    page, state = _open_restart_page(dashboard_browser)
    state["restart_header"] = "1"
    page.wait_for_selector("#restart-banner:not(.hidden)", timeout=15000)
    up = page.evaluate("() => document.querySelector('#chat-input').disabled")
    state["restart_header"] = "0"
    page.wait_for_function(
        "() => document.querySelector('#restart-banner').classList.contains('hidden')",
        timeout=15000,
    )
    down = page.evaluate("() => document.querySelector('#chat-input').disabled")
    page.close()

    assert up is True, "заголовок '1' обязан остановить отправку без единого клика"
    assert down is False, "заголовок '0' обязан снять паузу"


_NOTIFY_AGENT = "notify-268-probe"
_NOTIFY_SESSION = "sess-268"
_SILENT_TURN_MARKER = "[[ORCHESTRA:SILENT_TURN]]"


def _notify_stub(permission: str) -> str:
    """Подменяем Notification: настоящее системное окно из headless не наблюдаемо."""
    return f"""
    window.__notifications = [];
    window.__permissionRequests = 0;
    class FakeNotification {{
        static permission = '{permission}';
        static requestPermission() {{
            window.__permissionRequests++;
            FakeNotification.permission = 'granted';
            return Promise.resolve('granted');
        }}
        constructor(title, options) {{
            this.title = title;
            this.options = options || {{}};
            window.__notifications.push({{title, body: this.options.body,
                tag: this.options.tag, requireInteraction: !!this.options.requireInteraction}});
        }}
        close() {{}}
    }}
    window.Notification = FakeNotification;
    """


def _notify_row(log_id: int, reason: str) -> dict:
    """Форма строки — контракт `back` из #241: обычный вызов тула, без новых полей."""
    return {
        "id": log_id,
        "type": "tool",
        "content": "mcp__orchestra__notify_user: "
        + json.dumps({"reason": reason}, ensure_ascii=False),
        "ts": "2026-08-13T12:00:00+00:00",
        "session_id": _NOTIFY_SESSION,
        "tool_use_id": f"toolu_call{log_id}",
    }


def _silent_turn_row(log_id: int, row_type: str = "text", content: str | None = None) -> dict:
    return {
        "id": log_id,
        "type": row_type,
        "content": _SILENT_TURN_MARKER if content is None else content,
        "ts": "2026-08-16T12:00:00+00:00",
        "session_id": _NOTIFY_SESSION,
    }


def test_silent_turn_marker_is_hidden_only_when_exact_text_in_history(
    dashboard_browser: Browser,
):
    rows = [
        _silent_turn_row(51001),
        _silent_turn_row(51002, content=f" {_SILENT_TURN_MARKER}"),
        _silent_turn_row(51003, content=f"{_SILENT_TURN_MARKER}\n"),
        _silent_turn_row(51004, content=f"prefix {_SILENT_TURN_MARKER}"),
        _silent_turn_row(51005, content=f"{_SILENT_TURN_MARKER} suffix"),
        _silent_turn_row(51006, content=_SILENT_TURN_MARKER.replace("TURN", "TURN_")),
        _silent_turn_row(51007, "user_message"),
        _silent_turn_row(51008, "error"),
        _silent_turn_row(51009, "status", "turn ended"),
    ]
    page, _ = _open_notify_stream_page(
        dashboard_browser,
        "granted",
        history_rows=rows,
        stream_pages=[[]],
        stable_sse=True,
    )
    try:
        state = page.wait_for_function("""() => {
            const ids = [...document.querySelectorAll('#chat [data-chat-log-id]')]
                .map(node => node.dataset.chatLogId);
            if (!ids.includes('51009')) return false;
            return {markerType: typeof _isSilentTurnMarker, ids,
                lastId: chatLogs['notify-268-probe']?.lastId};
        }""", timeout=8000).json_value()
    finally:
        page.close()

    assert state["markerType"] == "function"
    assert "51001" not in state["ids"], "exact marker must not get a history bubble"
    assert {str(row_id) for row_id in range(51002, 51010)} <= set(state["ids"]), (
        "whitespace, prefix/suffix, underscore, user_message/error, and telemetry rows "
        "must remain visible"
    )
    assert state["lastId"] == 51009, "hidden presentation must not drop history bookkeeping"


def test_silent_turn_marker_is_hidden_from_live_sse_but_telemetry_survives(
    dashboard_browser: Browser,
):
    page, stream_calls = _open_notify_stream_page(
        dashboard_browser,
        "granted",
        history_rows=[],
        stream_pages=[[
            _silent_turn_row(52001),
            _silent_turn_row(52002, content=f" {_SILENT_TURN_MARKER}"),
            _silent_turn_row(52003, "status", "turn ended"),
        ]],
    )
    try:
        state = page.wait_for_function("""() => {
            const ids = [...document.querySelectorAll('#chat [data-chat-log-id]')]
                .map(node => node.dataset.chatLogId);
            if (!ids.includes('52003')) return false;
            return {ids, lastId: chatLogs['notify-268-probe']?.lastId};
        }""", timeout=8000).json_value()
    finally:
        page.close()

    assert stream_calls, "live SSE route must have been exercised"
    assert "52001" not in state["ids"], "exact marker must not get a live bubble"
    assert "52002" in state["ids"], "near-match live text must remain visible"
    assert "52003" in state["ids"], "turn ended telemetry must remain visible"
    assert state["lastId"] == 52003, "SSE cursor must advance across hidden rows"


def test_dashboard_polling_pauses_hidden_and_resumes_after_visibility_and_online(
    dashboard_browser: Browser,
):
    page = dashboard_browser.new_page()
    page.add_init_script("""() => {
        window.EventSource = class StableEventSource {
            constructor(url) { this.url = url; this.readyState = 1; }
            close() { this.readyState = 2; }
        };
    }""")
    _route_frontend_sources(page)
    _goto_dashboard(page)
    page.wait_for_function("() => typeof _pollRegister === 'function'")
    page.evaluate("""() => {
        _pollStop('oracle-301');
        window.__pollHits301 = 0;
        _pollRegister('oracle-301', () => { window.__pollHits301++; }, 30);
    }""")
    try:
        page.wait_for_function("() => window.__pollHits301 >= 2", timeout=5000)
        active_hits = page.evaluate("() => window.__pollHits301")

        page.evaluate("""() => {
            Object.defineProperty(document, 'hidden', {configurable: true, value: true});
            document.dispatchEvent(new Event('visibilitychange'));
            window.__hiddenPollHits301 = 0;
            _pollRegister('hidden-oracle-301', () => { window.__hiddenPollHits301++; }, 30);
        }""")
        page.wait_for_timeout(300)
        hidden_hits = page.evaluate("() => window.__pollHits301")
        hidden_registered_hits = page.evaluate("() => window.__hiddenPollHits301")

        page.evaluate("""() => {
            Object.defineProperty(document, 'hidden', {configurable: true, value: false});
            document.dispatchEvent(new Event('visibilitychange'));
        }""")
        page.wait_for_function(
            f"() => window.__pollHits301 > {hidden_hits}", timeout=5000
        )
        visible_again_hits = page.evaluate("() => window.__pollHits301")

        page.evaluate("""() => {
            Object.defineProperty(navigator, 'onLine', {configurable: true, value: false});
            window.dispatchEvent(new Event('offline'));
        }""")
        page.wait_for_timeout(300)
        offline_hits = page.evaluate("() => window.__pollHits301")

        page.evaluate("""() => {
            Object.defineProperty(navigator, 'onLine', {configurable: true, value: true});
            window.dispatchEvent(new Event('online'));
        }""")
        page.wait_for_function(
            f"() => window.__pollHits301 > {offline_hits}", timeout=5000
        )
    finally:
        page.close()

    assert hidden_hits <= active_hits + 1, "hidden tab must not spend polling ticks"
    assert hidden_registered_hits == 0, "hidden tab must not start a newly registered poller"
    assert visible_again_hits > hidden_hits, "visibility return must resume polling"
    assert offline_hits <= visible_again_hits + 1, "offline browser must pause polling"


def test_dashboard_polling_coalesces_same_inflight_request(
    dashboard_browser: Browser,
):
    page = dashboard_browser.new_page()
    _route_frontend_sources(page)
    _goto_dashboard(page)
    page.wait_for_function("() => typeof _pollCoalesce === 'function'")
    try:
        result = page.evaluate("""async () => {
            window.__coalesceRuns301 = 0;
            const fn = async () => {
                window.__coalesceRuns301++;
                await new Promise(resolve => setTimeout(resolve, 50));
                return 'same-result';
            };
            const [a, b] = await Promise.all([
                _pollCoalesce('oracle-dedup-301', fn),
                _pollCoalesce('oracle-dedup-301', fn),
            ]);
            return {runs: window.__coalesceRuns301, a, b};
        }""")
    finally:
        page.close()

    assert result == {"runs": 1, "a": "same-result", "b": "same-result"}


def test_dashboard_polling_scheduler_coalesces_wake_and_file_failure_backoff(
    dashboard_browser: Browser,
):
    page = dashboard_browser.new_page()
    page.add_init_script("""() => {
        window.EventSource = class StableEventSource {
            constructor(url) { this.url = url; this.readyState = 1; }
            close() { this.readyState = 2; }
        };
    }""")
    _route_frontend_sources(page)
    file_mode = {"value": "ok"}

    def api_route(route):
        path = route.request.url.split("?", 1)[0].split("/api", 1)[-1]
        path = "/api" + path
        if path == "/api/files":
            if file_mode["value"] == "503":
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body=json.dumps({"detail": "temporary file service failure"}),
                )
                return
            if file_mode["value"] == "timeout":
                return
            payload = [{"path": "/tmp/fe-scope/ok.txt", "name": "ok.txt", "is_dir": False}]
        elif path == "/api/orchestrators":
            payload = [{"id": "fe-orch-id", "name": "fe-orch", "scope": "/tmp/fe-scope"}]
        elif path == "/api/sessions":
            payload = [{"id": "fe-orch-id", "name": "fe-orch", "scope": "/tmp/fe-scope", "status": "idle", "model": "claude-opus-5[1m]"}]
        elif path == "/api/stats":
            payload = {"active": 0, "total_sessions": 1, "total_cost_usd": 0}
        elif path == "/api/models":
            payload = {"models": [], "proxy_connected": False}
        elif path.endswith("/stream"):
            route.fulfill(status=200, content_type="text/event-stream", body="")
            return
        elif path.endswith("/logs"):
            payload = []
        elif path.endswith("/context"):
            payload = {"percentage": 0, "total_tokens": 0, "max_tokens": 1}
        elif path == "/api/logs/sync":
            payload = {"logs": [], "max_log_id": 0, "live_sessions": []}
        else:
            payload = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    page.route(re.compile(r"/api/"), api_route)
    _goto_dashboard(page)
    try:
        page.wait_for_function("() => selectedAgent === 'fe-orch'", timeout=8000)
        page.evaluate("""() => {
            _pollStop('scheduler-oracle-301');
            window.__schedulerCalls301 = 0;
            window.__releaseScheduler301 = null;
            _pollRegister('scheduler-oracle-301', () => {
                window.__schedulerCalls301++;
                return new Promise(resolve => { window.__releaseScheduler301 = resolve; });
            }, 30);
        }""")
        page.wait_for_function("() => window.__schedulerCalls301 === 1", timeout=5000)
        page.evaluate("""() => {
            for (let i = 0; i < 8; i++) {
                document.dispatchEvent(new Event('visibilitychange'));
                window.dispatchEvent(new Event('online'));
            }
        }""")
        page.wait_for_timeout(150)
        assert page.evaluate("() => window.__schedulerCalls301") == 1
        page.evaluate("() => window.__releaseScheduler301()")
        page.wait_for_function("() => window.__schedulerCalls301 === 2", timeout=5000)
        page.evaluate("() => _pollStop('scheduler-oracle-301')")

        page.wait_for_function(
            "() => document.querySelector('#file-tree')?.innerText.includes('ok.txt')",
            timeout=5000,
        )
        file_mode["value"] = "503"
        page.evaluate("""() => {
            _pollStop('files');
            _pollRegister('files', refreshOpenFolders, 10000);
        }""")
        page.wait_for_function(
            "() => (_pollFailures.get('files') || 0) > 0", timeout=5000
        )
        file_state = page.evaluate("""() => ({
            failures: _pollFailures.get('files') || 0,
            nextDelay: _pollDelay('files', 10000),
            treeText: document.querySelector('#file-tree')?.innerText || '',
        })""")
        page.evaluate("""() => {
            _pollStop('files');
            _pollFailures.delete('files');
            window.__pollDelays301 = [];
            const nativeSetTimeout = window.setTimeout;
            window.setTimeout = (fn, ms, ...args) => {
                if (ms >= 10000) window.__pollDelays301.push(ms);
                return nativeSetTimeout(fn, ms, ...args);
            };
            const nativeFetch = window.fetch;
            window.fetch = (url, options = {}) => {
                if (!String(url).includes('/api/files')) return nativeFetch(url, options);
                return new Promise((resolve, reject) => {
                    const signal = options.signal;
                    if (signal?.aborted) {
                        reject(new DOMException('timed out', 'TimeoutError'));
                        return;
                    }
                    signal?.addEventListener('abort', () => {
                        reject(new DOMException('timed out', 'TimeoutError'));
                    }, {once: true});
                });
            };
        }""")
        file_mode["value"] = "timeout"
        page.evaluate("() => _pollRegister('files', refreshOpenFolders, 10000)")
        page.wait_for_function(
            "() => (_pollFailures.get('files') || 0) > 0", timeout=10000
        )
        timeout_state = page.evaluate("""() => ({
            failures: _pollFailures.get('files') || 0,
            delays: window.__pollDelays301,
            treeText: document.querySelector('#file-tree')?.innerText || '',
        })""")
    finally:
        page.close()

    assert file_state["failures"] >= 1
    assert file_state["nextDelay"] > 10000
    assert "ok.txt" in file_state["treeText"]
    assert timeout_state["failures"] >= 1
    assert any(delay > 10000 for delay in timeout_state["delays"])
    assert "ok.txt" in timeout_state["treeText"]


def test_dashboard_polling_resume_refreshes_status_after_hidden(
    dashboard_browser: Browser,
):
    page = dashboard_browser.new_page()
    page.add_init_script("""() => {
        window.EventSource = class StableEventSource {
            constructor(url) { this.url = url; this.readyState = 1; }
            close() { this.readyState = 2; }
        };
    }""")
    _route_frontend_sources(page)
    status = {"value": "idle"}

    def api_route(route):
        path = route.request.url.split("?", 1)[0].split("/api", 1)[-1]
        path = "/api" + path
        if path == "/api/orchestrators":
            payload = [{"id": "fe-orch-id", "name": "fe-orch", "scope": "/tmp/fe-scope"}]
        elif path == "/api/sessions":
            payload = [{"id": "fe-orch-id", "name": "fe-orch", "scope": "/tmp/fe-scope", "status": status["value"], "model": "claude-opus-5[1m]"}]
        elif path == "/api/stats":
            payload = {"active": 0, "total_sessions": 1, "total_cost_usd": 0}
        elif path == "/api/models":
            payload = {"models": [], "proxy_connected": False}
        elif path.endswith("/stream"):
            route.fulfill(status=200, content_type="text/event-stream", body="")
            return
        elif path.endswith("/logs"):
            payload = []
        elif path.endswith("/context"):
            payload = {"percentage": 0, "total_tokens": 0, "max_tokens": 1}
        elif path == "/api/logs/sync":
            payload = {"logs": [], "max_log_id": 0, "live_sessions": []}
        else:
            payload = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    page.route(re.compile(r"/api/"), api_route)
    _goto_dashboard(page)
    try:
        page.wait_for_function("() => selectedAgent === 'fe-orch'", timeout=8000)
        page.wait_for_function(
            "() => document.querySelector('[data-session-id=\"fe-orch-id\"]')?.innerText.includes('idle')",
            timeout=8000,
        )
        page.evaluate("""() => {
            Object.defineProperty(document, 'hidden', {configurable: true, value: true});
            document.dispatchEvent(new Event('visibilitychange'));
        }""")
        status["value"] = "running"
        page.evaluate("""() => {
            Object.defineProperty(document, 'hidden', {configurable: true, value: false});
            document.dispatchEvent(new Event('visibilitychange'));
        }""")
        page.wait_for_function(
            "() => document.querySelector('[data-session-id=\"fe-orch-id\"]')?.innerText.includes('running')",
            timeout=8000,
        )
    finally:
        page.close()


def test_dashboard_polling_equivalent_twelve_minutes_before_after(
    dashboard_browser: Browser,
    tmp_path: Path,
):
    """Use a 100x clock to count the same 720s window on main and this branch."""
    branch_source = Path(__file__).parent.parent / "app/static/js/app.js"
    main_source = tmp_path / "main-app.js"
    main_source.write_text(
        subprocess.check_output(
            ["git", "show", "main:app/static/js/app.js"], text=True,
        )
    )

    def measure(source_path: Path) -> dict[str, int]:
        page = dashboard_browser.new_page()
        page.add_init_script("""() => {
            const realTimeout = window.setTimeout.bind(window);
            const realInterval = window.setInterval.bind(window);
            const scale = 0.01;
            window.setTimeout = (fn, ms, ...args) => realTimeout(fn, Math.max(1, ms * scale), ...args);
            window.setInterval = (fn, ms, ...args) => realInterval(fn, Math.max(1, ms * scale), ...args);
            window.EventSource = class StableEventSource {
                constructor(url) { this.url = url; this.readyState = 1; }
                close() { this.readyState = 2; }
            };
        }""")
        _route_frontend_sources(page, source_path)
        counts: dict[str, int] = {}

        def api_route(route):
            path = route.request.url.split("?", 1)[0].split("/api", 1)[-1]
            path = "/api" + path
            counts[path] = counts.get(path, 0) + 1
            if path.endswith("/stream"):
                route.fulfill(status=200, content_type="text/event-stream", body="")
                return
            if path.endswith("/logs"):
                payload = []
            elif path == "/api/orchestrators":
                payload = [{"id": "fe-orch-id", "name": "fe-orch", "scope": "/tmp/fe-scope"}]
            elif path == "/api/sessions":
                payload = [{"id": "fe-orch-id", "name": "fe-orch", "scope": "/tmp/fe-scope", "status": "idle", "model": "claude-opus-5[1m]"}]
            elif path == "/api/stats":
                payload = {"active": 0, "total_sessions": 1, "total_cost_usd": 0}
            elif path == "/api/models":
                payload = {"models": [], "proxy_connected": False}
            elif path == "/api/logs/sync":
                payload = {"logs": [], "max_log_id": 0, "live_sessions": []}
            elif path.endswith("/context"):
                payload = {"percentage": 0, "total_tokens": 0, "max_tokens": 1}
            elif path == "/api/usage":
                payload = {}
            else:
                payload = []
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

        page.route(re.compile(r"/api/"), api_route)
        _goto_dashboard(page)
        page.wait_for_function("() => selectedAgent === 'fe-orch'", timeout=8000)
        page.wait_for_timeout(200)
        counts.clear()
        # The contract is visibility-aware pause.  Measuring an active tab lets
        # network timing and startup work dominate the 12-minute equivalent;
        # hold the tab hidden so main's fixed timers and this branch's coordinator
        # are compared on the behavior that changed.
        page.evaluate("() => { Object.defineProperty(document, 'hidden', {configurable: true, value: true}); document.dispatchEvent(new Event('visibilitychange')); }")
        page.wait_for_timeout(7200)
        result = dict(counts)
        page.close()
        return result

    before = measure(main_source)
    after = measure(branch_source)
    before_total = sum(before.values())
    after_total = sum(after.values())
    print(f"#301 equivalent 12m before_total={before_total} after_total={after_total} before={before} after={after}")
    assert after_total < before_total, (before_total, after_total)
    assert after.get("/api/models", 0) <= before.get("/api/models", 0), (before, after)


def _open_notify_stream_page(
    browser: Browser,
    permission: str,
    history_rows: list[dict],
    stream_pages: list[list[dict]],
    history_status: int = 200,
    stable_sse: bool = False,
) -> tuple[Page, list[int]]:
    """Гоняем НАСТОЯЩИЙ путь: история → `_renderHistory` → `connectSSE` → onmessage.

    Прямой вызов `_maybeNotifyCall` читался бы как покрытие и им не был: мутация
    «убрать проводку в поток» осталась бы зелёной.
    """
    page = browser.new_page()
    if stable_sse:
        page.add_init_script("""() => {
            window.EventSource = class StableEventSource {
                constructor(url) { this.url = url; this.readyState = 1; }
                close() { this.readyState = 2; }
            };
        }""")
    page.add_init_script(_notify_stub(permission))
    _route_frontend_sources(page)

    history_calls: list[int] = []

    def history_route(route):
        history_calls.append(1)
        # Вторую порцию (добор страницы) отдаём пустой — иначе добор идёт по кругу.
        rows = history_rows if len(history_calls) == 1 else []
        route.fulfill(status=history_status, content_type="application/json",
                      body=json.dumps(rows, ensure_ascii=False))

    stream_calls: list[int] = []

    def stream_route(route):
        stream_calls.append(1)
        # Каждому подключению — своя порция; последняя повторяется дальше, потому что
        # поток рвётся и переподключается, а живой сервер после рестарта способен
        # переслать уже показанное.
        rows = stream_pages[min(len(stream_calls) - 1, len(stream_pages) - 1)]
        body = "".join(
            f"data: {json.dumps(row, ensure_ascii=False)}\n\n" for row in rows
        )
        route.fulfill(status=200, content_type="text/event-stream", body=body)

    # Только СВОЙ агент: страница на загрузке уже держит поток агента по умолчанию, и
    # широкий шаблон кормил бы синтетикой ещё и его — уведомление приходило бы с чужим
    # именем в заголовке (поймано первым же прогоном).
    page.route(re.compile(rf"/api/sessions/{_NOTIFY_AGENT}/logs\?"), history_route)
    page.route(re.compile(rf"/api/sessions/{_NOTIFY_AGENT}/stream\?"), stream_route)
    _goto_dashboard(page)
    # Сперва дать странице восстановить своего последнего агента: её выбор приходит
    # асинхронно и иначе перебивает наш уже после selectAgent.
    page.wait_for_function(
        "() => typeof selectAgent === 'function' && selectedAgent && currentScope && orchData.length"
    )
    page.evaluate("() => _pollStop('sessions')")
    page.evaluate("name => selectAgent(name)", _NOTIFY_AGENT)
    page.wait_for_function("name => selectedAgent === name", arg=_NOTIFY_AGENT)
    # selectAgent starts one final refreshSessions directly; wait for that request
    # to settle before reading chat DOM, otherwise it can replace the history after
    # a row-specific wait. SSE/history remain live for the actual renderer paths.
    page.wait_for_function("() => !refreshInProgress", timeout=8000)
    return page, stream_calls


def test_live_call_notifies_once_while_history_and_replays_stay_silent(
    dashboard_browser: Browser,
):
    """#268: уведомление браузера на зов оркестратора — ровно одно на зов.

    Дашборд перерисовывает поток, дорисовывает историю сверху и переподключает SSE,
    поэтому одна и та же строка приходит не раз. Старые зовы из истории при загрузке
    не уведомляют вовсе: юзеру нужно свежее, а не разбор архива.
    """
    old_reason = "СТАРЫЙ ЗОВ из истории"
    live_reason = "кеш падает 93.6% → 15%"
    page, stream_calls = _open_notify_stream_page(
        dashboard_browser,
        "granted",
        history_rows=[_notify_row(41001, old_reason)],
        stream_pages=[[_notify_row(41010, live_reason)]],
    )
    try:
        page.wait_for_function("() => window.__notifications.length >= 1", timeout=8000)
    except PlaywrightTimeout:
        pytest.fail(
            f"live notify never fired: {page.evaluate('() => window.__notifications')}"
        )
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('#chat .chat-notify-user').length >= 1",
            timeout=5000,
        )
    except PlaywrightTimeout:
        pytest.fail(
            "notify card never appeared after live call: count="
            f"{page.evaluate('() => document.querySelectorAll(\"#chat .chat-notify-user\").length')}"
        )

    # Reconnect is a count, not a clock. 5s sleep under module load was the flake.
    deadline = time.monotonic() + 8
    while len(stream_calls) < 2 and time.monotonic() < deadline:
        page.wait_for_timeout(50)
    if len(stream_calls) < 2:
        pytest.fail(f"stream did not reconnect, connections={len(stream_calls)}")

    page.evaluate(
        """row => _prependHistory(selectedAgent, currentScope, [row])""",
        _notify_row(41010, live_reason),
    )
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('#chat .chat-notify-user').length >= 1",
            timeout=5000,
        )
    except PlaywrightTimeout:
        pytest.fail(
            "notify card gone after history prepend: count="
            f"{page.evaluate('() => document.querySelectorAll(\"#chat .chat-notify-user\").length')}"
        )
    state = page.evaluate("""() => ({
        notifications: window.__notifications,
        cards: document.querySelectorAll('#chat .chat-notify-user').length,
        permissionBtn: !!document.querySelector('#chat-notify-permission'),
    })""")
    page.close()

    assert len(stream_calls) >= 2, (
        f"поток обязан был переподключиться, подключений {len(stream_calls)}"
    )
    assert len(state["notifications"]) == 1, state["notifications"]
    notification = state["notifications"][0]
    assert notification["body"] == live_reason
    assert _NOTIFY_AGENT in notification["title"], notification["title"]
    assert notification["tag"] == "orchestra-call-41010"
    assert notification["requireInteraction"] is True
    assert old_reason not in json.dumps(state["notifications"], ensure_ascii=False), (
        "зов из истории приехал бы уведомлением при каждой перезагрузке страницы"
    )
    assert state["cards"] >= 1, "подсветка зова из #241 обязана остаться живой"
    assert state["permissionBtn"] is False, "разрешение уже есть — кнопке неоткуда взяться"


def test_history_carried_by_the_stream_itself_stays_silent_then_arms(
    dashboard_browser: Browser,
):
    """Запасной режим: `_fetchHistory` упал, историю везёт сам поток (`after_id=0`).

    Эта пачка — архив, а не свежее, и уведомлять по ней нельзя. Но и замолчать до
    следующего реконнекта нельзя: канал оказался бы тихо мёртвым на весь сеанс.
    """
    page, stream_calls = _open_notify_stream_page(
        dashboard_browser,
        "granted",
        history_rows=[],
        stream_pages=[
            [_notify_row(43001, "АРХИВНЫЙ зов из пачки потока")],
            [_notify_row(43010, "живой зов после взвода")],
        ],
        history_status=500,
    )
    page.wait_for_function("() => window.__notifications.length >= 1", timeout=20000)
    notifications = page.evaluate("() => window.__notifications")
    page.close()

    assert len(stream_calls) >= 2, "второе подключение обязано было состояться"
    assert len(notifications) == 1, notifications
    assert notifications[0]["body"] == "живой зов после взвода"
    assert notifications[0]["tag"] == "orchestra-call-43010"


def test_notification_permission_is_asked_by_click_and_never_on_load(
    dashboard_browser: Browser,
):
    """Всплывший на загрузке запрос юзер отклонит один раз — и канал потерян навсегда."""
    page, _ = _open_notify_stream_page(
        dashboard_browser,
        "default",
        history_rows=[],
        stream_pages=[[_notify_row(42010, "зов без разрешения")]],
    )
    page.wait_for_selector("#chat-notify-permission", timeout=15000)
    before = page.evaluate("""() => ({
        requests: window.__permissionRequests,
        notifications: window.__notifications.length,
    })""")
    page.click("#chat-notify-permission")
    page.wait_for_function("() => window.__permissionRequests === 1", timeout=5000)
    after = page.evaluate("""() => ({
        requests: window.__permissionRequests,
        btn: !!document.querySelector('#chat-notify-permission'),
        permission: Notification.permission,
    })""")
    page.close()

    assert before["requests"] == 0, "на загрузке разрешение не спрашиваем"
    assert before["notifications"] == 0, "без разрешения уведомление создавать нечем"
    assert after["requests"] == 1
    assert after["permission"] == "granted"
    assert after["btn"] is False, "решение принято — второй раз браузер не спросит"


@pytest.mark.parametrize("compact_mode", [False, True], ids=["normal", "compact"])
def test_legacy_rows_without_tool_use_id_pair_by_adjacency(
    dashboard_browser: Browser,
    compact_mode: bool,
):
    """63.7% строк журнала старше поля `tool_use_id` и не несут его вовсе.

    Для них соседство — единственный доступный признак и он верный; exact-only
    рисовал бы «Результат без вызова» на КАЖДОЙ такой строке.
    """
    page = _open_tool_correlation_page(dashboard_browser, compact_mode)
    rendered = page.evaluate("""() => {
        const chat = document.querySelector('#chat');
        addChatEntry('tool', 'Bash: {"command":"echo LEGACY-ONE"}', null, null, {id:32001});
        addChatEntry('tool_result', 'LEGACY-RESULT-ONE', null, null, {id:32002});
        addChatEntry('tool', 'Bash: {"command":"echo LEGACY-TWO"}', null, null, {id:32003});
        addChatEntry('tool_result', 'LEGACY-RESULT-TWO', null, null, {id:32004});
        const sel = window.compactMode
            ? '[data-compact-tool]'
            : '[data-tool-raw-name]:not([data-compact-tool])';
        return {
            orphans: chat.querySelectorAll('[data-unmatched-tool-result]').length,
            cards: [...chat.querySelectorAll(sel)].map(card => (
                window.compactMode
                    ? `${card.innerText} ${card.dataset.resultContent || ''}`
                    : card.innerText
            )),
        };
    }""")
    page.close()

    assert rendered["orphans"] == 0, "у строки без идентификатора сироты быть не может"
    cards = rendered["cards"]
    assert len(cards) == 2
    assert "LEGACY-RESULT-ONE" in cards[0] and "LEGACY-RESULT-TWO" not in cards[0]
    assert "LEGACY-RESULT-TWO" in cards[1] and "LEGACY-RESULT-ONE" not in cards[1]


@pytest.mark.parametrize("compact_mode", [False, True], ids=["normal", "compact"])
def test_unmatched_tool_result_is_visible_and_never_attaches_to_another_call(
    dashboard_browser: Browser,
    compact_mode: bool,
):
    page = _open_tool_correlation_page(dashboard_browser, compact_mode)
    rendered = page.evaluate("""() => {
        addChatEntry(
            'tool',
            'mcp__orchestra__task_create: {"title":"DO-NOT-ATTACH"}',
            null,
            null,
            {id:26011, tool_use_id:'known-call'},
        );
        addChatEntry(
            'tool_result',
            'ORPHAN-RESULT-MARKER',
            null,
            null,
            {id:26012, tool_use_id:'missing-call'},
        );
        const call = document.querySelector('[data-tool-use-id="known-call"]');
        const orphan = document.querySelector('[data-unmatched-tool-result]');
        return {
            callText: call?.innerText || '',
            orphanText: orphan?.innerText || '',
            orphanCount: document.querySelectorAll('[data-unmatched-tool-result]').length,
        };
    }""")
    page.close()

    assert rendered["orphanCount"] == 1
    assert "Результат без вызова" in rendered["orphanText"]
    assert "ORPHAN-RESULT-MARKER" in rendered["orphanText"]
    assert "ORPHAN-RESULT-MARKER" not in rendered["callText"]


@pytest.mark.parametrize("compact_mode", [False, True], ids=["normal", "compact"])
def test_load_more_keeps_tool_use_id_for_old_parallel_calls(
    dashboard_browser: Browser,
    compact_mode: bool,
):
    page = _open_tool_correlation_page(dashboard_browser, compact_mode)
    page.route(
        "**/api/sessions/history-fixture/logs*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                [
                    {
                        "id": 41,
                        "type": "tool",
                        "content": 'mcp__orchestra__task_create: {"title":"OLD-A"}',
                        "ts": None,
                        "tool_use_id": "old-a",
                    },
                    {
                        "id": 42,
                        "type": "tool",
                        "content": "mcp__orchestra__list_agents: {}",
                        "ts": None,
                        "tool_use_id": "old-b",
                    },
                    {
                        "id": 43,
                        "type": "tool_result",
                        "content": "OLD-RESULT-A",
                        "ts": None,
                        "tool_use_id": "old-a",
                    },
                    {
                        "id": 44,
                        "type": "tool_result",
                        "content": "OLD-RESULT-B",
                        "ts": None,
                        "tool_use_id": "old-b",
                    },
                ]
            ),
        ),
    )
    result_by_id = page.evaluate("""async compactMode => {
        window.compactMode = compactMode;
        selectedAgent = 'history-fixture';
        currentScope = '/fixture';
        chatLogs[selectedAgent] = {lastId:100, firstId:100, initialCount:1};
        await loadMoreLogs();
        const selector = compactMode
            ? '[data-compact-tool]'
            : '[data-tool-use-id]:not([data-compact-tool])';
        return Object.fromEntries([...document.querySelectorAll(`#chat ${selector}`)]
            .map(card => [
                card.dataset.toolUseId,
                compactMode ? card.dataset.resultContent || '' : card.innerText,
            ]));
    }""", compact_mode)
    page.close()

    assert "OLD-RESULT-A" in result_by_id["old-a"]
    assert "OLD-RESULT-B" in result_by_id["old-b"]
    assert "OLD-RESULT-B" not in result_by_id["old-a"]
    assert "OLD-RESULT-A" not in result_by_id["old-b"]


def test_load_more_increases_visible_cards(dashboard_browser: Browser):
    """Нажатие «Load 500 more» должно увеличить число рендернутых карточек."""
    page = _open_tool_correlation_page(dashboard_browser, False)
    page.route(
        "**/api/sessions/history-fixture/logs*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                [
                    {
                        "id": 500 + i,
                        "type": "tool_result",
                        "content": f"OLDER-{i}",
                        "ts": None,
                    }
                    for i in range(1, 501)
                ]
            ),
        ),
    )
    before = page.evaluate("""() => {
        selectedAgent = 'history-fixture';
        currentScope = '/fixture';
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
        if (window.chatLogs) chatLogs = {};
        chatLogs[selectedAgent] = {lastId: 1499, firstId: 1000, initialCount: 500};
        const chat = document.querySelector('#chat');
        chat.innerHTML = '';
        for (let id = 1000; id <= 1499; id += 1) {
            addChatEntry('tool', `visible-${id}`, null, null, {id});
        }
        updateLoadMoreBtn();
        return document.querySelectorAll('#chat [data-chat-log-id]').length;
    }""")
    page.click("#load-more-btn")
    page.wait_for_function(
        f"() => document.querySelectorAll('#chat [data-chat-log-id]').length > {before}",
        timeout=10000,
    )
    after = page.evaluate("""() => document.querySelectorAll('#chat [data-chat-log-id]').length""")
    page.close()

    assert after > before, (before, after)


def test_tool_view_mode_is_visible_without_desktop_header_overflow(
    dashboard_browser: Browser,
):
    page = dashboard_browser.new_page(viewport={"width": 1280, "height": 800})
    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
    page.route(
        "**/static/js/app.js*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/javascript",
            body=source,
        ),
    )
    _goto_dashboard(page)
    page.wait_for_function("() => typeof _toolForResult === 'function'")
    button = page.locator("#compact-toggle-btn")
    expect(button).to_have_text("📄 Normal")

    measurements = []
    for width in (1280, 1440, 1680, 1920):
        page.set_viewport_size({"width": width, "height": 800})
        measurements.append(page.evaluate("""() => {
            const button = document.querySelector('#compact-toggle-btn');
            const rect = button.getBoundingClientRect();
            return {
                viewport: innerWidth,
                bodyFits: document.body.scrollWidth <= document.body.clientWidth,
                buttonLeft: rect.left,
                buttonRight: rect.right,
                buttonVisible: getComputedStyle(button).display !== 'none',
            };
        }"""))

    button.click()
    expect(button).to_have_text("📋 Compact")
    expect(button).to_have_attribute("aria-pressed", "true")
    page.close()

    assert all(item["bodyFits"] for item in measurements)
    assert all(item["buttonVisible"] for item in measurements)
    assert all(
        0 <= item["buttonLeft"] < item["buttonRight"] <= item["viewport"]
        for item in measurements
    )


@pytest.mark.parametrize("compact_mode", [False, True], ids=["normal", "compact"])
def test_task_result_leads_with_action_and_keeps_raw_details(
    dashboard_browser: Browser,
    compact_mode: bool,
):
    page = _open_tool_correlation_page(dashboard_browser, compact_mode)
    rendered = page.evaluate("""compactMode => {
        addChatEntry(
            'tool',
            'mcp__orchestra__task_create: {"title":"Fix result correlation"}',
            null,
            null,
            {id:26101, tool_use_id:'task-create-260'},
        );
        addChatEntry(
            'tool_result',
            JSON.stringify({
                par:'ORC-260', id:9001, task_id:9001,
                title:'Fix result correlation', project:'Orchestra',
                price_rub:0, status:'new', priority:0,
                description:'Every result belongs to its own call.',
            }),
            null,
            null,
            {id:26102, tool_use_id:'task-create-260'},
        );
        const compactCard = document.querySelector('[data-tool-use-id="task-create-260"]');
        const compactResult = compactCard.querySelector('.compact-result')?.textContent || '';
        if (compactMode) compactCard.click();
        const card = compactMode
            ? document.querySelector('[data-tool-use-id="task-create-260"]:not([data-compact-tool])')
            : compactCard;
        const details = card.querySelector('details[data-tool-technical-details]');
        return {
            compactResult,
            cardText: card.innerText,
            detailsLabel: details.querySelector('summary').textContent,
            detailsOpen: details.open,
            raw: details.querySelector('pre').textContent,
        };
    }""", compact_mode)
    page.close()

    if compact_mode:
        assert rendered["compactResult"] == "✅ #260 создана"
    assert "Задача #260 создана" in rendered["cardText"]
    assert "Fix result correlation" in rendered["cardText"]
    assert rendered["detailsLabel"] == "Технические детали"
    assert not rendered["detailsOpen"]
    assert '"price_rub": 0' in rendered["raw"]
    assert '"task_id": 9001' in rendered["raw"]


@pytest.mark.parametrize("compact_mode", [False, True], ids=["normal", "compact"])
def test_agent_result_summarizes_statuses_and_keeps_raw_details(
    dashboard_browser: Browser,
    compact_mode: bool,
):
    page = _open_tool_correlation_page(dashboard_browser, compact_mode)
    rendered = page.evaluate("""compactMode => {
        addChatEntry(
            'tool',
            'mcp__orchestra__list_agents: {}',
            null,
            null,
            {id:26201, tool_use_id:'agent-list-260'},
        );
        addChatEntry(
            'tool_result',
            [
                '## Orchestrators',
                '🟢 👑 **Orchestra-orchestrator** | running | opus | ctx:31% | "Coordinates work"',
                '🟡 ⚙️ **frontend** | waiting | sol | ctx:42% | 260 | "Waiting review"',
                '❌ ⚙️ **broken-worker** | broken | sol | ctx:18% | 259 | "Needs restart"',
            ].join('\\n'),
            null,
            null,
            {id:26202, tool_use_id:'agent-list-260'},
        );
        const compactCard = document.querySelector('[data-tool-use-id="agent-list-260"]');
        const compactResult = compactCard.querySelector('.compact-result')?.textContent || '';
        if (compactMode) compactCard.click();
        const card = compactMode
            ? document.querySelector('[data-tool-use-id="agent-list-260"]:not([data-compact-tool])')
            : compactCard;
        const details = card.querySelector('details[data-tool-technical-details]');
        return {
            compactResult,
            cardText: card.innerText,
            summary: card.querySelector('[data-agent-summary]').textContent,
            attention: card.querySelector('[data-agent-attention]').textContent,
            detailsOpen: details.open,
            raw: details.querySelector('pre').textContent,
        };
    }""", compact_mode)
    page.close()

    if compact_mode:
        assert rendered["compactResult"] == (
            "3 всего · 1 работает · 1 ждёт · 1 сломан"
        )
    assert "Агенты · 3 всего" in rendered["cardText"]
    assert rendered["summary"] == "1 работает1 ждёт1 сломан"
    assert "frontend — waiting" in rendered["attention"]
    assert "broken-worker — broken" in rendered["attention"]
    assert not rendered["detailsOpen"]
    assert "## Orchestrators" in rendered["raw"]
    assert "ctx:42%" in rendered["raw"]


def test_task_card_uses_real_long_description_and_shared_expandable_body(
    dashboard_browser: Browser,
):
    root = Path(__file__).parent.parent
    source = (root / "app/static/js/app.js").read_text()
    helper_code = (
        "const _TASK_PRIORITY_META"
        + source.split("const _TASK_PRIORITY_META", 1)[1].split(
            "// Central renderer", 1,
        )[0]
    )
    # Isolated fixture DB has no TM rows. A real paragraph (not "x"*200) still
    # exercises wrap/expand; pulling live tasks was a silent skip on empty scope.
    description = (
        "Need a description long enough to wrap in the task card: the renderer "
        "collapses after two lines and the expand control must stay attached to "
        "this body, not to a sibling. Extra sentences keep the length above the "
        "180-character floor that used to come from a live ticket."
    )
    assert len(description) > 180
    task = {
        "description": description,
        "assignee": "frontend",
        "task_id": 987,
        "priority": 1,
        "title": "fixture task",
        "par": 987,
    }

    page = dashboard_browser.new_page(viewport={"width": 1440, "height": 900})
    page.set_content(
        '<body style="background:#0a0e17;color:#e2e8f0">'
        '<style>#chat-card,#panel-card,#xss-card{width:420px}</style>'
        '<div id="chat-card"></div><div id="panel-card"></div><div id="xss-card"></div>'
        '</body>'
    )
    page.add_style_tag(path=str(root / "app/static/css/style.css"))
    page.add_script_tag(path=str(root / "app/static/css/vendor/marked.min.js"))
    page.add_script_tag(path=str(root / "app/static/css/vendor/purify.min.js"))
    page.add_script_tag(content="const CUR = '₽';\n" + helper_code)
    page.evaluate(
        """task => {
            document.querySelector('#chat-card').innerHTML = _taskCardBodyHtml(task);
            document.querySelector('#panel-card').innerHTML = _taskCardBodyHtml(task);
            document.querySelector('#xss-card').innerHTML = _taskCardBodyHtml({
                description: '<img src=x onerror="window.taskXss=1"><script>window.taskXss=1</script>',
            });
        }""",
        task,
    )

    chat = page.locator("#chat-card")
    panel = page.locator("#panel-card")
    expect(chat).to_contain_text("🟠 High")
    expect(chat).to_contain_text("Assignee: frontend")
    expect(chat).to_contain_text("Task ID: 987")
    expect(chat.locator("[data-task-description-toggle]")).to_have_text("▼ Развернуть")
    assert chat.inner_html() == panel.inner_html()

    description = chat.locator("[data-task-description-body]")
    assert description.evaluate("el => el.scrollHeight > el.clientHeight")
    chat.locator("[data-task-description-toggle]").click()
    expect(chat.locator("[data-task-description-toggle]")).to_have_text("▲ Свернуть")
    assert description.evaluate("el => el.style.maxHeight") == "none"

    assert page.evaluate("() => window.taskXss") is None
    expect(page.locator("#xss-card script")).to_have_count(0)
    expect(page.locator("#xss-card img")).not_to_have_attribute("onerror", "window.taskXss=1")

    assert "taskBody.innerHTML = _taskCardBodyHtml(parsed);" in source
    assert "h += _taskCardBodyHtml(t);" in source
    assert "html += _taskCardBodyHtml(t);" in source
    page.close()


def test_chat_restores_last_read_boundary_only_when_unread(
    dashboard_browser: Browser,
):
    root = Path(__file__).parent.parent
    source = (root / "app/static/js/app.js").read_text()
    helper_code = (
        "const _CHAT_BOTTOM_GAP"
        + source.split("const _CHAT_BOTTOM_GAP", 1)[1].split(
            "window.compactMode", 1,
        )[0]
    )
    page = dashboard_browser.new_page(viewport={"width": 900, "height": 700})
    page.route(
        "http://chat-receipts.test/",
        lambda route: route.fulfill(status=200, content_type="text/html", body=""),
    )
    page.goto("http://chat-receipts.test/")
    page.set_content(
        """
        <style>
          .hidden { display:none !important }
          #chat { height:240px; overflow-y:auto }
          #chat > div { height:48px }
          .chat-unread-divider { height:20px !important }
        </style>
        <div style="position:relative;width:500px">
          <div id="chat"></div>
          <button id="chat-jump-latest" class="hidden"></button>
        </div>
        """
    )
    page.add_script_tag(
        content="""
        const $ = selector => document.querySelector(selector);
        let currentScope = '/scope';
        let selectedAgent = 'agent-a';
        let scrollAfterLoad = false;
        """
        + helper_code
        + """
        sessionStorage.clear();
        window.fillChat = (total = 24, start = 1) => {
            const chat = $('#chat');
            chat.innerHTML = '';
            for (let id = start; id < start + total; id++) {
                const row = document.createElement('div');
                row.className = 'chat-bot';
                row.dataset.chatLogId = String(id);
                row.textContent = `agent work ${id}`;
                chat.appendChild(row);
            }
            chat.scrollTop = 0;
        };
        initChatPositionMemory();
        """,
    )

    # Reading in the middle records the lowest visible log, not the user's last message.
    read_id = page.evaluate(
        """() => {
            window.fillChat(24);
            $('#chat').scrollTop = 8 * 48;
            _captureChatReadFrontier();
            return _chatReadReceipt(_chatPositionKey());
        }"""
    )
    assert 9 <= read_id < 24

    page.evaluate(
        """() => {
            window.fillChat(30);
            _prepareChatAnchorRestore(true);
            _restoreChatAnchor(_chatPositionKey());
        }"""
    )
    divider = page.locator(".chat-unread-divider")
    expect(divider).to_have_count(1)
    assert page.evaluate(
        """() => Number($('.chat-unread-divider').nextElementSibling.dataset.chatLogId)"""
    ) == read_id + 1
    expect(page.locator("#chat-jump-latest")).to_be_visible()
    expect(page.locator("#chat-jump-latest")).to_have_text("↓ Новые ниже")
    page.locator("#chat-jump-latest").click()
    page.wait_for_function("() => _chatAtBottom()")
    expect(page.locator("#chat-jump-latest")).to_be_hidden()

    # If the saved boundary fell outside the loaded window, start at the first
    # available unread record instead of cascading through older history.
    page.evaluate(
        """() => {
            selectedAgent = 'agent-boundary-outside-window';
            _saveChatReadReceipt(_chatPositionKey(), 50);
            window.fillChat(24, 100);
            _prepareChatAnchorRestore(true);
            _restoreChatAnchor(_chatPositionKey());
        }"""
    )
    assert page.evaluate(
        """() => Number($('.chat-unread-divider').nextElementSibling.dataset.chatLogId)"""
    ) == 100

    # A receipt at the old bottom puts the divider immediately before new work.
    page.evaluate(
        """() => {
            selectedAgent = 'agent-at-bottom';
            window.fillChat(24);
            $('#chat').scrollTop = $('#chat').scrollHeight;
            _captureChatReadFrontier();
            window.fillChat(28);
            _prepareChatAnchorRestore(true);
            _restoreChatAnchor(_chatPositionKey());
        }"""
    )
    expect(page.locator(".chat-unread-divider")).to_have_count(1)
    assert page.evaluate(
        """() => Number($('.chat-unread-divider').nextElementSibling.dataset.chatLogId)"""
    ) == 25

    # Opening and leaving before history settles must not invent a read boundary.
    page.evaluate(
        """() => {
            selectedAgent = 'agent-opened-and-left';
            window.fillChat(24);
            scrollAfterLoad = true;
            _captureChatReadFrontier();
            _prepareChatAnchorRestore(true);
            _restoreChatAnchor(_chatPositionKey());
        }"""
    )
    assert page.evaluate("() => _chatReadReceipt(_chatPositionKey())") is None
    expect(page.locator(".chat-unread-divider")).to_have_count(0)

    # Live work at the bottom stays pinned and advances the read frontier.
    page.evaluate(
        """() => {
            selectedAgent = 'agent-live';
            scrollAfterLoad = false;
            window.fillChat(24);
            $('#chat').scrollTop = $('#chat').scrollHeight;
            _captureChatReadFrontier();
            const wasAtBottom = _chatAtBottom();
            const row = document.createElement('div');
            row.className = 'chat-bot';
            row.dataset.chatLogId = '25';
            row.textContent = 'live work 25';
            $('#chat').appendChild(row);
            if (wasAtBottom) $('#chat').scrollTop = $('#chat').scrollHeight;
            _captureChatReadFrontier();
        }"""
    )
    assert page.evaluate("() => _chatAtBottom()") is True
    assert page.evaluate("() => _chatReadReceipt(_chatPositionKey())") == 25
    expect(page.locator(".chat-unread-divider")).to_have_count(0)

    assert "_scheduleChatInitialSettle();" in source
    assert "const restoreUnreadAnchor = _unreadTabs.delete(currentScope);" in source
    assert "_prepareChatAnchorRestore(restoreUnreadAnchor);" in source
    assert source.count("_unreadTabs.add(") == 1
    # Интент — «позиция чата не переживает рестарт», то есть localStorage не
    # ИСПОЛЬЗУЕТСЯ. Проверка на голое вхождение слова ломалась от комментария,
    # который объясняет, почему его здесь нет: смысл кода не изменился.
    code_without_comments = re.sub(r"//[^\n]*", "", helper_code)
    assert "localStorage" not in code_without_comments
    assert "sessionStorage" in helper_code
    page.close()


def test_chat_timeline_navigates_events_and_cycles_user_messages(
    dashboard_browser: Browser,
):
    root = Path(__file__).parent.parent
    source = (root / "app/static/js/app.js").read_text()
    timeline_code = (
        "let _chatTimelineObserver"
        + source.split("let _chatTimelineObserver", 1)[1].split(
            "function _prepareChatAnchorRestore", 1,
        )[0]
    )
    page = dashboard_browser.new_page(viewport={"width": 900, "height": 700})
    page.set_content(
        """
        <div style="position:relative;width:520px;height:260px">
          <div id="chat" style="height:100%;overflow-y:auto"></div>
          <aside id="chat-timeline" class="chat-timeline">
            <div class="chat-timeline-user-nav">
              <button id="chat-user-prev">↑</button><span id="chat-user-count"></span>
              <button id="chat-user-next">↓</button>
            </div>
            <div id="chat-timeline-track" class="chat-timeline-track"></div>
          </aside>
          <button id="chat-jump-latest"></button>
        </div>
        """
    )
    page.add_style_tag(path=str(root / "app/static/css/style.css"))
    page.add_script_tag(
        content="""
        const $ = selector => document.querySelector(selector);
        let _chatFollow = true;
        let scrollAfterLoad = true;
        let _pendingChatRestore = null;
        const _syncChatJumpButton = () => {};
        """
        + timeline_code
        + """
        window.addTimelineEntry = (type, label, from = '') => {
            const node = document.createElement('div');
            node.style.height = '90px';
            node.style.flex = '0 0 90px';
            node.dataset.testLabel = label;
            if (from) node.dataset.from = from;
            node.textContent = label;
            _tagChatTimelineNode(node, type, '2026-08-11T10:00:00Z');
            $('#chat').appendChild(node);
            return node;
        };
        addTimelineEntry('assistant', 'agent-1');
        addTimelineEntry('user_message', 'mine-1');
        addTimelineEntry('tool', 'tool-1');
        addTimelineEntry('user_message', 'worker-1', 'worker');
        addTimelineEntry('assistant', 'agent-2');
        addTimelineEntry('user_message', 'mine-2');
        initChatTimeline();
        """,
    )

    expect(page.locator("#chat-timeline-track .chat-timeline-marker")).to_have_count(6)
    expect(page.locator("#chat-timeline-track .is-user")).to_have_count(2)
    expect(page.locator("#chat-timeline-track .is-worker")).to_have_count(1)
    expect(page.locator("#chat-user-count")).to_have_text("Я 2")

    page.locator("#chat-timeline-track .is-tool").click()
    page.wait_for_timeout(400)
    assert page.evaluate(
        """() => {
            const chat = $('#chat');
            const node = chat.querySelector('[data-test-label="tool-1"]');
            const chatCenter = chat.getBoundingClientRect().top + chat.clientHeight / 2;
            const nodeCenter = node.getBoundingClientRect().top + node.offsetHeight / 2;
            return Math.abs(chatCenter - nodeCenter) < 3;
        }"""
    )

    page.locator("#chat-user-prev").click()
    page.wait_for_timeout(400)
    assert page.evaluate(
        """() => {
            const users = [...document.querySelectorAll('#chat-timeline-track .is-user')];
            return $('#chat-timeline-track .is-active') === users.at(-1);
        }"""
    )
    page.locator("#chat-user-prev").click()
    page.wait_for_timeout(400)
    assert page.evaluate(
        """() => {
            const users = [...document.querySelectorAll('#chat-timeline-track .is-user')];
            return $('#chat-timeline-track .is-active') === users[0];
        }"""
    )

    page.evaluate("() => addTimelineEntry('user_message', 'mine-3')")
    expect(page.locator("#chat-user-count")).to_have_text("Я 3")
    page.evaluate("() => $('#chat [data-test-label=\"mine-3\"]').remove()")
    expect(page.locator("#chat-user-count")).to_have_text("Я 2")
    assert "_tagChatTimelineNode(el, type, ts);" in source
    page.close()


def test_codex_successful_mcp_startup_status_is_hidden(
    dashboard_browser: Browser,
):
    page = _open_tool_fixture_page(dashboard_browser)
    page.evaluate("""() => {
        addChatEntry('status', 'codex mcp orchestra: starting');
        addChatEntry('status', 'codex mcp orchestra: ready');
    }""")

    expect(page.locator("#chat").locator("text=codex mcp")).to_have_count(0)
    page.close()


def test_native_codex_compact_renders_one_result_badge(
    dashboard_browser: Browser,
):
    page = _open_tool_fixture_page(dashboard_browser)
    page.evaluate("""() => {
        addChatEntry(
            'status',
            'compact started (native Codex, context 70%, thread=thread-secret)'
        );
        addChatEntry(
            'status',
            'compact done (native Codex): 70% → 29%, thread=thread-secret'
        );
    }""")

    badges = page.locator("#chat").locator("text=Codex context compacted natively")
    expect(badges).to_have_count(1)
    expect(badges).to_contain_text("70% → 29%")
    expect(page.locator("#chat")).not_to_contain_text("thread-secret")
    page.close()


def test_codex_web_search_renders_queries_without_transport_json(
    dashboard_browser: Browser,
):
    page = _open_tool_fixture_page(dashboard_browser)
    page.evaluate("""() => {
        addChatEntry(
            'tool',
            'WebSearch: {"query":"","action":null,"_codex_item_id":"web-1"}',
            null,
            null,
            {tool_use_id: 'web-1'}
        );
        addChatEntry(
            'tool_result',
            JSON.stringify({
                query: 'AOSP official documentation',
                action: {
                    type: 'search',
                    query: null,
                    queries: [
                        'site:source.android.com AOSP CDD official',
                        'site:source.android.com CTS compatibility official',
                        'site:developer.android.com Play Integrity official',
                    ],
                },
                status: 'completed',
            }),
            null,
            null,
            {tool_use_id: 'web-1'}
        );
    }""")

    card = page.locator("#chat .codex-tool-card")
    expect(card).to_have_count(1)
    expect(card.locator(".codex-tool-title")).to_have_text("Web search")
    expect(card.locator(".codex-search-query")).to_have_count(3)
    expect(card.locator(".codex-tool-state")).to_have_text("done")
    text = card.inner_text()
    assert '"action"' not in text
    assert '"queries"' not in text
    page.close()


def test_codex_spawn_worker_renders_task_model_and_completion(
    dashboard_browser: Browser,
):
    page = _open_tool_fixture_page(dashboard_browser)
    payload = {
        "name": "mobile-os-strategy",
        "role": "full-cycle",
        "model": "gpt-5.6-sol",
        "task": "Research an AOSP-first product strategy.",
        "description": "Mobile OS strategy",
        "system_prompt": "Detailed instructions. " * 200,
        "_codex_item_id": "spawn-1",
    }
    page.evaluate(
        """([payload]) => {
            addChatEntry(
                'tool',
                `mcp__orchestra__spawn_worker: ${JSON.stringify(payload)}`,
                null,
                null,
                {tool_use_id: 'spawn-1'}
            );
            addChatEntry(
                'tool_result',
                "Worker 'mobile-os-strategy' spawned. Model: gpt-5.6-sol. Task sent.",
                null,
                null,
                {tool_use_id: 'spawn-1'}
            );
        }""",
        [payload],
    )

    card = page.locator("#chat .codex-tool-card")
    expect(card).to_have_count(1)
    expect(card.locator(".codex-tool-title")).to_have_text(
        "mobile-os-strategy spawned"
    )
    expect(card.locator(".codex-tool-state")).to_have_text("done")
    expect(card).to_contain_text("GPT-5.6 Sol")
    expect(card).to_contain_text("Research an AOSP-first product strategy.")
    assert '"system_prompt"' not in card.inner_text()
    page.close()


def test_codex_file_change_renders_structured_kind(
    dashboard_browser: Browser,
):
    page = _open_tool_fixture_page(dashboard_browser)
    page.evaluate("""() => {
        addChatEntry(
            'tool',
            JSON.stringify({
                changes: [{
                    path: '/tmp/project/example.js',
                    kind: {type: 'update', move_path: null},
                    diff: '@@ -1 +1 @@\\n-old\\n+new\\n',
                }],
                _codex_item_id: 'change-1',
            }).replace(/^/, 'FileChange: '),
            null,
            null,
            {tool_use_id: 'change-1'}
        );
    }""")

    card = page.locator("#chat .codex-tool-card")
    expect(card.locator(".codex-change-kind")).to_have_text("update")
    expect(card).not_to_contain_text("[object Object]")
    expect(card).to_contain_text("+new")
    page.close()


def test_codex_view_image_loads_eagerly(
    dashboard_browser: Browser,
):
    page = _open_tool_fixture_page(dashboard_browser)
    image_path = str((Path(__file__).parents[1] / "docs/dashboard.png").resolve())
    requests = 0

    def fail_first_image_request(route):
        nonlocal requests
        requests += 1
        if requests == 1:
            route.fulfill(status=404)
        else:
            route.continue_()

    page.route("**/api/files/raw?**", fail_first_image_request)
    page.evaluate(
        """([imagePath]) => {
            addChatEntry(
                'tool',
                `ViewImage: ${JSON.stringify({
                    file_path: imagePath,
                    _codex_item_id: 'image-1',
                })}`,
                null,
                null,
                {tool_use_id: 'image-1'}
            );
        }""",
        [image_path],
    )

    image = page.locator("#chat .codex-tool-image")
    expect(image).to_have_attribute("loading", "eager")
    expect(image).to_have_class("codex-tool-image codex-tool-image-error")
    page.evaluate(
        """([imagePath]) => {
            addChatEntry(
                'tool_result',
                JSON.stringify({status: 'viewed', file_path: imagePath}),
                null,
                null,
                {tool_use_id: 'image-1'}
            );
        }""",
        [image_path],
    )

    page.wait_for_function(
        "() => document.querySelector('#chat .codex-tool-image')?.naturalWidth > 0"
    )
    assert image.evaluate("(img) => img.naturalWidth") == 2800
    assert requests == 2
    expect(image).not_to_have_class("codex-tool-image-error")
    page.close()


def test_truncated_read_image_restores_full_log_when_source_file_is_gone(
    dashboard_browser: Browser,
):
    root = Path(__file__).parent.parent
    source = (root / "app/static/js/app.js").read_text()
    page = dashboard_browser.new_page()
    png = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    requests = {"file": 0, "log": []}

    def missing_source(route):
        requests["file"] += 1
        route.fulfill(status=404)

    def full_log(route):
        log_id = int(route.request.url.rsplit("/", 1)[-1])
        requests["log"].append(log_id)
        image_data = png + " " * 20 if log_id == 42 else "A" * 120
        route.fulfill(
            status=200,
            content_type="application/json",
            json={
                "id": log_id,
                "type": "tool_result",
                "content": (
                    "{'type': 'image', 'source': {'type': 'base64', 'data': '"
                    + image_data
                    + "', 'media_type': 'image/png'}}"
                ),
            },
        )

    page.route("**/api/files/raw?**", missing_source)
    page.route(re.compile(r".*/api/logs/\d+$"), full_log)
    page.route(
        "**/static/js/app.js*",
        lambda route: route.fulfill(
            status=200, content_type="text/javascript", body=source,
        ),
    )
    _goto_dashboard(page)
    page.wait_for_function("() => typeof _restoreToolResultImage === 'function'")
    page.wait_for_function(
        "() => typeof selectedAgent !== 'undefined' && selectedAgent !== null"
    )
    page.evaluate(
        """() => {
            selectedAgent = null;
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
            window.compactMode = false;
            document.querySelector('#chat').innerHTML = '';
            addChatEntry(
                'tool',
                'Read: {"file_path":"/tmp/already-gone.png"}',
                null, null, {tool_use_id: 'read-1'}
            );
            addChatEntry(
                'tool_result',
                "{'type': 'image', 'source': {'type': 'base64', 'data': 'cut",
                null, null,
                {id: 42, trunc: 50000, tool_use_id: 'read-1'}
            );
        }"""
    )

    page.wait_for_timeout(1000)
    state = page.evaluate(
        """() => ({
            html: $('#chat').innerHTML,
            src: $('#chat img')?.src,
            width: $('#chat img')?.naturalWidth,
        })"""
    )
    image = page.locator("#chat img")
    assert state["width"] == 1, (state, requests)
    assert image.evaluate("img => [img.naturalWidth, img.naturalHeight]") == [1, 1]
    expect(page.locator("#chat")).not_to_contain_text("[Image result]")
    assert requests == {"file": 1, "log": [42]}

    page.evaluate(
        """() => {
            document.querySelector('#chat').innerHTML = '';
            addChatEntry(
                'tool',
                'Read: {"file_path":"/tmp/already-gone.png"}',
                null, null, {tool_use_id: 'read-2'}
            );
            addChatEntry(
                'tool_result',
                "{'type': 'image', 'source': {'type': 'base64', 'data': '"
                    + 'A'.repeat(120) + "', 'media_type': 'image/png'}}",
                null, null, {id: 42, tool_use_id: 'read-2'}
            );
        }"""
    )
    page.wait_for_function("() => $('#chat img')?.naturalWidth === 1")
    assert requests == {"file": 2, "log": [42, 42]}

    page.evaluate(
        """() => {
            document.querySelector('#chat').innerHTML = '';
            addChatEntry(
                'tool',
                'Read: {"file_path":"/tmp/already-gone.png"}',
                null, null, {tool_use_id: 'read-3'}
            );
            addChatEntry(
                'tool_result',
                "{'type': 'image', 'source': {'type': 'base64', 'data': 'cut",
                null, null, {id: 43, trunc: 50000, tool_use_id: 'read-3'}
            );
        }"""
    )
    expect(page.locator("#chat")).to_contain_text("Image unavailable")
    assert page.locator("#chat img").count() == 0
    assert requests == {"file": 3, "log": [42, 42, 43]}
    page.close()


def test_mobile_voice_input_records_transcribes_and_cancels(dashboard_browser: Browser):
    root = Path(__file__).parent.parent
    app_source = (root / "app/static/js/app.js").read_text()
    css_source = (root / "app/static/css/style.css").read_text()
    context = dashboard_browser.new_context(
        viewport={"width": 390, "height": 844},
        is_mobile=True,
        has_touch=True,
        device_scale_factor=3,
    )
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    requests = {"transcribe": 0, "send": 0, "body": b"", "content_type": ""}
    fake_media_script = """() => {
            window.__voiceTrackStops = 0;
            window.__voiceGetUserMediaCalls = 0;
            Object.defineProperty(navigator, 'mediaDevices', {
                configurable: true,
                value: {getUserMedia: async () => {
                    window.__voiceGetUserMediaCalls++;
                    return {getTracks: () => [{stop: () => window.__voiceTrackStops++}]};
                }},
            });
            class FakeRecorder {
                static isTypeSupported(type) {
                    return type === 'audio/mp4;codecs=mp4a.40.2';
                }
                constructor(_stream, options = {}) {
                    this.mimeType = options.mimeType || 'audio/mp4';
                    this.state = 'inactive';
                    this.listeners = {};
                    window.__voiceChosenMime = this.mimeType;
                }
                addEventListener(type, callback) { this.listeners[type] = callback; }
                start() { this.state = 'recording'; }
                stop() {
                    this.state = 'inactive';
                    setTimeout(() => {
                        this.listeners.dataavailable?.({data: new Blob(['recorded'], {type: this.mimeType})});
                        this.listeners.stop?.();
                    }, 80);
                }
            }
            class FakeAudioContext {
                createMediaStreamSource() { return {connect: () => {}}; }
                createAnalyser() {
                    return {
                        fftSize: 256,
                        getByteTimeDomainData: values => {
                            values.fill(128);
                            values[0] = 255;
                        },
                    };
                }
                close() { return Promise.resolve(); }
            }
            Object.defineProperty(window, 'MediaRecorder', {configurable: true, value: FakeRecorder});
            Object.defineProperty(window, 'AudioContext', {configurable: true, value: FakeAudioContext});
        }"""

    def transcribe(route):
        requests["transcribe"] += 1
        requests["body"] = route.request.post_data_buffer or b""
        requests["content_type"] = route.request.headers.get("content-type", "")
        route.fulfill(
            status=200,
            content_type="application/json",
            json={"text": "Надиктованный текст"},
        )

    def unexpected_send(route):
        requests["send"] += 1
        route.fulfill(status=500, content_type="application/json", json={"error": "unexpected"})

    page.route("**/api/transcribe", transcribe)
    page.route("**/api/sessions/*/send", unexpected_send)
    page.route(
        "**/static/js/app.js*",
        lambda route: route.fulfill(
            status=200, content_type="text/javascript", body=app_source,
        ),
    )
    page.route(
        "**/static/css/style.css*",
        lambda route: route.fulfill(
            status=200, content_type="text/css", body=css_source,
        ),
    )
    _goto_dashboard(page)
    page.wait_for_function("() => typeof initVoiceInput === 'function'")
    page.evaluate(fake_media_script)
    expect(page.locator("#voice-btn")).to_be_visible()

    page.locator("#voice-btn").click()
    page.wait_for_timeout(500)
    state = page.locator("#voice-controls").get_attribute("data-state")
    assert state == "recording", (state, page.locator("#voice-error").text_content(), page_errors)
    page.wait_for_timeout(1100)
    minutes, seconds = map(int, page.locator("#voice-timer").text_content().split(":"))
    assert 1 <= minutes * 60 + seconds < 10
    assert float(page.locator("#voice-level").evaluate(
        "node => node.style.getPropertyValue('--voice-level')"
    )) > 1
    assert page.evaluate("window.__voiceChosenMime") == "audio/mp4;codecs=mp4a.40.2"

    page.evaluate("() => { $('#voice-btn').click(); startVoiceInput(); }")
    page.wait_for_function("() => $('#chat-input').value === 'Надиктованный текст'")
    assert page.evaluate("window.__voiceGetUserMediaCalls") == 1
    assert requests["transcribe"] == 1
    assert requests["send"] == 0
    assert "multipart/form-data; boundary=" in requests["content_type"]
    assert b'filename="voice.m4a"' in requests["body"]
    assert page.evaluate("window.__voiceTrackStops") == 1

    page.locator("#voice-btn").click()
    page.wait_for_function("() => $('#voice-controls')?.dataset.state === 'recording'")
    page.locator("#voice-cancel-btn").click()
    page.wait_for_function("() => $('#voice-controls')?.dataset.state === 'idle'")
    assert requests["transcribe"] == 1
    assert page.locator("#chat-input").input_value() == "Надиктованный текст"
    assert page.evaluate("window.__voiceTrackStops") == 2

    page.evaluate(
        """() => Object.defineProperty(navigator, 'mediaDevices', {
            configurable: true,
            value: {getUserMedia: async () => { throw new DOMException('denied', 'NotAllowedError'); }},
        })"""
    )
    page.locator("#voice-btn").click()
    expect(page.locator("#voice-error")).to_contain_text("Доступ к микрофону запрещён")
    context.close()
