"""Corrected frozen RED oracle for #315 T3b.

Controls in this file are invariant before and after implementation.  The full gate also
selects every original T3 node except S11, whose valid structured new-topic behavior is
replaced here without its superseded README/topic assertions.
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
FIXTURE_PATH = HERE / "fixtures" / "t3b_agent_only_records_v2.json"
CONTRACT_PATH = HERE / "fixtures" / "t3b_agent_only_contract_v2.json"
T3_ORACLE_PATH = HERE / "test_t3_promotion_behavior.py"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture() -> dict:
    return _json(FIXTURE_PATH)


def _contract() -> dict:
    return _json(CONTRACT_PATH)


def _t3_oracle_module():
    spec = importlib.util.spec_from_file_location("t3_oracle_for_t3b_v2", T3_ORACLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_agent_api() -> SimpleNamespace:
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


def _reference_import(request: Mapping, canonical_root: Path) -> dict:
    """Harness positive control for byte-preserving, idempotent import semantics."""
    source = dict(request["source"])
    source_path = Path(source["source_root"]) / source["path"]
    observed = f"sha256:{hashlib.sha256(source_path.read_bytes()).hexdigest()}"
    assert observed == source["content_sha256"]
    index_path = canonical_root / "archive-index.json"
    index = {"schema_version": 1, "sources": []}
    if index_path.exists():
        index = _json(index_path)
    record = {
        key: source[key]
        for key in (
            "path",
            "class",
            "project_id",
            "stable_id",
            "canonical_uri",
            "git_commit",
            "anchor",
            "content_sha256",
        )
    }
    outcome = "noop" if record in index["sources"] else "created"
    if outcome == "created":
        index["sources"].append(record)
        index["sources"].sort(key=lambda item: item["path"])
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {"outcome": outcome, "source_sha256": observed}


def _nested_keys(value) -> set[str]:
    if isinstance(value, Mapping):
        return set(value) | {
            key for child in value.values() for key in _nested_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _nested_keys(child)}
    return set()


def _assert_agent_only_canonical(root: Path) -> None:
    files = [path for path in root.rglob("*") if path.is_file()]
    assert files, "canonical structured store is empty"
    assert {path.suffix.lower() for path in files} <= {".json"}
    forbidden_keys = set(_fixture()["forbidden_generated_keys"])
    for path in files:
        assert forbidden_keys.isdisjoint(_nested_keys(_json(path)))


def _asgi_app(api):
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(api.app_routes_knowledge.router)
    return app


def _asgi_transport_api(app, calls: list[str] | None = None):
    import httpx

    async def call(method, path, **kwargs):
        if calls is not None:
            calls.append(f"{method.upper()} {path}")
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


def test_t3b_v2_control_fixture_counts_hashes_and_detectors_are_invariant(tmp_path):
    fixture = _fixture()
    contract = _contract()
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == contract["fixture_sha256"]
    assert fixture["fixture_version"] == contract["contract_version"] == 2
    assert fixture["selected_t3_scenarios"] == [
        "S01", "S02", "S03", "S04", "S05", "S06",
        "S07", "S08", "S09", "S10", "S12",
    ]
    assert fixture["excluded_t3_scenarios"] == ["S11"]
    assert contract["original_t3_selection"]["expected_selected_nodes"] == 17
    assert contract["expected_controls"] == 3
    assert contract["expected_behavior_nodes"] == 6
    assert contract["expected_full_selected_nodes"] == 26
    assert contract["permanently_superseded"]["worker_commit"].startswith("21e1b071")
    assert Path(contract["permanently_superseded"]["evidence_only"]).is_file()

    mutant_root = tmp_path / "detector-control"
    mutant_path = mutant_root / fixture["compound_mutants"]["hidden_markdown_regeneration"][
        "nested_output"
    ]
    mutant_path.parent.mkdir(parents=True, exist_ok=True)
    mutant_path.write_text("must be detected", encoding="utf-8")
    with pytest.raises(AssertionError):
        _assert_agent_only_canonical(mutant_root)

    alternate_root = tmp_path / "alternate-control"
    alternate_root.mkdir(parents=True)
    (alternate_root / "registry.json").write_text(
        json.dumps({"future_projection_metadata": {"backend": "alternate"}}),
        encoding="utf-8",
    )
    _assert_agent_only_canonical(alternate_root)


def test_t3b_v2_control_reference_import_preserves_historical_paths_and_bytes(tmp_path):
    historical_root, before = _historical_root(tmp_path)
    before_paths = sorted(
        str(path.relative_to(historical_root))
        for path in historical_root.rglob("*")
        if path.is_file()
    )
    assert len(before) == len(before_paths) == 4
    request = _materialize_import_request(historical_root)
    canonical_root = tmp_path / "reference-canonical"
    first = _reference_import(request, canonical_root)
    second = _reference_import(copy.deepcopy(request), canonical_root)
    after_paths = sorted(
        str(path.relative_to(historical_root))
        for path in historical_root.rglob("*")
        if path.is_file()
    )
    after = {
        path: hashlib.sha256((historical_root / path).read_bytes()).hexdigest()
        for path in before
    }
    assert first["outcome"] == "created"
    assert second["outcome"] == "noop"
    assert after_paths == before_paths
    assert after == before
    assert [path.name for path in canonical_root.rglob("*") if path.is_file()] == [
        "archive-index.json"
    ]


def test_t3b_v2_control_real_t1_t2_t3_structured_behavior_is_preserved(tmp_path):
    t3 = _t3_oracle_module()
    api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    root = tmp_path / "knowledge-main"
    with t3._knowledge_mode(api, tmp_path, context):
        result = t3._promote(api, t3._request("current", context))
        query = t3._query(api, topic="repo-ops", fact_key="worker-wip-scope")
    assert result["outcome"] == "created"
    assert query["count"] == 1
    t3._assert_fact_is_t1_compatible(query["facts"][0])
    assert len(t3._fact_files(root)) == 1
    assert len(t3._event_files(root)) == 1


def test_t3b_v2_new_topic_is_atomic_structured_json_without_generated_human_output(
    tmp_path,
):
    """Replacement for excluded original T3 S11."""
    t3 = _t3_oracle_module()
    api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    root = tmp_path / "knowledge-main"
    with t3._knowledge_mode(api, tmp_path, context):
        result = t3._promote(api, t3._request("new_topic", context))
        query = t3._query(api, topic="runtime-guards")
    assert result["outcome"] == "created"
    assert result["topic_registered"] is True
    registry = _json(root / "registry.json")
    assert [
        topic["topic_slug"]
        for topic in registry["topics"]
        if topic["topic_slug"] == "runtime-safety"
    ] == ["runtime-safety"]
    assert query["count"] == 1
    t3._assert_fact_is_t1_compatible(query["facts"][0])
    assert len(t3._fact_files(root)) == 1
    assert len(t3._event_files(root)) == 1
    _assert_agent_only_canonical(root)


@pytest.mark.asyncio
async def test_t3b_v2_mcp_http_owner_service_chain_is_reachable_and_not_bypassable(
    tmp_path,
    monkeypatch,
):
    api = _load_agent_api()
    t3 = _t3_oracle_module()
    t3_api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    owner_calls = []
    service_calls = []
    transport_calls = []
    original_owner = api.app_ia_knowledge.knowledge_api
    original_promote = api.app_ia_knowledge.KnowledgeService.promote

    def tracked_owner(request):
        owner_calls.append(request["operation"])
        return original_owner(request)

    def tracked_promote(self, *args, **kwargs):
        service_calls.append("promote")
        return original_promote(self, *args, **kwargs)

    monkeypatch.setattr(api.app_ia_knowledge, "knowledge_api", tracked_owner)
    if hasattr(api.app_routes_knowledge, "knowledge_api"):
        monkeypatch.setattr(api.app_routes_knowledge, "knowledge_api", tracked_owner)
    monkeypatch.setattr(api.app_ia_knowledge.KnowledgeService, "promote", tracked_promote)
    app = _asgi_app(api)
    monkeypatch.setattr(
        api.app_mcp_stdio,
        "_api",
        _asgi_transport_api(app, transport_calls),
    )
    root = tmp_path / "knowledge-main"
    with t3._knowledge_mode(t3_api, tmp_path, context):
        raw = await api.app_mcp_stdio.knowledge(
            operation="promote",
            detail="summary",
            payload={
                "request": t3._request("new_topic", context),
                "expected_head": t3_api.knowledge.knowledge_head(),
                "wiring_sentinel": _fixture()["compound_mutants"][
                    "production_wiring_bypass"
                ]["sentinel"],
            },
        )
    result = json.loads(raw)
    assert result["operation"] == "promote"
    assert result["outcome"] == "created"
    assert result["uri"].startswith("orch://project/orchestra/knowledge/")
    assert transport_calls == ["POST /api/knowledge"]
    assert owner_calls == ["promote"]
    assert service_calls == ["promote"]
    _assert_agent_only_canonical(root)
    assert not hasattr(api.app_mcp_stdio, "promote_knowledge")
    assert not hasattr(api.app_mcp_stdio, "query_knowledge")


def test_t3b_v2_progressive_payloads_use_one_agent_api_and_one_head(tmp_path):
    api = _load_agent_api()
    t3 = _t3_oracle_module()
    t3_api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    with t3._knowledge_mode(t3_api, tmp_path, context):
        api.app_ia_knowledge.knowledge_api(_tool_request(
            "promote",
            "summary",
            payload={
                "request": t3._request("new_topic", context),
                "expected_head": t3_api.knowledge.knowledge_head(),
            },
        ))
        payloads = [
            api.app_ia_knowledge.knowledge_api(copy.deepcopy(request))
            for request in _fixture()["progressive_queries"]
        ]
    summary, record, evidence = payloads
    assert {
        "uri",
        "record_type",
        "status",
        "claim",
        "canonical_head",
        "evidence_count",
    } <= set(summary["items"][0])
    assert record["items"][0]["provenance"]
    assert evidence["items"][0]["evidence"]
    sizes = [len(json.dumps(payload, sort_keys=True)) for payload in payloads]
    assert sizes[0] < sizes[1] < sizes[2]
    assert len({payload["canonical_head"] for payload in payloads}) == 1


def test_t3b_v2_product_import_is_idempotent_and_preserves_historical_bytes(tmp_path):
    api = _load_agent_api()
    t3 = _t3_oracle_module()
    t3_api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    historical_root, before = _historical_root(tmp_path)
    before_paths = sorted(before)
    request = _materialize_import_request(historical_root)
    root = tmp_path / "knowledge-main"
    with t3._knowledge_mode(t3_api, tmp_path, context):
        first = api.app_ia_knowledge.knowledge_api(request)
        second = api.app_ia_knowledge.knowledge_api(copy.deepcopy(request))
    after_paths = sorted(
        str(path.relative_to(historical_root))
        for path in historical_root.rglob("*")
        if path.is_file()
    )
    after = {
        path: hashlib.sha256((historical_root / path).read_bytes()).hexdigest()
        for path in before
    }
    assert first["outcome"] == "created"
    assert second["outcome"] == "noop"
    assert after_paths == before_paths
    assert after == before
    assert first["source_sha256"] == f"sha256:{before['docs/tasks/315/research.md']}"
    _assert_agent_only_canonical(root)
    assert len(list(root.rglob("evidence/*.json"))) == 1


def test_t3b_v2_hidden_generated_output_and_metadata_are_rejected(tmp_path):
    api = _load_agent_api()
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
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in forbidden_extensions
    ]
    _assert_agent_only_canonical(root)


@pytest.mark.asyncio
async def test_t3b_v2_missing_canonical_fails_closed_without_direct_storage_fallback(
    tmp_path,
    monkeypatch,
):
    api = _load_agent_api()
    t3 = _t3_oracle_module()
    t3_api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    historical_root, _ = _historical_root(tmp_path)
    mutant = _fixture()["compound_mutants"]["direct_storage_fallback"]
    fallback_path = historical_root / mutant["fallback_path"]
    fallback_reads = []
    original_read_text = Path.read_text

    def guarded_read_text(path, *args, **kwargs):
        if path.resolve() == fallback_path.resolve():
            fallback_reads.append(str(path))
            return mutant["fallback_content"]
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
        next(root.rglob("facts/*/*.json")).unlink()
        request = _tool_request(
            "query",
            "summary",
            project_id="orchestra",
            topic="repo-ops",
            mode="current",
            fallback={
                "fallback_path": mutant["fallback_path"],
                "fallback_content": mutant["fallback_content"],
                "payload_json": mutant["payload_json"],
                "hits": mutant["hits"],
            },
        )
        with pytest.raises(api.app_ia_knowledge.CanonicalKnowledgeUnavailableError):
            api.app_ia_knowledge.knowledge_api(request)
    assert fallback_reads == []

    app = _asgi_app(api)
    monkeypatch.setattr(api.app_mcp_stdio, "_api", _asgi_transport_api(app))
    for operation in ("read_file", "sqlite_query", "vector_search"):
        raw = await api.app_mcp_stdio.knowledge(
            operation=operation,
            detail="summary",
            payload={"path": mutant["fallback_path"], "sql": "SELECT *", "query": "x"},
        )
        result = json.loads(raw)
        assert result["error"]["code"] == "unsupported_operation"
        rendered = json.dumps(result)
        assert mutant["fallback_content"] not in rendered
        assert mutant["payload_json"]["claim"] not in rendered
        assert mutant["hits"][0]["content"] not in rendered
