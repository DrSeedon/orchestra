"""CodexBackend — model dicts, runtime accounting, and per-worker MCP config.

Regression net for the three bugs found in the codex-integration audit:
  BUG 1 — Sol/Terra/Luna missing from context/price dicts (worker got 258400 ctx, $0).
  BUG 2 — reasoning effort hardcoded, xhigh/max not in the accepted set.
  MCP   — per-worker MCP servers now injected via -c dotted-leaf overrides.
"""

import asyncio
import json
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.backend_codex import (
    CodexBackend,
    CodexProtocolError,
    CODEX_CONTEXT_LIMITS,
    CODEX_TOKEN_PRICES,
    CODEX_REASONING_EFFORTS,
    _codex_cost,
    _read_rollout_context,
    _read_rollout_totals,
    _usage_delta,
)
from app.runtime_history import (
    CODEX_CLI_HISTORY_VERSION,
    HISTORICAL_TOOL_INSTRUCTION,
    NativeHistoryUnsupported,
    render_codex_history,
)


class _FakeProcess:
    def __init__(self, pid=123):
        self.pid = pid
        self.returncode = None
        self.stdin = SimpleNamespace(write=MagicMock(), drain=AsyncMock())
        self.stdout = SimpleNamespace(readline=AsyncMock(return_value=b""))
        self.stderr = SimpleNamespace(read=AsyncMock(return_value=b""))
        self.wait = AsyncMock(side_effect=self._wait)
        self.communicate = AsyncMock(return_value=(b"", b""))
        self.terminate = MagicMock()
        self.kill = MagicMock()

    async def _wait(self):
        self.returncode = 0
        return 0


def _history_import():
    return render_codex_history(
        [{
            "id": 1,
            "ts": "2026-08-11T10:00:00+00:00",
            "type": "user_message",
            "content": "remember",
        }],
        snapshot_id=1,
        thread_id="11111111-2222-4333-8444-555555555555",
    )


def test_installed_codex_history_version_matches_pin():
    cli = shutil.which("codex")
    if cli is None:
        pytest.skip("Codex CLI is not installed")
    result = subprocess.run(
        [cli, "--version"], capture_output=True, text=True, check=True, timeout=10
    )
    assert result.stdout.strip() == f"codex-cli {CODEX_CLI_HISTORY_VERSION}"


# ── BUG 1: GPT-5.6 models registered in backend dicts ──

def test_gpt56_context_limits_present():
    # ChatGPT-auth Codex runtime reports a 258400 effective budget for these models.
    # The public API's 1.05M window is a different surface and must not drive dashboard
    # accounting or auto-compact for a local Codex worker.
    for m in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
        assert CODEX_CONTEXT_LIMITS[m] == 258400, m


def test_spark_context_limit_matches_local_codex_metadata():
    assert CODEX_CONTEXT_LIMITS["gpt-5.3-codex-spark"] == 128000


def test_gpt56_prices_present():
    # Standard-tier list prices, https://platform.openai.com/docs/pricing, verified 11.08.2026.
    assert CODEX_TOKEN_PRICES["gpt-5.6-sol"] == {
        "input": 5.0, "cached": 0.5, "write": 6.25, "output": 30.0,
    }
    assert CODEX_TOKEN_PRICES["gpt-5.6-terra"] == {
        "input": 2.0, "cached": 0.2, "write": 2.5, "output": 12.0,
    }
    assert CODEX_TOKEN_PRICES["gpt-5.6-luna"] == {
        "input": 0.2, "cached": 0.02, "write": 0.25, "output": 1.2,
    }


def test_cached_input_is_a_tenth_of_fresh_input_for_every_model():
    """OpenAI prices cached input at 10% of the input rate — a typo in one row is
    otherwise invisible: the dashboard keeps rendering a plausible number."""
    for model, price in CODEX_TOKEN_PRICES.items():
        if price is None:
            continue
        assert price["cached"] == pytest.approx(price["input"] / 10), model


def test_legacy_gpt_models_unchanged():
    assert CODEX_CONTEXT_LIMITS["gpt-5.5"] == 258400
    assert CODEX_TOKEN_PRICES["gpt-5.4"] == {"input": 2.5, "cached": 0.25, "output": 15.0}


def test_sol_price_and_ctx_not_zero_fallback():
    # Sol has an explicit runtime limit and price rather than relying on fallbacks.
    b = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    assert CODEX_CONTEXT_LIMITS[b.model] == 258400
    assert CODEX_TOKEN_PRICES[b.model]["output"] == 30.0


def test_codex_cost_applies_cached_input_discount():
    # 100 fresh × $5/M + 900 cached × $0.5/M + 10 output × $30/M.
    assert _codex_cost("gpt-5.6-sol", 1000, 900, 0, 10) == pytest.approx(0.00125)


def test_codex_cost_charges_cache_writes_once_at_their_own_rate():
    # 100 fresh × $5/M + 700 cached × $0.5/M + 200 writes × $6.25/M + output.
    assert _codex_cost("gpt-5.6-sol", 1000, 700, 200, 10) == pytest.approx(0.0024)


def test_spark_cost_fails_loud_without_a_published_price():
    assert CODEX_TOKEN_PRICES["gpt-5.3-codex-spark"] is None
    with pytest.raises(ValueError, match="No published token price"):
        _codex_cost("gpt-5.3-codex-spark", 1000, 0, 0, 10)


