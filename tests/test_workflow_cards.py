"""Workflow detail API and chat-card rendering regression coverage."""

import json
from pathlib import Path

import pytest

pytest_plugins = ("tests.test_frontend",)


def _workflow_fixture(root: Path, run_id: str = "V-776-fixture") -> Path:
    run_dir = root / run_id
    (run_dir / "steps").mkdir(parents=True)
    (run_dir / "request.json").write_text(json.dumps({
        "mode": "parallel",
        "dashboard": {
            "task_id": "V-776", "repo": "/repo", "budget_usd": 3,
            "max_calls": 12, "max_concurrency": 5,
            "created_at": "2026-10-08T10:00:00+00:00",
        },
        "tasks": [{"label": "Task 1", "prompt": "First task", "model": "gpt-6-luna"}],
    }))
    key = "a" * 64 + ":0"
    step = {"value_id": key, "data": "First answer", "result_path": "internal path"}
    (run_dir / "steps" / f"{key.replace(':', '-')}.json").write_text(json.dumps(step))
    (run_dir / "journal.jsonl").write_text(json.dumps({
        "event": "completed", "call_key": key, "label": "Task 1",
        "reason": "completed", "value": step,
    }) + "\n")
    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": run_id, "complete": True, "partial_reason": None,
        "spent_usd": 0.25, "budget_usd": 3,
        "steps": [{"call_key": key, "label": "Task 1", "reason": "completed"}],
        "result": [step],
    }))
    return run_dir


@pytest.mark.asyncio
async def test_workflow_detail_returns_live_run_data_and_rejects_outside_paths(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routes import bg

    monkeypatch.setattr(bg, "WORKFLOW_RUNS_DIR", tmp_path)
    _workflow_fixture(tmp_path)
    outside = tmp_path.parent / "workflow-outside"
    outside.mkdir()
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    app = FastAPI()
    app.include_router(bg.router)

    with TestClient(app) as client:
        response = client.get("/api/bg/workflows/V-776-fixture")
        traversal = client.get("/api/bg/workflows/escape")
        missing = client.get("/api/bg/workflows/V-776-absent")
    detail = response.json()
    assert detail["mode"] == "parallel"
    assert detail["counts"] == {"running": 0, "waiting": 0, "completed": 1, "failed": 0, "pending": 0}
    assert detail["stages"][0]["tasks"][0]["answer_preview"] == "First answer"
    assert detail["stages"][0]["tasks"][0]["result_url"].endswith("/results/0")
    assert detail["finished"] is True

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private, max-age=0"
    assert traversal.status_code == 404
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_workflow_result_route_only_opens_a_result_from_that_run(tmp_path, monkeypatch):
    from app.routes import bg

    monkeypatch.setattr(bg, "WORKFLOW_RUNS_DIR", tmp_path)
    _workflow_fixture(tmp_path)

    result = await bg.bg_workflow_result("V-776-fixture", 0)
    assert json.loads(result.body)["data"] == "First answer"
    missing = await bg.bg_workflow_result("V-776-fixture", 1)
    assert missing.status_code == 404


def test_workflow_detail_maps_journal_progress_to_labeled_tasks(tmp_path, monkeypatch):
    from app.routes import bg

    run_id = "V-776-active"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    monkeypatch.setattr(bg, "WORKFLOW_RUNS_DIR", tmp_path)
    (run_dir / "request.json").write_text(json.dumps({
        "mode": "parallel",
        "tasks": [
            {"label": "Task 1", "prompt": "First prompt", "model": "gpt-6-luna"},
            {"label": "Task 2", "prompt": "Second prompt", "model": "gpt-6-luna"},
        ],
    }))
    key = "b" * 64 + ":0"
    waiting_key = "c" * 64 + ":0"
    (run_dir / "journal.jsonl").write_text("\n".join(json.dumps(row) for row in [
        {"event": "task_started", "call_key": key, "label": "Task 1"},
        {"event": "dispatched", "call_key": key, "attempt": 1},
        {"event": "task_started", "call_key": waiting_key, "label": "Task 2"},
        {"event": "slot_waiting", "reason": "slot_waiting", "call_key": waiting_key,
         "label": "Task 2", "position": 3, "limit": 2, "scheduler_reason": "CPU pressure"},
    ]) + "\n")
    (run_dir / "manifest.json").write_text(json.dumps({
        "scheduler": {"active": 2, "limit": 2, "reason": "CPU pressure"},
    }))

    detail = bg._workflow_detail(run_id, run_dir)

    assert detail["counts"] == {"running": 1, "waiting": 1, "completed": 0, "failed": 0, "pending": 0}
    assert [task["status"] for task in detail["stages"][0]["tasks"]] == ["running", "waiting"]
    assert detail["stages"][0]["tasks"][1]["position"] == 3
    assert detail["scheduler"] == {"active": 2, "limit": 2, "reason": "CPU pressure"}


def test_intermediate_scheduler_manifest_does_not_mark_workflow_finished(tmp_path):
    from app.routes.bg import _workflow_finished

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "journal.jsonl").write_text('{"event":"slot_waiting"}\n')
    (run_dir / "manifest.json").write_text(json.dumps({"finished": False, "complete": False}))
    assert _workflow_finished(run_dir) is False


