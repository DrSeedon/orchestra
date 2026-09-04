"""#472: the PROJECTS board is a per-orchestrator display slice, not a rights change."""

from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Один владелец у защиты боевой БД: фикстура #425 уже доказывает изоляцию счётчиком
# строк `sessions` до и после прогона. Копия здесь разошлась бы с оригиналом.
from tests.test_project_roadmap_backend_425 import (  # noqa: F401
    _save_session,
    portfolio_db,
)


def _app() -> FastAPI:
    module = importlib.import_module("app.routes.portfolio")
    app = FastAPI()
    app.include_router(module.router)
    return app


def _ids(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [project["id"] for project in response.json()["projects"]]


def _create(client: TestClient, owner: str, project_id: str) -> None:
    response = client.post(
        "/api/portfolio/projects",
        headers={"x-orchestra-session-id": owner},
        json={"id": project_id, "name": project_id.title()},
    )
    assert response.status_code == 201, response.text


@pytest.fixture
def operator_env(monkeypatch: pytest.MonkeyPatch):
    """Дашборд-оператор без логина: `_project_list_actor` отдаёт пустого актора."""
    monkeypatch.delenv("DASHBOARD_USER", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)


def test_operator_slice_shows_only_the_selected_orchestrators_projects(
    portfolio_db, operator_env
):
    db = portfolio_db
    alpha_owner, _ = _save_session(db, "alpha-orch", role="orchestrator", scope="/alpha")
    beta_owner, _ = _save_session(db, "beta-orch", role="orchestrator", scope="/beta")

    with TestClient(_app()) as client:
        _create(client, alpha_owner, "alpha")
        _create(client, beta_owner, "beta")

        alpha_slice = client.get(
            "/api/portfolio/projects", params={"agent_session_id": alpha_owner}
        )
        beta_slice = client.get(
            "/api/portfolio/projects", params={"agent_session_id": beta_owner}
        )
        unfiltered = client.get("/api/portfolio/projects")
        unknown = client.get(
            "/api/portfolio/projects", params={"agent_session_id": "no-such-session"}
        )

    assert _ids(alpha_slice) == ["alpha"]
    assert _ids(beta_slice) == ["beta"]
    # Право оператора видеть всё не тронуто — он лишь ПРОСИТ срез.
    assert _ids(unfiltered) == ["alpha", "beta"]
    # Пустой срез рисует «ПРОЕКТОВ ПОКА НЕТ», а не чужой проект.
    assert _ids(unknown) == []


def test_agent_session_header_wins_over_the_display_filter(portfolio_db, operator_env):
    db = portfolio_db
    alpha_owner, _ = _save_session(db, "alpha-orch", role="orchestrator", scope="/alpha")
    beta_owner, _ = _save_session(db, "beta-orch", role="orchestrator", scope="/beta")

    with TestClient(_app()) as client:
        _create(client, alpha_owner, "alpha")
        _create(client, beta_owner, "beta")

        escalation = client.get(
            "/api/portfolio/projects",
            params={"agent_session_id": beta_owner},
            headers={"x-orchestra-session-id": alpha_owner},
        )
        own = client.get(
            "/api/portfolio/projects",
            params={"agent_session_id": alpha_owner},
            headers={"x-orchestra-session-id": alpha_owner},
        )

    # Агент А просит срез по агенту Б → чужой проект НЕ появляется, своё остаётся.
    assert _ids(escalation) == ["alpha"]
    assert _ids(own) == ["alpha"]


def test_slice_follows_active_contributor_membership(portfolio_db, operator_env):
    db = portfolio_db
    owner, owner_name = _save_session(
        db, "root-orch", role="orchestrator", scope="/alpha"
    )
    contributor, _ = _save_session(
        db,
        "sub-orch",
        role="sub-orchestrator",
        scope="/alpha",
        parent_id=owner,
        parent_name=owner_name,
    )

    with TestClient(_app()) as client:
        _create(client, owner, "alpha")
        added = client.post(
            "/api/portfolio/projects/alpha/members",
            headers={"x-orchestra-session-id": owner},
            json={"session_id": contributor, "role": "contributor"},
        )
        assert added.status_code == 201, added.text
        active = client.get(
            "/api/portfolio/projects", params={"agent_session_id": contributor}
        )

        with db._conn() as connection:
            connection.execute(
                "UPDATE portfolio_members SET revoked_at=? WHERE session_id=?",
                ("2026-09-04T00:00:00+00:00", contributor),
            )

        revoked = client.get(
            "/api/portfolio/projects", params={"agent_session_id": contributor}
        )

    assert _ids(active) == ["alpha"]
    assert _ids(revoked) == []


def test_slice_never_resurrects_an_archived_project(portfolio_db, operator_env):
    db = portfolio_db
    owner, _ = _save_session(db, "alpha-orch", role="orchestrator", scope="/alpha")

    with TestClient(_app()) as client:
        _create(client, owner, "alpha")
        with db._conn() as connection:
            connection.execute(
                "UPDATE portfolio_projects SET archived_at=? WHERE id='alpha'",
                ("2026-09-04T00:00:00+00:00",),
            )
        sliced = client.get(
            "/api/portfolio/projects", params={"agent_session_id": owner}
        )
        unfiltered = client.get("/api/portfolio/projects")

    # Срез членства не должен возвращать то, что общий список уже скрывает.
    assert _ids(sliced) == []
    assert _ids(unfiltered) == []