def test_usage_delta_survives_resume_and_counter_reset():
    current = {
        "input_tokens": 130, "cached_input_tokens": 90,
        "cache_write_input_tokens": 12, "output_tokens": 20,
    }
    baseline = {
        "input_tokens": 100, "cached_input_tokens": 80,
        "cache_write_input_tokens": 5, "output_tokens": 5,
    }
    assert _usage_delta(current, baseline) == {
        "input_tokens": 30, "cached_input_tokens": 10,
        "cache_write_input_tokens": 7, "output_tokens": 15,
    }
    # A Codex-side compact may reset counters. Treat the new value as this turn rather
    # than producing negative usage or zeroing a real call.
    assert _usage_delta({"input_tokens": 10}, {"input_tokens": 100})["input_tokens"] == 10


def test_rollout_context_uses_last_call_not_accumulated_usage(tmp_path):
    rollout = tmp_path / "rollout.jsonl"
    rows = [
        {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 760838},
            "last_token_usage": {
                "input_tokens": 95489, "cached_input_tokens": 92928,
                "cache_write_input_tokens": 1024,
            },
            "model_context_window": 258400,
        }}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 2042411},
            "last_token_usage": {
                "input_tokens": 142165, "cached_input_tokens": 141056,
                "cache_write_input_tokens": 512,
            },
            "model_context_window": 258400,
        }}},
    ]
    rollout.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    assert _read_rollout_context(rollout) == {
        "input_tokens": 142165,
        "cached_input_tokens": 141056,
        "cache_write_input_tokens": 512,
        "model_context_window": 258400,
    }


def test_usage_breakdown_reads_cache_write_tokens():
    assert CodexBackend._usage_breakdown({
        "inputTokens": 1000,
        "cachedInputTokens": 700,
        "cacheWriteInputTokens": 200,
        "outputTokens": 10,
    }) == {
        "input_tokens": 1000,
        "cached_input_tokens": 700,
        "cache_write_input_tokens": 200,
        "output_tokens": 10,
    }


def test_rollout_totals_read_cache_write_tokens(tmp_path):
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(json.dumps({
        "type": "event_msg",
        "payload": {"type": "token_count", "info": {"total_token_usage": {
            "input_tokens": 1000,
            "cached_input_tokens": 700,
            "cache_write_input_tokens": 200,
            "output_tokens": 10,
        }}},
    }) + "\n")

    assert _read_rollout_totals(rollout)["cache_write_input_tokens"] == 200


def test_rollout_context_fails_soft_on_missing_or_corrupt_data(tmp_path):
    assert _read_rollout_context(tmp_path / "missing.jsonl") is None
    corrupt = tmp_path / "corrupt.jsonl"
    corrupt.write_text("not-json\n{}\n")
    assert _read_rollout_context(corrupt) is None


# ── BUG 2: reasoning effort ──

def test_xhigh_and_max_accepted():
    assert "xhigh" in CODEX_REASONING_EFFORTS
    assert "max" in CODEX_REASONING_EFFORTS


def test_effort_passthrough_and_fallback():
    assert CodexBackend(model="gpt-5.6-sol", cwd="/tmp", reasoning_effort="xhigh").reasoning_effort == "xhigh"
    # unknown value falls back to high, never crashes
    assert CodexBackend(model="gpt-5.6-sol", cwd="/tmp", reasoning_effort="bogus").reasoning_effort == "high"


# ── Per-worker MCP config (dotted-leaf -c overrides) ──

def test_mcp_config_args_dotted_leaves():
    b = CodexBackend(model="gpt-5.6-sol", cwd="/tmp", mcp_servers={
        "orchestra": {
            "command": "python",
            "args": ["/x/mcp_stdio.py"],
            "env": {"WORKER_NAME": "w1"},
        },
    })
    args = b._mcp_config_args()
    # dotted-leaf form — Codex rejects a whole-table value as a string
    assert 'mcp_servers.orchestra.command="python"' in args
    assert 'mcp_servers.orchestra.args=["/x/mcp_stdio.py"]' in args
    assert 'mcp_servers.orchestra.env={WORKER_NAME="w1"}' in args
    assert "mcp_servers.orchestra.enabled=true" in args
    enabled_tools = next(a for a in args if a.startswith("mcp_servers.orchestra.enabled_tools="))
    assert '"send_message"' in enabled_tools
    assert '"spawn_worker"' in enabled_tools


def test_mcp_config_supports_url_only_servers():
    b = CodexBackend(model="gpt-5.6-sol", cwd="/tmp", mcp_servers={
        "remote": {"url": "https://example/sse"},
    })
    args = b._mcp_config_args()
    assert "mcp_servers.remote.enabled=true" in args
    assert 'mcp_servers.remote.url="https://example/sse"' in args


def test_mcp_config_empty_when_no_servers():
    assert CodexBackend(model="gpt-5.6-sol", cwd="/tmp")._mcp_config_args() == []


def test_toml_str_escapes():
    assert CodexBackend._toml_str('a"b\\c') == '"a\\"b\\\\c"'


def test_codex_inherits_orchestra_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:12343")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:12343")
    env = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")._build_env()
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:12343"
    assert env["HTTP_PROXY"] == "http://127.0.0.1:12343"


@pytest.mark.asyncio
async def test_scope_preflight_requires_linger_and_real_attachment(monkeypatch):
    import app.backend_codex as module

    monkeypatch.setattr(module, "_scope_support_cache", None)
    monkeypatch.setattr(module.Path, "is_socket", lambda _path: True)
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/usr/bin/{name}")

    async def run(*cmd, **_kwargs):
        if cmd[0].endswith("loginctl"):
            return 0, "yes", ""
        unit = next(arg.split("=", 1)[1] for arg in cmd if arg.startswith("--unit="))
        return 0, f"/user.slice/{unit}\npopulated 1\nfrozen 0", ""

    monkeypatch.setattr(module, "_run_process", run)

    supported, env, reason = await module._codex_scope_support()

    assert supported is True
    assert env["XDG_RUNTIME_DIR"] == f"/run/user/{module.os.getuid()}"
    assert reason == ""


