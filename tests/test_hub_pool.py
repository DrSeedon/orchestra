"""Hub pool capacity endpoint: redaction, 5-minute cache, unavailable states."""

import asyncio
import json

import pytest

from app import hub_pool
from app.hub_workspace import HubWorkspaceError

_REAL_FETCH_RELAY_LIMITS = hub_pool._fetch_relay_limits

SECRET_ID = "acct-0123456789abcdef"
SECRET_MAIL = "someone@example.invalid"


def _relay() -> dict:
    def account(ident, loaded=True, used=40.0):
        return {
            "id": ident, "creds_loaded": loaded, "email": SECRET_MAIL, "plan": "max",
            "checked_at": "2026-10-22T00:00:00Z", "error": f"bad token for {SECRET_MAIL}",
            "rejected": False,
            "windows": [{"id": "w1", "kind": "five_hour", "label": "5h", "used_pct": used,
                         "resets_at": "2026-10-22T05:00:00Z", "window_minutes": 300}],
            "reset_credits": {"available": 2, "next_id": SECRET_ID,
                              "next_expires_at": "2026-11-01T00:00:00Z"},
            "cooldown_reason": f"limit for {SECRET_MAIL}", "cooldown_until": None,
        }
    return {"providers": {
        "claude": {"active_id": SECRET_ID, "ids": [account("other-id", False, 99), account(SECRET_ID)]},
        "codex": {"active_id": "x", "ids": []},
    }}


@pytest.fixture(autouse=True)
def _stable_worker_quota():
    # Override the global telemetry stub: these tests exercise real admission with a fake relay.
    pass



class _FakeHub:
    calls = 0
    result: object = None

    @classmethod
    def from_env(cls):
        return cls()

    async def run(self, remote, **kw):
        type(self).calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _patch_hub(monkeypatch, result):
    _FakeHub.calls = 0
    _FakeHub.result = result
    monkeypatch.setattr(hub_pool, "HubSsh", _FakeHub)
    monkeypatch.setattr(hub_pool, "_fetch_relay_limits", _REAL_FETCH_RELAY_LIMITS)


def test_response_has_no_ids_or_emails_and_uses_the_active_account(monkeypatch):
    _patch_hub(monkeypatch, json.dumps(_relay()).encode())
    pool = asyncio.run(hub_pool.get_hub_pool())
    text = json.dumps(pool)
    assert SECRET_ID not in text and SECRET_MAIL not in text and "other-id" not in text
    assert pool["available"] is True
    claude = pool["providers"]["claude"]
    assert (claude["accounts"], claude["creds_loaded"]) == (2, 1)
    assert claude["windows"] == [{"kind": "five_hour", "label": "5h", "used_pct": 40.0,
                                  "resets_at": "2026-10-22T05:00:00Z", "window_minutes": 300.0}]
    assert claude["reset_credits"] == {"available": 2.0, "next_expires_at": "2026-11-01T00:00:00Z"}
    assert pool["providers"]["codex"]["windows"] == []
    assert "grok" not in pool["providers"]


def test_second_call_is_served_from_cache(monkeypatch):
    _patch_hub(monkeypatch, json.dumps(_relay()).encode())
    asyncio.run(hub_pool.get_hub_pool())
    asyncio.run(hub_pool.get_hub_pool())
    assert _FakeHub.calls == 1
    asyncio.run(hub_pool.get_hub_pool(force=True))
    assert _FakeHub.calls == 2


def test_cache_expires_after_ttl(monkeypatch):
    _patch_hub(monkeypatch, json.dumps(_relay()).encode())
    asyncio.run(hub_pool.get_hub_pool())
    hub_pool._cache["ts"] -= hub_pool.CACHE_TTL + 1
    asyncio.run(hub_pool.get_hub_pool())
    assert _FakeHub.calls == 2


def test_unreachable_hub_is_a_state_not_an_error(monkeypatch):
    _patch_hub(monkeypatch, HubWorkspaceError("hub SSH command failed rc=255: secret-host"))
    pool = asyncio.run(hub_pool.get_hub_pool())
    assert pool["available"] is False and pool["reason"] == "unreachable"
    assert "secret-host" not in json.dumps(pool)
    asyncio.run(hub_pool.get_hub_pool())
    assert _FakeHub.calls == 1  # failure is cached briefly, not retried per poll


def test_garbage_from_hub_is_unavailable(monkeypatch):
    _patch_hub(monkeypatch, b"<html>502</html>")
    assert asyncio.run(hub_pool.get_hub_pool())["reason"] == "bad_response"
    hub_pool._cache["payload"] = None
    _patch_hub(monkeypatch, b'{"nope": 1}')
    assert asyncio.run(hub_pool.get_hub_pool())["reason"] == "bad_response"


