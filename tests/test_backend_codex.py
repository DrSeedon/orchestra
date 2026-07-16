"""CodexBackend — model dicts, runtime accounting, and per-worker MCP config.

Regression net for the three bugs found in the codex-integration audit:
  BUG 1 — Sol/Terra/Luna missing from context/price dicts (worker got 258400 ctx, $0).
  BUG 2 — reasoning effort hardcoded, xhigh/max not in the accepted set.
  MCP   — per-worker MCP servers now injected via -c dotted-leaf overrides.
"""

import json

import pytest

from app.backend_codex import (
    CodexBackend,
    CODEX_CONTEXT_LIMITS,
    CODEX_TOKEN_PRICES,
    CODEX_REASONING_EFFORTS,
    _codex_cost,
    _read_rollout_context,
    _usage_delta,
)


# ── BUG 1: GPT-5.6 models registered in backend dicts ──

def test_gpt56_context_limits_present():
    # ChatGPT-auth Codex runtime reports a 258400 effective budget for these models.
    # The public API's 1.05M window is a different surface and must not drive dashboard
    # accounting or auto-compact for a local Codex worker.
    for m in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
        assert CODEX_CONTEXT_LIMITS[m] == 258400, m


def test_gpt56_prices_present():
    assert CODEX_TOKEN_PRICES["gpt-5.6-sol"] == {"input": 5.0, "cached": 0.5, "output": 30.0}
    assert CODEX_TOKEN_PRICES["gpt-5.6-terra"] == {"input": 2.5, "cached": 0.25, "output": 15.0}
    assert CODEX_TOKEN_PRICES["gpt-5.6-luna"] == {"input": 1.0, "cached": 0.1, "output": 6.0}


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
    assert _codex_cost("gpt-5.6-sol", 1000, 900, 10) == pytest.approx(0.00125)


def test_usage_delta_survives_resume_and_counter_reset():
    current = {"input_tokens": 130, "cached_input_tokens": 90, "output_tokens": 20}
    baseline = {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 5}
    assert _usage_delta(current, baseline) == {
        "input_tokens": 30, "cached_input_tokens": 10, "output_tokens": 15,
    }
    # A Codex-side compact may reset counters. Treat the new value as this turn rather
    # than producing negative usage or zeroing a real call.
    assert _usage_delta({"input_tokens": 10}, {"input_tokens": 100})["input_tokens"] == 10


def test_rollout_context_uses_last_call_not_accumulated_usage(tmp_path):
    rollout = tmp_path / "rollout.jsonl"
    rows = [
        {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 760838},
            "last_token_usage": {"input_tokens": 95489, "cached_input_tokens": 92928},
            "model_context_window": 258400,
        }}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 2042411},
            "last_token_usage": {"input_tokens": 142165, "cached_input_tokens": 141056},
            "model_context_window": 258400,
        }}},
    ]
    rollout.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    assert _read_rollout_context(rollout) == {
        "input_tokens": 142165,
        "cached_input_tokens": 141056,
        "model_context_window": 258400,
    }


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


def test_mcp_config_skips_url_only_servers():
    b = CodexBackend(model="gpt-5.6-sol", cwd="/tmp", mcp_servers={
        "remote": {"url": "https://example/sse"},
    })
    assert b._mcp_config_args() == []  # no command → skipped, not crashed


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
