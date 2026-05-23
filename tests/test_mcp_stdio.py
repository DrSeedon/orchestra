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
async def test_spawn_base_branch_default_main(monkeypatch):
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
    assert captured["base_branch"] == "main"
