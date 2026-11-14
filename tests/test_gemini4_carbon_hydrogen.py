import pytest
from unittest.mock import AsyncMock

from app import backend_hub, models, quota_gate
from app.pipeline import get_role, load_pipeline, resolve_effort


def test_carbon_and_hydrogen_aliases_and_context_limits():
    assert models.resolve_model("hubcarbon") == "hub-gemini-4-carbon"
    assert models.resolve_model("hubhydrogen") == "hub-gemini-4-hydrogen"
    assert models.resolve_model("agy-carbon") == "antigravity/gemini-4-carbon-medium"
    assert models.resolve_model("agy-hydrogen") == "antigravity/gemini-4-hydrogen-high"

    for raw in (
        "gemini-4-carbon-low", "gemini-4-carbon-medium", "gemini-4-carbon-high",
        "gemini-4-hydrogen-low", "gemini-4-hydrogen-medium", "gemini-4-hydrogen-high", "gemini-4-hydrogen-xhigh",
    ):
        full = f"antigravity/{raw}"
        assert full in models.MODELS
        assert models.CONTEXT_LIMITS[full] == 1_000_000
        decision = quota_gate.evaluate_worker_admission(full, {}, {}, now=1000.0)
        assert decision.provider == "antigravity_gemini"


@pytest.mark.parametrize("scope", ["/home/kesha/orchestra", "/home/kesha/seedon", "/mnt/multicast/game"])
@pytest.mark.parametrize("alias", ["hubcarbon", "hubhydrogen", "hub-gemini-4-carbon", "hub-gemini-4-hydrogen"])
def test_carbon_and_hydrogen_admitted_across_all_project_scopes(scope, alias, monkeypatch):
    monkeypatch.delenv("ORCHESTRA_ALLOW_CLAUDE_ALL", raising=False)
    models.ensure_hub_worker_allowed(alias, role="worker", pipeline="default", scope=scope, task_id="t1")


def test_default_pipeline_effort_for_carbon_and_hydrogen():
    load_pipeline.cache_clear()
    for role_name in ("orchestrator", "sub-orchestrator", "worker", "full-cycle", "reducer", "specialist"):
        role = get_role("default", role_name)
        assert resolve_effort(role.effort, "hub-gemini-4-carbon", "hub") == "medium"
        assert resolve_effort(role.effort, "hub-gemini-4-hydrogen", "hub") == "high"


@pytest.mark.asyncio
async def test_hub_backend_model_selection_supports_carbon_and_unlisted_hydrogen():
    hb = backend_hub.HubBackend(model="hub-gemini-4-hydrogen", cwd="/tmp")
    mc = AsyncMock()
    # Simulate current T3 capabilities where Carbon is listed and Hydrogen is omitted by onlyListed=true.
    mc.tool_call = AsyncMock(return_value={
        "providers": [{
            "providerInstanceId": "antigravity",
            "models": [{
                "id": "gemini-4-carbon",
                "options": [{
                    "id": "reasoningEffort",
                    "type": "select",
                    "options": [{"id": "low"}, {"id": "medium"}, {"id": "high"}],
                }],
            }],
        }],
    })

    for eff in ("low", "medium", "high"):
        sel = await hb._model_selection(mc, "hub-gemini-4-carbon", eff)
        assert sel == {
            "instanceId": "antigravity",
            "model": "gemini-4-carbon",
            "options": {"reasoningEffort": eff},
        }
    with pytest.raises(ValueError, match="does not support effort 'xhigh'"):
        await hb._model_selection(mc, "hub-gemini-4-carbon", "xhigh")

    for eff in ("low", "medium", "high", "xhigh"):
        sel = await hb._model_selection(mc, "hub-gemini-4-hydrogen", eff)
        assert sel == {
            "instanceId": "antigravity",
            "model": "gemini-4-hydrogen",
            "options": {"reasoningEffort": eff},
        }
    with pytest.raises(ValueError, match="does not support effort 'max'"):
        await hb._model_selection(mc, "hub-gemini-4-hydrogen", "max")