@pytest.mark.asyncio
async def test_scope_preflight_requires_teardown_cgroup_contract(monkeypatch):
    import app.backend_codex as module

    monkeypatch.setattr(module, "_scope_support_cache", None)
    monkeypatch.setattr(module.Path, "is_socket", lambda _path: True)
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/usr/bin/{name}")

    async def run(*cmd, **_kwargs):
        if cmd[0].endswith("loginctl"):
            return 0, "yes", ""
        unit = next(arg.split("=", 1)[1] for arg in cmd if arg.startswith("--unit="))
        return 0, f"/user.slice/{unit}", ""

    monkeypatch.setattr(module, "_run_process", run)

    supported, env, reason = await module._codex_scope_support()

    assert supported is False
    assert env == {}
    assert reason.startswith("RuntimeError:")
    assert "cgroup.events" in reason


@pytest.mark.asyncio
async def test_scope_preflight_falls_back_with_visible_reason(monkeypatch, caplog):
    import app.backend_codex as module

    monkeypatch.setattr(module, "_scope_support_cache", None)
    monkeypatch.setattr(module.Path, "is_socket", lambda _path: True)
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        module,
        "_run_process",
        AsyncMock(return_value=(0, "no", "")),
    )

    with caplog.at_level("WARNING", logger="app.backend_codex"):
        supported, env, reason = await module._codex_scope_support()

    assert supported is False
    assert env == {}
    assert reason.startswith("RuntimeError:")
    assert "hibernation is disabled" in caplog.text


@pytest.mark.asyncio
async def test_connect_uses_scope_and_preserves_stdio(monkeypatch):
    import app.backend_codex as module

    proc = _FakeProcess()
    create = AsyncMock(return_value=proc)
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(
        module,
        "_codex_scope_support",
        AsyncMock(return_value=(True, {
            "XDG_RUNTIME_DIR": "/run/user/1000",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
        }, "")),
    )
    monkeypatch.setattr(module, "_scope_unit", lambda prefix="orchestra-codex": f"{prefix}-unit.scope")
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._read_stdout = AsyncMock()
    backend._drain_stderr = AsyncMock()
    backend._notify = AsyncMock()

    async def request(method, _params):
        return {"thread": {"id": "thread-1"}} if method == "thread/start" else {}

    backend._request = AsyncMock(side_effect=request)
    await backend.connect()

    args = create.await_args.args
    kwargs = create.await_args.kwargs
    assert args[:6] == (
        module.shutil.which("systemd-run") or "systemd-run",
        "--user", "--scope", "--quiet", "--collect",
        "--unit=orchestra-codex-unit.scope",
    )
    assert "--" in args
    assert args[-2:] == ("app-server", "--stdio")
    assert "features.multi_agent=false" in args
    assert kwargs["stdin"] is asyncio.subprocess.PIPE
    assert kwargs["stdout"] is asyncio.subprocess.PIPE
    assert kwargs["env"]["XDG_RUNTIME_DIR"] == "/run/user/1000"
    assert backend.hibernate_safe is True
    assert backend.session_id == "thread-1"


@pytest.mark.asyncio
async def test_connect_direct_fallback_is_not_hibernate_safe(monkeypatch):
    import app.backend_codex as module

    proc = _FakeProcess()
    create = AsyncMock(return_value=proc)
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(
        module,
        "_codex_scope_support",
        AsyncMock(return_value=(False, {}, "RuntimeError: Linger=no")),
    )
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._read_stdout = AsyncMock()
    backend._drain_stderr = AsyncMock()
    backend._notify = AsyncMock()
    backend._request = AsyncMock(side_effect=[{}, {"thread": {"id": "thread-1"}}])

    await backend.connect()

    assert create.await_args.args[0] == module.CODEX_BIN
    assert backend.hibernate_safe is False
    assert backend.hibernate_unavailable_reason == "RuntimeError: Linger=no"


@pytest.mark.asyncio
async def test_resume_rejects_substituted_thread_before_turn(monkeypatch):
    import app.backend_codex as module

    monkeypatch.setattr(
        module,
        "_codex_scope_support",
        AsyncMock(return_value=(False, {}, "unsupported")),
    )
    monkeypatch.setattr(
        module.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=_FakeProcess()),
    )
    backend = CodexBackend(
        model="gpt-5.6-sol",
        cwd="/tmp",
        resume_thread_id="thread-requested",
    )
    backend._read_stdout = AsyncMock()
    backend._drain_stderr = AsyncMock()
    backend._notify = AsyncMock()
    backend._request = AsyncMock(side_effect=[
        {},
        {"thread": {"id": "thread-substituted"}},
    ])
    backend.disconnect = AsyncMock()

    with pytest.raises(RuntimeError, match="resumed a different thread"):
        await backend.connect()

    assert backend.session_id == "thread-requested"
    backend.disconnect.assert_awaited_once()
    initialize_params = backend._request.await_args_list[0].args[1]
    resume_params = backend._request.await_args_list[1].args[1]
    assert "capabilities" not in initialize_params
    assert "history" not in resume_params


def test_wrong_codex_history_import_type_fails_loud():
    with pytest.raises(TypeError, match="CodexHistoryImport"):
        CodexBackend(
            model="gpt-5.6-sol",
            cwd="/tmp",
            history_import={"history": []},
        )


@pytest.mark.asyncio
async def test_history_import_requires_exact_codex_version(monkeypatch):
    import app.backend_codex as module

    backend = CodexBackend(
        model="gpt-5.6-sol",
        cwd="/tmp",
        history_import=_history_import(),
    )
    monkeypatch.setattr(
        module,
        "_run_process",
        AsyncMock(return_value=(0, "codex-cli 0.146.00", "")),
    )

    with pytest.raises(NativeHistoryUnsupported, match="0.146.00"):
        await backend._verify_history_version()


