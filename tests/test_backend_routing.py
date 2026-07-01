"""Task #96 Phase 2 — backend routing: non-Claude/non-GPT models → opencode."""

from app.models import _infer_backend, backend_for_model, BACKENDS
from app.backend_opencode import OpenCodeBackend


# ── _infer_backend prefix routing ──

def test_infer_gpt_to_codex():
    assert _infer_backend("gpt-5.5") == "codex"
    assert _infer_backend("gpt-5.4-mini") == "codex"


def test_infer_claude_to_claude():
    assert _infer_backend("claude-sonnet-5[1m]") == "claude"
    assert _infer_backend("claude-opus-4-8[1m]") == "claude"


def test_infer_others_to_opencode():
    assert _infer_backend("deepseek/deepseek-v4-flash") == "opencode"
    assert _infer_backend("gemini-2.5-flash") == "opencode"
    assert _infer_backend("meta-llama/llama-4") == "opencode"
    assert _infer_backend("mistral-large") == "opencode"
    assert _infer_backend("qwen/qwen-3") == "opencode"


# ── backend_for_model: registered wins, unregistered infers ──

def test_backend_for_model_registered_wins():
    # claude-sonnet-5[1m] is in the hardcoded BACKENDS dict
    assert "claude-sonnet-5[1m]" in BACKENDS
    assert backend_for_model("claude-sonnet-5[1m]") == "claude"


def test_backend_for_model_unregistered_infers_opencode():
    assert "deepseek/deepseek-v4-flash" not in BACKENDS
    assert backend_for_model("deepseek/deepseek-v4-flash") == "opencode"


def test_backend_for_model_unregistered_gpt_infers_codex():
    assert backend_for_model("gpt-9-future") == "codex"


# ── provider/model split for proxy IDs ──

def test_opencode_split_deepseek():
    b = OpenCodeBackend(model="deepseek/deepseek-v4-flash", cwd="/tmp")
    assert b.provider_id == "deepseek"
    assert b.model == "deepseek-v4-flash"


def test_opencode_split_nested_provider_path():
    # only the FIRST slash splits provider from model id
    b = OpenCodeBackend(model="meta-llama/llama-4-maverick", cwd="/tmp")
    assert b.provider_id == "meta-llama"
    assert b.model == "llama-4-maverick"


def test_opencode_bare_model_keeps_ctor_provider():
    # Proxy IDs are always "provider/model"; a bare ID is degenerate and keeps the
    # ctor provider_id verbatim (no split). Documents the contract, not an endorsement
    # of bare IDs for opencode (the daemon needs a real providerID).
    b = OpenCodeBackend(model="mistral-large", cwd="/tmp", provider_id="mistral")
    assert b.provider_id == "mistral"
    assert b.model == "mistral-large"
