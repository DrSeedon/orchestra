"""Gemini Web contracts. No real browser, credentials, provider or production DB."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import gemini_web_auth as auth
from app.harness import gemini_web as web
from app.harness import gemini_web_worker as worker
from app.models import get_model_spec, resolve_model, validate_harness_model_spec

TOOLS = [{"type": "function", "function": {
    "name": "read", "parameters": {"type": "object", "properties": {
        "path": {"type": "string"}}, "required": ["path"]},
}}]
AUTH = {"cookies": {"__Secure-1PSID": "fake-psid-for-unit-test",
                    "__Secure-1PSIDTS": "fake-psidts-for-unit-test"},
        "expected_email": "owner@example.com"}


@pytest.fixture
def private_auth(tmp_path, monkeypatch):
    path = tmp_path / "gemini-web/auth.json"
    monkeypatch.setenv("GEMINI_WEB_AUTH_FILE", str(path))
    monkeypatch.setenv("GEMINI_WEB_PYTHON", sys.executable)
    auth.write_auth(AUTH)
    return path


@pytest.mark.parametrize("alias,raw", [
    ("gweb-argon", "gemini-argon"), ("gemini-web-argon", "gemini-argon"),
    ("gweb-pro", "gemini-pro"), ("gweb-flash", "gemini-flash"),
    ("gweb-flash-lite", "gemini-flash-lite"),
])
def test_models_and_aliases(private_auth, alias, raw):
    spec = get_model_spec(resolve_model(alias))
    assert spec.id == f"gemini-web/{raw}"
    assert (spec.runtime, spec.provider) == ("harness", "gemini-web")
    assert spec.name == "Gemini Web: " + auth.MODELS[raw]
    validate_harness_model_spec(spec)


def test_models_survive_proxy_refresh(monkeypatch):
    from app import models
    for name in ("MODELS", "CONTEXT_LIMITS", "TOKEN_PRICES", "BACKENDS",
                 "MODEL_PROVIDERS", "MODEL_SPECS", "ALIASES"):
        monkeypatch.setattr(models, name, dict(getattr(models, name)))
    models._clear_selectable_models()
    assert models.ALIASES["gweb-argon"] in models.MODEL_SPECS
    assert len([s for s in models.MODEL_SPECS.values() if s.provider == "gemini-web"]) == 4


def test_registry_accepts_unknown_web_context():
    from app.models import validate_model_registry
    validate_model_registry()


def test_auth_is_atomic_private_and_readiness_is_local(private_auth, monkeypatch):
    assert private_auth.stat().st_mode & 0o777 == 0o600
    assert private_auth.parent.stat().st_mode & 0o777 == 0o700
    assert auth.read_auth() == AUTH
    assert auth.gemini_web_readiness()["ready"]
    before = private_auth.read_bytes()
    with pytest.raises(ValueError):
        auth.write_auth({"cookies": {}})
    assert private_auth.read_bytes() == before
    assert list(private_auth.parent.iterdir()) == [private_auth]
    monkeypatch.setenv("GEMINI_WEB_PYTHON", "/missing-python")
    assert not auth.gemini_web_readiness()["ready"]


@pytest.mark.parametrize("mode", [0o644, 0o666, 0o400])
def test_shared_auth_is_not_admitted(private_auth, mode):
    private_auth.chmod(mode)
    assert not auth.gemini_web_readiness()["ready"]
    with pytest.raises(ValueError, match="authorization"):
        validate_harness_model_spec(get_model_spec("gemini-web/gemini-argon"))


def test_symlink_and_missing_auth_are_not_admitted(private_auth):
    original = private_auth.with_name("original.json")
    private_auth.rename(original)
    private_auth.symlink_to(original)
    assert not auth.gemini_web_readiness()["ready"]
    private_auth.unlink()
    assert not auth.gemini_web_readiness()["ready"]


def test_auth_path_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_WEB_AUTH_FILE", raising=False)
    monkeypatch.delenv("ORCHESTRA_HOME", raising=False)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(tmp_path / "db/orchestra.db"))
    assert auth.auth_path() == tmp_path / "db/gemini-web/auth.json"
    monkeypatch.setenv("ORCHESTRA_HOME", str(tmp_path / "state"))
    assert auth.auth_path() == tmp_path / "state/gemini-web/auth.json"


def test_history_protocol_preserves_system_calls_and_tool_result():
    messages = [{"role": "system", "content": "keep all files"},
                {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "c1", "function": {"name": "read", "arguments": '{"path":"a"}'}}]},
                {"role": "tool", "tool_call_id": "c1", "content": "actual contents"}]
    prompt = web.format_prompt(messages, TOOLS)
    assert json.dumps(messages, ensure_ascii=False) in prompt
    assert json.dumps(TOOLS, ensure_ascii=False) in prompt


def test_text_and_usage_follow_loop_contract():
    events = web.parse_response("Привет", [])
    assert [(e.kind, e.text) for e in events] == [("text_delta", "Привет"), ("final", "")]
    assert events[-1].finish_reason == "stop"
    assert events[-1].usage["cost"] == 0
    assert events[-1].usage["token_counts_available"] is False


def test_multiple_tool_calls_and_prose():
    events = web.parse_response(
        'Read first.\n```tool_call\n{"name":"read","arguments":{"path":"a"}}\n```\n'
        '```tool_call\n{"name":"read","arguments":{"path":"b"}}\n```', TOOLS)
    assert [e.kind for e in events] == ["text_delta", "tool_call_done", "tool_call_done", "final"]
    assert [json.loads(e.arguments) for e in events[1:3]] == [{"path": "a"}, {"path": "b"}]
    assert events[1].tool_id != events[2].tool_id
    assert events[-1].finish_reason == "tool_calls"


@pytest.mark.parametrize("text", [
    "", "```tool_call\n{}", "```tool_call\nnot json\n```",
    '```tool_call\n{"name":"unknown","arguments":{}}\n```',
    '```tool_call\n{"name":"read","arguments":"wrong"}\n```',
    '```tool_call\n[]\n```',
])
def test_invalid_calls_fail_before_any_event(text):
    with pytest.raises(RuntimeError):
        web.parse_response(text, TOOLS)


def test_secrets_redacted_including_cache_filename():
    raw = 'error .cached_cookies_' + AUTH["cookies"]["__Secure-1PSID"] + '.json '
    raw += '__Secure-1PSIDTS="unseen-rotated-cookie"'
    clean = auth.redact_secrets(raw, AUTH["cookies"])
    assert all(value not in clean for value in AUTH["cookies"].values())
    assert "unseen-rotated-cookie" not in clean


def test_actual_audit_hook_prevents_cache_open(tmp_path):
    script = (
        "import sys; from app.harness.gemini_web_worker import prevent_cookie_files; "
        "sys.addaudithook(prevent_cookie_files); open(sys.argv[1], 'w')"
    )
    path = tmp_path / ".cached_cookies_dummy.json"
    result = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True)
    assert result.returncode != 0
    assert b"credential cache disabled" in result.stderr
    assert not path.exists()


@pytest.fixture
def vendor(monkeypatch):
    noop = lambda *args, **kwargs: None
    access = SimpleNamespace(_get_cookies_cache_path=lambda *_: "unsafe",
                             _extract_payload=lambda response: ("token",),
                             AsyncSession=lambda **kw: kw, load_browser_cookies=noop)
    cache = SimpleNamespace(_get_cookies_cache_path=noop, save_cookies=noop, clear_cookies_cache=noop)
    client_module = SimpleNamespace(save_cookies=noop, clear_cookies_cache=noop)
    for name, module in {"gemini_webapi.utils.get_access_token": access,
                         "gemini_webapi.utils.rotate_1psidts": cache,
                         "gemini_webapi.client": client_module,
                         "loguru": SimpleNamespace(logger=SimpleNamespace(remove=noop))}.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(sys, "addaudithook", noop)
    monkeypatch.setattr(worker, "version", lambda name: "2.1.1")
    return SimpleNamespace(access=access, cache=cache, client=client_module)


def test_cookie_patches_pin_account_and_reject_missing_or_wrong_principal(vendor):
    identity = {}
    worker.disable_cookie_files(identity, AUTH["expected_email"])
    assert vendor.access.AsyncSession(params={"x": 1}) == {
        "params": {"x": 1, "authuser": AUTH["expected_email"]}}
    assert vendor.access._get_cookies_cache_path({}) is None
    assert vendor.cache.save_cookies({}) is None
    assert vendor.client.save_cookies({}) is None
    assert vendor.access.load_browser_cookies() is None
    for text in ('{}', '{"oPEP7c":"someone@example.com"}'):
        with pytest.raises(RuntimeError, match="identity mismatch"):
            vendor.access._extract_payload(SimpleNamespace(text=text))
    vendor.access._extract_payload(SimpleNamespace(text='{"oPEP7c":"owner@example.com"}'))
    assert identity["owner_match"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("principal,model_available", [
    ("owner@example.com", True), ("someone@example.com", True), ("owner@example.com", False),
])
async def test_worker_identity_and_exact_model_gate(vendor, monkeypatch, principal, model_available):
    chosen = SimpleNamespace(model_name="gemini-argon", display_name="4 Argon", is_available=model_available)
    client = SimpleNamespace(close=AsyncMock(), account_status=SimpleNamespace(name="AVAILABLE"),
                             list_models=lambda: [chosen],
                             generate_content=AsyncMock(return_value=SimpleNamespace(text="OK")))

    async def initialize(**kwargs):
        assert kwargs["auto_refresh"] is False
        vendor.access._extract_payload(SimpleNamespace(text=json.dumps({"oPEP7c": principal})))

    client.init = initialize
    monkeypatch.setitem(sys.modules, "gemini_webapi", SimpleNamespace(GeminiClient=lambda *a: client))
    payload = {"auth": AUTH, "model": "gemini-argon", "prompt": "Reply OK"}
    if principal == AUTH["expected_email"] and model_available:
        result = await worker.generate(payload)
        assert result["selected_model"] == "gemini-argon"
        client.generate_content.assert_awaited_once_with("Reply OK", model=chosen, temporary=True)
    else:
        with pytest.raises(RuntimeError):
            await worker.generate(payload)
        client.generate_content.assert_not_awaited()
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_and_abort(private_auth, monkeypatch):
    client = web.GeminiWebClient("gemini-web/gemini-argon")
    request = AsyncMock(return_value={"text": "OK"})
    monkeypatch.setattr(client, "_request", request)
    assert [e.kind async for e in client.stream([{"role": "user", "content": "hi"}], [])] == ["text_delta", "final"]
    assert [e async for e in client.stream([], [], abort=lambda: True)] == []
    assert request.await_count == 1
    client.retarget("gemini-web/gemini-pro")
    assert client.model == "gemini-web/gemini-pro"


@pytest.mark.asyncio
async def test_helper_credentials_only_on_stdin_and_output_redacted(private_auth, monkeypatch):
    real_create = asyncio.create_subprocess_exec
    observed = []

    async def create(*args, **kwargs):
        assert all(value not in str(args) for value in AUTH["cookies"].values())
        observed.append(args)
        script = (
            "import sys,json; p=json.load(sys.stdin); "
            "print(json.dumps(dict(text=p['auth']['cookies']['__Secure-1PSID'], "
            "selected_model=p['model'], owner_match=True)))"
        )
        return await real_create(sys.executable, "-c", script, **kwargs)

    monkeypatch.setattr(web.asyncio, "create_subprocess_exec", create)
    client = web.GeminiWebClient("gemini-web/gemini-argon")
    result = await client._request("hello", AUTH)
    assert result["text"] == "[REDACTED]"
    assert len(observed) == 1
    assert not client._processes


@pytest.mark.asyncio
async def test_cancel_reaps_helper(private_auth, monkeypatch):
    real_create = asyncio.create_subprocess_exec
    created = asyncio.Event()
    processes = []

    async def create(*args, **kwargs):
        process = await real_create(sys.executable, "-c", "import time; time.sleep(30)", **kwargs)
        processes.append(process)
        created.set()
        return process

    monkeypatch.setattr(web.asyncio, "create_subprocess_exec", create)
    client = web.GeminiWebClient("gemini-web/gemini-argon")
    request = asyncio.create_task(client._request("hello", AUTH))
    await created.wait()
    await asyncio.sleep(0)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert processes[0].returncode is not None
    assert not client._processes


@pytest.mark.asyncio
async def test_backend_uses_gemini_without_openrouter_key(private_auth, monkeypatch, tmp_path):
    from app.backend_harness import HarnessBackend
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_KEY", raising=False)
    backend = HarnessBackend(cwd=str(tmp_path), model="gemini-web/gemini-argon")
    await backend.connect()
    try:
        assert isinstance(backend._llm, web.GeminiWebClient)
        assert backend._max_context() > 0
        backend.retarget_model("gemini-web/gemini-pro")
        assert backend._llm.model == "gemini-web/gemini-pro"
        with pytest.raises(RuntimeError, match="across Gemini Web"):
            backend.retarget_model("GigaChat-2")
    finally:
        await backend.disconnect()


@pytest.mark.asyncio
async def test_api_models_hides_unready_web_routes(private_auth, monkeypatch):
    from fastapi import Response
    from app.routes import system
    monkeypatch.setattr(system, "MODELS", {
        f"gemini-web/{raw}": "Gemini Web: " + display
        for raw, display in auth.MODELS.items()
    })
    monkeypatch.setattr(system, "get_model_flags", lambda mid: {"dashboard": True})
    result = await system.list_models(Response())
    assert len(result["models"]) == 4
    assert all(m["runtime"] == "harness" and m["provider"] == "gemini-web"
               for m in result["models"])
    catalog = await system.get_models_catalog()
    entries = [m for m in catalog["catalog"] if m["provider"] == "gemini-web"]
    assert len(entries) == 4
    assert all(m["harness_eligible"] and m["available"] for m in entries)
    private_auth.unlink()
    result = await system.list_models(Response())
    assert result["models"] == []
    catalog = await system.get_models_catalog()
    assert not any(m["harness_eligible"] or m["available"] for m in catalog["catalog"]
                   if m["provider"] == "gemini-web")


@pytest.mark.asyncio
async def test_helper_vendor_error_does_not_escape(private_auth, monkeypatch, caplog):
    real_create = asyncio.create_subprocess_exec

    async def create(*args, **kwargs):
        script = (
            "import sys,json; p=json.load(sys.stdin); "
            "print(p['auth']['cookies'],file=sys.stderr); print(p['auth']['cookies']); sys.exit(1)"
        )
        return await real_create(sys.executable, "-c", script, **kwargs)

    monkeypatch.setattr(web.asyncio, "create_subprocess_exec", create)
    client = web.GeminiWebClient("gemini-web/gemini-argon")
    with pytest.raises(RuntimeError) as error:
        await client._request("hello", AUTH)
    assert all(v not in str(error.value) + caplog.text for v in AUTH["cookies"].values())
    assert not client._processes


@pytest.mark.asyncio
async def test_worker_refuses_unpinned_library(monkeypatch):
    monkeypatch.setattr(worker, "version", lambda name: "9.9.9")
    with pytest.raises(RuntimeError, match="2.1.1"):
        await worker.generate({})
