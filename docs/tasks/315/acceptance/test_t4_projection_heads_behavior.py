"""Frozen behavior-level RED oracle for #315 T4 projection heads and fallback.

All T4 reads enter through the real agent/HTTP or legacy memory-route consumers.  Direct
projection primitives are used only as mutation boundaries after a production-shaped query
has populated the backend.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest


HERE = Path(__file__).resolve().parent
FIXTURE_PATH = HERE / "fixtures" / "t4_projection_records.json"
CONTRACT_PATH = HERE / "fixtures" / "t4_projection_contract.json"
T3_ORACLE_PATH = HERE / "test_t3_promotion_behavior.py"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture() -> dict:
    return _json(FIXTURE_PATH)


def _contract() -> dict:
    return _json(CONTRACT_PATH)


def _t3_oracle_module():
    spec = importlib.util.spec_from_file_location("t3_oracle_for_t4", T3_ORACLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_t4_api() -> SimpleNamespace:
    modules = {}
    for module_name, surface in _contract()["public_api"].items():
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            pytest.fail(f"#315 T4 missing behavior: cannot import {module_name}: {exc}")
        for name in surface.get("callables", []):
            assert callable(getattr(module, name, None)), (
                f"#315 T4 missing behavior: {module_name}.{name} is not callable"
            )
        for name in surface.get("classes", []):
            cls = getattr(module, name, None)
            assert isinstance(cls, type), (
                f"#315 T4 missing behavior: {module_name}.{name} is not a class"
            )
            for method in surface.get("methods", []):
                assert callable(getattr(cls, method, None)), (
                    f"#315 T4 missing behavior: {name}.{method} is not callable"
                )
        for name in surface.get("exceptions", []):
            error = getattr(module, name, None)
            assert isinstance(error, type) and issubclass(error, Exception), (
                f"#315 T4 missing behavior: {module_name}.{name} is not an exception"
            )
        for name in surface.get("attributes", []):
            assert getattr(module, name, None) is not None, (
                f"#315 T4 missing behavior: {module_name}.{name} is absent"
            )
        modules[module_name.replace(".", "_")] = module
    return SimpleNamespace(**modules)


def _write_legacy_corpus(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    root = tmp_path / "legacy-root"
    hashes = {}
    for record in _fixture()["legacy_corpus"]["files"]:
        path = root / record["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record["content"], encoding="utf-8")
        hashes[record["path"]] = hashlib.sha256(path.read_bytes()).hexdigest()
    log_db = tmp_path / "legacy-logs.sqlite3"
    with sqlite3.connect(log_db) as connection:
        connection.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT NOT NULL, scope TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE logs (id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, "
            "type TEXT NOT NULL, content TEXT NOT NULL)"
        )
        for record in _fixture()["legacy_corpus"]["logs"]:
            connection.execute(
                "INSERT INTO sessions(id, name, scope) VALUES (?, ?, ?)",
                (record["session_id"], record["session_name"], _fixture()["project_id"]),
            )
            connection.execute(
                "INSERT INTO logs(id, session_id, type, content) VALUES (?, ?, ?, ?)",
                (record["id"], record["session_id"], record["type"], record["content"]),
            )
    return root, log_db, hashes


def _current_request(t3, context: Mapping, *, changed: bool = False) -> dict:
    name = "supersede_one" if changed else "current"
    request = t3._request(name, context)
    values = _fixture()["canonical_changes"]["changed" if changed else "initial"]
    request["fact"]["claim"] = values["fact_claim"]
    return request


def _set_task_version(context: Mapping, *, changed: bool = False) -> dict:
    values = _fixture()["canonical_changes"]["changed" if changed else "initial"]
    return context["task_store"].task_update(
        "315",
        project="orchestra",
        title=values["task_title"],
        expected_head=context["task_store"].canonical_head,
    )


class _VectorDouble:
    def __init__(self, *, indexed_head: str | None, hits: list[dict] | None = None, error=None):
        self.indexed_head = indexed_head
        self.hits = copy.deepcopy(hits or [])
        self.error = error
        self.calls = []

    def __call__(self, request: Mapping) -> Mapping:
        self.calls.append(copy.deepcopy(dict(request)))
        if self.error is not None:
            raise self.error
        return {
            "indexed_head": self.indexed_head,
            "hits": copy.deepcopy(self.hits),
        }


class _AlternateBackend:
    """Valid alternate: same protocol, reordered items, additive safe metadata."""

    def __init__(self, delegate, metadata: Mapping):
        self.delegate = delegate
        self.metadata = copy.deepcopy(dict(metadata))

    def replace_current(self, *args, **kwargs):
        return self.delegate.replace_current(*args, **kwargs)

    def search_current(self, *args, **kwargs):
        result = copy.deepcopy(dict(self.delegate.search_current(*args, **kwargs)))
        result["items"] = list(reversed(result["items"]))
        result["backend_metadata"] = copy.deepcopy(self.metadata)
        return result


def _projection_mode(api, tmp_path: Path, context: Mapping, service, vector_query):
    legacy_root, legacy_log_db, _ = _write_legacy_corpus(tmp_path)
    return api.app_ia_projections.projection_mode(
        projection_path=tmp_path / "ia-current.sqlite3",
        task_store=context["task_store"],
        knowledge_service=service,
        legacy_root=legacy_root,
        legacy_log_db=legacy_log_db,
        vector_query=vector_query,
    )


def _typed_query(*, fallback: Mapping | None = None) -> dict:
    payload = {
        "project_id": _fixture()["project_id"],
        "text": _fixture()["queries"]["current"],
        "record_types": ["task.state", "knowledge.fact"],
        "limit": 10,
    }
    if fallback is not None:
        payload["fallback"] = copy.deepcopy(dict(fallback))
    return {"operation": "query", "detail": "record", "payload": payload}


def _assert_projection_response(response: Mapping, *, allow_extra: bool = True) -> None:
    contract = _contract()
    assert set(contract["response_required"]) <= set(response)
    assert isinstance(response["items"], list) and response["items"]
    assert response["count"] == len(response["items"])
    for head in ("canonical_head", "projection_head"):
        assert isinstance(response[head], str) and response[head].startswith("sha256:")
    assert response["indexed_head"] is None or (
        isinstance(response["indexed_head"], str)
        and response["indexed_head"].startswith("sha256:")
    )
    for item in response["items"]:
        assert set(contract["item_required"]) <= set(item)
        assert item["source"] in contract["allowed_sources"]
    for debt in response["debt"]:
        assert set(contract["debt_required"]) <= set(debt)
    if not allow_extra:
        assert set(response) == set(contract["response_required"])


def _assert_current_values(response: Mapping, *, changed: bool) -> None:
    values = _fixture()["canonical_changes"]["changed" if changed else "initial"]
    tasks = [item for item in response["items"] if item["record_type"] == "task.state"]
    facts = [item for item in response["items"] if item["record_type"] == "knowledge.fact"]
    assert len(tasks) == len(facts) == 1
    assert tasks[0]["title"] == values["task_title"]
    assert facts[0]["claim"] == values["fact_claim"]


def _assert_no_mutant_value(value: Mapping) -> None:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    mutants = _fixture()["compound_mutants"]
    forbidden = [
        mutants["forged_equal_head_stale_payload"]["task_title"],
        mutants["forged_equal_head_stale_payload"]["fact_claim"],
        mutants["deleted_canonical_with_stale_sources"]["fallback_content"],
        *[
            item.get("title") or item.get("claim")
            for item in mutants["deleted_canonical_with_stale_sources"]["sqlite_items"]
        ],
        mutants["deleted_canonical_with_stale_sources"]["vector_hits"][0]["content"],
        mutants["vector_fallback_hides_canonical_failure"]["fallback_hit"],
        mutants["route_query_wiring_bypass"]["legacy_rag_result"],
    ]
    assert all(item not in rendered for item in forbidden)


def _asgi_app(*routers):
    from fastapi import FastAPI

    app = FastAPI()
    for router in routers:
        app.include_router(router)
    return app


def _asgi_transport_api(app, calls: list[str] | None = None):
    import httpx

    async def call(method, path, **kwargs):
        if calls is not None:
            calls.append(f"{method.upper()} {path}")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t4.test") as client:
            response = await client.request(method, path, json=kwargs.get("json"))
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": response.text}
        if response.status_code >= 400:
            return {"error": payload.get("error", payload), "status": response.status_code}
        return payload

    return call


async def _mcp_query(api, monkeypatch, request: Mapping, calls: list[str] | None = None) -> dict:
    app = _asgi_app(api.app_routes_knowledge.router)
    monkeypatch.setattr(api.app_mcp_stdio, "_api", _asgi_transport_api(app, calls))
    raw = await api.app_mcp_stdio.knowledge(
        operation=request["operation"],
        detail=request["detail"],
        payload=request["payload"],
    )
    return json.loads(raw)


def test_t4_control_fixture_hash_denominators_and_t1_t3b_compatibility_are_frozen():
    contract = _contract()
    fixture = _fixture()
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == contract["fixture_sha256"]
    for relative, expected in contract["compatibility_sha256"].items():
        assert hashlib.sha256(Path(relative).read_bytes()).hexdigest() == expected
    assert fixture["expected_denominators"] == {
        "canonical_current_records": 2,
        "legacy_sources": 2,
        "controls": 4,
        "behavior_nodes": 7,
        "compound_mutants": 5,
    }
    assert len(fixture["legacy_corpus"]["files"]) == 1
    assert len(fixture["legacy_corpus"]["logs"]) == 1
    assert len(fixture["compound_mutants"]) == 5


@pytest.mark.asyncio
async def test_t4_control_existing_agent_query_reaches_t3b_owner(tmp_path, monkeypatch):
    t3 = _t3_oracle_module()
    api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    from app.ia import knowledge
    from app import mcp_stdio
    from app.routes import knowledge as knowledge_route

    calls = []
    original = knowledge.knowledge_api

    def tracked(request):
        calls.append(request["operation"])
        return original(request)

    monkeypatch.setattr(knowledge, "knowledge_api", tracked)
    app = _asgi_app(knowledge_route.router)
    monkeypatch.setattr(mcp_stdio, "_api", _asgi_transport_api(app))
    with t3._knowledge_mode(api, tmp_path, context):
        t3._promote(api, _current_request(t3, context))
        raw = await mcp_stdio.knowledge(
            operation="query",
            detail="record",
            payload={"project_id": "orchestra", "topic": "repo-ops", "mode": "current"},
        )
    response = json.loads(raw)
    assert calls == ["query"]
    assert response["count"] == 1
    assert response["items"][0]["claim"] == _fixture()["canonical_changes"]["initial"][
        "fact_claim"
    ]


def test_t4_control_real_task_fact_and_legacy_fixture_are_nonempty(tmp_path):
    t3 = _t3_oracle_module()
    api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    _set_task_version(context)
    with t3._knowledge_mode(api, tmp_path, context):
        t3._promote(api, _current_request(t3, context))
        task = context["task_store"].task_get("315", project="orchestra")
        fact = t3._query(api, topic="repo-ops", fact_key="worker-wip-scope")["facts"][0]
    legacy_root, legacy_log_db, before = _write_legacy_corpus(tmp_path)
    with sqlite3.connect(legacy_log_db) as connection:
        log_count = connection.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
    assert task["title"] == _fixture()["canonical_changes"]["initial"]["task_title"]
    assert fact["claim"] == _fixture()["canonical_changes"]["initial"]["fact_claim"]
    assert len(before) == log_count == 1
    assert all(
        hashlib.sha256((legacy_root / path).read_bytes()).hexdigest() == digest
        for path, digest in before.items()
    )


def test_t4_control_valid_alternate_and_compound_mutant_detectors_are_material():
    head = "sha256:" + "4" * 64
    task = {
        "record_type": "task.state",
        "stable_id": "41000000-0000-4000-8000-000000000001",
        "uri": "orch://project/orchestra/tasks/41000000-0000-4000-8000-000000000001/state",
        "project_id": "orchestra",
        "status": "in_progress",
        "canonical_head": head,
        "projection_head": head,
        "indexed_head": None,
        "source": "projection",
        "title": _fixture()["canonical_changes"]["initial"]["task_title"],
        "metadata": _fixture()["valid_alternate"]["metadata"],
    }
    fact = {
        **task,
        "record_type": "knowledge.fact",
        "stable_id": "42000000-0000-4000-8000-000000000001",
        "uri": "orch://project/orchestra/knowledge/topics/repo-ops/facts/t4/42000000-0000-4000-8000-000000000001",
        "claim": _fixture()["canonical_changes"]["initial"]["fact_claim"],
    }
    alternate = {
        "operation": "query",
        "detail": "record",
        "project_id": "orchestra",
        "items": [fact, task],
        "count": 2,
        "canonical_head": head,
        "projection_head": head,
        "indexed_head": None,
        "debt": [],
        "backend_metadata": _fixture()["valid_alternate"],
    }
    _assert_projection_response(alternate)
    _assert_current_values(alternate, changed=False)
    forged = copy.deepcopy(alternate)
    forged["items"][0]["claim"] = _fixture()["compound_mutants"][
        "forged_equal_head_stale_payload"
    ]["fact_claim"]
    with pytest.raises(AssertionError):
        _assert_current_values(forged, changed=False)
    assert _fixture()["compound_mutants"]["deleted_canonical_with_stale_sources"][
        "vector_hits"
    ]


@pytest.mark.asyncio
async def test_t4_query_synchronously_projects_current_task_fact_and_exposes_index_lag(
    tmp_path,
    monkeypatch,
):
    api = _load_t4_api()
    t3 = _t3_oracle_module()
    t3_api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    _set_task_version(context)
    vector = _VectorDouble(indexed_head="sha256:" + "1" * 64)
    with t3._knowledge_mode(t3_api, tmp_path, context) as service:
        t3._promote(t3_api, _current_request(t3, context))
        with _projection_mode(api, tmp_path, context, service, vector):
            transport_calls = []
            response = await _mcp_query(api, monkeypatch, _typed_query(), transport_calls)
    _assert_projection_response(response)
    _assert_current_values(response, changed=False)
    assert response["canonical_head"] == response["projection_head"]
    assert response["indexed_head"] != response["canonical_head"]
    assert {debt["layer"] for debt in response["debt"]} >= {"vector", "legacy-log"}
    assert {item["source"] for item in response["items"]} == {"projection"}
    assert transport_calls == ["POST /api/knowledge"]
    assert (tmp_path / "ia-current.sqlite3").is_file()
    assert not list((tmp_path / "knowledge-main").rglob("*.md"))

    alternate_root, alternate_log_db, _ = _write_legacy_corpus(tmp_path / "alternate")
    delegate = api.app_ia_projections.SQLiteProjectionBackend(
        path=tmp_path / "alternate" / "ia-current.sqlite3"
    )
    alternate = _AlternateBackend(delegate, _fixture()["valid_alternate"]["metadata"])
    with t3._knowledge_mode(t3_api, tmp_path / "alternate-mode", context) as service:
        t3._promote(t3_api, _current_request(t3, context))
        with api.app_ia_projections.projection_mode(
            projection_path=tmp_path / "alternate" / "ignored.sqlite3",
            task_store=context["task_store"],
            knowledge_service=service,
            legacy_root=alternate_root,
            legacy_log_db=alternate_log_db,
            vector_query=vector,
            backend=alternate,
        ):
            alternate_response = api.app_ia_knowledge.knowledge_api(_typed_query())
    _assert_projection_response(alternate_response)
    _assert_current_values(alternate_response, changed=False)


def test_t4_stale_sqlite_fts_and_vector_cannot_hide_changed_canonical_records(tmp_path):
    api = _load_t4_api()
    t3 = _t3_oracle_module()
    t3_api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    _set_task_version(context)
    stale = _fixture()["compound_mutants"]["deleted_canonical_with_stale_sources"]
    vector = _VectorDouble(
        indexed_head="sha256:" + "2" * 64,
        hits=stale["vector_hits"],
    )
    with t3._knowledge_mode(t3_api, tmp_path, context) as service:
        t3._promote(t3_api, _current_request(t3, context))
        with _projection_mode(api, tmp_path, context, service, vector):
            api.app_ia_knowledge.knowledge_api(_typed_query())
            _set_task_version(context, changed=True)
            t3._promote(t3_api, _current_request(t3, context, changed=True))
            response = api.app_ia_knowledge.knowledge_api(_typed_query())
    _assert_projection_response(response)
    _assert_current_values(response, changed=True)
    _assert_no_mutant_value(response)
    assert response["canonical_head"] == response["projection_head"]
    assert response["indexed_head"] != response["canonical_head"]
    assert "vector" in {debt["layer"] for debt in response["debt"]}


def test_t4_forged_equal_head_with_stale_payload_falls_back_to_canonical(
    tmp_path,
    monkeypatch,
):
    api = _load_t4_api()
    t3 = _t3_oracle_module()
    t3_api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    _set_task_version(context)
    vector = _VectorDouble(indexed_head=None)
    mutant = _fixture()["compound_mutants"]["forged_equal_head_stale_payload"]
    with t3._knowledge_mode(t3_api, tmp_path, context) as service:
        t3._promote(t3_api, _current_request(t3, context))
        with _projection_mode(api, tmp_path, context, service, vector):
            api.app_ia_knowledge.knowledge_api(_typed_query())
            original = api.app_ia_projections.SQLiteProjectionBackend.search_current

            def forged(self, *args, **kwargs):
                result = copy.deepcopy(dict(original(self, *args, **kwargs)))
                for item in result["items"]:
                    if item["record_type"] == "task.state":
                        item["title"] = mutant["task_title"]
                    elif item["record_type"] == "knowledge.fact":
                        item["claim"] = mutant["fact_claim"]
                return result

            monkeypatch.setattr(
                api.app_ia_projections.SQLiteProjectionBackend,
                "search_current",
                forged,
            )
            response = api.app_ia_knowledge.knowledge_api(_typed_query())
    _assert_projection_response(response)
    _assert_current_values(response, changed=False)
    _assert_no_mutant_value(response)
    assert response["canonical_head"] == response["projection_head"]
    assert {item["source"] for item in response["items"]} == {"canonical-fallback"}
    assert "content_mismatch" in {debt["reason"] for debt in response["debt"]}


def test_t4_vector_failure_never_erases_current_canonical_results(tmp_path):
    api = _load_t4_api()
    t3 = _t3_oracle_module()
    t3_api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    _set_task_version(context)
    mutant = _fixture()["compound_mutants"]["vector_fallback_hides_canonical_failure"]
    vector = _VectorDouble(indexed_head=None, error=RuntimeError(mutant["message"]))
    with t3._knowledge_mode(t3_api, tmp_path, context) as service:
        t3._promote(t3_api, _current_request(t3, context))
        with _projection_mode(api, tmp_path, context, service, vector):
            response = api.app_ia_knowledge.knowledge_api(_typed_query(fallback={
                "vector_hits": [{"content": mutant["fallback_hit"], "score": 1.0}],
            }))
    _assert_projection_response(response)
    _assert_current_values(response, changed=False)
    _assert_no_mutant_value(response)
    assert response["count"] == 2
    assert response["indexed_head"] is None
    assert "index_failure" in {debt["reason"] for debt in response["debt"]}


def test_t4_projection_write_failure_after_canonical_commit_returns_current_with_debt(
    tmp_path,
    monkeypatch,
):
    api = _load_t4_api()
    t3 = _t3_oracle_module()
    t3_api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    _set_task_version(context)
    vector = _VectorDouble(indexed_head=None)
    failure = _fixture()["compound_mutants"]["projection_write_failure_after_commit"][
        "message"
    ]
    with t3._knowledge_mode(t3_api, tmp_path, context) as service:
        t3._promote(t3_api, _current_request(t3, context))
        with _projection_mode(api, tmp_path, context, service, vector):
            initial = api.app_ia_knowledge.knowledge_api(_typed_query())
            _set_task_version(context, changed=True)
            t3._promote(t3_api, _current_request(t3, context, changed=True))
            calls = []

            def fail_write(self, *args, **kwargs):
                calls.append("replace_current")
                raise OSError(failure)

            monkeypatch.setattr(
                api.app_ia_projections.SQLiteProjectionBackend,
                "replace_current",
                fail_write,
            )
            response = api.app_ia_knowledge.knowledge_api(_typed_query())
    _assert_projection_response(response)
    _assert_current_values(response, changed=True)
    assert calls == ["replace_current"]
    assert response["canonical_head"] != response["projection_head"]
    assert response["projection_head"] == initial["projection_head"]
    assert {item["source"] for item in response["items"]} == {"canonical-fallback"}
    assert "projection_write_failed" in {debt["reason"] for debt in response["debt"]}


@pytest.mark.asyncio
async def test_t4_missing_canonical_fails_closed_over_stale_sqlite_vector_and_file(
    tmp_path,
    monkeypatch,
):
    api = _load_t4_api()
    t3 = _t3_oracle_module()
    t3_api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    _set_task_version(context)
    mutant = _fixture()["compound_mutants"]["deleted_canonical_with_stale_sources"]
    vector = _VectorDouble(indexed_head="sha256:" + "3" * 64, hits=mutant["vector_hits"])
    fallback_path = tmp_path / "legacy-root" / mutant["fallback_path"]
    reads = []
    original_read_text = Path.read_text

    def guarded_read_text(path, *args, **kwargs):
        if path.resolve() == fallback_path.resolve():
            reads.append(str(path))
            return mutant["fallback_content"]
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    with t3._knowledge_mode(t3_api, tmp_path, context) as service:
        t3._promote(t3_api, _current_request(t3, context))
        with _projection_mode(api, tmp_path, context, service, vector):
            api.app_ia_knowledge.knowledge_api(_typed_query())
            task_path = next(
                path
                for path in (tmp_path / "task-canonical").rglob("state.json")
                if context["task_101"] in str(path)
            )
            fact_path = next((tmp_path / "knowledge-main").rglob("facts/*/*.json"))
            task_path.unlink()
            fact_path.unlink()
            response = await _mcp_query(api, monkeypatch, _typed_query(fallback={
                "path": mutant["fallback_path"],
                "content": mutant["fallback_content"],
                "sqlite_items": mutant["sqlite_items"],
                "vector_hits": mutant["vector_hits"],
            }))
    assert response["status"] == 503
    assert response["error"]["code"] == "canonical_unavailable"
    assert reads == []
    _assert_no_mutant_value(response)


@pytest.mark.asyncio
async def test_t4_legacy_rebuild_and_memory_route_use_shared_projection_without_file_fallback(
    tmp_path,
    monkeypatch,
):
    api = _load_t4_api()
    t3 = _t3_oracle_module()
    t3_api = t3._load_api()
    context = t3._materialization_context(tmp_path)
    legacy_root, legacy_log_db, before = _write_legacy_corpus(tmp_path)
    source_path = legacy_root / next(iter(before))
    reads = []
    vector = _VectorDouble(indexed_head=None)
    owner_calls = []
    bypass = _fixture()["compound_mutants"]["route_query_wiring_bypass"]

    async def legacy_search(*args, **kwargs):
        raise AssertionError(bypass["legacy_rag_result"])

    def legacy_schedule(*args, **kwargs):
        raise AssertionError(bypass["legacy_rag_result"])

    monkeypatch.setattr(api.app_routes_memory.rag_service, "is_enabled", lambda: True)
    monkeypatch.setattr(api.app_routes_memory.rag_service, "search", legacy_search)
    monkeypatch.setattr(api.app_routes_memory.rag_service, "schedule_backfill", legacy_schedule)
    original_rebuild = api.app_ia_projections.rebuild_legacy
    original_query = api.app_ia_projections.query_current

    def tracked_rebuild(*args, **kwargs):
        owner_calls.append("rebuild")
        return original_rebuild(*args, **kwargs)

    def tracked_query(*args, **kwargs):
        owner_calls.append("query")
        return original_query(*args, **kwargs)

    monkeypatch.setattr(api.app_ia_projections, "rebuild_legacy", tracked_rebuild)
    monkeypatch.setattr(api.app_ia_projections, "query_current", tracked_query)
    if hasattr(api.app_routes_memory, "rebuild_legacy"):
        monkeypatch.setattr(api.app_routes_memory, "rebuild_legacy", tracked_rebuild)
    if hasattr(api.app_routes_memory, "query_current"):
        monkeypatch.setattr(api.app_routes_memory, "query_current", tracked_query)

    with t3._knowledge_mode(t3_api, tmp_path, context) as service:
        with api.app_ia_projections.projection_mode(
            projection_path=tmp_path / "ia-current.sqlite3",
            task_store=context["task_store"],
            knowledge_service=service,
            legacy_root=legacy_root,
            legacy_log_db=legacy_log_db,
            vector_query=vector,
        ):
            app = _asgi_app(api.app_routes_memory.router)
            transport = _asgi_transport_api(app)
            rebuilt = await transport(
                "POST",
                "/api/memory/reindex",
                json={"scope": "orchestra", "session_name": None},
            )
            before_query_hashes = {
                path: hashlib.sha256((legacy_root / path).read_bytes()).hexdigest()
                for path in before
            }
            original_read_text = Path.read_text

            def guarded_read_text(path, *args, **kwargs):
                if path.resolve() == source_path.resolve():
                    reads.append(str(path))
                return original_read_text(path, *args, **kwargs)

            monkeypatch.setattr(Path, "read_text", guarded_read_text)
            legacy_log_db.unlink()
            response = await transport(
                "POST",
                "/api/memory/search",
                json={
                    "scope": "orchestra",
                    "query": _fixture()["queries"]["legacy"],
                    "limit": 10,
                    "cross_project": False,
                },
            )
    assert rebuilt["ok"] is True
    assert rebuilt["file_refs"] == rebuilt["log_refs"] == 1
    assert owner_calls == ["rebuild", "query"]
    assert reads == []
    assert before_query_hashes == before
    assert len(response["results"]) == 2
    assert {item["record_type"] for item in response["results"]} == set(
        _contract()["legacy_record_types"]
    )
    assert set(("canonical_head", "projection_head", "indexed_head", "debt")) <= set(response)
    _assert_no_mutant_value(response)
    knowledge_root = tmp_path / "knowledge-main"
    assert not list(knowledge_root.rglob("*.md"))
    assert all(path.suffix == ".json" for path in knowledge_root.rglob("*") if path.is_file())