@pytest.mark.asyncio
async def test_history_connect_fails_before_spawn_on_version_mismatch(monkeypatch):
    import app.backend_codex as module

    monkeypatch.setattr(
        module,
        "_codex_scope_support",
        AsyncMock(return_value=(False, {}, "unsupported")),
    )
    backend = CodexBackend(
        model="gpt-5.6-sol",
        cwd="/tmp",
        history_import=_history_import(),
    )
    monkeypatch.setattr(
        module,
        "_run_process",
        AsyncMock(return_value=(0, "codex-cli 0.147.0", "")),
    )
    spawn = AsyncMock(return_value=_FakeProcess())
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    backend._read_stdout = AsyncMock()
    backend._drain_stderr = AsyncMock()
    backend._request = AsyncMock(side_effect=AssertionError("app-server started"))

    with pytest.raises(NativeHistoryUnsupported, match="0.147.0"):
        await backend.connect()

    spawn.assert_not_awaited()
    assert backend.has_owned_processes is False


@pytest.mark.asyncio
async def test_history_import_uses_experimental_resume_and_accepts_fresh_id(monkeypatch):
    import app.backend_codex as module

    history = _history_import()
    monkeypatch.setattr(
        module,
        "_codex_scope_support",
        AsyncMock(return_value=(False, {}, "unsupported")),
    )
    monkeypatch.setattr(
        module.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=_FakeProcess()),
    )
    backend = CodexBackend(
        model="gpt-5.6-sol",
        cwd="/tmp",
        system_prompt="CURRENT ROLE",
        resume_thread_id=history.thread_id,
        history_import=history,
    )
    backend._verify_history_version = AsyncMock()
    backend._read_stdout = AsyncMock()
    backend._drain_stderr = AsyncMock()
    backend._notify = AsyncMock()
    requests = []

    async def request(method, params):
        requests.append((method, params))
        if method == "thread/resume":
            return {"thread": {"id": "fresh-thread-id"}}
        return {}

    backend._request = AsyncMock(side_effect=request)

    await backend.connect()

    assert requests[0] == (
        "initialize",
        {
            "clientInfo": {
                "name": "orchestra",
                "title": "Orchestra",
                "version": "1",
            },
            "capabilities": {"experimentalApi": True},
        },
    )
    method, params = requests[1]
    assert method == "thread/resume"
    assert params["threadId"] == history.thread_id
    assert params["history"] == list(history.history)
    assert params["developerInstructions"] == (
        "CURRENT ROLE\n\n" + HISTORICAL_TOOL_INSTRUCTION
    )
    assert "path" not in params
    assert backend.session_id == "fresh-thread-id"
    assert backend._history_import is None

    backend._proc = None
    requests.clear()
    await backend.connect()

    assert "capabilities" not in requests[0][1]
    assert requests[1][0] == "thread/resume"
    assert requests[1][1]["threadId"] == "fresh-thread-id"
    assert "history" not in requests[1][1]
    assert requests[1][1]["developerInstructions"] == "CURRENT ROLE"


@pytest.mark.asyncio
@pytest.mark.parametrize(("protocol_code", "protocol_message"), [
    (-32600, "thread/resume.history requires experimentalApi capability"),
    (-32600, "invalid params: invalid type for history item"),
    (-32600, "failed to deserialize ResponseItem variant"),
    (-32602, "invalid params: unknown model gpt-bad"),
    (-32602, "invalid params: cwd does not exist"),
    (-32602, "invalid params: invalid threadId"),
    (-32602, "failed to parse approval policy"),
    (-32601, "method not found"),
    (-32602, "invalid params: cwd '/srv/history' does not exist"),
    (-32602, "invalid params: unknown model 'history-large'"),
    (-32602, "failed to parse developerInstructions: history must be preserved"),
    (-32602, "invalid params: invalid threadId history-legacy"),
])
async def test_resume_protocol_error_without_structured_field_is_not_summary_eligible(
    monkeypatch, protocol_code, protocol_message,
):
    import app.backend_codex as module

    monkeypatch.setattr(
        module,
        "_codex_scope_support",
        AsyncMock(return_value=(False, {}, "unsupported")),
    )
    monkeypatch.setattr(
        module.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=_FakeProcess()),
    )
    backend = CodexBackend(
        model="gpt-5.6-sol",
        cwd="/tmp",
        history_import=_history_import(),
    )
    backend._verify_history_version = AsyncMock()
    backend._read_stdout = AsyncMock()
    backend._drain_stderr = AsyncMock()
    backend._notify = AsyncMock()
    protocol_error = CodexProtocolError(
        "request",
        {"code": protocol_code, "message": protocol_message},
    )
    backend._request = AsyncMock(side_effect=[{}, protocol_error])
    backend.disconnect = AsyncMock()

    with pytest.raises(CodexProtocolError, match=protocol_message):
        await backend.connect()

    backend.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_history_initialize_protocol_error_is_not_summary_eligible(monkeypatch):
    import app.backend_codex as module

    monkeypatch.setattr(
        module,
        "_codex_scope_support",
        AsyncMock(return_value=(False, {}, "unsupported")),
    )
    monkeypatch.setattr(
        module.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=_FakeProcess()),
    )
    backend = CodexBackend(
        model="gpt-5.6-sol",
        cwd="/tmp",
        history_import=_history_import(),
    )
    backend._verify_history_version = AsyncMock()
    backend._read_stdout = AsyncMock()
    backend._drain_stderr = AsyncMock()
    backend._request = AsyncMock(side_effect=CodexProtocolError(
        "request",
        {"code": -32602, "message": "invalid params: initialize schema changed"},
    ))
    backend.disconnect = AsyncMock()

    with pytest.raises(CodexProtocolError, match="initialize schema changed"):
        await backend.connect()

    backend.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_history_connect_auth_failure_is_not_summary_eligible(monkeypatch):
    import app.backend_codex as module

    monkeypatch.setattr(
        module,
        "_codex_scope_support",
        AsyncMock(return_value=(False, {}, "unsupported")),
    )
    monkeypatch.setattr(
        module.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=_FakeProcess()),
    )
    backend = CodexBackend(
        model="gpt-5.6-sol",
        cwd="/tmp",
        history_import=_history_import(),
    )
    backend._verify_history_version = AsyncMock()
    backend._read_stdout = AsyncMock()
    backend._drain_stderr = AsyncMock()
    backend._notify = AsyncMock()
    backend._request = AsyncMock(side_effect=RuntimeError("authentication required"))
    backend.disconnect = AsyncMock()

    with pytest.raises(RuntimeError, match="authentication required"):
        await backend.connect()

    backend.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_scoped_disconnect_interrupts_then_clears_verified_owner():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._proc = _FakeProcess()
    backend._scope_unit = "codex.scope"
    backend._active_turn_id = "turn-1"
    order = []
    backend.interrupt = AsyncMock(side_effect=lambda: order.append("interrupt"))
    backend._signal_scope = AsyncMock(side_effect=lambda sig: order.append(sig))
    backend._wait_owned_process = AsyncMock(side_effect=lambda _proc: order.append("root-gone"))
    backend._wait_scope_empty = AsyncMock(side_effect=lambda: order.append("scope-empty"))

    await backend.disconnect()

    assert order == ["interrupt", "TERM", "root-gone", "scope-empty"]
    assert backend.has_owned_processes is False
    assert backend._teardown_error is None


