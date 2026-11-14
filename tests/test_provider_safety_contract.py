"""Dynamic runtime anti-ban & residential proxy safety contracts for subscription OAuth providers."""
from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import subprocess
import tomllib
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from app import backend_antigravity, backend_claude, backend_codex, backend_grok, mcp_stdio, models
from app import provider_safety as ps
from app.routes import system


@pytest.fixture(autouse=True)
def _isolated_safety_state(tmp_path, monkeypatch):
    ps.reset_provider_safety_state_for_tests()
    disabled_file = tmp_path / "disabled_providers.json"
    disabled_file.write_text(json.dumps({"disabled_providers": []}), encoding="utf-8")
    monkeypatch.setenv("ORCHESTRA_DISABLED_PROVIDERS_FILE", str(disabled_file))
    monkeypatch.delenv("ORCHESTRA_DISABLED_PROVIDERS", raising=False)
    for var in (
        *ps.PROXY_ENV_VARS,
        *ps.NO_PROXY_ENV_VARS,
        "ORCHESTRA_RESIDENTIAL_PROXY_URL",
        "CLAUDE_PROXY_URL",
        "CODEX_PROXY_URL",
        "GROK_PROXY_URL",
        "ANTIGRAVITY_PROXY_URL",
        "ALLOW_DATACENTER_OAUTH_EGRESS",
        "ORCHESTRA_ENFORCE_PROVIDER_EGRESS",
    ):
        monkeypatch.delenv(var, raising=False)
    yield
    ps.reset_provider_safety_state_for_tests()


@contextlib.contextmanager
def _local_dummy_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(8)
    port = sock.getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        sock.close()


