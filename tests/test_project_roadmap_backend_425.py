"""Frozen RED backend acceptance oracles for #425 project roads."""

from __future__ import annotations

import importlib
import json
import sqlite3
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _production_db() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=_repository_root(),
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip()).resolve().parent / "data/orchestra.db"


def _sessions_count(connect, path: Path) -> int | None:
    if not path.is_file():
        return None
    connection = connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()
        return int(row[0])
    finally:
        connection.close()


@pytest.fixture
def portfolio_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Install the production-DB guard before any application DB call."""
    production_path = _production_db()
    real_connect = sqlite3.connect
    before = _sessions_count(real_connect, production_path)

    def guarded_connect(database, *args, **kwargs):
        raw = str(database)
        if raw.startswith("file:"):
            raw = raw.removeprefix("file:").split("?", 1)[0]
        if raw != ":memory:" and Path(raw).resolve() == production_path:
            raise AssertionError(f"#425 oracle attempted production DB: {production_path}")
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
    from app import db

    isolated_path = tmp_path / "project-roadmap-425.sqlite"
    monkeypatch.setattr(db, "DB_PATH", isolated_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(isolated_path))
    db.init_db()
    assert isolated_path.is_file()
    try:
        yield db
    finally:
        after = _sessions_count(real_connect, production_path)
        print(f"#425 production sessions invariant: before={before} after={after}")
        assert after == before, "#425 oracle changed production sessions"


def _save_session(
    db,
    name: str,
    *,
    role: str,
    scope: str,
    parent_id: str = "",
    parent_name: str = "",
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
            "branch": "main",
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


def _portfolio_app(*required_paths: str) -> FastAPI:
    from app.main import app as production_app

    paths = {getattr(route, "path", "") for route in production_app.routes}
    missing = [path for path in required_paths if path not in paths]
    assert not missing, f"#425 T1 missing behavior: portfolio roadmap routes {missing}"
    module = importlib.import_module("app.routes.portfolio")
    app = FastAPI()
    app.include_router(module.router)
    return app


def _headers(session_id: str) -> dict[str, str]:
    return {"x-orchestra-session-id": session_id}


def _seed_namespace(tm, namespace: str, scope: str) -> None:
    with tm._conn() as connection:
        tm.ensure_project(connection, namespace, name=namespace, scope=scope)


def _create_project(client: TestClient, owner: str, project_id: str) -> dict:
    response = client.post(
        "/api/portfolio/projects",
        headers=_headers(owner),
        json={"id": project_id, "name": project_id.title()},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_t1_complete_task_source_single_label_and_bounded_order(
    portfolio_db, monkeypatch
):
    db = portfolio_db
    owner, owner_name = _save_session(
        db, "owner", role="orchestrator", scope="/portfolio-home"
    )
    contributor, _ = _save_session(
        db,
        "sub",
        role="sub-orchestrator",
        scope="/linked-extra",
        parent_id=owner,
        parent_name=owner_name,
    )

    from app import tm

    _seed_namespace(tm, "primary", "/portfolio-home")
    _seed_namespace(tm, "extra", "/linked-extra")
    _seed_namespace(tm, "foreign", "/foreign")
    primary = [
        tm.api_create_task("primary", "Primary done", status="done"),
        tm.api_create_task("primary", "Primary active", status="in_progress"),
        tm.api_create_task("primary", "Primary queue A", status="new"),
        tm.api_create_task("primary", "Primary queue B", status="new"),
    ]
    linked_extra = tm.api_create_task("extra", "Explicit extra", status="in_progress")
    tm.api_create_task("extra", "Unlinked extra must stay hidden", status="new")

    app = _portfolio_app(
        "/api/portfolio/projects/{project_id}/source",
        "/api/portfolio/projects/{project_id}/stages",
        "/api/portfolio/projects/{project_id}/tasks/{task_ref}/stage",
    )
    with TestClient(app) as client:
        created = _create_project(client, owner, "alpha")
        assert created["stage_order"] == []
        assert created["task_namespace_id"] is None

        member = client.post(
            "/api/portfolio/projects/alpha/members",
            headers=_headers(owner),
            json={"session_id": contributor, "role": "contributor"},
        )
        assert member.status_code == 201, member.text

        source = client.put(
            "/api/portfolio/projects/alpha/source",
            headers=_headers(owner),
            json={"task_project": "primary"},
        )
        assert source.status_code == 200, source.text
        assert source.json()["task_namespace_id"] == "primary"
        denied_source = client.put(
            "/api/portfolio/projects/alpha/source",
            headers=_headers(contributor),
            json={"task_project": "extra"},
        )
        assert denied_source.status_code == 403, denied_source.text

        visible = client.get(
            "/api/portfolio/projects/alpha", headers=_headers(owner)
        ).json()
        assert visible["stage_order"] == []
        assert {task["title"] for task in visible["tasks"]} == {
            task["title"] for task in primary
        }
        assert all(task["stage_label"] is None for task in visible["tasks"])

        foreign = client.put(
            "/api/portfolio/projects/alpha/source",
            headers=_headers(owner),
            json={"task_project": "foreign"},
        )
        assert foreign.status_code == 403, foreign.text

        _create_project(client, owner, "beta")
        duplicate_source = client.put(
            "/api/portfolio/projects/beta/source",
            headers=_headers(owner),
            json={"task_project": "primary"},
        )
        assert duplicate_source.status_code == 409, duplicate_source.text

        ambiguous_owner, _ = _save_session(
            db, "ambiguous-owner", role="orchestrator", scope="/ambiguous"
        )
        _seed_namespace(tm, "amb-one", "/ambiguous")
        _seed_namespace(tm, "amb-two", "/ambiguous/")
        _create_project(client, ambiguous_owner, "ambiguous-road")
        ambiguous_source = client.put(
            "/api/portfolio/projects/ambiguous-road/source",
            headers=_headers(ambiguous_owner),
            json={"task_project": "amb-one"},
        )
        assert ambiguous_source.status_code == 409, ambiguous_source.text

        mixed = client.post(
            "/api/portfolio/projects/alpha/tasks",
            headers=_headers(contributor),
            json={"task_project": "extra", "task_ref": linked_extra["par"]},
        )
        assert mixed.status_code == 201, mixed.text
        visible = client.get(
            "/api/portfolio/projects/alpha", headers=_headers(owner)
        ).json()["tasks"]
        assert {task["title"] for task in visible} == {
            *(task["title"] for task in primary),
            "Explicit extra",
        }
        assert "Unlinked extra must stay hidden" not in {task["title"] for task in visible}

        seven = ["Reliability", "Memory", "Board", "Delivery", "Runtime", "Tests", "Later"]
        order = client.put(
            "/api/portfolio/projects/alpha/stages",
            headers=_headers(owner),
            json={"stages": seven, "renames": {}},
        )
        assert order.status_code == 200, order.text
        assert order.json()["stage_order"] == seven

        denied_contributor = client.put(
            "/api/portfolio/projects/alpha/stages",
            headers=_headers(contributor),
            json={"stages": seven, "renames": {}},
        )
        assert denied_contributor.status_code == 403, denied_contributor.text
        too_many = client.put(
            "/api/portfolio/projects/alpha/stages",
            headers=_headers(owner),
            json={"stages": [*seven, "Eighth"], "renames": {}},
        )
        assert too_many.status_code == 422, too_many.text
        duplicate = client.put(
            "/api/portfolio/projects/alpha/stages",
            headers=_headers(owner),
            json={"stages": ["Memory", " memory "], "renames": {}},
        )
        assert duplicate.status_code == 422, duplicate.text

        assigned = client.put(
            f"/api/portfolio/projects/alpha/tasks/{primary[1]['par']}/stage",
            headers=_headers(owner),
            json={"stage": " memory "},
        )
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["stage_label"] == "Memory"
        absent = client.put(
            f"/api/portfolio/projects/alpha/tasks/{primary[2]['par']}/stage",
            headers=_headers(owner),
            json={"stage": "Unknown"},
        )
        assert absent.status_code == 422, absent.text

        renamed_order = [
            "Reliability", "Agent memory", "Board", "Delivery", "Runtime", "Tests", "Later"
        ]
        renamed = client.put(
            "/api/portfolio/projects/alpha/stages",
            headers=_headers(owner),
            json={"stages": renamed_order, "renames": {"Memory": "Agent memory"}},
        )
        assert renamed.status_code == 200, renamed.text
        tasks = client.get(
            "/api/portfolio/projects/alpha", headers=_headers(owner)
        ).json()["tasks"]
        active = next(task for task in tasks if task["title"] == "Primary active")
        assert active["stage_label"] == "Agent memory"
        assert sum(task["stage_label"] is not None for task in tasks) == 1

        cleared = client.put(
            f"/api/portfolio/projects/alpha/tasks/{primary[1]['par']}/stage",
            headers=_headers(owner),
            json={"stage": None},
        )
        assert cleared.status_code == 200, cleared.text
        tasks = client.get(
            "/api/portfolio/projects/alpha", headers=_headers(owner)
        ).json()["tasks"]
        assert len(tasks) == 5
        assert all(task["stage_label"] is None for task in tasks)


def test_t2_wait_text_delivery_targets_opener_and_resolves_only_on_submission(
    portfolio_db, monkeypatch
):
    db = portfolio_db
    routes = importlib.import_module("app.routes.portfolio")
    resolve_model = getattr(routes, "WaitResolve", None)
    assert resolve_model is not None and "response" in resolve_model.model_fields, (
        "#425 T2 missing behavior: WaitResolve.response"
    )

    owner, owner_name = _save_session(
        db, "owner", role="orchestrator", scope="/portfolio-home"
    )
    opener, _ = _save_session(
        db,
        "opener",
        role="sub-orchestrator",
        scope="/portfolio-home",
        parent_id=owner,
        parent_name=owner_name,
    )

    from app import message_deliveries, portfolio, tm
    from app.deps import manager

    _seed_namespace(tm, "primary", "/portfolio-home")
    task = tm.api_create_task("primary", "Decision task", status="in_progress")
    portfolio.create_project(owner, "alpha", "Alpha")
    portfolio.add_member(owner, "alpha", opener, "contributor")
    portfolio.link_task(owner, "alpha", "primary", task["par"])
    portfolio.create_goal(owner, "alpha", "Ship Alpha")
    first_wait, _ = portfolio.open_wait(
        opener, "alpha", "Choose release mode", task_ref=portfolio.list_tasks(owner, "alpha")["tasks"][0]["task_stable_id"]
    )

    preflight: list[str] = []

    async def allow_delivery(session_id: str):
        preflight.append(session_id)

    monkeypatch.setattr(manager, "preflight_message_delivery", allow_delivery)
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _session_id: None)
    monkeypatch.setenv("DASHBOARD_USER", "operator")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")
    from app.auth import create_session

    app = _portfolio_app()
    with TestClient(app) as client:
        client.cookies.set("session", create_session("operator"))
        board = client.get("/api/portfolio/projects")
        assert board.status_code == 200, board.text
        csrf = board.json().get("csrf_token")
        assert csrf, "#425 T2 operator portfolio payload must carry CSRF token"

        missing_csrf = client.post(
            f"/api/portfolio/projects/alpha/waits/{first_wait['id']}/resolve",
            json={"response": "Ship the guarded release"},
        )
        assert missing_csrf.status_code == 403, missing_csrf.text
        invalid_csrf = client.post(
            f"/api/portfolio/projects/alpha/waits/{first_wait['id']}/resolve",
            headers={"X-CSRF-Token": "wrong-token"},
            json={"response": "Ship the guarded release"},
        )
        assert invalid_csrf.status_code == 403, invalid_csrf.text
        with db._conn() as connection:
            untouched = connection.execute(
                "SELECT response_text,response_delivery_id FROM portfolio_waits WHERE id=?",
                (first_wait["id"],),
            ).fetchone()
        assert tuple(untouched) == (None, None)

        answered = client.post(
            f"/api/portfolio/projects/alpha/waits/{first_wait['id']}/resolve",
            headers={"X-CSRF-Token": csrf},
            json={"response": "Ship the guarded release"},
        )
        assert answered.status_code == 200, answered.text
        payload = answered.json()
        assert payload["wait"]["status"] == "open"
        assert payload["wait"]["response_text"] == "Ship the guarded release"
        assert payload["delivery"]["delivery_state"] == "QUEUED"
        delivery_id = payload["delivery"]["delivery_id"]
        assert preflight == [opener]

        with db._conn() as connection:
            wait_row = connection.execute(
                "SELECT * FROM portfolio_waits WHERE id=?", (first_wait["id"],)
            ).fetchone()
            delivery_row = connection.execute(
                "SELECT * FROM message_deliveries WHERE delivery_id=?", (delivery_id,)
            ).fetchone()
            before_generation = connection.execute(
                "SELECT stall_generation FROM portfolio_goals WHERE id=?",
                (first_wait["goal_id"],),
            ).fetchone()[0]
        assert wait_row["status"] == "open" and wait_row["response_attempt"] == 1
        assert delivery_row["target_session_id"] == opener
        assert delivery_row["message_kind"] == "portfolio_wait_answer"
        assert f"#{task['par']}" in delivery_row["rendered_message"]
        assert "Ship the guarded release" in delivery_row["rendered_message"]

        message_deliveries.prepare_message_delivery(delivery_id)
        message_deliveries.mark_message_delivery_dispatching(delivery_id)
        message_deliveries.mark_message_delivery_submitted(delivery_id, "provider-accepted")
        with db._conn() as connection:
            resolved = connection.execute(
                "SELECT status,resolved_at FROM portfolio_waits WHERE id=?", (first_wait["id"],)
            ).fetchone()
            after_generation = connection.execute(
                "SELECT stall_generation FROM portfolio_goals WHERE id=?",
                (first_wait["goal_id"],),
            ).fetchone()[0]
            assert connection.execute(
                "SELECT COUNT(*) FROM message_deliveries WHERE delivery_id=?", (delivery_id,)
            ).fetchone()[0] == 1
        assert resolved["status"] == "resolved" and resolved["resolved_at"]
        assert after_generation == before_generation + 1
        message_deliveries.mark_message_delivery_submitted(delivery_id, "provider-replay")
        with db._conn() as connection:
            assert connection.execute(
                "SELECT stall_generation FROM portfolio_goals WHERE id=?",
                (first_wait["goal_id"],),
            ).fetchone()[0] == after_generation

        replay = client.post(
            f"/api/portfolio/projects/alpha/waits/{first_wait['id']}/resolve",
            headers={"X-CSRF-Token": csrf},
            json={"response": "Ship the guarded release"},
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["delivery"]["delivery_id"] == delivery_id

        retry_wait, _ = portfolio.open_wait(
            opener, "alpha", "Choose retry path", task_ref=first_wait["task_stable_id"]
        )
        queued = client.post(
            f"/api/portfolio/projects/alpha/waits/{retry_wait['id']}/resolve",
            headers={"X-CSRF-Token": csrf},
            json={"response": "Retry safely"},
        ).json()
        first_attempt = queued["delivery"]["delivery_id"]
        message_deliveries.prepare_message_delivery(first_attempt)
        message_deliveries.mark_message_delivery_dispatching(first_attempt)
        message_deliveries.mark_message_delivery_failed_before_submit(
            first_attempt, message_deliveries.TargetTaskChangedError("target moved")
        )
        second = client.post(
            f"/api/portfolio/projects/alpha/waits/{retry_wait['id']}/resolve",
            headers={"X-CSRF-Token": csrf},
            json={"response": "Retry safely"},
        )
        assert second.status_code == 200, second.text
        second_attempt = second.json()["delivery"]["delivery_id"]
        assert second_attempt != first_attempt
        assert second.json()["wait"]["response_attempt"] == 2

        # A stale old attempt cannot resolve the wait after the current id moved to B.
        with db._conn() as connection:
            connection.execute(
                "UPDATE message_deliveries SET state='DISPATCHING' WHERE delivery_id=?",
                (first_attempt,),
            )
        message_deliveries.mark_message_delivery_submitted(first_attempt, "stale-provider")
        with db._conn() as connection:
            stale_safe = connection.execute(
                "SELECT status,response_delivery_id,response_attempt FROM portfolio_waits WHERE id=?",
                (retry_wait["id"],),
            ).fetchone()
        assert tuple(stale_safe) == ("open", second_attempt, 2)

        message_deliveries.prepare_message_delivery(second_attempt)
        message_deliveries.mark_message_delivery_dispatching(second_attempt)
        message_deliveries.mark_message_delivery_unknown(
            second_attempt, RuntimeError("outcome unknown")
        )
        ambiguous = client.post(
            f"/api/portfolio/projects/alpha/waits/{retry_wait['id']}/resolve",
            headers={"X-CSRF-Token": csrf},
            json={"response": "Retry safely"},
        )
        assert ambiguous.status_code == 200, ambiguous.text
        assert ambiguous.json()["delivery"]["delivery_id"] == second_attempt
        assert ambiguous.json()["wait"]["response_attempt"] == 2

        concurrent_wait, _ = portfolio.open_wait(
            opener, "alpha", "Concurrent identical response", task_ref=first_wait["task_stable_id"]
        )

        def answer_concurrently() -> tuple[int, dict]:
            with TestClient(app) as concurrent_client:
                concurrent_client.cookies.set("session", create_session("operator"))
                response = concurrent_client.post(
                    f"/api/portfolio/projects/alpha/waits/{concurrent_wait['id']}/resolve",
                    headers={"X-CSRF-Token": csrf},
                    json={"response": "One durable answer"},
                )
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            concurrent_results = list(pool.map(lambda _index: answer_concurrently(), range(2)))
        assert {status for status, _body in concurrent_results} == {200}
        concurrent_ids = {
            body["delivery"]["delivery_id"] for _status, body in concurrent_results
        }
        assert len(concurrent_ids) == 1
        with db._conn() as connection:
            current_id = next(iter(concurrent_ids))
            assert connection.execute(
                "SELECT COUNT(*) FROM message_deliveries WHERE delivery_id=?", (current_id,)
            ).fetchone()[0] == 1

        legacy_wait, _ = portfolio.open_wait(owner, "alpha", "Legacy agent resolve")
        legacy = client.post(
            f"/api/portfolio/projects/alpha/waits/{legacy_wait['id']}/resolve",
            headers=_headers(owner),
            json={},
        )
        assert legacy.status_code == 200, legacy.text
        assert legacy.json()["status"] == "resolved"
        cancel_wait, _ = portfolio.open_wait(owner, "alpha", "Legacy agent cancel")
        cancelled = client.post(
            f"/api/portfolio/projects/alpha/waits/{cancel_wait['id']}/cancel",
            headers=_headers(owner),
            json={},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"

        archived_wait, _ = portfolio.open_wait(
            opener, "alpha", "Archived opener", task_ref=first_wait["task_stable_id"]
        )
        with db._conn() as connection:
            connection.execute("UPDATE sessions SET status='archived' WHERE id=?", (opener,))
        archived = client.post(
            f"/api/portfolio/projects/alpha/waits/{archived_wait['id']}/resolve",
            headers={"X-CSRF-Token": csrf},
            json={"response": "This must not go to somebody else"},
        )
        assert archived.status_code == 409, archived.text
        with db._conn() as connection:
            row = connection.execute(
                "SELECT status,response_text,response_delivery_id FROM portfolio_waits WHERE id=?",
                (archived_wait["id"],),
            ).fetchone()
        assert tuple(row) == ("open", None, None)