@pytest.mark.asyncio
async def test_scoped_disconnect_failure_retains_retryable_owner():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    proc = _FakeProcess()
    backend._proc = proc
    backend._scope_unit = "codex.scope"
    backend._signal_scope = AsyncMock(side_effect=PermissionError("denied"))

    with pytest.raises(PermissionError, match="denied"):
        await backend.disconnect()

    assert backend._proc is proc
    assert backend._scope_unit == "codex.scope"
    assert backend.has_owned_processes is True
    assert backend._teardown_error == "PermissionError: denied"

    backend._signal_scope = AsyncMock()
    backend._wait_owned_process = AsyncMock()
    backend._wait_scope_empty = AsyncMock()
    await backend.disconnect()
    assert backend.has_owned_processes is False


@pytest.mark.asyncio
async def test_scoped_disconnect_escalates_timeout_to_unit_kill():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._proc = _FakeProcess()
    backend._scope_unit = "codex.scope"
    backend._signal_scope = AsyncMock()
    backend._wait_owned_process = AsyncMock(side_effect=[TimeoutError, None])
    backend._wait_scope_empty = AsyncMock()

    await backend.disconnect()

    assert [call.args[0] for call in backend._signal_scope.await_args_list] == [
        "TERM", "KILL",
    ]


@pytest.mark.asyncio
async def test_thread_started_exposes_session_id_before_turn_completion():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    events = backend._convert_notification({
        "method": "thread/started",
        "params": {"thread": {"id": "thread-early"}},
    })
    event = events[0]

    assert event.type == "status"
    assert event.metadata["session_id"] == "thread-early"


@pytest.mark.asyncio
async def test_send_steers_active_app_server_turn():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._proc = SimpleNamespace(returncode=None)
    backend._thread_id = "thread-1"
    backend._active_turn_id = "turn-1"
    backend._request = AsyncMock(return_value={"turnId": "turn-1"})

    await backend.send("extra context")

    backend._request.assert_awaited_once_with("turn/steer", {
        "threadId": "thread-1",
        "expectedTurnId": "turn-1",
        "input": [{"type": "text", "text": "extra context"}],
    })


@pytest.mark.asyncio
async def test_send_starts_turn_when_idle():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._proc = SimpleNamespace(returncode=None)
    backend._thread_id = "thread-1"
    backend._request = AsyncMock(return_value={"turn": {"id": "turn-2"}})

    await backend.send("do it")

    backend._request.assert_awaited_once_with("turn/start", {
        "threadId": "thread-1",
        "input": [{"type": "text", "text": "do it"}],
        "model": "gpt-5.6-sol",
        "effort": "high",
    })
    assert backend._active_turn_id == "turn-2"


@pytest.mark.asyncio
async def test_events_reject_stale_lifecycle_without_losing_current_turn(caplog):
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._proc = SimpleNamespace(returncode=None)
    backend._thread_id = "thread-1"
    backend._active_turn_id = "task-turn"

    for method, turn_id in (
        ("turn/started", "compact-turn"),
        ("turn/completed", "compact-turn"),
        ("turn/started", "task-turn"),
    ):
        await backend._notifications.put({
            "method": method,
            "params": {"threadId": "thread-1", "turn": {"id": turn_id}},
        })
    await backend._notifications.put({
        "method": "item/agentMessage/delta",
        "params": {"threadId": "thread-1", "delta": "FIRST_PROCESSED"},
    })
    await backend._notifications.put({
        "method": "turn/completed",
        "params": {
            "threadId": "thread-1",
            "turn": {"id": "task-turn", "status": "completed"},
        },
    })

    with caplog.at_level("DEBUG", logger="app.backend_codex"):
        events = [event async for event in backend.events()]

    assert any(event.type == "stream" and event.content == "FIRST_PROCESSED"
               for event in events)
    assert [event.type for event in events].count("turn_end") == 1
    assert "compact-turn" in caplog.text
    assert "task-turn" in caplog.text
    assert "turn/started" in caplog.text
    assert "turn/completed" in caplog.text
    assert backend._active_turn_id is None