def test_antigravity_gemini4_dashboard_visibility_and_frontend_tokens():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert models.resolve_model("agy-hydrogen-xhigh") == "antigravity/gemini-4-hydrogen-xhigh"
    for raw in (
        "gemini-4-carbon-medium", "gemini-4-carbon-high", "gemini-4-carbon-low",
        "gemini-4-hydrogen-xhigh", "gemini-4-hydrogen-high", "gemini-4-hydrogen-medium", "gemini-4-hydrogen-low",
        "gemini-4-argon-medium", "gemini-pro-orchestrator",
        "claude-opus-5-5-high", "claude-sonnet-5-5-high",
    ):
        spec = models.get_model_spec(f"antigravity/{raw}")
        assert spec.default_dashboard is True
        assert spec.default_agents is False
        assert spec.context_length == 1_000_000

    css = (root / "app/static/css/design-system.css").read_text()
    for token in ("--model-carbon:", "--model-hydrogen:", "--model-argon:"):
        assert token in css

    theme_js = (root / "app/static/js/theme.js").read_text()
    for fam in ("carbon", "hydrogen", "argon"):
        assert f"['{fam}'," in theme_js

    app_js = (root / "app/static/js/app.js").read_text()
    assert "['antigravity', 'Antigravity']" in app_js