def test_workflow_fixture_preserves_refresh_when_unrelated_get_follows(dashboard_browser):
    from playwright.sync_api import expect

    source_root = Path(__file__).resolve().parents[1]
    app_source = (source_root / 'app/static/js/app.js').read_text()
    chat_source = (source_root / 'app/static/js/chat.js').read_text()
    polling = app_source[app_source.index('const _POLL_MAX_BACKOFF_MS'):app_source.index('function scheduleRefresh()')]
    api = app_source[app_source.index('const _API_TIMEOUT_MS'):app_source.index('// === Rate Limit Banner')]
    workflow = chat_source[chat_source.index('function _workflowModeLabel('):chat_source.index('function _renderFullToolCall(')]
    page = dashboard_browser.new_page()
    try:
        page.route('http://workflow.test/**', lambda route: route.fulfill(
            status=200, content_type='application/json', body='{"background":true}',
        ))
        page.goto('http://workflow.test/')
        page.set_content('<div data-tool-raw-name="mcp__orchestra__dynamic_workflow" data-workflow-mode="parallel">'
                         '<div data-role="workflow-status"></div><div data-role="workflow-detail"></div></div>')
        page.add_script_tag(content="""
            const MODEL_COST_CURRENCY = '$';
            const _modelLabel = model => model;
            const modelColorVar = () => 'gray';
            const orchLocale = () => 'en-US';
            const T = (text, values = {}) => Object.entries(values).reduce(
                (value, [key, replacement]) => value.replaceAll(`{${key}}`, replacement), text);
            const Connection = {observe(){}, ok(){}, fail(){}, restartFromBody(){return false;}};
            let selectedAgent = null;
            let currentScope = null;
            let eventSource = null;
            window.backgroundRequests = [];
            const baseFetch = window.fetch.bind(window);
            window.fetch = (url, options) => {
                window.backgroundRequests.push(String(url));
                return baseFetch(url, options);
            };
        """)
        page.add_script_tag(content=polling + api + workflow)
        page.evaluate("""() => {
            _initPollingVisibility();
            Object.defineProperty(document, 'hidden', {configurable:true, value:true});
            document.dispatchEvent(new Event('visibilitychange'));
        }""")
        detail = dict(available=True, finished=True, complete=True, spent_usd=0.25,
                      budget_usd=3, counts=dict(completed=1), stages=[dict(index=0, tasks=[dict(
                          status='completed', label='Task 1', model='hub-gpt-6.1-sol',
                          answer_preview='First answer expands here',
                          result_url='/api/bg/workflows/V-776-fixture/results/0',
                      )])])
        _watch_workflow_fixture(page, detail, 'V-776-fixture')
        expect(page.locator('[data-role="workflow-detail"]')).to_contain_text('Task 1')
        requests_before = page.evaluate('window.__workflowApiRequests.slice()')
        assert requests_before == ['/api/bg/workflows/V-776-fixture']

        # A real, later unrelated GET must keep its own response and cannot erase
        # proof that this card fetched its detail, even while polling is hidden.
        assert page.evaluate("api('/api/background-fixture')") == {'background': True}
        assert page.evaluate('window.backgroundRequests') == ['/api/background-fixture']
        assert page.evaluate('window.__workflowApiRequests') == requests_before
        assert page.evaluate('_pollCanRun()') is False
        assert page.evaluate('_pollTimers.size') == 0
        answer = page.locator('details')
        answer.locator('summary').click()
        expect(answer.locator('pre')).to_have_text('First answer expands here')
        assert page.evaluate('window.__workflowApiRequests') == requests_before + [
            '/api/bg/workflows/V-776-fixture/results/0',
        ]
    finally:
        page.close()