@pytest.mark.asyncio
async def test_native_compact_drains_terminal_before_returning():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._thread_id = "thread-1"
    stdout = asyncio.StreamReader()
    backend._proc = SimpleNamespace(
        returncode=None,
        stdout=stdout,
        wait=AsyncMock(return_value=0),
    )
    backend._reader_task = asyncio.create_task(backend._read_stdout())
    request_started = asyncio.Event()
    compact_queue_was_attached = []

    def feed(message):
        stdout.feed_data((json.dumps(message) + "\n").encode())

    async def request(method, params):
        compact_queue_was_attached.append(
            getattr(backend, "_compact_notifications", None) is not None
        )
        feed({
            "method": "turn/started",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "compact-turn"},
            },
        })
        feed({
            "method": "thread/tokenUsage/updated",
            "params": {
                "threadId": "thread-1",
                "tokenUsage": {
                    "last": {"totalTokens": 33_124},
                    "total": {},
                    "modelContextWindow": 258_400,
                },
            },
        })
        feed({
            "method": "item/completed",
            "params": {
                "threadId": "thread-1",
                "item": {"type": "contextCompaction", "id": "compact-1"},
            },
        })
        request_started.set()
        return {}

    backend._request = AsyncMock(side_effect=request)
    task = asyncio.create_task(backend.compact_context())
    try:
        await asyncio.wait_for(request_started.wait(), timeout=0.5)
        done, _ = await asyncio.wait({task}, timeout=0.05)
        assert task not in done

        feed({
            "method": "turn/completed",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "compact-turn", "status": "completed"},
            },
        })
        result = await asyncio.wait_for(task, timeout=0.5)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        backend._disconnecting = True
        stdout.feed_eof()
        await asyncio.wait_for(backend._reader_task, timeout=0.5)

    backend._request.assert_awaited_once_with(
        "thread/compact/start",
        {"threadId": "thread-1"},
    )
    assert compact_queue_was_attached == [True]
    assert backend._notifications.empty()
    assert backend._compact_notifications is None
    assert backend.session_id == "thread-1"
    assert result == {
        "ok": True,
        "thread_id": "thread-1",
        "context_tokens": 33_124,
        "max_tokens": 258_400,
    }


@pytest.mark.asyncio
async def test_native_compact_missing_terminal_times_out_and_detaches(monkeypatch):
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._thread_id = "thread-1"
    stdout = asyncio.StreamReader()
    backend._proc = SimpleNamespace(
        returncode=None,
        stdout=stdout,
        wait=AsyncMock(return_value=0),
    )
    backend._reader_task = asyncio.create_task(backend._read_stdout())
    monkeypatch.setattr("app.backend_codex.CODEX_COMPACT_TIMEOUT_SECONDS", 0.03)

    async def request(_method, _params):
        for message in (
            {
                "method": "turn/started",
                "params": {
                    "threadId": "thread-1",
                    "turn": {"id": "compact-turn"},
                },
            },
            {
                "method": "item/completed",
                "params": {
                    "threadId": "thread-1",
                    "item": {"type": "contextCompaction", "id": "compact-1"},
                },
            },
        ):
            stdout.feed_data((json.dumps(message) + "\n").encode())
        return {}

    backend._request = AsyncMock(side_effect=request)
    try:
        with pytest.raises(TimeoutError):
            await backend.compact_context()
    finally:
        backend._disconnecting = True
        stdout.feed_eof()
        await asyncio.wait_for(backend._reader_task, timeout=0.5)

    assert backend._compact_notifications is None
    assert backend._notifications.empty()


@pytest.mark.asyncio
async def test_native_compact_rejects_active_turn():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._proc = SimpleNamespace(returncode=None)
    backend._thread_id = "thread-1"
    backend._active_turn_id = "turn-1"

    with pytest.raises(RuntimeError, match="active turn"):
        await backend.compact_context()


@pytest.mark.asyncio
async def test_silent_active_turn_emits_transient_heartbeat():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._proc = SimpleNamespace(returncode=None)
    backend._thread_id = "thread-1"
    backend._active_turn_id = "turn-1"
    backend._notifications = SimpleNamespace(
        get=AsyncMock(side_effect=asyncio.TimeoutError),
    )

    iterator = backend.events()
    event = await anext(iterator)
    await iterator.aclose()

    assert event.type == "thinking_stream"
    assert event.metadata == {"activity": "waiting", "item_id": "turn-1"}
    assert "still working" in event.content.lower()


def test_app_server_events_cover_web_reasoning_and_network_failure():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")

    web = backend._convert_notification({
        "method": "item/started",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "item": {"id": "web-1", "type": "webSearch", "query": "official Codex docs"},
        },
    })
    assert web[0].type == "tool_use"
    assert web[0].metadata["short_name"] == "WebSearch"

    reasoning = backend._convert_notification({
        "method": "item/completed",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "item": {
                "id": "reason-1",
                "type": "reasoning",
                "summary": ["Inspecting runtime", "Checking transport"],
                "content": [],
            },
        },
    })
    assert reasoning[0].type == "thinking"
    assert "Checking transport" in reasoning[0].content

    backend._last_turn_error = {
        "message": "stream disconnected",
        "codexErrorInfo": {"responseStreamDisconnected": {"httpStatusCode": None}},
    }
    failed = backend._convert_notification({
        "method": "turn/completed",
        "params": {
            "threadId": "thread-1",
            "turn": {"id": "turn-1", "status": "failed", "items": []},
        },
    })
    end = next(event for event in failed if event.type == "turn_end")
    assert end.metadata["ok"] is False
    assert end.metadata["model_error"] == "server_error"


