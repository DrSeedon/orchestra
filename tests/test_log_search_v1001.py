from datetime import datetime, timezone
import json

import pytest


@pytest.fixture
def searchable_logs(tmp_path, monkeypatch):
    from app import db
    from app.events import MessageProvenance

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "search.db")
    db.init_db()
    for sid, name, scope in (
        ("s1", "seedon-orchestrator", "/home/kesha/projects/seedon"),
        ("s2", "other-worker", "/other/project"),
    ):
        with db._conn() as connection:
            connection.execute(
                "INSERT INTO sessions (id,name,scope,cwd,model,created_at) VALUES (?,?,?,?,?,?)",
                (sid, name, scope, scope, "test", "2026-08-01T00:00:00+00:00"),
            )
    db.add_log(
        "s1", datetime(2026, 8, 27, 10, tzinfo=timezone.utc), "user_message",
        "Открой Сбер: [voice: /data/uploads/seedon.oga] транскрипт: встреча у Сбербанка",
        provenance=MessageProvenance("user", ("owner",), subtype="telegram"),
    )
    db.add_log(
        "s1", datetime(2026, 8, 28, 10, tzinfo=timezone.utc), "text",
        "Sber account decision is pending",
    )
    db.add_log(
        "s2", datetime(2026, 8, 27, 10, tzinfo=timezone.utc), "user_message",
        "Сбербанк account in another project",
        provenance=MessageProvenance("user", ("owner",)),
    )
    return db


@pytest.mark.asyncio
async def test_search_matches_casefold_date_scope_voice_and_limit(searchable_logs):
    from app.routes.sessions import search_logs_endpoint

    response = await search_logs_endpoint(
        "СБЕР", scope="/home/kesha/projects/seedon",
        date_from="2026-08-27", date_to="2026-08-27", limit=50,
    )
    assert response.status_code == 200
    data = json.loads(response.body)
    assert "транскрипт: встреча у Сбербанка" in data["results"][0]["snippet"]
    assert data["results"][0]["agent"] == "seedon-orchestrator"
    assert data["results"][0]["type"] == "user message"

    english = await search_logs_endpoint("sBeR", scope="/home/kesha/projects/seedon")
    assert any("Sber account" in row["snippet"] for row in json.loads(english.body)["results"])

    limited = await search_logs_endpoint(
        "sber", scope="/home/kesha/projects/seedon", limit=1,
    )
    assert limited.status_code == 200
    limited_data = json.loads(limited.body)
    assert len(limited_data["results"]) == 1
    assert limited_data["result_limit_reached"] is True


@pytest.mark.asyncio
async def test_all_projects_is_explicit_and_caller_scope_is_required(searchable_logs):
    from app.routes.sessions import search_logs_endpoint

    own_scope = await search_logs_endpoint("сбер", scope="/home/kesha/projects/seedon")
    assert b"other-worker" not in own_scope.body

    all_projects = await search_logs_endpoint("сбер", all_projects=True)
    assert b"other-worker" in all_projects.body
    assert b"seedon-orchestrator" in all_projects.body

    missing_scope = await search_logs_endpoint("сбер")
    assert missing_scope.status_code == 400


@pytest.mark.asyncio
async def test_context_fetch_returns_only_bounded_neighbors(searchable_logs):
    from app.db import search_logs
    from app.routes.sessions import log_context_endpoint

    match = search_logs("сбер", scope="/home/kesha/projects/seedon")["results"][0]
    context = await log_context_endpoint(match["id"], scope="/home/kesha/projects/seedon")
    assert context.status_code == 200
    assert "транскрипт" in context.body.decode()
    hidden = await log_context_endpoint(match["id"], scope="/other/project")
    assert hidden.status_code == 404


def test_search_logs_tool_uses_callers_project_by_default(monkeypatch):
    import asyncio
    import json
    from app import mcp_stdio

    calls = []

    async def fake_api(method, path, params=None, **kwargs):
        calls.append((method, path, params))
        return {"results": []}

    monkeypatch.setattr(mcp_stdio, "SCOPE", "/caller/project")
    monkeypatch.setattr(mcp_stdio, "_api", fake_api)
    result = asyncio.run(mcp_stdio.search_logs("Sber"))
    assert json.loads(result) == {"results": []}
    assert calls[0][2]["scope"] == "/caller/project"
    assert calls[0][2]["all_projects"] is False
    registered = {tool.name for tool in mcp_stdio.mcp._tool_manager.list_tools()}
    assert {"search_logs", "get_log_context"} <= registered
    assert {"search_logs", "get_log_context"} <= mcp_stdio.READ_ONLY_MCP_TOOLS


def test_date_filter_uses_log_day_index(searchable_logs):
    with searchable_logs._conn() as connection:
        plan = connection.execute(
            """EXPLAIN QUERY PLAN
               SELECT l.id, l.content, s.name FROM logs AS l CROSS JOIN sessions AS s
               WHERE s.id=l.session_id AND s.scope=?
                 AND date(l.ts)>=date(?) AND date(l.ts)<=date(?)
               ORDER BY l.id DESC LIMIT ?""",
            ("/home/kesha/projects/seedon", "2026-08-27", "2026-08-27", 10_001),
        ).fetchall()
    assert any("idx_logs_day" in row["detail"] for row in plan)


def test_search_rule_module_is_delivered_to_every_role():
    from app import pipeline

    module = pipeline.prompt_path("default", "modules/knowledge.md").read_text().strip()
    for role in ("orchestrator", "sub-orchestrator", "worker", "full-cycle", "reducer"):
        assert pipeline.build_system_prompt("default", role).count(module) == 1