@pytest.mark.asyncio
async def test_antigravity_agent_markdown_accepted_by_agy_cli(tmp_path, monkeypatch):
    import json
    import os
    import shutil
    import subprocess
    from app.runtime_registry import BackendBuildContext, build_backend

    homes = tmp_path / "ag-homes"
    from app import backend_antigravity
    monkeypatch.setattr(backend_antigravity, "ANTIGRAVITY_HOME_ROOT", homes)
    cwd = tmp_path / "ws"
    cwd.mkdir()
    backend = build_backend(
        "antigravity",
        BackendBuildContext(
            model="antigravity/gemini-4-carbon-medium",
            provider="google-antigravity",
            cwd=str(cwd),
            system_prompt="# Orchestra Prompt\n\nKeep working.",
            resume_session_id=None,
            mcp_servers={
                "orchestra": {
                    "command": "/opt/orchestra/python",
                    "args": ["/opt/orchestra/mcp_stdio.py"],
                    "env": {"ORCHESTRA_SESSION_ID": "test-carbon-cli"},
                }
            },
            is_orchestrator=True,
            scope=str(cwd),
            pipeline="default",
            role="orchestrator",
            profile="default",
            effort="medium",
            context_limit=1_000_000,
        ),
    )
    await backend.connect()

    agent_md = (backend.home / ".gemini/config/agents/orchestra/agent.md").read_text()
    assert "description: Orchestra session agent" in agent_md
    assert "commandExecutionPolicy: eager" in agent_md
    assert "  - run_command" in agent_md
    assert "# Agent System Instructions" in agent_md
    assert "# Orchestra Prompt" in agent_md

    settings = json.loads((backend.home / ".gemini/antigravity-cli/settings.json").read_text())
    assert settings["toolPermission"] == "always-proceed"
    assert settings["allowNonWorkspaceAccess"] is True

    agy_bin = shutil.which("agy") or "/home/kesha/.local/bin/agy"
    if os.path.exists(agy_bin):
        env = {**os.environ, "HOME": str(backend.home)}
        res = subprocess.run(
            [agy_bin, "--output-format", "json", "agents"],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert res.returncode == 0, res.stderr
        parsed = json.loads(res.stdout)
        agents = (parsed.get("command", {}).get("data", {}).get("agents") or parsed.get("agents") or [])
        assert "orchestra" in agents, parsed



def test_antigravity_carbon_cost_turn_usage_and_5h_quota(monkeypatch):
    import time
    from app.backend_antigravity import (
        _antigravity_cost,
        normalize_antigravity_five_hour_quota,
    )
    from app.routes import system
    from app.runtime_registry import BackendBuildContext, build_backend
    from app.session_turns import _cached_quota_snapshot

    # 1M fresh ($2.00) + 2M cached ($0.20) + 0.1M output incl thinking ($1.00) = $3.20
    assert _antigravity_cost("gemini-4-carbon-medium", 1_000_000, 2_000_000, 100_000) == 3.2
    # Hydrogen: 1M fresh ($1.50) + 1M cached ($0.075) + 0.1M output ($0.75) = $2.325
    assert _antigravity_cost("gemini-4-hydrogen-high", 1_000_000, 1_000_000, 100_000) == 2.325
    # Legacy unpriced model keeps None -> cost_unaccounted=True
    assert _antigravity_cost("gemini-3.6-flash-low", 1_000, 500, 100) is None

    b = build_backend(
        "antigravity",
        BackendBuildContext(
            model="antigravity/gemini-4-carbon-medium",
            provider="google-antigravity",
            cwd="/tmp",
            system_prompt="test",
            resume_session_id="conv-123",
            mcp_servers={
                "orchestra": {
                    "command": "python3",
                    "args": [],
                    "env": {"ORCHESTRA_SESSION_ID": "sess-123"},
                }
            },
            is_orchestrator=True,
            scope="/tmp",
            pipeline="default",
            role="orchestrator",
            profile="default",
            effort="medium",
            context_limit=1_000_000,
        ),
    )
    usage = {
        "input_tokens": 100_000,
        "output_tokens": 10_000,
        "thinking_tokens": 6_000,
        "cache_read_tokens": 500_000,
        "total_tokens": 110_000,
    }
    terminal = {
        "conversation_id": "conv-123",
        "status": "SUCCESS",
        "num_turns": 4,
        "duration_seconds": 12.345,
        "usage": usage,
    }
    ev = b._end(ok=True, reason="end_turn", usage=usage, terminal=terminal)
    assert ev.metadata["cost_unaccounted"] is False
    assert ev.metadata["cost_is_delta"] is True
    # 0.1*2.0 + 0.5*0.1 + 0.01*10.0 = 0.20 + 0.05 + 0.10 = 0.35
    assert ev.metadata["cost_usd"] == pytest.approx(0.35)
    assert ev.metadata["cost_usd_cached"] == pytest.approx(0.35)
    assert ev.metadata["event_id"].startswith("agy:conv-123:")
    assert ev.metadata["num_turns"] == 4
    assert ev.metadata["reasoning_tokens"] == 6000
    assert ev.metadata["turn_duration_ms"] == 12345

    raw_q = {
        "status": "SUCCESS",
        "command": {
            "name": "usage",
            "data": {
                "groups": [
                    {
                        "buckets": [
                            {
                                "id": "gemini-weekly",
                                "window": "weekly",
                                "remaining_fraction": 0.675,
                                "reset_time": "2026-11-19T19:00:07Z",
                            },
                            {
                                "id": "gemini-5h",
                                "window": "5h",
                                "remaining_fraction": 0.95,
                                "reset_time": "2026-11-13T20:00:07Z",
                            },
                        ]
                    },
                    {
                        "buckets": [
                            {
                                "id": "3p-5h",
                                "window": "5h",
                                "remaining_fraction": 1.0,
                                "reset_time": "2026-11-13T21:00:00Z",
                            }
                        ]
                    },
                ]
            },
        },
    }
    five_h = normalize_antigravity_five_hour_quota(raw_q)
    assert five_h["gemini-5h"]["remaining_fraction"] == pytest.approx(0.95)
    assert five_h["3p-5h"]["remaining_fraction"] == pytest.approx(1.0)

    now = time.time()
    monkeypatch.setattr(
        system,
        "_antigravity_usage_cache",
        {
            "data": {
                "gemini-weekly": {
                    "remaining_fraction": 0.675,
                    "reset_time": "2026-11-19T19:00:07Z",
                },
                "3p-weekly": {
                    "remaining_fraction": 0.35,
                    "reset_time": "2026-11-19T18:24:00Z",
                },
            },
            "five_hour": five_h,
            "ts": now,
        },
    )
    snap = _cached_quota_snapshot(
        "antigravity", "antigravity/gemini-4-carbon-medium", now=now
    )
    assert snap["state"]["quota_five_hour_pct"] == pytest.approx(5.0)
    assert snap["state"]["quota_seven_day_pct"] == pytest.approx(32.5)



def test_cli_environment_injects_antigravity_proxy_and_preserves_local_no_proxy(
    tmp_path, monkeypatch
):
    from app.backend_antigravity import cli_environment

    monkeypatch.setenv("ANTIGRAVITY_PROXY_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("NO_PROXY", "internal.local")
    monkeypatch.delenv("no_proxy", raising=False)
    env = cli_environment(tmp_path / "home")

    assert env["HTTPS_PROXY"] == "http://127.0.0.1:18080"
    assert env["HTTP_PROXY"] == "http://127.0.0.1:18080"
    assert env["https_proxy"] == "http://127.0.0.1:18080"
    assert env["http_proxy"] == "http://127.0.0.1:18080"
    for host in ("internal.local", "localhost", "127.0.0.1", "::1"):
        assert host in env["NO_PROXY"].split(",")
        assert host in env["no_proxy"].split(",")


@pytest.mark.asyncio
async def test_disabled_antigravity_provider_never_spawns_agy_in_readiness_or_usage(
    monkeypatch,
):
    from app import backend_antigravity as ba
    from app.models import set_provider_disabled
    from app.runtime_registry import RuntimeReadinessContext

    calls = []

    async def forbidden_cli(*args, **kwargs):
        calls.append(args)
        raise AssertionError("_cli must not be spawned while antigravity is disabled")

    monkeypatch.setattr(ba, "_cli", forbidden_cli)
    set_provider_disabled("antigravity", True)

    readiness = await ba.antigravity_readiness(
        RuntimeReadinessContext(model="antigravity/gemini-4-carbon-medium", profile="")
    )
    assert readiness.credentials_ready is False
    assert readiness.catalog_ready is False
    assert "disabled" in readiness.reason.lower()

    with pytest.raises(RuntimeError, match="disabled"):
        await ba.fetch_antigravity_usage()

    assert calls == []


@pytest.mark.asyncio
async def test_tos_403_account_disabled_trips_circuit_breaker_and_marks_credentials_error(
    tmp_path, monkeypatch
):
    import stat
    from app import backend_antigravity as ba
    from app.models import is_provider_disabled, set_provider_disabled
    from app.runtime_registry import BackendBuildContext, build_backend

    set_provider_disabled("antigravity", False)
    assert is_provider_disabled("antigravity") is False

    fake_agy = tmp_path / "agy"
    fake_agy.write_text(
        """#!/usr/bin/env python3
import json, sys
print(json.dumps({
    "event": "result",
    "result": {
        "conversation_id": "conv-tos",
        "status": "ERROR",
        "response": "",
        "error": "This service has been disabled in this account for violation of Terms of Service. Please submit an appeal to continue using this product.",
        "num_turns": 1,
        "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "thinking_tokens": 0, "total_tokens": 0},
    },
}), flush=True)
sys.exit(1)
""",
        encoding="utf-8",
    )
    fake_agy.chmod(fake_agy.stat().st_mode | stat.S_IXUSR)

    auth_home = tmp_path / "auth"
    tok = auth_home / ".gemini/antigravity-cli/antigravity-oauth-token"
    tok.parent.mkdir(parents=True, exist_ok=True)
    tok.write_text("dummy-token", encoding="utf-8")
    tok.chmod(0o600)

    monkeypatch.setattr(ba, "ANTIGRAVITY_BIN", str(fake_agy))
    monkeypatch.setattr(ba, "ANTIGRAVITY_AUTH_HOME", auth_home)
    monkeypatch.setattr(ba, "ANTIGRAVITY_HOME_ROOT", tmp_path / "homes")

    ctx = BackendBuildContext(
        model="antigravity/gemini-4-carbon-medium",
        provider="google-antigravity",
        cwd=str(tmp_path),
        system_prompt="SYS",
        resume_session_id=None,
        mcp_servers={"orchestra": {"command": "/bin/true", "args": [], "env": {"ORCHESTRA_SESSION_ID": "tos-worker"}}},
        is_orchestrator=False,
        scope=str(tmp_path),
        pipeline="default",
        role="worker",
        profile="",
        effort="medium",
        context_limit=200_000,
    )
    backend = build_backend("antigravity", ctx)
    await backend.connect()
    await backend.send("hello")
    events = [ev async for ev in backend.events()]

    end = next(ev for ev in events if ev.type == "turn_end")
    assert end.metadata["ok"] is False
    assert end.metadata["model_error"] == "credentials"
    assert is_provider_disabled("antigravity") is True