def test_collab_agent_event_is_visible_as_subagent():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    events = backend._convert_notification({
        "method": "item/started",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "item": {
                "id": "collab-1",
                "type": "collabAgentToolCall",
                "tool": "spawnAgent",
                "receiverThreadIds": ["child-1"],
                "senderThreadId": "thread-1",
                "agentsStates": {},
                "status": "inProgress",
                "prompt": "Research the API",
            },
        },
    })
    assert events[0].type == "subagent_start"
    assert events[0].metadata["subagent_id"] == "child-1"


def test_completed_collab_wait_emits_subagent_end_for_terminal_agent():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    events = backend._convert_notification({
        "method": "item/completed",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "item": {
                "id": "collab-2",
                "type": "collabAgentToolCall",
                "tool": "wait",
                "receiverThreadIds": ["child-1"],
                "senderThreadId": "thread-1",
                "agentsStates": {"child-1": {"status": "completed", "message": "Done"}},
                "status": "completed",
            },
        },
    })

    assert events[0].type == "subagent_end"
    assert events[0].metadata["status"] == "completed"


def test_agent_message_delta_is_streamed_to_frontend():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")

    events = backend._convert_notification({
        "method": "item/agentMessage/delta",
        "params": {"threadId": "thread-1", "turnId": "turn-1", "delta": "partial"},
    })

    assert [(event.type, event.content) for event in events] == [("stream", "partial")]


def test_command_execution_exposes_actions_and_live_output():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    started = backend._convert_notification({
        "method": "item/started",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "item": {
                "id": "cmd-1",
                "type": "commandExecution",
                "command": "rg -n TODO app",
                "commandActions": [{
                    "type": "search",
                    "command": "rg -n TODO app",
                    "path": "app",
                    "query": "TODO",
                }],
                "cwd": "/tmp",
                "status": "inProgress",
            },
        },
    })
    live = backend._convert_notification({
        "method": "item/commandExecution/outputDelta",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "itemId": "cmd-1",
            "delta": "app/main.py:4:TODO\n",
        },
    })

    assert started[0].type == "tool_use"
    assert started[0].metadata["tool_name"] == "Bash"
    command_payload = json.loads(started[0].content.split(": ", 1)[1])
    assert command_payload["command"] == "rg -n TODO app"
    assert command_payload["command_actions"][0]["type"] == "search"
    assert live[0].type == "tool_stream"
    assert live[0].metadata["tool_use_id"] == "cmd-1"


def test_file_change_exposes_unified_diff_and_patch_updates():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    item = {
        "id": "patch-1",
        "type": "fileChange",
        "changes": [{
            "path": "/tmp/app.py",
            "kind": "update",
            "diff": "@@ -1 +1 @@\n-old\n+new\n",
        }],
        "status": "inProgress",
    }
    started = backend._convert_notification({
        "method": "item/started",
        "params": {"threadId": "thread-1", "turnId": "turn-1", "item": item},
    })
    patch = backend._convert_notification({
        "method": "item/fileChange/patchUpdated",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "itemId": "patch-1",
            "changes": item["changes"],
        },
    })
    completed = backend._convert_notification({
        "method": "item/completed",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "item": {**item, "status": "completed"},
        },
    })

    assert started[0].metadata["tool_name"] == "FileChange"
    assert json.loads(started[0].content.split(": ", 1)[1])["changes"][0]["diff"]
    assert patch[0].type == "tool_patch"
    assert patch[0].metadata["tool_use_id"] == "patch-1"
    assert completed[0].type == "tool_result"
    assert json.loads(completed[0].content)["status"] == "completed"


def test_completed_turn_id_is_carried_as_durable_event_id():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    events = backend._turn_completed({
        "id": "turn-1",
        "status": "completed",
    })

    assert events[-1].metadata["event_id"] == "turn-1"


def test_turn_usage_keeps_codex_delta_and_last_call_context_distinct():
    from app.usage_contract import KnownContext

    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._thread_usage_total = {
        "input_tokens": 100_000,
        "cached_input_tokens": 80_000,
        "cache_write_input_tokens": 5_000,
        "output_tokens": 2_000,
    }
    backend._usage_baseline = {
        "input_tokens": 40_000,
        "cached_input_tokens": 30_000,
        "cache_write_input_tokens": 2_000,
        "output_tokens": 500,
    }
    backend._last_call_usage = {
        "input_tokens": 33_124,
        "model_context_window": 258_400,
    }

    end = backend._turn_completed({
        "id": "turn-usage",
        "status": "completed",
    })[-1]

    assert end.usage.aggregate.input_tokens == 60_000
    assert end.usage.aggregate.cache_create_tokens == 3_000
    assert end.metadata["cost_usd"] == pytest.approx(0.12375)
    assert isinstance(end.usage.current, KnownContext)
    assert end.metadata["context_tokens"] == 33_124
    assert end.metadata["context_known"] is True


def test_explicit_codex_tool_failures_keep_identity_and_tool_name():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")

    command = backend._item_completed({
        "id": "cmd-1",
        "type": "commandExecution",
        "command": "false",
        "aggregatedOutput": "exit 1",
        "exitCode": 1,
    })
    mcp = backend._item_completed({
        "id": "mcp-1",
        "type": "mcpToolCall",
        "server": "orchestra",
        "tool": "send_message",
        "arguments": {},
        "error": {"message": "delivery failed"},
    })
    dynamic = backend._item_completed({
        "id": "dynamic-1",
        "type": "dynamicToolCall",
        "tool": "custom",
        "status": "failed",
        "success": False,
    })

    failures = [
        event
        for event in command + mcp + dynamic
        if event.type == "tool_result" and event.metadata.get("is_error")
    ]
    assert [(event.metadata["tool_use_id"], event.metadata["tool_name"]) for event in failures] == [
        ("cmd-1", "Bash"),
        ("mcp-1", "mcp__orchestra__send_message"),
        ("dynamic-1", "custom"),
    ]


