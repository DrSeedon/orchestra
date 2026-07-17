"""Runtime registry contract shared by Claude, Codex, OpenCode, and future adapters."""

from dataclasses import replace

import pytest

from app.backend_protocol import BackendLike
from app.runtime_registry import (
    BUILTIN_RUNTIMES,
    BackendBuildContext,
    RuntimeCapabilities,
    RuntimeDefinition,
    build_backend,
    get_runtime,
    register_runtime,
    unregister_runtime,
)


def test_builtin_runtime_capabilities_are_explicit():
    claude = get_runtime("claude").capabilities
    codex = get_runtime("codex").capabilities
    opencode = get_runtime("opencode").capabilities

    assert claude.event_stream == "persistent"
    assert claude.mid_turn_inject is True
    assert claude.reconnect is True
    assert claude.hibernate is True

    assert codex.event_stream == "per_turn"
    assert codex.mid_turn_inject is False
    assert codex.process_liveness is True
    assert codex.resume_across_models is False

    assert opencode.event_stream == "per_turn"
    assert opencode.mid_turn_inject is False
    assert opencode.reconnect is False
    assert opencode.process_liveness is True


def test_runtime_registry_accepts_external_adapter_without_core_branch():
    runtime_id = "test-runtime"

    class _Backend:
        session_id = None

        async def connect(self): ...
        async def send(self, _message): ...
        async def events(self):
            if False:
                yield None
        async def interrupt(self): ...
        async def disconnect(self): ...

    built = _Backend()
    definition = RuntimeDefinition(
        id=runtime_id,
        capabilities=RuntimeCapabilities(
            event_stream="per_turn",
            mid_turn_inject=False,
            reconnect=False,
            hibernate=False,
        ),
        factory=lambda _ctx: built,
    )
    register_runtime(definition)
    try:
        ctx = BackendBuildContext(
            model="provider/model",
            provider="provider",
            cwd="/tmp",
            system_prompt="",
            resume_session_id=None,
            mcp_servers={},
            is_orchestrator=False,
            scope="/tmp",
            pipeline="default",
            role="worker",
            profile="",
            effort=None,
            context_limit=123,
        )
        assert build_backend(runtime_id, ctx) is built
    finally:
        unregister_runtime(runtime_id)


def test_runtime_registry_rejects_incompatible_plugin_backend():
    runtime_id = "broken-runtime"
    register_runtime(RuntimeDefinition(
        id=runtime_id,
        capabilities=RuntimeCapabilities(
            event_stream="per_turn",
            mid_turn_inject=False,
            reconnect=False,
            hibernate=False,
        ),
        factory=lambda _ctx: object(),
    ))
    try:
        ctx = BackendBuildContext(
            model="provider/model",
            provider="provider",
            cwd="/tmp",
            system_prompt="",
            resume_session_id=None,
            mcp_servers={},
            is_orchestrator=False,
            scope="/tmp",
            pipeline="default",
            role="worker",
            profile="",
            effort=None,
            context_limit=123,
        )
        with pytest.raises(TypeError, match="incompatible backend"):
            build_backend(runtime_id, ctx)
    finally:
        unregister_runtime(runtime_id)


def test_builtin_runtime_cannot_be_overwritten_accidentally():
    original = get_runtime("codex")
    with pytest.raises(ValueError, match="already registered"):
        register_runtime(replace(original, factory=lambda _ctx: object()))
    assert set(BUILTIN_RUNTIMES) == {"claude", "codex", "opencode"}


@pytest.mark.parametrize("runtime_id", ["claude", "codex", "opencode"])
def test_backend_classes_satisfy_structural_contract(runtime_id, tmp_path, monkeypatch):
    monkeypatch.setattr("app.pipeline.get_role", lambda *_args: None)
    ctx = BackendBuildContext(
        model={
            "claude": "claude-sonnet-5[1m]",
            "codex": "gpt-5.6-sol",
            "opencode": "x-ai/grok-4",
        }[runtime_id],
        provider={
            "claude": "anthropic",
            "codex": "openai",
            "opencode": "x-ai",
        }[runtime_id],
        cwd=str(tmp_path),
        system_prompt="test",
        resume_session_id=None,
        mcp_servers={},
        is_orchestrator=False,
        scope=str(tmp_path),
        pipeline="default",
        role="worker",
        profile="",
        effort="high",
        context_limit=256_000,
    )
    backend = build_backend(runtime_id, ctx)
    required = ("connect", "send", "events", "interrupt", "disconnect")
    assert all(callable(getattr(backend, name, None)) for name in required)
    assert isinstance(backend, BackendLike)
