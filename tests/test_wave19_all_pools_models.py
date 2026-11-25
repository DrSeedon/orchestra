"""Wave 19 regression contracts: all 3 Antigravity pools, Codex 6.2 & Hub open; audio strip."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import acp_mux, db, models
from app.models import (
    ANTIGRAVITY_DISPLAY_NAMES,
    RETIRED_ANTIGRAVITY_XHIGH_IDS,
    ensure_dashboard_visible,
    ensure_project_model_allowed,
    ensure_spawn_allowed,
    supports_native_audio_input,
)


@pytest.fixture
def isolated_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "catalog.db")
    db.init_db()
    monkeypatch.setattr(models, "is_provider_disabled", lambda _: False)
    monkeypatch.setattr("app.backend_hub.hub_configured", lambda: None)


def test_acp_mux_model_regex_admits_all_3_pools_and_bans_xhigh():
    for raw in ANTIGRAVITY_DISPLAY_NAMES:
        assert acp_mux.MODEL.fullmatch(raw), f"{raw} must be accepted by acp_mux.MODEL"
    for xhigh in (
        "gemini-4-neon-xhigh",
        "gemini-4-hydrogen-xhigh",
        "gemini-4-carbon-xhigh",
        "gemini-4-argon-xhigh",
        "claude-sonnet-5-5-xhigh",
        "claude-opus-5-5-xhigh",
    ):
        assert not acp_mux.MODEL.fullmatch(xhigh)


@pytest.mark.asyncio
async def test_acp_mux_check_quota_isolates_three_pools(monkeypatch):
    from app.routes import system as sys_routes

    monkeypatch.setattr("app.provider_safety.get_antigravity_cooldown", lambda: None)
    cache = {
        "data": {
            "gemini-weekly": {"remaining_fraction": 0.02},
            "gemini-argon-wtu-weekly": {"remaining_fraction": 0.70},
            "3p-weekly": {"remaining_fraction": 0.85},
        },
        "five_hour": {
            "gemini-5h": {"remaining_fraction": 0.01},
            "gemini-argon-wtu-5h": {"remaining_fraction": 0.90},
            "3p-5h": {"remaining_fraction": 0.95},
        },
    }
    monkeypatch.setattr(sys_routes, "_antigravity_usage_cache", cache)

    with pytest.raises(acp_mux.AcpSessionError, match="hard stop"):
        await acp_mux._check_quota("gemini-4-neon-medium")
    await acp_mux._check_quota("gemini-4-argon-medium")
    await acp_mux._check_quota("claude-sonnet-5-5-medium")

    cache["data"]["3p-weekly"] = {"remaining_fraction": 0.03}
    with pytest.raises(acp_mux.AcpSessionError, match="hard stop"):
        await acp_mux._check_quota("claude-opus-5-5-medium")
    await acp_mux._check_quota("gemini-4-argon-medium")


@pytest.mark.asyncio
async def test_acp_mux_run_prompt_strips_audio_for_claude_keeps_for_gemini(tmp_path, monkeypatch):
    monkeypatch.setattr(acp_mux, "_check_quota", AsyncMock(return_value=None))
    monkeypatch.setattr(acp_mux, "_reserve_turn", lambda *a, **kw: None)
    monkeypatch.setattr(acp_mux, "_egress", AsyncMock(return_value=None))
    monkeypatch.setattr(acp_mux, "select_model", AsyncMock(return_value=None))
    monkeypatch.setattr(acp_mux, "profile_epoch", lambda _home: 1)

    recorded_prompts = []

    class FakeOwner:
        capabilities = {"promptCapabilities": {"audio": True}}
        uncertain_sessions = set()
        failure = None
        transport_generation = 1
        epoch = 1
        listeners = {}
        client_request_handlers = {}
        usage_totals = {}
        cost_totals = {}

        def _check_settings(self):
            return None

        def session_lock(self, _sid):
            import contextlib
            return contextlib.nullcontext()

        def turn_slot(self, _conn):
            import contextlib
            return contextlib.nullcontext()

        async def request(self, method, params, **_kw):
            recorded_prompts.append(params["prompt"])
            return {"stopReason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 5}}

    # Async lock replacement
    class _AsyncNull:
        async def __aenter__(self): return None
        async def __aexit__(self, *args): return False

    owner = FakeOwner()
    owner.session_lock = lambda _sid: _AsyncNull()
    owner.turn_slot = lambda _conn: _AsyncNull()
    monkeypatch.setattr(acp_mux, "cached_profile", lambda _home: owner)

    conn = acp_mux.Connection(tmp_path, None)
    conn.owner = owner
    conn.owner_id = "test"
    conn.session_id = "sid-1"
    conn.origin = "telegram"
    conn.prompt_generation = 1
    sent = []
    conn.send = sent.append

    ogg = "T2dnUwACAAAAAAAAAAA="  # valid base64 starting with "OggS"
    blocks = [
        {"type": "text", "text": "hello"},
        {"type": "audio", "mimeType": "audio/ogg", "data": ogg},
    ]

    await conn.run_prompt(1, {
        "sessionId": "sid-1",
        "origin": "telegram",
        "model": "claude-sonnet-5-5-medium",
        "turnId": "a" * 32,
        "blocks": blocks,
    })
    assert all(b["type"] != "audio" for b in recorded_prompts[-1])

    await conn.run_prompt(2, {
        "sessionId": "sid-1",
        "origin": "telegram",
        "model": "gemini-4-argon-medium",
        "turnId": "b" * 32,
        "blocks": blocks,
    })
    assert any(b["type"] == "audio" for b in recorded_prompts[-1])


def test_orchestra_all_active_models_open_across_scopes_while_guards_remain(isolated_catalog, monkeypatch):
    # All 26 active 3-pool Antigravity models open for dashboard + agents (worker & orchestrator)
    for raw in ANTIGRAVITY_DISPLAY_NAMES:
        mid = f"antigravity/{raw}"
        ensure_dashboard_visible(mid)
        ensure_spawn_allowed(mid, role="worker", scope="/home/kesha/projects/seedon")
        ensure_project_model_allowed(mid, "/home/kesha/projects/seedon")

    # Native Codex models open
    for mid in ("gpt-6.2-sol", "gpt-6.2-astra", "gpt-6-luna", "gpt-5.3-codex-spark"):
        ensure_dashboard_visible(mid)
        ensure_spawn_allowed(mid, role="worker", scope="/home/kesha/projects/orchestra")

    # Hub models open across non-Multicast projects
    for mid in (
        "hub-claude-haiku-5-5", "hub-claude-sonnet-5-5", "hub-claude-opus-5-5",
        "hub-gpt-6.2-sol", "hub-gpt-6.2-astra", "hub-gpt-6-luna",
        "hub-gemini-4-neon", "hub-gemini-4-argon", "hub-gemini-4-carbon", "hub-gemini-4-hydrogen",
    ):
        ensure_dashboard_visible(mid)
        ensure_spawn_allowed(mid, role="worker", scope="/home/kesha/projects/seedon")

    # Native audio support strictly Gemini only
    assert supports_native_audio_input("antigravity/gemini-4-neon-medium")
    assert supports_native_audio_input("antigravity/gemini-4-argon-medium")
    assert not supports_native_audio_input("antigravity/claude-sonnet-5-5-medium")
    assert not supports_native_audio_input("antigravity/gpt-oss-120b-medium")

    # Guards that stay enforced: retired / xhigh / disabled providers / opt-in credit-only routes
    for bad in sorted(RETIRED_ANTIGRAVITY_XHIGH_IDS) + ["gpt-6.1-sol", "gpt-6-astra", "hub-gpt-6.1-sol"]:
        with pytest.raises(ValueError, match="retired"):
            ensure_spawn_allowed(bad)
    with pytest.raises(ValueError, match=models.AGENT_HUB_ROUTE_RULE):
        ensure_spawn_allowed("claude-sonnet-5-5[1m]", billing="subscription")

    monkeypatch.setattr(models, "is_provider_disabled", lambda p: p in {"codex", "openai"})
    with pytest.raises(ValueError, match="locally disabled"):
        ensure_spawn_allowed("gpt-6.2-sol")
