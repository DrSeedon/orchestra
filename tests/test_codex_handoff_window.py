import json
from types import SimpleNamespace

import pytest

from app.backend_codex import CodexBackend
from app.runtime_history import preflight_runtime_handoff


@pytest.fixture
def target(tmp_path, monkeypatch):
    monkeypatch.setattr("app.backend_codex._base_codex_home", lambda: tmp_path)
    (tmp_path / "config.toml").write_text("model_context_window = 872000\n")
    (tmp_path / "models_cache.json").write_text(json.dumps({"models": [{
        "slug": "gpt-6-astra", "context_window": 272000,
        "max_context_window": 872000, "effective_context_window_percent": 95,
    }]}))
    return CodexBackend(model="gpt-6-astra", system_prompt="s" * 99000, cwd=str(tmp_path)), tmp_path


def manifest(target):
    backend, _ = target
    prepared = SimpleNamespace(packet={"recent_messages": ["x" * 100000]},
                               packet_sha256="fixture", project_docs=[])
    return backend.build_handoff_manifest(prepared, validation_profile=True)


def test_configured_supported_window_allows_warm_packet_before_connect(target):
    receipt = preflight_runtime_handoff(manifest(target), native_context_tokens=0)
    assert receipt.effective_window == 828400
    assert receipt.fits
    assert receipt.candidate_upper_tokens > 199000


def test_provider_catalog_caps_unbounded_configuration(target):
    _, home = target
    (home / "config.toml").write_text("model_context_window = 999999999\n")
    assert manifest(target).effective_window == 828400


def test_smaller_configured_window_still_rejects_oversized_transfer(target):
    _, home = target
    (home / "config.toml").write_text("model_context_window = 128000\n")
    receipt = preflight_runtime_handoff(manifest(target), native_context_tokens=0)
    assert receipt.effective_window == 121600
    assert not receipt.fits


@pytest.mark.parametrize("catalog", ["{}", "invalid", '{"models": []}',
                                     '{"models": [{"slug":"gpt-6-astra","max_context_window":true}]}'])
def test_missing_or_invalid_catalog_never_increases_window(target, catalog):
    _, home = target
    (home / "models_cache.json").write_text(catalog)
    assert manifest(target).effective_window == 258400


def test_native_window_takes_precedence(target):
    backend, _ = target
    backend._thread_id = "native-thread"
    backend._model_context_window = 200000
    assert manifest(target).effective_window == 200000


def test_cold_resume_descriptor_uses_same_window_as_fresh_staging(target):
    backend, _ = target
    before = manifest(target)
    backend._thread_id = "validated-target-thread"
    after = manifest(target)
    assert before.configuration_sha256 == after.configuration_sha256
    assert after.effective_window == 828400


def test_genuine_overflow_still_blocked_with_large_supported_window(target):
    receipt = preflight_runtime_handoff(manifest(target), native_context_tokens=800000)
    assert not receipt.fits
