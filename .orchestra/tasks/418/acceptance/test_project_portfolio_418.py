"""Frozen RED acceptance oracles for #418 project portfolio tickets."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _init_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app import db

    isolated_path = tmp_path / "portfolio-oracle.sqlite"
    production_path = db._DEFAULT_DB_PATH.resolve()
    real_connect = sqlite3.connect

    def guarded_connect(database, *args, **kwargs):
        raw = str(database)
        if raw.startswith("file:"):
            raw = raw.removeprefix("file:").split("?", 1)[0]
        if raw != ":memory:" and Path(raw).resolve() == production_path:
            raise AssertionError(f"#418 oracle attempted production DB: {production_path}")
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(db, "DB_PATH", isolated_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(isolated_path))
    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
    db.init_db()
    assert db.DB_PATH == isolated_path
    assert isolated_path.is_file()
    return db


def _save_session(
    db,
    name: str,
    *,
    role: str,
    parent_id: str = "",
    parent_name: str = "",
    scope: str = "/portfolio-home",
) -> tuple[str, str]:
    session_id = str(uuid.uuid4())
    durable_name = f"{name}-{session_id[:8]}"
    db.save_session(
        {
            "id": session_id,
            "name": durable_name,
            "scope": scope,
            "cwd": scope,
            "model": "claude-opus-5[1m]",
            "system_prompt": "",
            "status": "idle",
            "session_id": None,
            "cost_usd": 0.0,
            "worktree_path": "",
            "branch": "",
            "base_branch": "main",
            "is_orchestrator": role in {"orchestrator", "sub-orchestrator"},
            "color": "",
            "role": role,
            "parent_id": parent_id,
            "parent_name": parent_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "task_id": "",
            "needs_switch": 0,
        }
    )
    return session_id, durable_name


def _production_paths() -> set[str]:
    from app.main import app

    return {getattr(route, "path", "") for route in app.routes}


def _portfolio_app(required_path: str) -> FastAPI:
    assert required_path in _production_paths(), f"#418 missing portfolio route: {required_path}"
    module = importlib.import_module("app.routes.portfolio")
    app = FastAPI()
    app.include_router(module.router)
    return app


def _headers(session_id: str) -> dict[str, str]:
    return {"x-orchestra-session-id": session_id}


def _create_project(client: TestClient, owner_id: str, project_id: str = "alpha") -> dict:
    response = client.post(
        "/api/portfolio/projects",
        headers=_headers(owner_id),
        json={"id": project_id, "name": project_id.title()},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_contributor(client: TestClient, owner_id: str, project_id: str, sub_id: str):
    response = client.post(
        f"/api/portfolio/projects/{project_id}/members",
        headers=_headers(owner_id),
        json={"session_id": sub_id, "role": "contributor"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _seed_namespace(tm, namespace: str, scope: str) -> None:
    with tm._conn() as connection:
        tm.ensure_project(connection, namespace, name=namespace, scope=scope)


def test_t1_project_foundation_preserves_tasks_and_enforces_membership_goal_wait(
    tmp_path, monkeypatch
):
    db = _init_db(tmp_path, monkeypatch)
    owner, owner_name = _save_session(db, "owner", role="orchestrator")
    sub, _ = _save_session(
        db, "sub", role="sub-orchestrator", parent_id=owner, parent_name=owner_name
    )
    helper, _ = _save_session(
        db, "helper", role="sub-orchestrator", parent_id=owner, parent_name=owner_name
    )
    worker, _ = _save_session(
        db, "worker", role="worker", parent_id=owner, parent_name=owner_name
    )
    outsider, outsider_name = _save_session(
        db, "outsider", role="orchestrator", scope="/other"
    )

    app = _portfolio_app("/api/portfolio/projects")
    with TestClient(app) as client:
        first = _create_project(client, owner)
        assert first["owner_session_id"] == owner
        assert first["scope"] is None
        assert _create_project(client, owner, "beta")["owner_session_id"] == owner

        _add_contributor(client, owner, "alpha", sub)
        _add_contributor(client, owner, "alpha", helper)
        assert client.get(
            "/api/portfolio/projects/alpha", headers=_headers(sub)
        ).status_code == 200
        assert client.get(
            "/api/portfolio/projects/alpha", headers=_headers(outsider)
        ).status_code == 403

        worker_grant = client.post(
            "/api/portfolio/projects/alpha/members",
            headers=_headers(owner),
            json={"session_id": worker, "role": "contributor"},
        )
        assert worker_grant.status_code == 422, worker_grant.text
        sub_owner = client.post(
            "/api/portfolio/projects/alpha/members",
            headers=_headers(owner),
            json={"session_id": sub, "role": "owner"},
        )
        assert sub_owner.status_code == 422, sub_owner.text
        second_owner = client.post(
            "/api/portfolio/projects/alpha/members",
            headers=_headers(owner),
            json={"session_id": outsider, "role": "owner"},
        )
        assert second_owner.status_code == 409, second_owner.text

        respawned_sub, _ = _save_session(
            db, "sub", role="sub-orchestrator", parent_id=owner, parent_name=owner_name
        )
        assert client.get(
            "/api/portfolio/projects/alpha", headers=_headers(respawned_sub)
        ).status_code == 403

        with db._conn() as connection:
            connection.execute(
                "UPDATE sessions SET parent_id=?,parent_name=? WHERE id=?",
                (outsider, outsider_name, sub),
            )
        assert client.get(
            "/api/portfolio/projects/alpha", headers=_headers(sub)
        ).status_code == 403

        from app import tm

        _seed_namespace(tm, "namespace", "/portfolio-home")
        _seed_namespace(tm, "foreign", "/foreign")
        linked_task = tm.api_create_task("namespace", "Linked task")
        unlinked_task = tm.api_create_task("namespace", "Unlinked task")
        foreign_task = tm.api_create_task("foreign", "Foreign task")

        linked = client.post(
            "/api/portfolio/projects/alpha/tasks",
            headers=_headers(owner),
            json={"task_project": "namespace", "task_ref": linked_task["par"]},
        )
        assert linked.status_code == 201, linked.text
        denied_link = client.post(
            "/api/portfolio/projects/alpha/tasks",
            headers=_headers(owner),
            json={"task_project": "foreign", "task_ref": foreign_task["par"]},
        )
        assert denied_link.status_code == 403, denied_link.text

        bound = tm.bind_task_to_session("/portfolio-home", worker, linked_task["par"])
        assert bound["project_id"] == "namespace"
        assert bound["worker_session_id"] == worker
        project_tasks = client.get(
            "/api/portfolio/projects/alpha/tasks", headers=_headers(owner)
        ).json()["tasks"]
        assert {task["title"] for task in project_tasks} == {"Linked task"}
        assert tm.api_get_task(unlinked_task["par"], project="namespace")["project"] == "namespace"

        empty_goal = client.get(
            "/api/portfolio/projects/alpha/goal", headers=_headers(owner)
        )
        assert empty_goal.status_code == 200 and empty_goal.json()["goal"] is None
        created = client.post(
            "/api/portfolio/projects/alpha/goals",
            headers=_headers(owner),
            json={"objective": "Ship Alpha", "watchdog_enabled": False},
        )
        assert created.status_code == 201, created.text
        goal = created.json()
        assert goal["status"] == "active" and goal["watchdog_enabled"] is False

        progress = client.post(
            f"/api/portfolio/projects/alpha/goals/{goal['id']}/progress",
            headers=_headers(helper),
            json={"note": "Checkpoint reached"},
        )
        assert progress.status_code == 200, progress.text
        denied_policy = client.patch(
            f"/api/portfolio/projects/alpha/goals/{goal['id']}",
            headers=_headers(helper),
            json={"watchdog_enabled": True},
        )
        assert denied_policy.status_code == 403, denied_policy.text

    def open_wait() -> tuple[int, dict]:
        with TestClient(app) as concurrent_client:
            response = concurrent_client.post(
                "/api/portfolio/projects/alpha/waits",
                headers=_headers(helper),
                json={"question": "Choose A or B"},
            )
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_wait, second_wait = list(pool.map(lambda _: open_wait(), range(2)))
    assert first_wait[0] in {200, 201} and second_wait[0] in {200, 201}
    assert first_wait[1]["id"] == second_wait[1]["id"]
    with TestClient(app) as client:
        waits = client.get(
            "/api/portfolio/projects/alpha/waits", headers=_headers(owner)
        ).json()["waits"]
    assert [wait["question"] for wait in waits] == ["Choose A or B"]


@pytest.mark.asyncio
async def test_t2_watchdog_goal_only_atomic_claim_and_retry_reuse_delivery_id(
    tmp_path, monkeypatch
):
    db = _init_db(tmp_path, monkeypatch)
    spec = importlib.util.find_spec("app.portfolio_watchdog")
    assert spec is not None, "#418 T2 missing behavior: app.portfolio_watchdog"
    watchdog = importlib.import_module("app.portfolio_watchdog")
    evaluate_once = getattr(watchdog, "evaluate_once", None)
    assert callable(evaluate_once), "#418 T2 missing behavior: evaluate_once"

    owner, _ = _save_session(db, "owner", role="orchestrator")
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    app = _portfolio_app("/api/portfolio/projects/{project_id}/goals")
    with TestClient(app) as client:
        _create_project(client, owner)
        goal = client.post(
            "/api/portfolio/projects/alpha/goals",
            headers=_headers(owner),
            json={
                "objective": "Goal-only project must advance",
                "watchdog_enabled": True,
                "now": (now - timedelta(minutes=31)).isoformat(),
            },
        ).json()

    entered = asyncio.Event()
    release = asyncio.Event()
    deliveries: list[dict] = []

    async def slow_deliver(payload: dict) -> str:
        deliveries.append(payload)
        entered.set()
        await release.wait()
        return "accepted-1"

    first_run = asyncio.create_task(evaluate_once(now=now, deliver=slow_deliver))
    await entered.wait()
    second_run = asyncio.create_task(evaluate_once(now=now, deliver=slow_deliver))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first_run, second_run)
    assert len(deliveries) == 1
    assert deliveries[0]["target_session_id"] == owner

    with TestClient(app) as client:
        assert client.post(
            f"/api/portfolio/projects/alpha/goals/{goal['id']}/progress",
            headers=_headers(owner),
            json={"note": "new generation", "now": now.isoformat()},
        ).status_code == 200

    failed_ids: list[str] = []

    async def fail_once(payload: dict) -> str:
        failed_ids.append(payload["delivery_id"])
        raise RuntimeError("transport down after durable claim")

    failed = await evaluate_once(now=now + timedelta(minutes=31), deliver=fail_once)
    assert failed["failed"] == 1
    recovered: list[str] = []

    async def recover(payload: dict) -> str:
        recovered.append(payload["delivery_id"])
        return "accepted-2"

    await evaluate_once(now=now + timedelta(minutes=36), deliver=recover)
    assert recovered == failed_ids

    with TestClient(app) as client:
        assert client.post(
            "/api/portfolio/projects/alpha/waits",
            headers=_headers(owner),
            json={"question": "Need user choice"},
        ).status_code == 201
    await evaluate_once(now=now + timedelta(minutes=67), deliver=recover)
    assert len(recovered) == 1


def test_t3_dashboard_button_opens_portfolio_panel_with_real_project_payload():
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

    root = Path(__file__).parents[4]
    app_js = root / "app/static/js/app.js"
    utils_js = root / "app/static/js/utils.js"
    connection_js = root / "app/static/js/connection.js"
    style_css = root / "app/static/css/style.css"
    vendor_js = [
        root / "app/static/css/vendor/marked.min.js",
        root / "app/static/css/vendor/purify.min.js",
        root / "app/static/css/vendor/diff_match_patch.js",
        root / "app/static/css/vendor/highlight.min.js",
    ]
    payload = {
        "projects": [
            {
                "id": "alpha",
                "name": "Alpha",
                "owner": {"session_id": "owner-1", "name": "owner-visible"},
                "contributors": [{"session_id": "sub-1", "name": "sub-visible"}],
                "goal": {"objective": "Goal visible without task dependence", "status": "active"},
                "tasks": [
                    {"id": "task-1", "title": "Linked board task", "status": "in_progress"},
                ],
                "waits": [{"id": "wait-1", "question": "Exact visible question?", "status": "open"}],
            },
            {
                "id": "goal-only",
                "name": "Goal Only",
                "owner": {"session_id": "owner-1", "name": "owner-visible"},
                "contributors": [],
                "goal": {"objective": "Goal-only project remains visible", "status": "active"},
                "tasks": [],
                "waits": [],
            },
        ]
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(
            "http://portfolio.test/",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body="""
                    <body class="bg-slate-950">
                      <div id="file-panel">
                        <div id="left-tabs">
                          <button data-left-tab="files" class="left-tab">FILES</button>
                          <button data-left-tab="tasks" class="left-tab">TASKS</button>
                          <button data-left-tab="jobs" class="left-tab">JOBS</button>
                          <button id="open-folder-btn">FOLDER</button>
                        </div>
                        <div id="file-tree"></div>
                        <div id="tasks-panel" class="hidden"></div>
                        <div id="jobs-panel" class="hidden"></div>
                      </div>
                    </body>
                """,
            ),
        )
        page.goto("http://portfolio.test/")
        page.add_style_tag(path=str(style_css))
        for vendor in vendor_js:
            page.add_script_tag(path=str(vendor))
        page.add_script_tag(path=str(utils_js))
        page.add_script_tag(path=str(connection_js))
        page.add_script_tag(path=str(app_js))

        try:
            page.wait_for_function(
                "typeof window.PortfolioPanel?.init === 'function'", timeout=500
            )
        except PlaywrightTimeoutError:
            pytest.fail("#418 T3 missing behavior: portfolio dashboard panel control")
        page.evaluate(
            """payload => {
                api = async path => {
                    if (path === '/api/portfolio/projects') return payload;
                    throw new Error(`unexpected API call: ${path}`);
                };
                PortfolioPanel.init();
            }""",
            payload,
        )
        assert page.locator('[data-left-tab="portfolio"]').count() == 1
        page.locator('[data-left-tab="portfolio"]').click()
        page.wait_for_selector('#tasks-panel [data-portfolio-board="true"]')

        panel = page.locator("#tasks-panel")
        assert not panel.evaluate("element => element.classList.contains('hidden')")
        assert page.locator("#file-panel").evaluate(
            "element => parseFloat(getComputedStyle(element).width)"
        ) >= 900
        for anchor in ("Планируется", "В работе", "Ждёт решения", "Сделано"):
            assert anchor in panel.inner_text()
        for value in (
            "Linked board task",
            "Goal visible without task dependence",
            "Exact visible question?",
            "owner-visible",
            "sub-visible",
            "Goal-only project remains visible",
        ):
            assert value in panel.inner_text()
        assert "Unlinked hidden task" not in panel.inner_text()
        assert errors == []
        browser.close()


@pytest.mark.asyncio
async def test_t4_attention_is_durable_before_tag_and_wait_watchdog_never_tag(monkeypatch):
    from app import mcp_stdio as mcp
    import app.tg_bridge as tg_bridge

    signature = inspect.signature(mcp.notify_user)
    assert "project" in signature.parameters, "#418 T4 missing project attention integration"
    assert "kind" in signature.parameters, "#418 T4 missing typed attention taxonomy"
    assert signature.parameters["kind"].default == "legacy"

    calls: list[tuple[str, str, dict]] = []

    async def api(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True, "event_id": f"attention-{len(calls)}"}

    monkeypatch.setattr(mcp, "_api", api)
    monkeypatch.setattr(mcp, "SESSION_ID", "owner-session")
    legacy = await mcp.notify_user("Legacy platform incident")
    typed = await mcp.notify_user("Production incident", project="alpha", kind="incident")
    assert "attention-1" in legacy and "attention-2" in typed
    assert calls[0][0:2] == ("POST", "/api/portfolio/attention")
    assert calls[1][0:2] == ("POST", "/api/portfolio/projects/alpha/attention")

    parse_result = getattr(tg_bridge, "_attention_from_tool_result", None)
    assert callable(parse_result), "#418 T4 missing durable-result TG attention parser"
    assert parse_result(typed)["event_id"] == "attention-2"
    assert parse_result("PROJECT_WAIT_DURABLE:wait-1") is None
    assert parse_result("WATCHDOG_WAKE_DURABLE:wake-1") is None

    with pytest.raises(ValueError, match="project_wait"):
        await mcp.notify_user("Need a choice", project="alpha", kind="waiting")