def test_not_configured(monkeypatch):
    _patch_hub(monkeypatch, None)
    monkeypatch.setattr(_FakeHub, "from_env", classmethod(lambda cls: None))
    monkeypatch.delenv("MULTICODE_HUB_SSH", raising=False)
    monkeypatch.delenv("MULTICODE_HUB_SSH_KEY", raising=False)
    pool = asyncio.run(hub_pool.get_hub_pool())
    assert pool["available"] is False and pool["reason"] == "not_configured"


def test_endpoint_returns_pool_and_hides_it_from_non_owner(monkeypatch):
    from fastapi import HTTPException
    from app.routes import system

    _patch_hub(monkeypatch, json.dumps(_relay()).encode())
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)
    assert asyncio.run(system.get_usage_hub_pool())["available"] is True
    monkeypatch.setattr(system, "is_owner_mode", lambda: False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(system.get_usage_hub_pool())
    assert exc.value.status_code == 404


def _account(five=10, weekly=20, **extra):
    return {"id": SECRET_ID, "email": SECRET_MAIL, "creds_loaded": True,
            "windows": [{"kind": "five_hour", "used_pct": five, "window_minutes": 300},
                        {"kind": "weekly", "used_pct": weekly, "window_minutes": 10080}], **extra}


def _pool(monkeypatch, claude, codex):
    raw = {"providers": {p: {"active_id": SECRET_ID, "ids": accounts}
                         for p, accounts in (("claude", claude), ("codex", codex))}}
    _patch_hub(monkeypatch, json.dumps(raw).encode())
    return raw


@pytest.mark.parametrize("five,weekly,usable", [
    (0, 0, 1), (99.99, 99.99, 1), (100, 1, 0), (1, 100, 0), (100, 100, 0),
    (None, 1, 0), (1, None, 0), (-1, 1, 0), (True, 1, 0),
])
def test_both_windows_must_be_below_the_threshold(monkeypatch, five, weekly, usable):
    _pool(monkeypatch, [_account(five, weekly)], [])
    pool = asyncio.run(hub_pool.get_hub_pool())
    assert pool["providers"]["claude"]["usable"] == usable
    assert SECRET_ID not in json.dumps(pool) and SECRET_MAIL not in json.dumps(pool)


@pytest.mark.parametrize("value,usable", [(79.99, 1), (80, 0), (80.01, 0)])
def test_configured_threshold_boundary(monkeypatch, value, usable):
    monkeypatch.setenv("MULTICODE_HUB_POOL_THRESHOLD_PCT", "80")
    _pool(monkeypatch, [_account(value, value)], [])
    summary = asyncio.run(hub_pool.get_hub_pool())["providers"]["claude"]
    assert summary["usable"] == usable and summary["threshold_pct"] == 80


@pytest.mark.parametrize("extra", [{"rejected": True}, {"windows": []}])
def test_unready_accounts_do_not_count(monkeypatch, extra):
    _pool(monkeypatch, [_account(**extra)], [])
    assert asyncio.run(hub_pool.get_hub_pool())["providers"]["claude"]["usable"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("model,provider,other", [
    ("hubsonnet", "claude", "hubsol"), ("hubopus", "claude", "hubsol"),
    ("hubsol", "codex", "hubsonnet"),
])
async def test_admission_checks_the_whole_pool_and_suggests_other_provider(monkeypatch, model, provider, other):
    from app.quota_gate import get_worker_admission, require_worker_admission, QuotaGateError

    accounts = [_account(100, 20), _account(30, 100)]
    _pool(monkeypatch, accounts if provider == "claude" else [_account()],
          accounts if provider == "codex" else [_account()])
    decision = await get_worker_admission(model)
    with pytest.raises(QuotaGateError, match=f"model='{other}'"):
        require_worker_admission(decision)
    assert decision.provider == f"hub_{provider}"
    assert decision.state == "blocked"
    # An inactive account with headroom opens admission even though the active one is exhausted.
    _pool(monkeypatch, accounts + [_account(id="inactive")] if provider == "claude" else [_account()],
                accounts + [_account(id="inactive")] if provider == "codex" else [_account()])
    await hub_pool.get_hub_pool(force=True)
    decision = await get_worker_admission(model)
    require_worker_admission(decision)
    assert decision.state == "available"
    assert _FakeHub.calls == 1  # forced dashboard read and admission share the cache


@pytest.mark.asyncio
async def test_unavailable_pool_warns_and_allows_admission(monkeypatch, caplog):
    from app.quota_gate import get_worker_admission, require_worker_admission

    _patch_hub(monkeypatch, HubWorkspaceError("offline"))
    decision = await get_worker_admission("hubsol")
    require_worker_admission(decision)
    assert decision.state == "unknown" and "unavailable" in decision.reason
    assert "pool unavailable" in caplog.text
    assert "unavailable" in await hub_pool.require_hub_capacity("hubsonnet")
    assert _FakeHub.calls == 1



def test_inactive_credentials_do_not_hide_an_account_with_headroom(monkeypatch):
    _pool(monkeypatch, [_account(creds_loaded=False)], [])
    assert asyncio.run(hub_pool.get_hub_pool())["providers"]["claude"]["usable"] == 1


@pytest.mark.asyncio
async def test_session_preflight_refuses_new_turn_on_exhausted_hub_pool(monkeypatch):
    from app.session import AgentSession
    from app.quota_gate import QuotaGateError

    _pool(monkeypatch, [_account(100, 20)], [_account()])
    session = AgentSession(id="worker-id", name="worker", scope="/s", cwd="/s",
                           model="hub-claude-sonnet-5-5", backend_type="hub")
    with pytest.raises(QuotaGateError, match="model='hubsol'"):
        await session.preflight_delivery_admission()
    assert _FakeHub.calls == 1


@pytest.mark.asyncio
async def test_codex_and_grok_weekly_only_real_relay_shape_is_usable(monkeypatch):
    raw = {"providers": {
        "codex": {"active_id": "codex-0", "ids": [
            {"id": f"codex-{index}", "creds_loaded": index == 0, "windows": [
                {"kind": "weekly", "label": "Weekly", "used_pct": used, "window_minutes": 10080}]}
            for index, used in enumerate([59, 28, 31, 95])]},
        "grok": {"active_id": "grok-0", "ids": [
            {"id": f"grok-{index}", "windows": [
                {"kind": "weekly", "label": "Weekly", "used_pct": used, "window_minutes": 10080}]}
            for index, used in enumerate([65, 99])]},
    }}
    _patch_hub(monkeypatch, json.dumps(raw).encode())
    pool = await hub_pool.get_hub_pool()
    assert pool["providers"]["codex"]["usable"] == 4
    assert pool["providers"]["codex"]["unknown"] == 0
    assert pool["providers"]["grok"]["usable"] == 2
    assert await hub_pool.require_hub_capacity("hubsol") is None
    assert _FakeHub.calls == 1


@pytest.mark.parametrize("values,usable,unknown", [
    ([79.99], 1, 0), ([80], 0, 0), ([80.01], 0, 0),
    ([20, 80], 0, 0), ([20, 30], 1, 0), ([], 0, 1), ([None], 0, 1),
])
def test_every_reported_window_counts_without_requiring_window_kinds(monkeypatch, values, usable, unknown):
    monkeypatch.setenv("MULTICODE_HUB_POOL_THRESHOLD_PCT", "80")
    _pool(monkeypatch, [], [_account(windows=[{"used_pct": value} for value in values])])
    codex = asyncio.run(hub_pool.get_hub_pool())["providers"]["codex"]
    assert codex["usable"] == usable and codex["unknown"] == unknown


@pytest.mark.asyncio
@pytest.mark.parametrize("headroom", [False, True])
async def test_accounts_without_windows_stay_unknown_and_are_not_admitted(monkeypatch, headroom):
    from app.quota_gate import QuotaGateError

    codex = [_account(windows=[])]
    if headroom:
        codex.append(_account(windows=[{"kind": "weekly", "used_pct": 20}]))
    _pool(monkeypatch, [], codex)
    pool = await hub_pool.get_hub_pool()
    assert pool["providers"]["codex"]["unknown"] == 1
    if headroom:
        assert await hub_pool.require_hub_capacity("hubsol") is None
    else:
        with pytest.raises(QuotaGateError, match="model='hubsonnet'") as caught:
            await hub_pool.require_hub_capacity("hubsol")
        assert caught.value.decision.state == "blocked"


@pytest.mark.asyncio
async def test_shared_capacity_fixture_prevents_live_relay_even_when_configured(monkeypatch):
    def forbidden(cls):
        raise AssertionError("tests must not construct the live hub relay transport")

    monkeypatch.setenv("MULTICODE_HUB_SSH", "test.invalid")
    monkeypatch.setenv("MULTICODE_HUB_SSH_KEY", "fixture-only")
    monkeypatch.setattr(hub_pool.HubSsh, "from_env", classmethod(forbidden))
    pool = await hub_pool.get_hub_pool(force=True)
    assert pool["available"] is True
    assert pool["providers"]["codex"]["usable"] == 1
    assert await hub_pool.require_hub_capacity("hubsol") is None