def test_reasoning_plan_warning_compaction_and_mcp_failure_telemetry():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")

    reasoning = backend._convert_notification({
        "method": "item/reasoning/summaryTextDelta",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "itemId": "reason-1",
            "summaryIndex": 0,
            "delta": "Checking contracts",
        },
    })
    plan_delta = backend._convert_notification({
        "method": "item/plan/delta",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "itemId": "plan-1",
            "delta": "1. Inspect UI",
        },
    })
    plan = backend._convert_notification({
        "method": "turn/plan/updated",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "explanation": "Parity pass",
            "plan": [
                {"step": "Inspect UI", "status": "completed"},
                {"step": "Patch renderer", "status": "inProgress"},
            ],
        },
    })
    warning = backend._convert_notification({
        "method": "warning",
        "params": {"threadId": "thread-1", "message": "Transport is degraded"},
    })
    compacted = backend._convert_notification({
        "method": "thread/compacted",
        "params": {"threadId": "thread-1"},
    })
    mcp_starting = backend._convert_notification({
        "method": "mcpServer/startupStatus/updated",
        "params": {
            "threadId": "thread-1",
            "name": "orchestra",
            "status": "starting",
        },
    })
    mcp_ready = backend._convert_notification({
        "method": "mcpServer/startupStatus/updated",
        "params": {
            "threadId": "thread-1",
            "name": "orchestra",
            "status": "ready",
        },
    })
    mcp_failed = backend._convert_notification({
        "method": "mcpServer/startupStatus/updated",
        "params": {
            "threadId": "thread-1",
            "name": "orchestra",
            "status": "failed",
            "failureReason": "process exited",
        },
    })

    assert reasoning[0].type == "thinking_stream"
    assert reasoning[0].metadata["activity"] == "reasoning"
    assert plan_delta[0].type == "thinking_stream"
    assert plan_delta[0].metadata["activity"] == "plan"
    assert plan[0].type == "plan"
    assert json.loads(plan[0].content)["plan"][1]["status"] == "inProgress"
    assert warning[0].type == "warning"
    assert compacted[0].content == "codex context compacted"
    assert mcp_starting == []
    assert mcp_ready == []
    assert mcp_failed[0].type == "warning"
    assert mcp_failed[0].content == "codex mcp orchestra: failed — process exited"


def test_long_mcp_arguments_remain_valid_structured_json():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    events = backend._convert_notification({
        "method": "item/started",
        "params": {
            "item": {
                "id": "spawn-1",
                "type": "mcpToolCall",
                "server": "orchestra",
                "tool": "spawn_worker",
                "arguments": {
                    "name": "mobile-os-strategy",
                    "model": "gpt-5.6-sol",
                    "task": "Research the mobile OS strategy",
                    "system_prompt": "Detailed worker instructions. " * 200,
                },
            },
        },
    })

    assert len(events) == 1
    payload = json.loads(events[0].content.split(": ", 1)[1])
    assert payload["name"] == "mobile-os-strategy"
    assert payload["model"] == "gpt-5.6-sol"
    assert payload["task"] == "Research the mobile OS strategy"
    assert payload["system_prompt"].startswith("Detailed worker instructions.")
    assert payload["_codex_item_id"] == "spawn-1"


def test_collab_terminal_event_keeps_spawn_description_and_summary():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._convert_notification({
        "method": "item/started",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "item": {
                "id": "collab-1",
                "type": "collabAgentToolCall",
                "tool": "spawnAgent",
                "receiverThreadIds": ["child-1"],
                "senderThreadId": "thread-1",
                "agentsStates": {},
                "status": "inProgress",
                "prompt": "Research the API",
            },
        },
    })
    ended = backend._convert_notification({
        "method": "item/completed",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "item": {
                "id": "collab-2",
                "type": "collabAgentToolCall",
                "tool": "wait",
                "receiverThreadIds": ["child-1"],
                "senderThreadId": "thread-1",
                "agentsStates": {
                    "child-1": {"status": "completed", "message": "Found the schema"},
                },
                "status": "completed",
            },
        },
    })

    assert ended[0].type == "subagent_end"
    assert ended[0].metadata["description"] == "Research the API"
    assert ended[0].metadata["summary"] == "Found the schema"
    assert "Found the schema" in ended[0].content


def test_image_and_review_items_have_frontend_friendly_payloads():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    viewed = backend._item_started({
        "id": "image-1",
        "type": "imageView",
        "path": "/tmp/chart.png",
    })
    generated = backend._item_completed({
        "id": "image-2",
        "type": "imageGeneration",
        "status": "completed",
        "result": "generated",
        "savedPath": "/tmp/generated.png",
    })
    review = backend._item_completed({
        "id": "review-1",
        "type": "enteredReviewMode",
        "review": "Review the current diff",
    })

    assert json.loads(viewed[0].content.split(": ", 1)[1])["file_path"] == "/tmp/chart.png"
    assert json.loads(generated[-1].content)["saved_path"] == "/tmp/generated.png"
    assert review[0].type == "review"


def test_is_alive_tracks_codex_process_state():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    assert backend.is_alive is False

    backend._proc = SimpleNamespace(returncode=None)
    assert backend.is_alive is True

    backend._proc.returncode = 0
    assert backend.is_alive is False
