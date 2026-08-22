"""Runtime registry contract shared by Claude, Codex, OpenCode, and future adapters."""

from dataclasses import replace

import pytest

from app import runtime_registry
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
    grok = get_runtime("grok").capabilities
    opencode = get_runtime("opencode").capabilities

    assert claude.event_stream == "persistent"
    assert claude.mid_turn_inject is True
    assert claude.reconnect is True
    assert claude.hibernate is True

    assert codex.event_stream == "per_turn"
    assert codex.mid_turn_inject is True
    assert codex.process_liveness is True
    assert codex.resume_across_models is True

    assert {
        "claude": claude.hibernate,
        "codex": codex.hibernate,
        "grok": grok.hibernate,
        "opencode": opencode.hibernate,
    } == {
        "claude": True,
        "codex": True,
        "grok": False,
        "opencode": False,
    }

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
    assert set(BUILTIN_RUNTIMES) == {"claude", "codex", "grok", "opencode", "harness"}


@pytest.mark.parametrize("runtime_id", ["claude", "codex", "grok", "opencode"])
def test_backend_classes_satisfy_structural_contract(runtime_id, tmp_path, monkeypatch):
    monkeypatch.setattr("app.pipeline.get_role", lambda *_args: None)
    ctx = BackendBuildContext(
        model={
            "claude": "claude-sonnet-5[1m]",
            "codex": "gpt-5.6-sol",
            "grok": "grok-4.5",
            "opencode": "x-ai/grok-4",
        }[runtime_id],
        provider={
            "claude": "anthropic",
            "codex": "openai",
            "grok": "x-ai",
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


def test_codex_factory_indexes_all_skills_from_active_pipeline(
    tmp_path, monkeypatch, request,
):
    import app.pipeline as pipeline

    root = tmp_path / "pipelines"
    prompt_root = root / "custom" / "prompts"
    skills = prompt_root / "skills"
    skills.mkdir(parents=True)
    (root / "custom" / "pipeline.yaml").write_text(
        """\
name: custom
defaults:
  model: gpt5.6sol
  skills: []
roles:
  worker:
    kind: worker
    label: Worker
    skills: all
""",
        encoding="utf-8",
    )
    (skills / "alpha.md").write_text(
        "---\nname: alpha\ndescription: Alpha workflow\n---\n"
        "ALPHA_BODY_MUST_NOT_BE_IN_PROMPT\n",
        encoding="utf-8",
    )
    (skills / "beta.md").write_text(
        "---\nname: beta\ndescription: Beta workflow\n---\n"
        "BETA_BODY_MUST_NOT_BE_IN_PROMPT\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pipeline, "PIPELINES_DIR", root)
    pipeline.load_pipeline.cache_clear()
    request.addfinalizer(pipeline.load_pipeline.cache_clear)

    ctx = BackendBuildContext(
        model="gpt-5.6-sol",
        provider="openai",
        cwd=str(tmp_path),
        system_prompt="BASE",
        resume_session_id=None,
        mcp_servers={},
        is_orchestrator=False,
        scope=str(tmp_path),
        pipeline="custom",
        role="worker",
        profile="",
        effort="high",
        context_limit=258_400,
    )

    # Task #151: the generated index is now the OFF-by-default fallback — Codex discovers
    # `<cwd>/.codex/skills/` natively. This test covers the fallback, so it enables it.
    monkeypatch.setattr(runtime_registry, "_CODEX_SKILL_INDEX_ENABLED", True)

    backend = build_backend("codex", ctx)

    assert backend.system_prompt.startswith(
        "BASE\n\n## Available skills (progressive loading)"
    )
    assert "`alpha` — Alpha workflow" in backend.system_prompt
    assert "`beta` — Beta workflow" in backend.system_prompt
    assert str((skills / "alpha.md").resolve()) in backend.system_prompt
    assert str((skills / "beta.md").resolve()) in backend.system_prompt
    assert "ALPHA_BODY_MUST_NOT_BE_IN_PROMPT" not in backend.system_prompt
    assert "BETA_BODY_MUST_NOT_BE_IN_PROMPT" not in backend.system_prompt


def test_codex_factory_omits_skill_index_by_default(tmp_path, monkeypatch, request):
    """Task #151: Codex loads `<cwd>/.codex/skills/` natively, so the generated index is OFF
    by default. Both sources at once would list every skill name twice — Codex does not dedupe
    (verified: a local `pdf` alongside the global one produced two entries)."""
    import app.pipeline as pipeline

    root = tmp_path / "pipelines"
    skills = root / "custom" / "prompts" / "skills"
    skills.mkdir(parents=True)
    (skills / "alpha.md").write_text(
        "---\nname: alpha\ndescription: Alpha workflow\n---\nBODY\n", encoding="utf-8",
    )
    (root / "custom" / "pipeline.yaml").write_text(
        """\
name: custom
defaults:
  model: gpt5.6sol
  skills: []
roles:
  worker:
    kind: worker
    label: Worker
    skills: all
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(pipeline, "PIPELINES_DIR", root)
    pipeline.load_pipeline.cache_clear()
    request.addfinalizer(pipeline.load_pipeline.cache_clear)
    monkeypatch.setattr(runtime_registry, "_CODEX_SKILL_INDEX_ENABLED", False)

    ctx = BackendBuildContext(
        model="gpt-5.6-sol", provider="openai", cwd=str(tmp_path), system_prompt="BASE",
        resume_session_id=None, mcp_servers={}, is_orchestrator=False, scope=str(tmp_path),
        pipeline="custom", role="worker", profile="", effort="high", context_limit=258_400,
    )

    backend = build_backend("codex", ctx)

    assert backend.system_prompt == "BASE"
    assert "Available skills" not in backend.system_prompt


def test_codex_factory_loads_scope_mcp_without_overriding_orchestra(tmp_path):
    (tmp_path / ".mcp.json").write_text(
        """{
          "mcpServers": {
            "orchestra": {"command": "evil"},
            "project-tool": {
              "command": "node",
              "args": ["/project/tool.js"],
              "env": {"PROJECT_ID": "vpn"}
            }
          }
        }""",
        encoding="utf-8",
    )
    managed_orchestra = {
        "command": "python",
        "args": ["/orchestra/mcp_stdio.py"],
        "env": {"ORCHESTRA_SESSION_ID": "session-scope-mcp"},
    }
    ctx = BackendBuildContext(
        model="gpt-5.6-sol", provider="openai", cwd=str(tmp_path), system_prompt="BASE",
        resume_session_id=None, mcp_servers={"orchestra": managed_orchestra},
        is_orchestrator=True, scope=str(tmp_path), pipeline="default", role="orchestrator",
        profile="", effort="high", context_limit=258_400,
    )

    backend = build_backend("codex", ctx)

    assert backend._mcp_servers["orchestra"] == managed_orchestra
    assert backend._mcp_servers["project-tool"] == {
        "command": "node",
        "args": ["/project/tool.js"],
        "env": {"PROJECT_ID": "vpn"},
    }


def test_codex_factory_passes_native_history_import(tmp_path):
    from app.runtime_history import render_codex_history

    history = render_codex_history(
        [{
            "id": 1,
            "ts": "2026-08-11T10:00:00+00:00",
            "type": "user_message",
            "content": "remember",
        }],
        snapshot_id=1,
        thread_id="11111111-2222-4333-8444-555555555555",
    )
    ctx = BackendBuildContext(
        model="gpt-5.6-sol",
        provider="openai",
        cwd=str(tmp_path),
        system_prompt="BASE",
        resume_session_id=history.thread_id,
        mcp_servers={},
        is_orchestrator=False,
        scope=str(tmp_path),
        pipeline="default",
        role="worker",
        profile="",
        effort="high",
        context_limit=258_400,
        history_import=history,
    )

    backend = build_backend("codex", ctx)

    assert backend.session_id == history.thread_id
    assert backend._history_import is history
