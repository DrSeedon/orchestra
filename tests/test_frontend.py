"""Playwright smoke tests for Orchestra dashboard.

Requires: Orchestra running on localhost:8888 (no auth).
Run: pytest tests/test_frontend.py -v
"""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright

BASE = os.environ.get("ORCHESTRA_TEST_BASE", "http://localhost:8888")
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


@pytest.fixture(scope="module")
def dashboard_browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture(scope="module")
def dashboard_page(dashboard_browser: Browser):
    page = dashboard_browser.new_page()
    resp = page.goto(BASE, wait_until="domcontentloaded")
    assert resp.status == 200
    expect(page.locator("#agent-list")).to_be_visible()
    yield page
    page.close()


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


def test_bug_report_banner_is_compact_overlay_with_safe_reader_contract():
    root = Path(__file__).parent.parent
    template = (root / "app/templates/dashboard.html").read_text()
    source = (root / "app/static/js/app.js").read_text()
    banner_tag = template.split('id="bug-report-banner"', 1)[1].split(">", 1)[0]
    block = source.split("const _BUG_INBOX_SEEN_KEY", 1)[1].split(
        "document.addEventListener('DOMContentLoaded'", 1,
    )[0]

    assert "fixed" in banner_tag
    assert "top-12" in banner_tag
    assert "DOMPurify.sanitize(marked.parse(markdown))" in block
    assert "await response.text()" in block
    assert block.index("await _fetchBugInbox(viewUrl)") < block.index(
        "localStorage.setItem(_BUG_INBOX_SEEN_KEY, version)"
    )
    assert "setInterval(_refreshBugReportStatus, 30000)" in block
    assert "initBugReportBanner();" in source


def test_bug_report_banner_acknowledges_only_complete_sanitized_read(
    dashboard_browser: Browser,
):
    root = Path(__file__).parent.parent
    source = (root / "app/static/js/app.js").read_text()
    block = "const _BUG_INBOX_SEEN_KEY" + source.split(
        "const _BUG_INBOX_SEEN_KEY", 1,
    )[1].split("document.addEventListener('DOMContentLoaded'", 1)[0]
    page = dashboard_browser.new_page()
    page.route(
        "http://orchestra.test/",
        lambda route: route.fulfill(
            content_type="text/html",
            body='<div id="bug-report-banner" class="hidden"></div>',
        ),
    )
    page.goto("http://orchestra.test/")
    page.add_script_tag(path=str(root / "app/static/css/vendor/purify.min.js"))
    page.add_script_tag(path=str(root / "app/static/css/vendor/marked.min.js"))
    page.evaluate("""
        window._bugResponses = [];
        window.fetch = async () => {
            const item = window._bugResponses.shift();
            return {ok: item.ok, status: item.status, text: async () => item.body};
        };
        window.open = () => {
            const reader = {
                document: document.implementation.createHTMLDocument(''),
                opener: window,
                closed: false,
                close() { this.closed = true; },
            };
            window._bugReader = reader;
            return reader;
        };
    """)
    page.add_script_tag(content=block)
    page.evaluate("""
        window._bugResponses.push({
            ok: true,
            status: 200,
            body: JSON.stringify({
                has_reports: true,
                version: 'v1',
                view_url: '/api/report_bug',
            }),
        });
    """)
    page.evaluate("() => _refreshBugReportStatus()")

    expect(page.locator("#bug-report-banner")).to_contain_text("Новые bug reports")
    assert page.evaluate("localStorage.getItem('orchestraBugInboxSeenVersion')") is None

    page.evaluate("""
        window._bugResponses.push({
            ok: true,
            status: 200,
            body: '# Report\\n<img src=x onerror="window.pwned=1"><script>window.pwned=2</script>',
        });
    """)
    page.get_by_role("button", name="Прочитать").click()
    page.wait_for_function(
        "localStorage.getItem('orchestraBugInboxSeenVersion') === 'v1'",
    )

    rendered = page.evaluate("window._bugReader.document.body.innerHTML")
    assert "<script" not in rendered
    assert "onerror" not in rendered
    assert page.evaluate("window.pwned") is None

    page.evaluate("""
        window._bugResponses.push({
            ok: true,
            status: 200,
            body: JSON.stringify({
                has_reports: true,
                version: 'v2',
                view_url: '/api/report_bug',
            }),
        });
    """)
    page.evaluate("() => _refreshBugReportStatus()")
    page.evaluate("""
        window._bugResponses.push({
            ok: false,
            status: 500,
            body: '<b>ReadTimeout</b>',
        });
    """)
    page.get_by_role("button", name="Прочитать").click()
    expect(page.locator("#bug-report-banner")).to_contain_text("HTTP500")
    assert page.evaluate(
        "localStorage.getItem('orchestraBugInboxSeenVersion')"
    ) == "v1"
    assert page.evaluate("window._bugReader.closed") is True
    page.close()


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


def test_header_has_orch_tabs(dashboard_page: Page):
    tabs = dashboard_page.locator("#orch-tabs")
    expect(tabs).to_be_visible()


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
            await new Promise(resolve => setTimeout(resolve, 100));
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
    assert "blocked.py: file type .py not allowed" in partial_failure["error"]


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
    page.goto(BASE, wait_until="domcontentloaded")
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
    page.goto(BASE, wait_until="domcontentloaded")
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
    api_page = dashboard_browser.new_page()
    response = api_page.request.get(
        f"{BASE}/api/tm/tasks/112",
        params={"scope": "/mnt/data/Projects/Python/orchestra"},
    )
    assert response.status == 200
    task = response.json()
    api_page.close()
    assert len(task["description"]) > 180
    task.update({"assignee": "frontend", "task_id": 987})

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
    assert "localStorage" not in helper_code
    assert "sessionStorage" in helper_code
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
