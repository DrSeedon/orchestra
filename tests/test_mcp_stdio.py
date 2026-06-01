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
                             model="claude-sonnet-4-6", base_branch="feature/auth")
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
        await m.spawn_worker(name="w", task="t", repo_path="/s", model="claude-sonnet-4-6")
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
