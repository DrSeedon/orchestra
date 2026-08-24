"""Frozen RED correction for #315 T3b: agent-only structured knowledge.

The only agent-facing surface is one ``knowledge`` MCP tool backed by one
``POST /api/knowledge`` route and ``app.ia.knowledge.knowledge_api`` owner.
Canonical writes are JSON records/indexes only.  Historical Markdown remains
byte-preserved cold evidence and is never regenerated or used as truth fallback.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest


HERE = Path(__file__).resolve().parent
FIXTURE_PATH = HERE / "fixtures" / "t3b_agent_only_records.json"
CONTRACT_PATH = HERE / "fixtures" / "t3b_agent_only_contract.json"
T3_ORACLE_PATH = HERE / "test_t3_promotion_behavior.py"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture() -> dict:
    return _json(FIXTURE_PATH)


def _contract() -> dict:
    return _json(CONTRACT_PATH)


def _t3_oracle_module():
    spec = importlib.util.spec_from_file_location("t3_oracle_for_t3b", T3_ORACLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_api() -> SimpleNamespace:
    modules = {}
    for module_name, surface in _contract()["public_api"].items():
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            pytest.fail(f"#315 T3b missing behavior: cannot import {module_name}: {exc}")
        for name in surface.get("callables", []):
            assert callable(getattr(module, name, None)), (
                f"#315 T3b missing behavior: {module_name}.{name} is not callable"
            )
        for name in surface.get("exceptions", []):
            error = getattr(module, name, None)
            assert isinstance(error, type) and issubclass(error, Exception), (
                f"#315 T3b missing behavior: {module_name}.{name} is not an exception"
            )
        for name in surface.get("attributes", []):
            assert getattr(module, name, None) is not None, (
                f"#315 T3b missing behavior: {module_name}.{name} is absent"
            )
        modules[module_name.replace(".", "_")] = module
    return SimpleNamespace(**modules)


def _historical_root(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "historical"
    hashes = {}
    for source in _fixture()["historical_sources"]:
        path = root / source["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source["content"], encoding="utf-8")
        hashes[source["path"]] = hashlib.sha256(path.read_bytes()).hexdigest()
    return root, hashes


def _materialize_import_request(historical_root: Path) -> dict:
    request = copy.deepcopy(_fixture()["import_request"])
    source_path = historical_root / request["source"]["path"]
    request["source"]["content_sha256"] = (
        f"sha256:{hashlib.sha256(source_path.read_bytes()).hexdigest()}"
    )
    request["source"]["source_root"] = str(historical_root)
    return request


def _nested_keys(value) -> set[str]:
    if isinstance(value, Mapping):
        return set(value) | {
            key for child in value.values() for key in _nested_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _nested_keys(child)}
    return set()


def _assert_agent_only_canonical(root: Path) -> None:
    allowed = {".json"}
    files = [path for path in root.rglob("*") if path.is_file()]
    assert files, "canonical structured store is empty"
    assert {path.suffix.lower() for path in files} <= allowed
    forbidden_keys = set(_fixture()["forbidden_generated_keys"])
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert forbidden_keys.isdisjoint(_nested_keys(payload))


def _asgi_app(api):
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(api.app_routes_knowledge.router)
    return app


def _asgi_transport_api(app):
    import httpx

    async def call(method, path, **kwargs):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t3b.test") as client:
            response = await client.request(method, path, json=kwargs.get("json"))
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": response.text}
        if response.status_code >= 400:
            return {"error": payload.get("error", payload), "status": response.status_code}
        return payload

    return call


def _tool_request(operation: str, detail: str, **payload) -> dict:
    return {"operation": operation, "detail": detail, **payload}


def test_t3b_harness_quantifies_current_t3_and_repository_conflicts():
    fixture = _fixture()
    contract = _contract()
    audit = fixture["audit_baseline"]
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == contract["fixture_sha256"]
    for relative, expected in contract["merged_t3_implementation_sha256"].items():
        assert hashlib.sha256(Path(relative).read_bytes()).hexdigest() == expected
    assert audit == {
        "merged_t3_command": "uv run python -m pytest docs/tasks/315/acceptance/test_t3_promotion_behavior.py -q",
        "merged_t3_result": "18 passed",
        "markdown_generator_call_sites": 2,
        "initial_generated_markdown_files": 3,
        "new_topic_generated_markdown_files": 4,
        "t3_contract_markdown_layout_paths": 2,
        "t3_oracle_markdown_behavior_assertions": 2,
        "current_repo_inventory": {
            "docs_tasks_md": 1281,
            "docs_kb_md": 20,
            "session_archive_md": 3,
            "pipeline_prompt_md": 23,
            "codex_skill_md": 2,
            "todo_md": 1,
            "claude_md": 1,
            "agents_md": 1,
        },
    }
    knowledge_source = Path("app/ia/knowledge.py").read_text(encoding="utf-8")
    assert knowledge_source.count("self._write_topic_documents()") == 2
    assert '"README.md"' in knowledge_source and '"topic.md"' in knowledge_source
    old_contract = _json(HERE / "fixtures" / "t3_promotion_contract.json")
    assert set(old_contract["canonical_layout"]) >= {"readme", "topic"}
    old_oracle = T3_ORACLE_PATH.read_text(encoding="utf-8")
    assert 'root / "README.md"' in old_oracle
    assert '["canonical_layout"]["topic"]' in old_oracle


def test_t3b_harness_existing_structured_t3_behavior_and_markdown_mutation_execute(tmp_path):
    t3 = _t3_oracle_module()
    api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    root = tmp_path / "knowledge-main"
    with t3._knowledge_mode(api, tmp_path, context):
        initial_markdown = sorted(root.rglob("*.md"))
        result = t3._promote(api, t3._request("new_topic", context))
        after_markdown = sorted(root.rglob("*.md"))
    assert result["outcome"] == "created"
    assert len(initial_markdown) == 3
    assert len(after_markdown) == 4
    assert len(t3._fact_files(root)) == 1
    assert len(t3._event_files(root)) == 1
    assert any(path.name == "README.md" for path in after_markdown)
    assert any(path.name == "topic.md" for path in after_markdown)


def test_t3b_harness_historical_sources_and_compound_mutants_are_material(tmp_path):
    historical_root, before = _historical_root(tmp_path)
    assert len(before) == 4
    assert all(hashlib.sha256((historical_root / path).read_bytes()).hexdigest() == digest
               for path, digest in before.items())
    mutants = _fixture()["compound_mutants"]
    assert mutants["hidden_markdown_regeneration"]["nested_output"].endswith(".markdown")
    assert "human_projection" in _nested_keys(
        mutants["hidden_markdown_regeneration"]["json_marker"]
    )
    assert mutants["direct_file_fallback"]["fallback_path"].endswith(".md")
    assert mutants["sqlite_fallback"]["payload_json"]["claim"]
    assert mutants["vector_fallback"]["hits"][0]["content"]


@pytest.mark.asyncio
async def test_t3b_single_mcp_tool_routes_to_one_typed_owner_and_writes_only_json(
    tmp_path,
    monkeypatch,
):
    api = _load_api()
    t3 = _t3_oracle_module()
    t3_api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    calls = []
    original = api.app_ia_knowledge.knowledge_api

    def tracked(request):
        calls.append(request["operation"])
        return original(request)

    monkeypatch.setattr(api.app_ia_knowledge, "knowledge_api", tracked)
    app = _asgi_app(api)
    monkeypatch.setattr(api.app_mcp_stdio, "_api", _asgi_transport_api(app))
    root = tmp_path / "knowledge-main"
    with t3._knowledge_mode(t3_api, tmp_path, context):
        request = t3._request("new_topic", context)
        raw = await api.app_mcp_stdio.knowledge(
            operation="promote",
            detail="summary",
            payload={
                "request": request,
                "expected_head": t3_api.knowledge.knowledge_head(),
            },
        )
    result = json.loads(raw)
    assert result["operation"] == "promote"
    assert result["outcome"] == "created"
    assert result["uri"].startswith("orch://project/orchestra/knowledge/")
    assert calls == ["promote"]
    _assert_agent_only_canonical(root)
    assert not list(root.rglob("*.md"))
    assert not hasattr(api.app_mcp_stdio, "promote_knowledge")
    assert not hasattr(api.app_mcp_stdio, "query_knowledge")


def test_t3b_progressive_summary_record_evidence_payloads_use_same_api(tmp_path):
    api = _load_api()
    t3 = _t3_oracle_module()
    t3_api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    with t3._knowledge_mode(t3_api, tmp_path, context):
        promote = _tool_request(
            "promote",
            "summary",
            payload={
                "request": t3._request("new_topic", context),
                "expected_head": t3_api.knowledge.knowledge_head(),
            },
        )
        api.app_ia_knowledge.knowledge_api(promote)
        payloads = [
            api.app_ia_knowledge.knowledge_api(copy.deepcopy(request))
            for request in _fixture()["progressive_queries"]
        ]
    summary, record, evidence = payloads
    assert summary["detail"] == "summary"
    assert set(summary["items"][0]) == {
        "uri", "record_type", "status", "claim", "canonical_head", "evidence_count"
    }
    assert record["detail"] == "record" and record["items"][0]["provenance"]
    assert evidence["detail"] == "evidence" and evidence["items"][0]["evidence"]
    sizes = [len(json.dumps(payload, sort_keys=True)) for payload in payloads]
    assert sizes[0] < sizes[1] < sizes[2]
    assert {payload["canonical_head"] for payload in payloads} == {
        payloads[0]["canonical_head"]
    }


def test_t3b_import_evidence_is_idempotent_byte_preserving_and_json_only(tmp_path):
    api = _load_api()
    t3 = _t3_oracle_module()
    t3_api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    historical_root, before = _historical_root(tmp_path)
    request = _materialize_import_request(historical_root)
    root = tmp_path / "knowledge-main"
    with t3._knowledge_mode(t3_api, tmp_path, context):
        first = api.app_ia_knowledge.knowledge_api(request)
        second = api.app_ia_knowledge.knowledge_api(copy.deepcopy(request))
    assert first["outcome"] == "created"
    assert second["outcome"] == "noop"
    after = {
        path: hashlib.sha256((historical_root / path).read_bytes()).hexdigest()
        for path in before
    }
    assert after == before
    assert first["source_sha256"] == f"sha256:{before['docs/tasks/315/research.md']}"
    _assert_agent_only_canonical(root)
    assert len(list(root.rglob("evidence/*.json"))) == 1


def test_t3b_hidden_markdown_or_human_projection_output_is_rejected(tmp_path):
    api = _load_api()
    t3 = _t3_oracle_module()
    t3_api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    root = tmp_path / "knowledge-main"
    with t3._knowledge_mode(t3_api, tmp_path, context):
        api.app_ia_knowledge.knowledge_api(_tool_request(
            "promote",
            "record",
            payload={
                "request": t3._request("new_topic", context),
                "expected_head": t3_api.knowledge.knowledge_head(),
            },
        ))
    forbidden_extensions = set(_fixture()["forbidden_generated_extensions"])
    assert not [
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in forbidden_extensions
    ]
    _assert_agent_only_canonical(root)
    forbidden_keys = set(_fixture()["forbidden_generated_keys"])
    for path in root.rglob("*.json"):
        assert forbidden_keys.isdisjoint(_nested_keys(_json(path)))


def test_t3b_missing_canonical_never_uses_direct_file_sqlite_or_vector_fallback(
    tmp_path,
    monkeypatch,
):
    api = _load_api()
    t3 = _t3_oracle_module()
    t3_api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    historical_root, _ = _historical_root(tmp_path)
    fallback_path = historical_root / _fixture()["compound_mutants"]["direct_file_fallback"][
        "fallback_path"
    ]
    fallback_reads = []
    original_read_text = Path.read_text

    def guarded_read_text(path, *args, **kwargs):
        if path.resolve() == fallback_path.resolve():
            fallback_reads.append(str(path))
            return _fixture()["compound_mutants"]["direct_file_fallback"]["fallback_content"]
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    root = tmp_path / "knowledge-main"
    with t3._knowledge_mode(t3_api, tmp_path, context):
        api.app_ia_knowledge.knowledge_api(_tool_request(
            "promote",
            "summary",
            payload={
                "request": t3._request("current", context),
                "expected_head": t3_api.knowledge.knowledge_head(),
            },
        ))
        fact_path = next(root.rglob("facts/*/*.json"))
        fact_path.unlink()
        mutant = _tool_request(
            "query",
            "summary",
            project_id="orchestra",
            topic="repo-ops",
            mode="current",
            fallback={
                **_fixture()["compound_mutants"]["direct_file_fallback"],
                **_fixture()["compound_mutants"]["sqlite_fallback"],
                **_fixture()["compound_mutants"]["vector_fallback"],
            },
        )
        with pytest.raises(api.app_ia_knowledge.CanonicalKnowledgeUnavailableError):
            api.app_ia_knowledge.knowledge_api(mutant)
    assert fallback_reads == []


@pytest.mark.asyncio
async def test_t3b_agent_tool_rejects_direct_storage_operations(tmp_path, monkeypatch):
    api = _load_api()
    app = _asgi_app(api)
    monkeypatch.setattr(api.app_mcp_stdio, "_api", _asgi_transport_api(app))
    for operation in ("read_file", "sqlite_query", "vector_search"):
        raw = await api.app_mcp_stdio.knowledge(
            operation=operation,
            detail="summary",
            payload={"path": "docs/kb/repo-ops.md", "sql": "SELECT *", "query": "x"},
        )
        result = json.loads(raw)
        assert result["error"]["code"] == "unsupported_operation"
        rendered = json.dumps(result)
        assert "T3B_DIRECT_FILE_FALLBACK_MUST_NOT_WIN" not in rendered
        assert "T3B_SQLITE_SECOND_TRUTH_MUST_NOT_WIN" not in rendered
        assert "T3B_VECTOR_SECOND_TRUTH_MUST_NOT_WIN" not in rendered
