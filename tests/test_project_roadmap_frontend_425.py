"""Frozen RED browser acceptance oracle for #425 concept 01."""

from __future__ import annotations

from pathlib import Path

import pytest


def _task(
    par: int,
    title: str,
    status: str,
    *,
    stage: str | None = None,
    stable_id: str | None = None,
) -> dict:
    return {
        "id": par,
        "par_number": par,
        "title": title,
        "description": f"Description for {title}",
        "status": status,
        "task_namespace_id": "primary",
        "task_stable_id": stable_id or f"task-{par}",
        "stage_label": stage,
        "git_commits": "[]",
    }


def test_t3_concept_one_keeps_every_task_and_answers_wait_in_read_only_modal():
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

    root = Path(__file__).resolve().parents[1]
    styles = [
        root / "app/static/css/style.css",
        root / "app/static/css/vendor/tailwind.css",
    ]
    # Same production order as dashboard.html:8-13. In particular, marked and DOMPurify
    # are loaded before chat.js/app.js so the RED can fail only on its own roadmap seam.
    vendor_scripts = [
        root / "app/static/css/vendor/marked.min.js",
        root / "app/static/css/vendor/purify.min.js",
        root / "app/static/css/vendor/diff_match_patch.js",
        root / "app/static/css/vendor/highlight.min.js",
    ]
    app_scripts = [
        root / "app/static/js/utils.js",
        root / "app/static/js/tool-renderers.js",
        root / "app/static/js/connection.js",
        root / "app/static/js/chat.js",
        root / "app/static/js/app.js",
    ]

    queue = [_task(100 + index, f"Queue task {index + 1:02d}", "new") for index in range(96)]
    large_queue = [
        {
            **_task(300 + index, f"Large queue task {index + 1:03d}", "new"),
            "task_namespace_id": "large-ns",
        }
        for index in range(137)
    ]
    waiting = _task(
        7,
        "Decision task",
        "in_progress",
        stage="Board",
        stable_id="stable-decision",
    )
    payload = {
        "csrf_token": "csrf-425",
        "projects": [
            {
                "id": "alpha",
                "name": "Alpha Road",
                "task_namespace_id": "primary",
                "stage_order": ["Reliability", "Memory", "Board", "Delivery", "Runtime"],
                "owner": {"session_id": "owner-1", "name": "owner-visible"},
                "contributors": [{"session_id": "sub-1", "name": "sub-visible"}],
                "goal": {"objective": "Ship the reliable project road", "status": "active"},
                "tasks": [
                    _task(1, "Merged fix", "done", stage="Reliability"),
                    _task(2, "Memory work", "in_progress", stage="Memory"),
                    waiting,
                    _task(3, "Delivery next", "new", stage="Delivery"),
                    _task(4, "Cancelled experiment", "cancelled", stage="Runtime"),
                    _task(8, "Unlabelled active", "in_progress"),
                    _task(9, "Unlabelled terminal", "done"),
                    *queue,
                ],
                "waits": [
                    {
                        "id": "wait-1",
                        "question": "Which release path should we ship?",
                        "task_stable_id": "stable-decision",
                        "status": "open",
                        "response_text": None,
                        "response_delivery_state": None,
                    }
                ],
            },
            {
                "id": "zero",
                "name": "No Stages Yet",
                "task_namespace_id": "zero-ns",
                "stage_order": [],
                "owner": {"session_id": "owner-1", "name": "owner-visible"},
                "contributors": [],
                "goal": {"objective": "A valid goal without labels", "status": "active"},
                "tasks": [
                    {
                        **_task(1, "Visible without a stage", "in_progress"),
                        "task_namespace_id": "zero-ns",
                    },
                    {
                        **_task(2, "Queued without a stage", "new"),
                        "task_namespace_id": "zero-ns",
                    },
                ],
                "waits": [],
            },
            {
                "id": "large",
                "name": "No Slice Control",
                "task_namespace_id": "large-ns",
                "stage_order": [],
                "owner": {"session_id": "owner-1", "name": "owner-visible"},
                "contributors": [],
                "goal": None,
                "tasks": large_queue,
                "waits": [],
            },
        ],
    }

    html = """
      <body class="h-screen overflow-hidden flex" data-currency="₽" data-auth-enabled="true">
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
        <div id="prompt-modal" class="hidden fixed inset-0">
          <div><span id="prompt-modal-name"></span><div id="prompt-modal-body"></div></div>
        </div>
      </body>
    """

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route(
            "http://roadmap.test/",
            lambda route: route.fulfill(status=200, content_type="text/html", body=html),
        )
        page.route(
            "http://roadmap.test/api/**",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body='{"ok":true}'
            ),
        )
        page.goto("http://roadmap.test/")
        for style in styles:
            page.add_style_tag(path=str(style))
        for script in [*vendor_scripts, *app_scripts]:
            page.add_script_tag(path=str(script))

        page.evaluate(
            """payload => {
                window.__roadCalls = [];
                api = async (path, opts = {}) => {
                    window.__roadCalls.push({path, opts});
                    if (path === '/api/portfolio/projects') return payload;
                    if (path === '/api/tm/tasks/7?project=primary') {
                        return {
                            par: '7', title: 'Decision task', description: 'Read-only decision detail',
                            project: 'primary', status: 'in_progress', assignee: '', priority: 1,
                            price_rub: 0, created_at: '2026-08-31T00:00:00Z', completed_at: null,
                            commits: [{hash:'abcdef123', message:'road detail commit', date:'2026-08-31', insertions:4, deletions:1, files:2}],
                            sync_revision: 3
                        };
                    }
                    if (path === '/api/portfolio/projects/alpha/waits/wait-1/resolve') {
                        const body = JSON.parse(opts.body || '{}');
                        if (opts.method !== 'POST' || opts.headers?.['X-CSRF-Token'] !== 'csrf-425') {
                            throw new Error('wait response did not use POST + CSRF');
                        }
                        if (body.response !== 'Ship option B') throw new Error('wrong response payload');
                        return {
                            wait: {id:'wait-1', status:'open', response_text:body.response, response_delivery_state:'QUEUED'},
                            delivery: {delivery_id:'delivery-1', delivery_state:'QUEUED'}
                        };
                    }
                    throw new Error(`unexpected API call: ${path}`);
                };
                PortfolioPanel.init();
                switchLeftTab('portfolio');
                PortfolioPanel.render(payload);
            }""",
            payload,
        )

        try:
            page.wait_for_selector('#tasks-panel [data-portfolio-road="true"]', timeout=700)
        except PlaywrightTimeoutError:
            assert page_errors == [], (
                "#425 browser harness failed before its roadmap seam: " + repr(page_errors)
            )
            pytest.fail("#425 T3 missing behavior: concept-01 project road")

        panel = page.locator("#tasks-panel")
        assert "Alpha Road" in panel.inner_text()
        assert "Ship the reliable project road" in panel.inner_text()
        assert page.locator('[data-project-id="alpha"] [data-road-stage]').count() == 5
        assert "Memory work" in page.locator(
            '[data-project-id="alpha"] [data-road-stage-label="Memory"]'
        ).inner_text()
        assert "Decision task" in page.locator(
            '[data-project-id="alpha"] [data-road-stage-label="Board"]'
        ).inner_text()
        assert "Unlabelled active" in page.locator(
            '[data-project-id="alpha"] [data-road-unassigned]'
        ).inner_text()
        assert page.locator(
            '[data-project-id="alpha"] [data-road-stage-label="Memory"][data-stage-active="true"]'
        ).count() == 1
        assert page.locator(
            '[data-project-id="alpha"] [data-road-stage-label="Board"][data-stage-active="true"]'
        ).count() == 1
        assert page.locator(
            '[data-project-id="alpha"] [data-task-par="1"][data-task-status="done"]'
        ).count() == 1
        assert page.locator('[data-project-id="alpha"] [data-road-marker]').count() == 1
        assert "мы здесь" in page.locator(
            '[data-project-id="alpha"] [data-road-marker]'
        ).inner_text().lower()
        assert page.locator(
            '[data-project-id="alpha"] [data-task-stable-id="stable-decision"][data-wait-open="true"]'
        ).count() == 1
        assert "Which release path should we ship?" in panel.inner_text()

        no_stages = page.locator('[data-project-id="zero"]')
        assert "БЕЗ ЭТАПОВ" in no_stages.inner_text().upper()
        assert "Visible without a stage" in no_stages.inner_text()
        assert no_stages.locator('[data-road-marker]').count() == 1

        queue_toggle = page.locator(
            '[data-project-id="alpha"] [data-road-disclosure="queue"]'
        )
        assert queue_toggle.get_attribute("aria-expanded") == "false"
        assert "+96" in queue_toggle.inner_text()
        assert page.locator(
            '[data-project-id="alpha"] [data-road-task-kind="queue"]'
        ).count() == 0
        queue_toggle.click()
        assert page.locator(
            '[data-project-id="alpha"] [data-road-task-kind="queue"]'
        ).count() == 96

        large_toggle = page.locator(
            '[data-project-id="large"] [data-road-disclosure="queue"]'
        )
        assert "+137" in large_toggle.inner_text()
        large_toggle.click()
        large_ids = page.locator(
            '[data-project-id="large"] [data-road-task-kind="queue"]'
        ).evaluate_all(
            "elements => elements.map(element => Number(element.dataset.taskPar)).sort((a,b) => a-b)"
        )
        assert large_ids == list(range(300, 437))
        assert "Queue task 96" in panel.inner_text()

        # A normal 15-second refresh re-renders the panel; disclosure must stay open.
        page.evaluate("payload => PortfolioPanel.render(payload)", payload)
        assert page.locator(
            '[data-project-id="alpha"] [data-road-disclosure="queue"]'
        ).get_attribute("aria-expanded") == "true"
        assert page.locator(
            '[data-project-id="alpha"] [data-road-task-kind="queue"]'
        ).count() == 96

        waiting_card = page.locator(
            '[data-project-id="alpha"] [data-task-stable-id="stable-decision"]'
        )
        url_before = page.url
        waiting_card.click()
        page.wait_for_selector('#prompt-modal textarea[data-wait-response]')
        modal = page.locator("#prompt-modal")
        assert "Read-only decision detail" in modal.inner_text()
        assert "road detail commit" in modal.inner_text()
        assert "Which release path should we ship?" in modal.inner_text()
        assert modal.locator('input[name="title"], select[name="status"]').count() == 0
        modal.locator('textarea[data-wait-response]').fill("Ship option B")
        modal.locator('[data-wait-submit]').click()
        page.wait_for_function(
            "document.querySelector('#prompt-modal')?.textContent.includes('Ответ принят и отправляется')"
        )
        assert page.url == url_before
        calls = page.evaluate("window.__roadCalls")
        assert any(call["path"] == "/api/tm/tasks/7?project=primary" for call in calls)
        assert any(
            call["path"] == "/api/portfolio/projects/alpha/waits/wait-1/resolve"
            and call["opts"].get("method") == "POST"
            for call in calls
        )

        for width in (1280, 1920):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            road_metrics = page.locator('[data-project-id="alpha"] [data-road-scroll]').evaluate(
                "element => ({client: element.clientWidth, scroll: element.scrollWidth})"
            )
            assert road_metrics["client"] > 0
            assert road_metrics["scroll"] >= road_metrics["client"]

        assert page_errors == []
        browser.close()
