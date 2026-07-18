import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_spawn_passes_base_branch(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "coder-auth")
    captured = {}
    async def fake_api(method, path, **kw):
        if path == "/api/sessions":
            captured.update(kw.get("json", {}))
        return {"ok": True}
    with patch.object(m, "_api", side_effect=fake_api):
        await m.spawn_worker(name="w-step1", task="do it", repo_path="/s",
                             model="claude-sonnet-5[1m]", base_branch="feature/auth")
    assert captured["base_branch"] == "feature/auth"
    assert captured["use_worktree"] is True


@pytest.mark.asyncio
async def test_spawn_base_branch_default_empty(monkeypatch):
    # Sentinel "" = авто-резолв базовой ветки по стратегии пайплайна (DESIGN §10):
    # parent → от ветки родителя, иначе main. Явная ветка переопределяет стратегию.
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "x")
    captured = {}
    async def fake_api(method, path, **kw):
        if path == "/api/sessions":
            captured.update(kw.get("json", {}))
        return {"ok": True}
    with patch.object(m, "_api", side_effect=fake_api):
        await m.spawn_worker(name="w", task="t", repo_path="/s", model="claude-sonnet-5[1m]")
    assert captured["base_branch"] == ""


@pytest.mark.asyncio
async def test_acquire_test_lock_uses_worker_as_holder(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "coder-auth")
    captured = {}
    async def fake_api(method, path, **kw):
        captured["path"] = path
        captured["json"] = kw.get("json")
        return {"acquired": True, "holder": None}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.acquire_test_lock(reason="full suite before merge")
    assert captured["path"] == "/api/test-lock/acquire"
    assert captured["json"]["holder"] == "coder-auth"
    assert captured["json"]["scope"] == "/s"
    assert captured["json"]["reason"] == "full suite before merge"
    assert "acquired" in out.lower() or "взял" in out.lower()


@pytest.mark.asyncio
async def test_acquire_test_lock_reports_holder_when_busy(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "coder-b")
    async def fake_api(method, path, **kw):
        return {"acquired": False, "holder": "coder-a"}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.acquire_test_lock(reason="x")
    assert "coder-a" in out  # держатель указан в отказе


@pytest.mark.asyncio
async def test_release_and_status(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "coder-a")
    calls = {}
    async def fake_api(method, path, **kw):
        calls[path] = kw.get("json") or kw.get("params")
        if path == "/api/test-lock/release":
            return {"released": True}
        if path == "/api/test-lock":
            return {"held": True, "holder": "coder-a", "reason": "r", "acquired_at": "t"}
        return {}
    with patch.object(m, "_api", side_effect=fake_api):
        rel = await m.release_test_lock()
        st = await m.test_lock_status()
    assert "/api/test-lock/release" in calls
    assert "coder-a" in st  # статус упоминает держателя
    assert "released" in rel.lower() or "освобод" in rel.lower()

@pytest.mark.asyncio
async def test_merge_worker_with_next_task_id(monkeypatch):
    """next_task_id передаётся в body запроса к /api/sessions/{name}/merge."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch")
    captured = {}
    async def fake_api(method, path, **kw):
        captured["path"] = path
        captured["json"] = kw.get("json", {})
        return {"ok": True, "commits_merged": 1, "branch": "task-42/w", "merged_commits": {}}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.merge_worker(name="coder", target="main", next_task_id="task-43")
    assert captured["path"] == "/api/sessions/coder/merge"
    assert captured["json"]["next_task_id"] == "task-43"
    assert captured["json"]["target"] == "main"


@pytest.mark.asyncio
async def test_merge_worker_no_next_task_id(monkeypatch):
    """Без next_task_id ключ next_task_id не отправляется в body."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch")
    captured = {}
    async def fake_api(method, path, **kw):
        captured["json"] = kw.get("json", {})
        return {"ok": True, "commits_merged": 1, "branch": "task-42/w", "merged_commits": {}}
    with patch.object(m, "_api", side_effect=fake_api):
        await m.merge_worker(name="coder")
    assert "next_task_id" not in captured["json"]


@pytest.mark.asyncio
async def test_kill_worker_force_param(monkeypatch):
    """force=True передаётся как строчный параметр в DELETE-запрос."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch")
    captured = {}
    async def fake_api(method, path, **kw):
        captured["method"] = method
        captured["path"] = path
        captured["params"] = kw.get("params", {})
        return {"ok": True}
    with patch.object(m, "_api", side_effect=fake_api):
        await m.kill_worker(name="coder", force=True)
    assert captured["method"] == "DELETE"
    assert captured["path"] == "/api/sessions/coder"
    assert captured["params"]["force"] == "true"


@pytest.mark.asyncio
async def test_kill_worker_force_false_default(monkeypatch):
    """force=False (default) → params force='false'."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch")
    captured = {}
    async def fake_api(method, path, **kw):
        captured["params"] = kw.get("params", {})
        return {"ok": True}
    with patch.object(m, "_api", side_effect=fake_api):
        await m.kill_worker(name="coder")
    assert captured["params"]["force"] == "false"


@pytest.mark.asyncio
async def test_send_message_cross_scope_warning(monkeypatch):
    """Если worker принадлежит другому parent → warning в ответе."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch-a")
    async def fake_api(method, path, **kw):
        return {"ok": True, "parent_name": "orch-b"}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.send_message(to="coder", message="hi")
    assert "⚠️" in out or "warning" in out.lower() or "orch-b" in out


@pytest.mark.asyncio
async def test_send_message_same_parent_no_warning(monkeypatch):
    """Сообщение воркеру того же родителя → нет предупреждения."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch-a")
    async def fake_api(method, path, **kw):
        return {"ok": True, "parent_name": "orch-a"}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.send_message(to="coder", message="hi")
    assert "⚠️" not in out


@pytest.mark.asyncio
async def test_list_agents_groups_by_parent(monkeypatch):
    """list_agents группирует сессии на Orchestrators / Your workers / Other workers."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch-a")
    sessions = [
        {"name": "orch-a", "scope": "/s", "role": "orchestrator", "parent_name": "", "status": "idle", "model": "opus"},
        {"name": "my-coder", "scope": "/s", "role": "worker", "parent_name": "orch-a", "status": "idle", "model": "sonnet"},
        {"name": "their-coder", "scope": "/s", "role": "worker", "parent_name": "orch-b", "status": "idle", "model": "sonnet"},
    ]
    async def fake_api(method, path, **kw):
        if path == "/api/sessions":
            return sessions
        if path == "/api/role-icons":
            return {}
        return {}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.list_agents()
    assert "## Orchestrators" in out
    assert "## Your workers" in out
    assert "## Other orchestrators' workers" in out
    assert "orch-a" in out
    assert "my-coder" in out
    assert "their-coder" in out


def test_read_only_access_mode_hides_mutating_tools():
    import app.mcp_stdio as m

    visible = m._tool_names_for_access_mode(
        {"list_agents", "get_worker_logs", "send_message", "spawn_worker", "kill_worker"},
        "read-only",
    )

    assert visible == {"list_agents", "get_worker_logs"}


def test_full_access_mode_preserves_all_tools():
    import app.mcp_stdio as m

    names = {"list_agents", "send_message", "spawn_worker"}
    assert m._tool_names_for_access_mode(names, "full") == names


def test_unknown_access_mode_is_rejected():
    import app.mcp_stdio as m

    with pytest.raises(ValueError, match="ORCHESTRA_ACCESS_MODE"):
        m._tool_names_for_access_mode({"list_agents", "spawn_worker"}, "typo")
