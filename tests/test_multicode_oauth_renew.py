import base64
import hashlib
import json
import os
import stat

from scripts.multicode_oauth_renew import (
    atomic_write_token,
    build_authorization_request,
    build_decision_payload,
    build_token_request,
    pkce_challenge,
    renewal_decision,
    token_claims,
)


def test_pkce_challenge_uses_base64url_sha256_without_padding():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert pkce_challenge(verifier) == expected
    assert "=" not in pkce_challenge(verifier)


def test_oauth_payload_builders_keep_callback_and_full_access_decision():
    authorization = build_authorization_request(
        "client", "http://127.0.0.1:18765/auth/callback", "challenge", "state", "http://hub/mcp")
    assert authorization == {
        "response_type": "code", "client_id": "client",
        "redirect_uri": "http://127.0.0.1:18765/auth/callback",
        "code_challenge": "challenge", "code_challenge_method": "S256",
        "state": "state", "resource": "http://hub/mcp",
    }
    assert build_decision_payload(authorization, "pair-code") == {
        "authorization": authorization,
        "decision": {"_tag": "pairing-code", "access": "full-access", "code": "pair-code"},
    }
    assert build_token_request("code", "redirect", "client", "verifier", "resource") == {
        "grant_type": "authorization_code", "code": "code", "redirect_uri": "redirect",
        "client_id": "client", "code_verifier": "verifier", "resource": "resource",
    }


def test_token_claims_extract_session_and_access_ceiling():
    claims = {"sub": "mcp-client", "sid": "session-id", "rtc": "full-access",
              "scopes": ["orchestration:read"], "exp": 123}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    assert token_claims(f"{payload}.signature") == claims


def test_atomic_write_replaces_token_with_private_file(tmp_path):
    path = tmp_path / "multicode.token"
    path.write_text("old-token")
    path.chmod(0o644)

    atomic_write_token(path, "new-token")

    assert path.read_text() == "new-token"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".multicode.token.*"))


def test_renewal_decision_skips_only_when_more_than_threshold_remains():
    day_ms = 24 * 60 * 60 * 1000
    now_ms = 1_800_000_000_000
    assert renewal_decision(now_ms + 11 * day_ms, 10, now_ms=now_ms) == (True, 11.0)
    assert renewal_decision(now_ms + 10 * day_ms, 10, now_ms=now_ms) == (False, 10.0)


def test_expiration_skip_does_not_touch_hub(tmp_path, monkeypatch, capsys):
    from scripts import multicode_oauth_renew as renewal

    now_ms = 1_800_000_000_000
    claims = {"sub": "mcp-client", "sid": "session-id", "exp": now_ms + 10 * 24 * 60 * 60 * 1000}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    token_path = tmp_path / "token"
    token_path.write_text(f"{payload}.signature")
    monkeypatch.setattr(renewal, "TOKEN_PATH", token_path)
    monkeypatch.setattr(renewal.time, "time", lambda: now_ms / 1000)
    monkeypatch.setattr(renewal, "ssh_run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Hub touched")))
    monkeypatch.setattr(renewal.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Hub tunnel opened")))

    assert renewal.main(["--if-expiring-within-days", "9"]) == 0
    assert capsys.readouterr().out.strip() == "RENEW_SKIPPED 10.00"
