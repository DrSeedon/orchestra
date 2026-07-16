"""CodexBackend — model dicts, reasoning effort, per-worker MCP config.

Regression net for the three bugs found in the codex-integration audit:
  BUG 1 — Sol/Terra/Luna missing from context/price dicts (worker got 258400 ctx, $0).
  BUG 2 — reasoning effort hardcoded, xhigh/max not in the accepted set.
  MCP   — per-worker MCP servers now injected via -c dotted-leaf overrides.
"""

from app.backend_codex import (
    CodexBackend,
    CODEX_CONTEXT_LIMITS,
    CODEX_TOKEN_PRICES,
    CODEX_REASONING_EFFORTS,
)


# ── BUG 1: GPT-5.6 models registered in backend dicts ──

def test_gpt56_context_limits_present():
    # 1.05M window × 0.95 usable = 997500 (not the 258400 fallback for 5.4/5.5)
    for m in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
        assert CODEX_CONTEXT_LIMITS[m] == 997500, m


def test_gpt56_prices_present():
    assert CODEX_TOKEN_PRICES["gpt-5.6-sol"] == {"input": 5.0, "output": 30.0}
    assert CODEX_TOKEN_PRICES["gpt-5.6-terra"] == {"input": 2.5, "output": 15.0}
    assert CODEX_TOKEN_PRICES["gpt-5.6-luna"] == {"input": 1.0, "output": 6.0}


def test_legacy_gpt_models_unchanged():
    assert CODEX_CONTEXT_LIMITS["gpt-5.5"] == 258400
    assert CODEX_TOKEN_PRICES["gpt-5.4"] == {"input": 2.5, "output": 15.0}


def test_sol_price_and_ctx_not_zero_fallback():
    # The bug's symptom: a Sol worker used the {input:0,output:0} / 258400 fallbacks.
    b = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    assert CODEX_CONTEXT_LIMITS.get(b.model, 258400) == 997500
    assert CODEX_TOKEN_PRICES.get(b.model, {"input": 0, "output": 0})["output"] == 30.0


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
