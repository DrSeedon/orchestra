#!/usr/bin/env python3
"""T1: file-first memory reaches every decision role and every builtin model runtime."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from app.pipeline import build_system_prompt  # noqa: E402
from app import mcp_stdio  # noqa: E402
from app.manager import SessionManager  # noqa: E402
from app.runtime_registry import BackendBuildContext, build_backend  # noqa: E402


DECISION_ROLES = ("orchestrator", "sub-orchestrator", "worker", "full-cycle")
LEXICAL_ANCHORS = (
    "Выдели 1–3 отличительных поисковых якоря",
    "Сначала ищи только в `docs/kb/`",
    "`rg -l -i -F --glob '*.md'`",
    "`docs/tasks/` открывай только по ссылке из найденного факта",
    "`search_memory` остаётся compatibility-тулом и не является обязательным шагом",
)


def main() -> None:
    module = (ROOT / "pipelines/default/prompts/modules/memory-search.md").read_text(
        encoding="utf-8"
    )
    missing_source = [anchor for anchor in LEXICAL_ANCHORS if anchor not in module]
    assert not missing_source, (
        "T1 missing lexical protocol in its single prompt owner: "
        f"{missing_source}"
    )
    assert module.count("search_memory") == 1, (
        "T1 memory module must contain exactly one compatibility-only search_memory reference; "
        "a second reference can silently restore a mandatory call"
    )

    for role in DECISION_ROLES:
        prompt = build_system_prompt("default", role)
        missing = [anchor for anchor in LEXICAL_ANCHORS if anchor not in prompt]
        assert not missing, f"T1 {role} did not receive lexical protocol: {missing}"
        assert "**Step 2 — `search_memory(" not in prompt, (
            f"T1 {role} still mandates the disabled semantic call before lexical search"
        )
        assert "search_memory" in prompt, (
            f"T1 {role} lost the explicitly preserved compatibility tool"
        )
        assert prompt.count("search_memory") == 1, (
            f"T1 {role} has another search_memory instruction beyond the compatibility-only invariant"
        )
        assert "<knowledge-capability>" not in prompt, (
            f"T1 {role} still receives instructions for the retired generic knowledge tool"
        )

    reducer = build_system_prompt("default", "reducer")
    assert "Canonical project memory lives in `docs/kb/`" in reducer, (
        "T1 reducer lacks the all-agent canonical-owner invariant"
    )
    assert LEXICAL_ANCHORS[0] not in reducer, (
        "T1 reducer received a mandatory interpretation/search workflow despite its lossless-collector role"
    )
    assert "<knowledge-capability>" not in reducer, (
        "T1 reducer still receives instructions for the retired generic knowledge tool"
    )

    registered = {
        tool.name: tool for tool in mcp_stdio.mcp._tool_manager.list_tools()
    }
    assert "search_memory" in registered, (
        "T1 removed search_memory from the actual FastMCP registry"
    )
    assert "knowledge" not in registered, (
        "T1 left knowledge exposed in the actual FastMCP registry"
    )
    assert "knowledge" not in mcp_stdio.READ_ONLY_MCP_TOOLS, (
        "T1 left the retired tool in the read-only access-mode registry"
    )
    assert "knowledge" not in mcp_stdio.REDUCER_MCP_TOOLS, (
        "T1 left the retired tool in the reducer access-mode registry"
    )

    old_api, old_scope = mcp_stdio._api, mcp_stdio.SCOPE

    async def disabled_rag(*_args, **_kwargs):
        raise mcp_stdio.ApiToolError(
            code="http_503",
            message="RAG disabled (set RAG_ENABLED=true)",
        )

    try:
        mcp_stdio._api = disabled_rag
        mcp_stdio.SCOPE = "/project"
        fallback = asyncio.run(registered["search_memory"].run({"query": "needle"}))
    finally:
        mcp_stdio._api, mcp_stdio.SCOPE = old_api, old_scope
    assert "RAG_ENABLED=false" in fallback and 'rg "needle"' in fallback, (
        "T1 registered search_memory does not execute the disabled-RAG → rg fallback"
    )

    models = {
        "claude": ("claude-sonnet-5[1m]", "anthropic"),
        "codex": ("gpt-5.6-sol", "openai"),
        "grok": ("grok-4.5", "x-ai"),
    }
    assembled = build_system_prompt("default", "worker") + "\n\nRUNTIME_SENTINEL_417"
    with tempfile.TemporaryDirectory(prefix="runtime-memory-") as tmp:
        for runtime, (model, provider) in models.items():
            ctx = BackendBuildContext(
                model=model,
                provider=provider,
                cwd=tmp,
                system_prompt=assembled,
                resume_session_id=None,
                mcp_servers={},
                is_orchestrator=False,
                scope=tmp,
                pipeline="default",
                role="worker",
                profile="",
                effort="high",
                context_limit=256_000,
                validation_profile=True,
            )
            backend = build_backend(runtime, ctx)
            assert "RUNTIME_SENTINEL_417" in backend.system_prompt, (
                f"T1 {runtime} backend did not receive the assembled prompt sentinel"
            )
            assert all(anchor in backend.system_prompt for anchor in LEXICAL_ANCHORS), (
                f"T1 {runtime} backend lost lexical protocol content"
            )

    manager = object.__new__(SessionManager)
    manager._find_orchestrator_name = lambda _scope: "orchestrator"
    resumed, overlay = SessionManager.assemble_prompt(
        manager,
        pipeline="default",
        role="worker",
        scope="/project",
        is_orch=False,
        name="oracle-no-memory-417",
        owned_dirs=[],
        branch="task-417/oracle",
        stored_overlay="",
        old_prompt="legacy",
        repository_path="",
    )
    assert overlay == "" and all(anchor in resumed for anchor in LEXICAL_ANCHORS), (
        "T1 resumed-session assembly did not rebuild the current lexical protocol"
    )
    override, overlay = SessionManager.assemble_prompt(
        manager,
        pipeline="default",
        role="worker",
        scope="/project",
        is_orch=False,
        name="oracle-no-memory-417",
        owned_dirs=[],
        branch="task-417/oracle",
        stored_overlay=None,
        old_prompt="OPERATOR_FULL_PROMPT_417",
        repository_path="",
    )
    assert override == "OPERATOR_FULL_PROMPT_417" and overlay is None, (
        "T1 rewrote a full operator prompt whose component boundary is unknown"
    )

    print("T1 PASS: file-first protocol delivered; knowledge retired; search_memory preserved")


if __name__ == "__main__":
    main()
