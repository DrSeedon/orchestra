"""V-958: Orchestra never spends the Claude CLI's single-use refresh token."""
import json
import logging

import pytest

from app.routes import system


@pytest.fixture
def stale_token(monkeypatch, tmp_path):
    """A credentials file with a refresh token, a 401 from Anthropic, and a tripwire on every POST."""
    credentials = tmp_path / ".credentials.json"
    original = json.dumps({"claudeAiOauth": {
        "accessToken": "access-old", "refreshToken": "refresh-single-use", "rateLimitTier": "max",
    }})
    credentials.write_text(original)
    monkeypatch.setattr(system, "_CREDENTIALS_PATH", credentials)
    monkeypatch.setattr(system, "_usage_cache", {
        "data": {"five_hour": {"utilization": 41, "resets_at": "2026-10-18T15:00:00Z"},
                 "seven_day": {"utilization": 10, "resets_at": "2026-10-22T15:00:00Z"}},
        "ts": 0.0, "error": None,
    })
    monkeypatch.setattr(system, "_codex_usage_cache", {"data": None, "ts": 0.0})
    monkeypatch.setattr(system, "_grok_usage_cache", {"data": None, "ts": 0.0})
    monkeypatch.setattr(system, "_save_usage_cache", lambda: None)
    monkeypatch.setattr(system, "_read_grok_token", lambda: "")
    monkeypatch.setattr(system, "_get_agents_cost", lambda: {})
    monkeypatch.setattr(system, "_get_voice_cost_usd", lambda: 0.0)
    monkeypatch.setattr(system, "_stale_logged", set())

    async def codex_unavailable():
        return None

    monkeypatch.setattr(system, "_fetch_codex_usage", codex_unavailable)
    monkeypatch.setattr("shutil.which", lambda _binary: None)

    async def expired(_token):
        raise PermissionError("token_expired")

    monkeypatch.setattr(system, "_fetch_anthropic_usage", expired)
    posts = []

    async def tripwire(self, url, **kwargs):
        posts.append((url, kwargs))
        raise AssertionError(f"unexpected POST to {url}: the refresh token must never be exchanged")

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "post", tripwire)
    return credentials, original, posts


def test_refresh_exchange_no_longer_exists_and_refresh_token_is_not_read(stale_token):
    credentials, _original, _posts = stale_token
    assert not hasattr(system, "_refresh_oauth_token")
    assert system._read_oauth_credentials() == ("access-old", "max")


@pytest.mark.asyncio
async def test_cached_usage_path_serves_cache_with_reason_and_never_posts(stale_token, caplog):
    credentials, original, posts = stale_token

    with caplog.at_level(logging.DEBUG, logger="orchestra.system"):
        first = await system._get_usage_data(force_refresh=True)
        second = await system._get_usage_data(force_refresh=True)

    assert first["anthropic"]["five_hour"]["utilization"] == 41
    assert first["anthropic_error"] == system.ANTHROPIC_TOKEN_STALE_REASON
    assert second["anthropic_error"] == system.ANTHROPIC_TOKEN_STALE_REASON
    assert posts == []
    assert credentials.read_text() == original
    warnings = [r for r in caplog.records
                if r.levelno >= logging.WARNING and "token expired" in r.getMessage()]
    assert len(warnings) == 1, "a standing condition must warn once, not on every poll"


@pytest.mark.asyncio
async def test_snapshot_path_names_the_reason_and_never_posts(stale_token, monkeypatch):
    credentials, original, posts = stale_token
    import app.db

    saved = []
    monkeypatch.setattr(app.db, "usage_save_snapshot", lambda *a, **k: saved.append(k.get("providers") or {}))

    await system._collect_usage_snapshot()

    assert posts == []
    assert credentials.read_text() == original
    anthropic = saved[0]["anthropic"]
    assert anthropic["status"] == "unavailable"
    assert system.ANTHROPIC_TOKEN_STALE_REASON in anthropic["error"]


@pytest.mark.asyncio
async def test_recovery_clears_the_reason_and_rearms_the_warning(stale_token, monkeypatch):
    _credentials, _original, _posts = stale_token
    await system._get_usage_data(force_refresh=True)
    assert "anthropic_token" in system._stale_logged

    async def fresh(_token):
        return {"five_hour": {"utilization": 5}, "seven_day": {"utilization": 6}}

    monkeypatch.setattr(system, "_fetch_anthropic_usage", fresh)
    result = await system._get_usage_data(force_refresh=True)

    assert result["anthropic_error"] is None
    assert "anthropic_token" not in system._stale_logged
