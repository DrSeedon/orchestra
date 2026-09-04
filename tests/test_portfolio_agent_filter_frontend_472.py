"""#472: the board asks the server for the selected orchestrator's slice."""

from __future__ import annotations

from pathlib import Path


def _harness_html(orchestrators: str) -> str:
    return f"""
      <body class="h-screen overflow-hidden flex" data-currency="₽" data-auth-enabled="true">
        <select id="orch-picker">{orchestrators}</select>
        <div id="file-panel" class="w-[250px] flex flex-col overflow-hidden">
          <div id="left-tabs" class="flex">
            <button data-left-tab="files" class="left-tab">FILES</button>
            <button data-left-tab="tasks" class="left-tab">TASKS</button>
            <button data-left-tab="jobs" class="left-tab">JOBS</button>
            <button id="open-folder-btn">FOLDER</button>
          </div>
          <div id="file-tree"></div>
          <div id="tasks-panel" class="hidden"></div>
          <div id="jobs-panel" class="hidden"></div>
        </div>
        <main id="chat-shell" class="flex-1"></main>
      </body>
    """


def test_board_requests_the_slice_of_the_selected_orchestrator():
    from playwright.sync_api import sync_playwright

    root = Path(__file__).resolve().parents[1]
    # Тот же порядок, что в dashboard.html:8-13 — иначе app.js падает на vendor-символах.
    scripts = [
        root / "app/static/css/vendor/marked.min.js",
        root / "app/static/css/vendor/purify.min.js",
        root / "app/static/css/vendor/diff_match_patch.js",
        root / "app/static/css/vendor/highlight.min.js",
        root / "app/static/js/utils.js",
        root / "app/static/js/tool-renderers.js",
        root / "app/static/js/connection.js",
        root / "app/static/js/chat.js",
        root / "app/static/js/app.js",
    ]
    options = (
        '<option value="/alpha" data-id="session-alpha" data-name="alpha-orch">alpha-orch</option>'
        '<option value="/beta" data-id="session-beta" data-name="beta-orch">beta-orch</option>'
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route(
            "http://portfolio-slice.test/",
            lambda route: route.fulfill(
                status=200, content_type="text/html", body=_harness_html(options)
            ),
        )
        page.route(
            "http://portfolio-slice.test/api/**",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body='{"ok":true}'
            ),
        )
        page.goto("http://portfolio-slice.test/")
        for script in scripts:
            page.add_script_tag(path=str(script))

        paths = page.evaluate(
            """async () => {
                const calls = [];
                api = async (path) => { calls.push(path); return {projects: []}; };
                PortfolioPanel.init();
                switchLeftTab('portfolio');
                await PortfolioPanel.load();
                document.getElementById('orch-picker').selectedIndex = 1;
                await PortfolioPanel.load();
                return calls;
            }"""
        )
        browser.close()

    assert page_errors == [], f"#472 harness broke before its seam: {page_errors!r}"
    slices = [path for path in paths if path.startswith("/api/portfolio/projects")]
    assert slices, "#472 board never asked for projects"
    # Смена оркестратора обязана менять ЗАПРОС, иначе доска рисует один и тот же проект.
    assert "agent_session_id=session-alpha" in slices[0]
    assert "agent_session_id=session-beta" in slices[-1]