def test_build_provider_env_pins_residential_proxy_and_strips_untrusted_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRA_RESIDENTIAL_PROXY_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("NO_PROXY", "*,internal.local,.openai.com,.googleapis.com,.com,0.0.0.0/0")
    monkeypatch.setenv("GEMINI_API_KEY", "leak-gemini")
    monkeypatch.setenv("OPENAI_API_KEY", "leak-openai")

    malicious_mcp_env = {
        "HTTPS_PROXY": "http://evil.proxy:9999",
        "https_proxy": "http://evil.proxy:9999",
        "ALL_PROXY": "socks5://evil.proxy:9999",
        "NO_PROXY": "*",
        "OPENAI_BASE_URL": "https://attacker.invalid/v1",
        "SSL_CERT_FILE": "/tmp/mitm.pem",
        "NODE_OPTIONS": "--require /tmp/pwn.js",
        "LD_PRELOAD": "/tmp/pwn.so",
        "SAFE_CUSTOM_FLAG": "kept",
    }

    for provider in ps.SUBSCRIPTION_OAUTH_RUNTIMES:
        env = ps.build_provider_env(provider, extra_env=malicious_mcp_env)
        for var in ps.PROXY_ENV_VARS:
            assert env[var] == "http://127.0.0.1:18080"
        no_proxy_parts = [p.strip() for p in env["NO_PROXY"].split(",") if p.strip()]
        assert "*" not in no_proxy_parts
        assert "0.0.0.0/0" not in no_proxy_parts
        assert ".openai.com" not in no_proxy_parts
        assert ".googleapis.com" not in no_proxy_parts
        assert ".com" not in no_proxy_parts
        assert "internal.local" in no_proxy_parts
        for loop_host in ("localhost", "127.0.0.1", "::1", "[::1]"):
            assert loop_host in no_proxy_parts
        assert env["NO_PROXY"] == env["no_proxy"]
        assert env["SAFE_CUSTOM_FLAG"] == "kept"
        assert "SSL_CERT_FILE" not in env
        assert "NODE_OPTIONS" not in env
        assert "LD_PRELOAD" not in env

    agy_env = backend_antigravity.cli_environment(tmp_path / "agy-home")
    assert agy_env["HTTPS_PROXY"] == "http://127.0.0.1:18080"
    assert agy_env["ALL_PROXY"] == "http://127.0.0.1:18080"
    assert "GEMINI_API_KEY" not in agy_env

    fake_grok_user = tmp_path / "user-grok"
    fake_grok_user.mkdir()
    (fake_grok_user / "auth.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(backend_grok, "GROK_HOME_DIR", tmp_path / "grok-home")
    monkeypatch.setattr(backend_grok, "GROK_USER_HOME", fake_grok_user)
    grok_b = backend_grok.GrokBackend(model="grok-4.20", cwd=str(tmp_path), mcp_env=malicious_mcp_env)
    grok_env = grok_b._build_env()
    assert grok_env["HTTPS_PROXY"] == "http://127.0.0.1:18080"
    assert grok_env["ALL_PROXY"] == "http://127.0.0.1:18080"
    assert "*" not in grok_env["NO_PROXY"]

    claude_overlay = ps.build_claude_sdk_env_overlay(config_dir="~/claude-prof")
    assert claude_overlay["HTTPS_PROXY"] == "http://127.0.0.1:18080"
    assert claude_overlay["ANTHROPIC_API_KEY"] == ""
    assert claude_overlay["ORCHESTRA_CLAUDE_CREDIT_API_KEY"] == ""
    assert claude_overlay["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert claude_overlay["DISABLE_AUTOUPDATER"] == "1"
    assert Path(claude_overlay["CLAUDE_ENV_FILE"]).is_file()


def test_worker_bash_tool_proxy_isolation_in_codex_and_claude(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRA_RESIDENTIAL_PROXY_URL", "http://127.0.0.1:18080")
    monkeypatch.setattr(backend_codex, "_CODEX_HOME_ROOT", tmp_path / "codex-homes")
    cb = backend_codex.CodexBackend(
        model="gpt-5.6-sol",
        cwd=str(tmp_path),
        mcp_servers={"orchestra": {"command": "python3", "args": [], "env": {"ORCHESTRA_SESSION_ID": "sess-anti-ban"}}},
    )
    home = cb._prepare_codex_home()
    parsed = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    assert parsed["check_for_update_on_startup"] is False
    assert parsed["analytics"]["enabled"] is False
    assert parsed["feedback"]["enabled"] is False
    excluded = set(parsed["shell_environment_policy"]["exclude"])
    for proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        assert proxy_var in excluded

    cmd = cb._codex_command()
    overrides = [cmd[i + 1] for i, tok in enumerate(cmd[:-1]) if tok == "-c"]
    assert "analytics.enabled=false" in overrides
    assert "feedback.enabled=false" in overrides
    assert "check_for_update_on_startup=false" in overrides
    assert any(o.startswith("shell_environment_policy.exclude=") for o in overrides)
    assert overrides[-1] == "features.sleep_tool=false"

    # Verify Claude's CLAUDE_ENV_FILE actually strips proxy vars in bash subshells.
    clean_script = ps.ensure_claude_bash_clean_script()
    out = subprocess.check_output(
        ["bash", "-c", f'. "{clean_script}"; env | grep -i "_proxy=" || true'],
        env={
            "PATH": "/usr/bin:/bin",
            "HTTP_PROXY": "http://127.0.0.1:18080",
            "HTTPS_PROXY": "http://127.0.0.1:18080",
            "ALL_PROXY": "http://127.0.0.1:18080",
            "http_proxy": "http://127.0.0.1:18080",
            "https_proxy": "http://127.0.0.1:18080",
            "all_proxy": "http://127.0.0.1:18080",
        },
        text=True,
    )
    assert out.strip() == ""


@pytest.mark.asyncio
async def test_verify_provider_egress_fail_closed_matrix_and_singleflight(monkeypatch):
    monkeypatch.setenv("ORCHESTRA_ENFORCE_PROVIDER_EGRESS", "1")

    # 1. Missing proxy -> Fail-Closed with 0 network requests.
    with pytest.raises(ps.EgressSafetyError, match="no residential proxy configured"):
        await ps.verify_provider_egress("codex")

    # 2. Closed local TCP port -> Fail-Closed immediately.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    closed_port = sock.getsockname()[1]
    sock.close()
    monkeypatch.setenv("ORCHESTRA_RESIDENTIAL_PROXY_URL", f"http://127.0.0.1:{closed_port}")
    with pytest.raises(ps.EgressSafetyError, match="unreachable"):
        await ps.verify_provider_egress("codex")

    # 3. Contabo AS51167 datacenter exit -> Fail-Closed.
    with _local_dummy_listener() as proxy_url:
        monkeypatch.setenv("ORCHESTRA_RESIDENTIAL_PROXY_URL", proxy_url)
        ps.reset_provider_safety_state_for_tests()
        monkeypatch.setattr(
            ps,
            "_probe_proxy_egress_identity",
            AsyncMock(return_value={
                "ip": "158.220.127.161",
                "country": "DE",
                "asn": 51167,
                "org": "Contabo GmbH",
                "hosting": True,
                "source": "ipwho.is",
            }),
        )
        with pytest.raises(ps.EgressSafetyError, match="AS51167"):
            await ps.verify_provider_egress("codex")

    # 4. RU / BY country -> Fail-Closed.
    with _local_dummy_listener() as proxy_url:
        monkeypatch.setenv("ORCHESTRA_RESIDENTIAL_PROXY_URL", proxy_url)
        ps.reset_provider_safety_state_for_tests()
        monkeypatch.setattr(
            ps,
            "_probe_proxy_egress_identity",
            AsyncMock(return_value={
                "ip": "95.24.10.20",
                "country": "RU",
                "asn": 8402,
                "org": "Vimpelcom",
                "hosting": False,
                "source": "ipwho.is",
            }),
        )
        with pytest.raises(ps.EgressSafetyError, match="Blocked egress country 'RU'"):
            await ps.verify_provider_egress("claude")

    # 5. Clean NL residential ISP + concurrent singleflight -> 1 probe total!
    with _local_dummy_listener() as proxy_url:
        monkeypatch.setenv("ORCHESTRA_RESIDENTIAL_PROXY_URL", proxy_url)
        ps.reset_provider_safety_state_for_tests()
        calls = 0

        async def _slow_nl_probe(_url: str) -> dict:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.03)
            return {
                "ip": "178.93.29.64",
                "country": "NL",
                "asn": 215294,
                "org": "Lumina broadband UAB",
                "hosting": False,
                "source": "ipwho.is",
            }

        monkeypatch.setattr(ps, "_probe_proxy_egress_identity", _slow_nl_probe)
        results = await asyncio.gather(
            *(ps.verify_provider_egress(p) for p in ("codex", "claude", "grok", "antigravity"))
        )
        assert calls == 1
        assert all(r["ip"] == "178.93.29.64" and r["country"] == "NL" for r in results)

        # Disabled provider is rejected BEFORE touching cache or proxy.
        models.set_provider_disabled("antigravity", True)
        with pytest.raises(ps.ProviderDisabledError):
            await ps.verify_provider_egress("antigravity")


@pytest.mark.asyncio
async def test_mcp_stdio_local_api_uses_trust_env_false(monkeypatch):
    captured_kwargs: dict = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, path, params=None):
            return httpx.Response(200, json={"ok": True})

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:18080")
    monkeypatch.setattr(mcp_stdio.httpx, "AsyncClient", FakeClient)
    res = await mcp_stdio._api("GET", "/api/health")
    assert res == {"ok": True}
    assert captured_kwargs.get("trust_env") is False


@pytest.mark.asyncio
async def test_idle_snapshot_loop_makes_zero_external_calls_and_persists_piggyback(tmp_path, monkeypatch):
    import app.db

    saved_snapshots: list[dict] = []
    monkeypatch.setattr(app.db, "usage_save_snapshot", lambda *a, **kw: saved_snapshots.append(kw))
    monkeypatch.setattr(system.manager, "sessions", {})
    monkeypatch.setattr(system, "_usage_cache", {"data": None, "ts": 0.0, "error": None, "failed_at": 0.0})
    monkeypatch.setattr(system, "_codex_usage_cache", {"data": None, "ts": 0.0, "failed_at": 0.0})
    monkeypatch.setattr(system, "_grok_usage_cache", {"data": None, "ts": 0.0, "failed_at": 0.0})
    monkeypatch.setattr(system, "_antigravity_usage_cache", {"data": None, "ts": 0.0, "failed_at": 0.0})
    monkeypatch.setattr(system, "_last_snapshot_persisted_ts", {})

    def _forbid(*_a, **_kw):
        raise AssertionError("Idle snapshot loop must NOT invoke active OAuth fetchers!")

    monkeypatch.setattr(system, "_fetch_anthropic_usage", _forbid)
    monkeypatch.setattr(system, "_fetch_codex_usage", _forbid)
    monkeypatch.setattr(system, "_fetch_grok_usage", _forbid)
    monkeypatch.setattr(system, "_fetch_antigravity_usage", _forbid)

    # 1. Completely idle system -> 0 fetches, 0 snapshots written.
    await system._collect_usage_snapshot(respect_idle=True)
    assert saved_snapshots == []

    # 2. Piggyback Codex rollout `token_count.rate_limits` (snake_case) -> persisted with 0 fetches!
    rollout = tmp_path / "rollout-thread-1.jsonl"
    rollout.write_text(
        json.dumps({
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {"input_tokens": 1000, "output_tokens": 200},
                    "last_token_usage": {"input_tokens": 1000},
                    "model_context_window": 272000,
                },
                "rate_limits": {
                    "plan_type": "pro",
                    "primary": {"used_percent": 14.0, "window_minutes": 300, "resets_at": 1794680000},
                    "secondary": {"used_percent": 6.0, "window_minutes": 10080, "resets_at": 1795200000},
                    "credits": {"has_credits": False, "unlimited": False, "balance": None},
                },
            },
        }) + "\n",
        encoding="utf-8",
    )
    extracted = backend_codex._read_rollout_rate_limits(rollout)
    assert extracted is not None
    system.record_codex_rate_limits(extracted)

    await system._collect_usage_snapshot(respect_idle=True)
    assert len(saved_snapshots) == 1
    assert saved_snapshots[0]["providers"]["codex"]["windows"][0]["utilization"] == 14


