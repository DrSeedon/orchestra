import importlib
import importlib.util
import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _controller():
    spec = importlib.util.find_spec("app.quota_controller")
    assert spec is not None, "app.quota_controller is not implemented"
    return importlib.import_module("app.quota_controller")


def test_t5_default_and_missing_evidence_cannot_enforce():
    controller = _controller()

    policy = controller.default_policy()
    assert policy.mode == "shadow"
    assert policy.enforcement_active is False

    verdict = controller.authorize_enforcement(
        policy=policy,
        evidence=None,
        live_regime_set_hash="live",
        owner_authenticated=True,
        now="2030-01-01T00:00:00Z",
    )
    assert verdict.allowed is False
    assert verdict.reason == "prospective_evidence_required"


def _enforce_policy(controller):
    return controller.policy_from_dict({
        "mode": "enforce",
        "revision": 1,
        "evidence_id": "e-1",
        "enabled_strata": ["codex:primary/sol/normal/worker"],
    })


def _current_evidence():
    return {
        "evidence_id": "e-1",
        "eligible": True,
        "prospective": True,
        "created_at": "2030-01-01T00:00:00Z",
        "regime_set_hash": "live",
        "eligible_strata": ["codex:primary/sol/normal/worker"],
    }


def test_t5_positive_path_enables_only_named_strata():
    controller = _controller()
    verdict = controller.authorize_enforcement(
        policy=_enforce_policy(controller),
        evidence=_current_evidence(),
        live_regime_set_hash="live",
        owner_authenticated=True,
        now="2030-01-01T00:09:59Z",
    )

    assert verdict.allowed is True
    assert verdict.enabled_strata == ("codex:primary/sol/normal/worker",)

    static_decision = object()
    adaptive_decision = object()
    named = controller.select_authoritative_decision(
        mode="enforce",
        stratum="codex:primary/sol/normal/worker",
        enabled_strata=verdict.enabled_strata,
        static_decision=static_decision,
        adaptive_decision=adaptive_decision,
        live_evidence_valid=True,
    )
    unlisted = controller.select_authoritative_decision(
        mode="enforce",
        stratum="grok:primary/grok/normal/worker",
        enabled_strata=verdict.enabled_strata,
        static_decision=static_decision,
        adaptive_decision=adaptive_decision,
        live_evidence_valid=True,
    )

    assert named.decision is adaptive_decision
    assert named.source == "adaptive"
    assert unlisted.decision is static_decision
    assert unlisted.reason == "stratum_not_enabled"


def test_t5_wrong_regime_stale_evidence_or_agent_auth_cannot_enable():
    controller = _controller()
    evidence = _current_evidence()

    wrong_regime = controller.authorize_enforcement(
        policy=_enforce_policy(controller),
        evidence={**evidence, "regime_set_hash": "old"},
        live_regime_set_hash="new",
        owner_authenticated=True,
        now="2030-01-01T00:09:59Z",
    )
    agent_attempt = controller.authorize_enforcement(
        policy=_enforce_policy(controller),
        evidence=evidence,
        live_regime_set_hash="live",
        owner_authenticated=False,
        now="2030-01-01T00:09:59Z",
    )
    stale = controller.authorize_enforcement(
        policy=_enforce_policy(controller),
        evidence=evidence,
        live_regime_set_hash="live",
        owner_authenticated=True,
        now="2030-01-01T00:10:01Z",
    )

    assert wrong_regime.allowed is False
    assert wrong_regime.reason == "live_regime_mismatch"
    assert agent_attempt.allowed is False
    assert agent_attempt.reason == "owner_auth_required"
    assert stale.allowed is False
    assert stale.reason == "evidence_stale"


def test_t5_hot_disable_and_drift_restore_static_decision_identity():
    controller = _controller()
    static_decision = object()
    adaptive_decision = object()

    disabled = controller.select_authoritative_decision(
        mode="shadow",
        stratum="codex:primary/sol/normal/worker",
        enabled_strata=("codex:primary/sol/normal/worker",),
        static_decision=static_decision,
        adaptive_decision=adaptive_decision,
        live_evidence_valid=True,
    )
    drifted = controller.select_authoritative_decision(
        mode="enforce",
        stratum="codex:primary/sol/normal/worker",
        enabled_strata=("codex:primary/sol/normal/worker",),
        static_decision=static_decision,
        adaptive_decision=adaptive_decision,
        live_evidence_valid=False,
    )
    failed = controller.select_authoritative_decision(
        mode="enforce",
        stratum="codex:primary/sol/normal/worker",
        enabled_strata=("codex:primary/sol/normal/worker",),
        static_decision=static_decision,
        adaptive_decision=adaptive_decision,
        live_evidence_valid=True,
        controller_error=RuntimeError("boom"),
    )

    assert disabled.decision is static_decision
    assert disabled.reason == "shadow_mode"
    assert drifted.decision is static_decision
    assert drifted.reason == "live_evidence_invalid"
    assert failed.decision is static_decision
    assert failed.reason == "controller_error:RuntimeError"
    assert failed.demote_to_shadow is True


def test_t5_policy_replace_is_revision_cas_and_fail_safe_demotes_atomically(tmp_path):
    controller = _controller()
    store = controller.SQLiteControllerStore(tmp_path / "controller.db")
    store.append_evidence(_current_evidence())

    enabled = store.replace_policy(
        expected_revision=0,
        policy=_enforce_policy(controller),
        live_regime_set_hash="live",
        owner_authenticated=True,
        now="2030-01-01T00:09:59Z",
    )
    assert enabled.mode == "enforce"
    assert enabled.revision == 1
    with pytest.raises(controller.PolicyRevisionError):
        store.replace_policy(
            expected_revision=0,
            policy=_enforce_policy(controller),
            live_regime_set_hash="live",
            owner_authenticated=True,
            now="2030-01-01T00:09:59Z",
        )

    demoted = store.fail_safe_demote(
        expected_revision=1,
        reason="controller_error:RuntimeError",
    )
    assert demoted.mode == "shadow"
    assert demoted.revision == 2
    assert store.last_fail_safe_reason() == "controller_error:RuntimeError"


def _request(*, cookie="", bearer=""):
    headers = []
    if cookie:
        headers.append((b"cookie", f"session={cookie}".encode()))
    if bearer:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    return Request({"type": "http", "method": "PUT", "path": "/", "headers": headers})


@pytest.mark.asyncio
async def test_t5_policy_api_rejects_internal_token_and_accepts_owner_cookie(monkeypatch):
    from app import auth
    from app.routes import system

    monkeypatch.setenv("DASHBOARD_USER", "owner")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")
    monkeypatch.setenv("INTERNAL_TOKEN", "agent-token")

    class Service:
        def __init__(self):
            self.calls = 0

        async def replace_policy(self, payload):
            self.calls += 1
            return {"mode": payload["mode"], "revision": 1}

    service = Service()
    monkeypatch.setattr(system, "get_quota_controller", lambda: service)
    payload = {"mode": "shadow", "expected_revision": 0}

    with pytest.raises(HTTPException) as denied:
        await system.replace_quota_controller_policy(
            _request(bearer="agent-token"), payload,
        )
    assert denied.value.status_code == 403

    result = await system.replace_quota_controller_policy(
        _request(cookie=auth.create_session("owner")), payload,
    )
    assert result == {"mode": "shadow", "revision": 1}
    assert service.calls == 1