def _watch_workflow_fixture(page, detail, run_id, card_index=0):
    page.evaluate("""({detail, runId, cardIndex}) => {
        const fallbackFetch = window.fetch.bind(window);
        const detailPath = `/api/bg/workflows/${encodeURIComponent(runId)}`;
        const requests = [];
        window.__workflowApiRequests = requests;
        window.fetch = async (url, options) => {
            const path = new URL(String(url), location.href).pathname;
            if (path !== detailPath && path !== `${detailPath}/results/0`) {
                return fallbackFetch(url, options);
            }
            requests.push(path);
            const payload = path === `${detailPath}/results/0`
                ? {data: 'First answer expands here'}
                : detail;
            return new Response(JSON.stringify(payload), {
                status: 200, headers: {'Content-Type': 'application/json'},
            });
        };
        _watchWorkflowCard(document.querySelectorAll('[data-tool-raw-name="mcp__orchestra__dynamic_workflow"]')[cardIndex], runId);
    }""", {"detail": detail, "runId": run_id, "cardIndex": card_index})


def test_dynamic_workflow_call_renders_detail_card_and_expands_answer(dashboard_browser, tmp_path):
    import shlex

    from playwright.sync_api import expect

    from tests.test_frontend import _goto_dashboard, _repo_scope, _route_frontend_sources

    actual_id = "V-167-3df7f2f85763"
    actual_dir = Path(_repo_scope()) / "data" / "workflow-runs" / actual_id
    actual_detail = None
    actual_request = None
    actual_repo = ""
    if actual_dir.is_dir():
        from app.routes.bg import _workflow_detail

        actual_request = json.loads((actual_dir / "request.json").read_text())
        actual_detail = _workflow_detail(actual_id, actual_dir)
        manifest = json.loads((actual_dir / "manifest.json").read_text())
        command = shlex.split(manifest.get("resume_command") or "")
        if "--repo" in command:
            actual_repo = command[command.index("--repo") + 1]

    page = dashboard_browser.new_page()
    page.set_default_navigation_timeout(120_000)
    _route_frontend_sources(page)
    _goto_dashboard(page)
    page.wait_for_function("() => typeof addChatEntry === 'function'")
    page.evaluate("""() => {
        Object.defineProperty(document, 'hidden', {configurable: true, value: true});
        document.dispatchEvent(new Event('visibilitychange'));
    }""")
    page.wait_for_function(
        "() => !_pollCanRun() && !refreshInProgress && _pollTimers.size === 0 && _pollInFlight.size === 0",
        timeout=10_000,
    )
    page.evaluate("""() => {
        selectedAgent = null;
        if (eventSource) { eventSource.close(); eventSource = null; }
        window.compactMode = false;
        document.querySelector('#chat').innerHTML = '';
    }""")
    fixture_detail = {
        "run_id": "V-776-fixture", "mode": "parallel", "task_id": "V-776",
        "repo": "/repo", "budget_usd": 3, "max_calls": 12,
        "max_concurrency": 5, "spent_usd": 0.25, "complete": True, "available": True,
        "finished": True, "elapsed_seconds": 14,
        "counts": {"running": 0, "completed": 1, "failed": 0, "pending": 0},
        "stages": [{"index": 0, "tasks": [{
            "index": 0, "global_index": 0, "label": "Task 1",
            "prompt": "First task prompt", "model": "gpt-6-luna",
            "status": "completed", "answer_preview": "First answer expands here",
            "result_url": "/api/bg/workflows/V-776-fixture/results/0",
        }]}],
    }
    tool_id = "workflow-card-fixture"
    page.evaluate("""toolId => {
        addChatEntry('tool', 'mcp__orchestra__dynamic_workflow: ' + JSON.stringify({
            budget_usd: 3, max_calls: 12, max_concurrency: 5,
            task_id: 'V-776', repo: '/repo', mode: 'parallel',
            tasks: [{prompt: 'First task prompt', model: 'luna'}],
        }), null, null, {tool_use_id: toolId});
    }""", tool_id)
    card = page.locator('[data-tool-raw-name="mcp__orchestra__dynamic_workflow"]')
    _watch_workflow_fixture(page, fixture_detail, "V-776-fixture")
    page.wait_for_function("() => window.__workflowApiRequests.includes('/api/bg/workflows/V-776-fixture')")
    expect(card).to_contain_text("Parallel")
    expect(card).to_contain_text("First task prompt")
    expect(card).to_contain_text("1/1 ready")
    expect(card).to_contain_text("$0.25 / $3.00")
    answer = card.locator("details").filter(has_text="Answer:")
    expect(answer).to_contain_text("First answer expands here")
    answer.locator("summary").click()
    expect(answer.locator("pre")).to_contain_text("First answer expands here")
    expect(card.get_by_role("link", name="📎 Open result file")).to_have_attribute(
        "href", "/api/bg/workflows/V-776-fixture/results/0",
    )
    page.evaluate("""card => {
        window.fetch = async () => new Response('{"error":"not found"}', {status: 404});
        return _refreshWorkflowCard(card, 'V-776-missing');
    }""", card.element_handle())
    expect(card).to_contain_text("Run files unavailable")
    expect(card).to_contain_text("First task prompt")

    shared = "Прочитай файл с расчётом и выполни независимую проверку результата. " + "Общие инструкции. " * 10
    repeated = [f"Номер прогона: {8401 + index}. {shared}" for index in range(10)]
    page.evaluate("""prompts => addChatEntry('tool', 'mcp__orchestra__dynamic_workflow: ' + JSON.stringify({
        budget_usd: 3, max_calls: 12, max_concurrency: 5, task_id: 'V-167', repo: '/repo',
        mode: 'parallel', tasks: prompts.map(prompt => ({prompt, model: 'luna'})),
    }), null, null, {tool_use_id: 'workflow-repeat'});""", repeated)
    compact_card = page.locator('[data-tool-raw-name="mcp__orchestra__dynamic_workflow"]').nth(1)
    expect(compact_card).to_contain_text("×10")
    expect(compact_card).to_contain_text("8401")
    expect(compact_card).to_contain_text("8410")
    rendered_text = compact_card.inner_text()
    assert rendered_text.count(shared[:45]) == 1

    page.evaluate("""() => addChatEntry('tool', 'mcp__orchestra__dynamic_workflow: ' + JSON.stringify({
        budget_usd: 1, max_calls: 10, max_concurrency: 5, task_id: 'V-167', repo: '/repo',
        mode: 'stages', stages: [{prompt: 'Номер прогона: {item}. Прочитай общий файл и проверь итог.',
            items: [8401, 8402, 8403, 8404, 8405, 8406, 8407, 8408, 8409, 8410]}],
    }), null, null, {tool_use_id: 'workflow-items'});""")
    item_card = page.locator('[data-tool-raw-name="mcp__orchestra__dynamic_workflow"]').nth(2)
    expect(item_card).to_contain_text("Items:")
    expect(item_card).to_contain_text("×10")
    expect(item_card).to_contain_text("8410")
    assert item_card.inner_text().count("Прочитай общий файл") == 1

    if actual_detail and actual_request:
        actual_tool_id = "workflow-v167-real"
        args = {
            "budget_usd": 3, "max_calls": 12, "max_concurrency": 5,
            "task_id": "V-167", "repo": actual_repo, "mode": actual_request["mode"],
            "tasks": actual_request.get("tasks", []),
        }
        page.evaluate("""({toolId, args, runId}) => {
            addChatEntry('tool', 'mcp__orchestra__dynamic_workflow: ' + JSON.stringify(args),
                null, null, {tool_use_id: toolId});
        }""", {"toolId": actual_tool_id, "args": args, "runId": actual_id})
        real_card = page.locator('[data-tool-raw-name="mcp__orchestra__dynamic_workflow"]').nth(3)
        _watch_workflow_fixture(page, actual_detail, actual_id, card_index=3)
        expect(real_card).to_contain_text("8410")
        expect(real_card).to_contain_text("failed")
        page.evaluate("""() => {
            const card = document.querySelectorAll('[data-tool-raw-name="mcp__orchestra__dynamic_workflow"]')[3];
            const clone = card.cloneNode(true);
            clone.id = 'workflow-v167-screenshot';
            clone.style.cssText = 'position:fixed;top:8px;left:8px;width:900px;max-height:none;overflow:visible;z-index:99999;background:#0b1120';
            document.body.appendChild(clone);
        }""")
        page.locator("#workflow-v167-screenshot").screenshot(
            path=str(tmp_path / "workflow-v167.png")
        )
        page.locator("#workflow-v167-screenshot").evaluate("node => node.remove()")
    page.close()