@pytest.mark.asyncio
async def test_grok_quota_observation_uses_grok_cache_not_codex_cache(monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(
        system,
        "_codex_usage_cache",
        {"data": {"primary": {"utilization": 10, "window_minutes": 300, "resets_at": None}}, "ts": now, "failed_at": 0.0},
    )
    monkeypatch.setattr(system, "_grok_usage_cache", {"data": None, "ts": 0.0, "failed_at": 0.0})

    refresh_called = []

    async def _fake_get_usage(*, force_refresh=False, required_provider=""):
        refresh_called.append((force_refresh, required_provider))
        system._grok_usage_cache["data"] = {
            "plan_type": "supergrok",
            "primary": {"utilization": 22, "window_minutes": 10080, "resets_at": "2026-11-20T00:00:00Z"},
            "secondary": None,
        }
        system._grok_usage_cache["ts"] = now
        return {}

    monkeypatch.setattr(system, "_get_usage_data", _fake_get_usage)
    obs = await system.current_quota_observation(required_provider="grok", max_age=300.0, now=now)
    assert refresh_called == [(True, "grok")]
    assert obs["providers"]["grok"]["windows"][0]["utilization"] == 22


def test_permanent_ban_circuit_breaker_trips_only_on_unambiguous_bans():
    # 429 rate-limit and 401 token expiry MUST NEVER disable a provider.
    assert ps.classify_and_trip_if_banned("codex", status_code=429, payload="rate limit exceeded") is None
    assert ps.classify_and_trip_if_banned("claude", status_code=401, payload="token_expired") is None
    assert not models.is_provider_disabled("codex")
    assert not models.is_provider_disabled("claude")

    # Unambiguous ToS / account-disabled payload trips durable circuit-breaker.
    res = backend_codex.CodexBackend._classify_error(
        {"message": "403 Forbidden: Your account has been disabled for violation of Terms of Service"}
    )
    assert res == "credentials"
    assert models.is_provider_disabled("codex")

    res_grok = backend_grok.GrokBackend._classify_error(
        {"code": 403, "message": "Access denied: organization has been disabled"}
    )
    assert res_grok == "credentials"
    assert models.is_provider_disabled("grok")


@pytest.mark.asyncio
async def test_antigravity_partial_stream_never_masks_credentials_ban(tmp_path, monkeypatch):
    auth_home = tmp_path / "agy-auth"
    token_file = auth_home / backend_antigravity.TOKEN_RELATIVE_PATH
    token_file.parent.mkdir(parents=True)
    token_file.write_bytes(b"oauth-secret-blob")
    monkeypatch.setattr(backend_antigravity, "ANTIGRAVITY_AUTH_HOME", auth_home)
    monkeypatch.setattr(backend_antigravity, "ANTIGRAVITY_HOME_ROOT", tmp_path / "agy-homes")

    class _Ctx:
        model = "antigravity/gemini-4-carbon"
        cwd = str(tmp_path)
        system_prompt = ""
        context_limit = 200000
        resume_session_id = None
        mcp_servers = {"orchestra": {"env": {"ORCHESTRA_SESSION_ID": "sess-agy-1"}}}

    b = backend_antigravity.AntigravityBackend(_Ctx())
    b.home.mkdir(parents=True, exist_ok=True)

    lines = [
        json.dumps({"event": "init", "conversation_id": "conv-1"}).encode() + b"\n",
        json.dumps({
            "event": "step_update",
            "step_update": {"step_type": "agent_response", "text_delta": "Partial text before ban", "state": "DONE"},
        }).encode() + b"\n",
        json.dumps({
            "event": "result",
            "result": {
                "status": "ERROR",
                "response": "Partial text before ban",
                "error": "403 Forbidden: This service has been disabled in this account for violation of Terms of Service.",
            },
        }).encode() + b"\n",
    ]

    class FakeStream:
        def __init__(self, items):
            self._items = iter(items)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._items)
            except StopIteration:
                raise StopAsyncIteration

        async def read(self, _n):
            return b""

    class FakeProc:
        pid = 999999
        returncode = 1
        stdout = FakeStream(lines)
        stderr = FakeStream([])

        async def wait(self):
            return 1

    monkeypatch.setattr(backend_antigravity.asyncio, "create_subprocess_exec", AsyncMock(return_value=FakeProc()))
    await b.send("ping")
    collected = [ev async for ev in b.events()]
    turn_end = [ev for ev in collected if ev.type == "turn_end"][-1]
    assert turn_end.metadata["ok"] is False
    assert turn_end.metadata["model_error"] == "credentials"
    assert models.is_provider_disabled("antigravity")


