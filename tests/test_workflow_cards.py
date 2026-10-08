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
    assert detail["counts"] == {"running": 0, "completed": 1, "failed": 0, "pending": 0}
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
    (run_dir / "journal.jsonl").write_text("\n".join(json.dumps(row) for row in [
        {"event": "task_started", "call_key": key, "label": "Task 1"},
        {"event": "dispatched", "call_key": key, "attempt": 1},
    ]) + "\n")

    detail = bg._workflow_detail(run_id, run_dir)

    assert detail["counts"] == {"running": 1, "completed": 0, "failed": 0, "pending": 1}
    assert [task["status"] for task in detail["stages"][0]["tasks"]] == ["running", "pending"]


def test_dynamic_workflow_call_renders_detail_card_and_expands_answer(dashboard_browser):
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
    page.evaluate("""({detail, runId}) => {
        window.fetch = async url => {
            window.__workflowApiPath = String(url);
            const payload = String(url).endsWith('/results/0')
                ? {data: 'First answer expands here'}
                : detail;
            return new Response(JSON.stringify(payload), {
                status: 200, headers: {'Content-Type': 'application/json'},
            });
        };
        _watchWorkflowCard(document.querySelector('[data-tool-raw-name="mcp__orchestra__dynamic_workflow"]'), runId);
    }""", {"detail": fixture_detail, "runId": "V-776-fixture"})
    page.wait_for_function("() => window.__workflowApiPath.endsWith('/api/bg/workflows/V-776-fixture')")
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
        page.evaluate("""({runId, detail}) => {
            window.fetch = async url => {
                window.__workflowApiPath = String(url);
                return new Response(JSON.stringify(detail), {
                    status: 200, headers: {'Content-Type': 'application/json'},
                });
            };
            _watchWorkflowCard(document.querySelectorAll('[data-tool-raw-name="mcp__orchestra__dynamic_workflow"]')[3], runId);
        }""", {"runId": actual_id, "detail": actual_detail})
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
            path=str(Path(__file__).resolve().parents[1] / ".orchestra/tasks/V-776/workflow-v167.png")
        )
        page.locator("#workflow-v167-screenshot").evaluate("node => node.remove()")
    page.close()