def test_codex_review_resume_aborts_on_ban_without_firing_second_fresh_request(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    (tmp_path / ".orchestra").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".orchestra" / "project-context.toml").write_text(
        'schema_version = 1\nscale = "solo"\nusers = "1"\nstack = "python"\n'
        'philosophy = "safety"\nwhat_matters = "correctness"\nwhat_does_not_matter = "hype"\n',
        encoding="utf-8",
    )
    (tmp_path / "plan.md").write_text("# Plan\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], check=True, capture_output=True)

    (tmp_path / "codex_sessions.json").write_text(
        json.dumps({"sessions": {"ban-review": {"uuid": "019f0000-0000-7000-8000-000000000099"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(tmp_path / "test.db"))
    from app import db
    db.init_db()

    invocations_log = tmp_path / "invocations.log"
    fake_codex = tmp_path / "fake-codex"
    fake_codex.write_text(
        f"""#!/bin/sh
echo "CALL:$*" >> "{invocations_log}"
echo "403 Forbidden: Your account has been disabled for violation of Terms of Service" >&2
exit 1
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)

    captured: dict = {}

    async def fake_api(method, path, **kwargs):
        if method == "GET" and path.startswith("/api/sessions/"):
            return {
                "id": "sess-worker-1",
                "role": "worker",
                "is_orchestrator": False,
                "cwd": str(tmp_path),
                "worktree_path": str(tmp_path),
                "task_id": "1",
            }
        if method == "POST" and path == "/api/bg/jobs":
            captured.update(kwargs["json"])
            return {"id": "job-1", "status": "running"}
        return {"ok": True}

    monkeypatch.setenv("ORCHESTRA_RESIDENTIAL_PROXY_URL", "http://127.0.0.1:18080")
    monkeypatch.setattr(mcp_stdio, "_api", fake_api)
    monkeypatch.setattr(mcp_stdio, "_quota_refusal", AsyncMock(return_value=None))
    monkeypatch.setattr(mcp_stdio, "_codex_bin", lambda: str(fake_codex))
    monkeypatch.setattr(mcp_stdio, "WORKER_NAME", "w1")
    monkeypatch.setattr(mcp_stdio, "SCOPE", str(tmp_path))
    (tmp_path / "plan.md").write_text("# Plan\n", encoding="utf-8")

    asyncio.run(
        mcp_stdio.codex_review(
            context="Check plan",
            target="plan.md",
            output="ban-review.md",
            mode="exec",
            resume=True,
        )
    )
    cmd = captured["config"]["command"]
    assert "HTTPS_PROXY=http://127.0.0.1:18080" in cmd
    assert "shell_environment_policy.exclude=" in cmd
    proc = subprocess.run(["dash", "-c", cmd], capture_output=True, text=True)
    assert proc.returncode != 0
    calls = invocations_log.read_text(encoding="utf-8").strip().splitlines()
    # Must have executed ONLY `exec resume`, NEVER the second `fresh` call!
    assert len(calls) == 1
    assert models.is_provider_disabled("codex")
