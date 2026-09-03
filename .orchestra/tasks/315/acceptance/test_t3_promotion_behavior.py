"""Frozen RED oracle for #315 T3 evidence-backed fact promotion.

All writes and reads enter through the module-level public seam in
``app.ia.knowledge``.  ``KnowledgeService`` is the production owner; it must
delegate evidence lookup to ``EvidenceResolver`` and idempotent/CAS event
recording to ``FactEventLog``.  The 12 frozen scenarios are defined in the
fixture and are separate from harness and wiring/compatibility tests.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest


HERE = Path(__file__).resolve().parent
FIXTURE_PATH = HERE / "fixtures" / "t3_promotion_records.json"
CONTRACT_PATH = HERE / "fixtures" / "t3_promotion_contract.json"
T2_FIXTURE_PATH = HERE / "fixtures" / "t2_task_store_records.json"
T1_FIXTURE_PATH = HERE / "fixtures" / "t1_namespace_records.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture() -> dict:
    return _json(FIXTURE_PATH)


def _contract() -> dict:
    return _json(CONTRACT_PATH)


def _load_api() -> SimpleNamespace:
    modules = {}
    for module_name, surface in _contract()["public_api"].items():
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            pytest.fail(f"#315 T3 missing behavior: cannot import {module_name}: {exc}")
        for name in surface.get("callables", []):
            assert callable(getattr(module, name, None)), (
                f"#315 T3 missing behavior: {module_name}.{name} is not callable"
            )
        for name in surface.get("classes", []):
            cls = getattr(module, name, None)
            assert isinstance(cls, type), (
                f"#315 T3 missing behavior: {module_name}.{name} is not a class"
            )
            for method in surface.get("methods", []):
                assert callable(getattr(cls, method, None)), (
                    f"#315 T3 missing behavior: {name}.{method} is not callable"
                )
        for name in surface.get("exceptions", []):
            error = getattr(module, name, None)
            assert isinstance(error, type) and issubclass(error, Exception), (
                f"#315 T3 missing behavior: {module_name}.{name} is not an exception"
            )
        modules[module_name.rsplit(".", 1)[-1]] = module
    return SimpleNamespace(**modules)


def _task_store(tmp_path: Path):
    from app.ia.task_store import TaskStore, build_migration_manifest

    snapshot = copy.deepcopy(_json(T2_FIXTURE_PATH)["snapshot"])
    manifest = build_migration_manifest(snapshot)
    store = TaskStore(
        canonical_root=tmp_path / "task-canonical",
        projection_path=tmp_path / "task-projection.sqlite3",
    )
    store.migrate(manifest)
    detail = store.task_get("315", project="orchestra")
    return store, manifest, detail


def _write_registry(tmp_path: Path, *, duplicate: bool = False) -> Path:
    key = "duplicate_topic_registry" if duplicate else "registry"
    path = tmp_path / ("duplicate-registry.json" if duplicate else "registry-input.json")
    path.write_text(
        json.dumps(_fixture()[key], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _materialization_context(tmp_path: Path) -> dict:
    store, manifest, detail = _task_store(tmp_path)
    resource = next(
        record
        for record in _json(T1_FIXTURE_PATH)["records"]
        if record["record_type"] == "resource"
    )
    return {
        "task_store": store,
        "task_101": detail["stable_id"],
        "evidence_101": detail["evidence_refs"][0],
        "resource_uri": resource["uri"],
        "manifest": manifest,
    }


def _materialize(value, context: Mapping):
    if isinstance(value, str):
        if value == "$base_provenance":
            return _materialize(_fixture()["base_provenance"], context)
        if value.startswith("$"):
            return copy.deepcopy(context[value[1:]])
        return value
    if isinstance(value, Mapping):
        return {key: _materialize(child, context) for key, child in value.items()}
    if isinstance(value, list):
        return [_materialize(child, context) for child in value]
    return copy.deepcopy(value)


def _request(name: str, context: Mapping, *, reordered: bool = False) -> dict:
    request = _materialize(_fixture()["requests"][name], context)
    if reordered:
        request["fact"] = dict(reversed(tuple(request["fact"].items())))
        request = dict(reversed(tuple(request.items())))
    return request


def _knowledge_mode(api, tmp_path: Path, context: Mapping, *, duplicate: bool = False):
    suffix = "duplicate" if duplicate else "main"
    return api.knowledge.knowledge_service_mode(
        canonical_root=tmp_path / f"knowledge-{suffix}",
        registry_path=_write_registry(tmp_path, duplicate=duplicate),
        task_store=context["task_store"],
    )


def _promote(api, request: Mapping) -> dict:
    return api.knowledge.promote_fact(
        copy.deepcopy(dict(request)),
        expected_head=api.knowledge.knowledge_head(),
    )


def _query(
    api,
    *,
    topic: str,
    mode: str = "current",
    fact_key: str = "",
    as_of: str | None = None,
    now: str | None = None,
) -> dict:
    return api.knowledge.query_facts(
        project_id="orchestra",
        topic=topic,
        mode=mode,
        fact_key=fact_key,
        as_of=as_of,
        now=now,
    )


def _assert_fact_is_t1_compatible(fact: Mapping) -> None:
    from app.ia.schema import projection_payload, validate_record

    assert validate_record(fact) == fact
    for sink in ("hot", "fts", "vector"):
        projected = projection_payload(fact, sink)
        assert projected["stable_id"] == fact["stable_id"]
        assert projected["claim"] == fact["claim"]
        assert "T3_PRIVATE_CREDENTIAL_MUST_BE_REJECTED" not in json.dumps(projected)


def _fact_files(root: Path) -> list[Path]:
    return sorted(root.rglob("facts/*/*.json"))


def _event_files(root: Path) -> list[Path]:
    return sorted(root.rglob("events/*.json"))


def _run_setup(api, context: Mapping, names: Sequence[str]) -> None:
    for name in names:
        result = _promote(api, _request(name, context))
        assert result["outcome"] in {"created", "superseded", "disputed"}


def test_t3_harness_fixture_hash_and_exact_twelve_scenarios_are_frozen():
    fixture = _fixture()
    contract = _contract()
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == contract["fixture_sha256"]
    assert hashlib.sha256(T2_FIXTURE_PATH.read_bytes()).hexdigest() == (
        contract["t2_fixture_sha256"]
    )
    scenarios = fixture["scenarios"]
    assert len(scenarios) == contract["expected_scenario_nodes"] == 12
    assert [scenario["id"] for scenario in scenarios] == contract["scenario_ids"]
    assert Counter(scenario["class"] for scenario in scenarios) == Counter(
        contract["scenario_class_counts"]
    )
    assert len({scenario["action"] for scenario in scenarios}) == 11


def test_t3_harness_t1_t2_namespace_schema_and_evidence_are_reachable(tmp_path):
    from app.ia.namespace import parse_uri
    from app.ia.schema import validate_record

    context = _materialization_context(tmp_path)
    uuid.UUID(context["task_101"])
    evidence = parse_uri(context["evidence_101"])
    assert evidence.record_type == "task.evidence"
    assert evidence.task_id == context["task_101"]
    assert len(list((tmp_path / "task-canonical").rglob("evidence/*.json"))) == 2
    fact = next(
        record
        for record in _json(T1_FIXTURE_PATH)["records"]
        if record["record_type"] == "knowledge.fact"
    )
    assert validate_record(fact) == fact


def test_t3_harness_conflict_orphan_duplicate_and_privacy_mutants_are_material(tmp_path):
    fixture = _fixture()
    context = _materialization_context(tmp_path)
    conflict = _request("bare_conflict", context)
    assert conflict["fact"]["supersedes"] == []
    assert conflict["fact"]["metadata"]["supersedes_hint"]
    source_less = _request("source_less", context)
    assert source_less["fact"]["provenance"] == []
    assert source_less["fact"]["metadata"]["fallback_path"]
    orphan = _request("orphan", context)
    assert orphan["new_topic"] is False
    assert orphan["fact"]["metadata"]["fallback_topic_slug"] == "repo-ops"
    duplicate_aliases = [
        topic
        for topic in fixture["duplicate_topic_registry"]["topics"]
        if "shared-ops" in topic["aliases"]
    ]
    assert len(duplicate_aliases) == 2
    private = fixture["compatibility_mutations"]["private_metadata"]
    assert private["opaque"]["credential_material"] == (
        "T3_PRIVATE_CREDENTIAL_MUST_BE_REJECTED"
    )


def test_t3_harness_valid_alias_field_order_and_safe_metadata_are_alternate(tmp_path):
    context = _materialization_context(tmp_path)
    request = _request("supersede_two_alternate", context)
    reordered = _request("supersede_two_alternate", context, reordered=True)
    assert request == reordered
    assert request["topic"] == "repository-operations"
    assert request["fact"]["metadata"]["future_projection_metadata"] == {
        "version": 2,
        "label": "safe",
    }


SCENARIOS = _fixture()["scenarios"]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[item["id"] for item in SCENARIOS])
def test_t3_exact_promotion_scenario(scenario, tmp_path):
    api = _load_api()
    context = _materialization_context(tmp_path)
    root = tmp_path / "knowledge-main"

    if scenario["id"] == "S12":
        with _knowledge_mode(api, tmp_path, context):
            initial_head = api.knowledge.knowledge_head()
            with pytest.raises(api.evidence.EvidenceResolutionError):
                _promote(api, _request("source_less", context))
            with pytest.raises(api.knowledge.TopicResolutionError):
                _promote(api, _request("orphan", context))
            assert api.knowledge.knowledge_head() == initial_head
            assert _query(api, topic="repo-ops", mode="all")["count"] == 0
            assert not _fact_files(root)
            assert not _event_files(root)

        duplicate_request = _request("current", context)
        duplicate_request["topic"] = "shared-ops"
        duplicate_request["event_id"] = "30000000-0000-4000-8000-000000000099"
        duplicate_request["idempotency_key"] = "t3-duplicate-topic"
        duplicate_request["fact"]["stable_id"] = "31000000-0000-4000-8000-000000000099"
        with _knowledge_mode(api, tmp_path, context, duplicate=True):
            duplicate_head = api.knowledge.knowledge_head()
            with pytest.raises(api.knowledge.TopicResolutionError):
                _promote(api, duplicate_request)
            assert api.knowledge.knowledge_head() == duplicate_head
            assert not _fact_files(tmp_path / "knowledge-duplicate")
        return

    with _knowledge_mode(api, tmp_path, context):
        _run_setup(api, context, scenario["setup"])
        action = _request(
            scenario["action"],
            context,
            reordered=scenario["id"] == "S05",
        )
        expected = scenario["expected"]

        if expected == "identical-noop":
            before_head = api.knowledge.knowledge_head()
            before_events = len(_event_files(root))
            result = _promote(api, action)
            assert result["outcome"] == "noop"
            assert result["canonical_head"] == before_head
            assert len(_event_files(root)) == before_events
            changed_payload = copy.deepcopy(action)
            changed_payload["fact"]["claim"] += " but mutated"
            with pytest.raises(api.events.EventConflictError):
                _promote(api, changed_payload)
            return

        if expected == "conflict-rejected":
            before_head = api.knowledge.knowledge_head()
            with pytest.raises(api.knowledge.PromotionConflictError):
                _promote(api, action)
            assert api.knowledge.knowledge_head() == before_head
            current = _query(
                api,
                topic="repo-ops",
                fact_key="worker-wip-scope",
            )
            assert [fact["stable_id"] for fact in current["facts"]] == [
                "31000000-0000-4000-8000-000000000001"
            ]
            return

        result = _promote(api, action)
        assert result["canonical_head"] == result["projection_head"]

        if expected == "current":
            assert result["outcome"] == "created"
            current = _query(api, topic="repo-ops", fact_key="worker-wip-scope")
            assert current["count"] == 1
            _assert_fact_is_t1_compatible(current["facts"][0])
        elif expected in {"superseded-as-of", "superseded-valid-alternate"}:
            assert result["outcome"] == "superseded"
            current = _query(api, topic="repo-ops", fact_key="worker-wip-scope")
            assert current["facts"][0]["stable_id"] == action["fact"]["stable_id"]
            superseded = _query(
                api,
                topic="repo-ops",
                mode="superseded",
                fact_key="worker-wip-scope",
            )
            assert superseded["count"] >= 1
            assert all(fact["status"] == "historical" for fact in superseded["facts"])
            assert all(fact["metadata"]["superseded_by"] for fact in superseded["facts"])
            if expected == "superseded-as-of":
                old = _query(
                    api,
                    topic="repo-ops",
                    mode="as_of",
                    fact_key="worker-wip-scope",
                    as_of="2026-08-15T00:00:00Z",
                )
                new = _query(
                    api,
                    topic="repo-ops",
                    mode="as_of",
                    fact_key="worker-wip-scope",
                    as_of="2026-08-17T00:00:00Z",
                )
                assert old["facts"][0]["stable_id"].endswith("0001")
                assert new["facts"][0]["stable_id"].endswith("0003")
            else:
                assert current["facts"][0]["topic_slug"] == "repo-ops"
                assert current["facts"][0]["metadata"]["future_projection_metadata"] == {
                    "version": 2,
                    "label": "safe",
                }
            _assert_fact_is_t1_compatible(current["facts"][0])
        elif expected == "rejected-query":
            key = action["fact"]["fact_key"]
            assert _query(api, topic="repo-ops", fact_key=key)["count"] == 0
            rejected = _query(api, topic="repo-ops", mode="rejected", fact_key=key)
            assert rejected["count"] == 1
            assert rejected["facts"][0]["status"] == "rejected"
            assert rejected["facts"][0]["metadata"]["rejection_reason"]
            _assert_fact_is_t1_compatible(rejected["facts"][0])
        elif expected == "additive-no-false-supersede":
            current = _query(api, topic="repo-ops")
            assert {fact["fact_key"] for fact in current["facts"]} == {
                "worker-wip-scope",
                "worker-wip-display",
            }
            assert _query(api, topic="repo-ops", mode="superseded")["count"] == 0
            for fact in current["facts"]:
                _assert_fact_is_t1_compatible(fact)
        elif expected == "disputed-visible":
            disputed = _query(
                api,
                topic="repo-ops",
                mode="disputed",
                fact_key="worker-wip-scope",
            )
            assert disputed["count"] == 2
            assert all(fact["status"] == "disputed" for fact in disputed["facts"])
            assert _query(
                api,
                topic="repo-ops",
                fact_key="worker-wip-scope",
            )["count"] == 0
            for fact in disputed["facts"]:
                _assert_fact_is_t1_compatible(fact)
        elif expected == "validation-debt-only":
            stale = _query(
                api,
                topic="review-routing",
                fact_key="provider-window-state",
                now="2026-09-01T00:00:00Z",
            )
            assert stale["count"] == 1
            assert stale["facts"][0]["status"] == "stale-needs-validation"
            assert stale["validation_debt"] == [action["fact"]["stable_id"]]
            fact_path = next(path for path in _fact_files(root) if action["fact"]["stable_id"] in path.name)
            canonical = json.loads(fact_path.read_text(encoding="utf-8"))
            assert canonical["status"] == "current"
            _assert_fact_is_t1_compatible(canonical)
            _assert_fact_is_t1_compatible(stale["facts"][0])
            assert _query(
                api,
                topic="review-routing",
                mode="rejected",
                fact_key="provider-window-state",
            )["count"] == 0
        elif expected == "new-topic-atomic":
            assert result["topic_registered"] is True
            registry = _json(root / _contract()["canonical_layout"]["registry"])
            assert [
                topic["topic_slug"]
                for topic in registry["topics"]
                if topic["topic_slug"] == "runtime-safety"
            ] == ["runtime-safety"]
            assert (root / "README.md").is_file()
            topic_path = root / _contract()["canonical_layout"]["topic"].format(
                project_id="orchestra",
                topic_slug="runtime-safety",
            )
            assert topic_path.is_file()
            new_topic = _query(api, topic="runtime-guards")
            assert new_topic["count"] == 1
            _assert_fact_is_t1_compatible(new_topic["facts"][0])
        else:
            raise AssertionError(f"unhandled T3 expected outcome: {expected}")


def test_t3_public_entry_is_wired_to_service_evidence_and_event_owner(tmp_path, monkeypatch):
    api = _load_api()
    context = _materialization_context(tmp_path)
    calls = []

    original_promote = api.knowledge.KnowledgeService.promote
    original_resolve = api.evidence.EvidenceResolver.resolve
    original_append = api.events.FactEventLog.append

    def tracked_promote(self, *args, **kwargs):
        calls.append("service")
        return original_promote(self, *args, **kwargs)

    def tracked_resolve(self, *args, **kwargs):
        calls.append("evidence")
        return original_resolve(self, *args, **kwargs)

    def tracked_append(self, *args, **kwargs):
        calls.append("event")
        return original_append(self, *args, **kwargs)

    monkeypatch.setattr(api.knowledge.KnowledgeService, "promote", tracked_promote)
    monkeypatch.setattr(api.evidence.EvidenceResolver, "resolve", tracked_resolve)
    monkeypatch.setattr(api.events.FactEventLog, "append", tracked_append)

    with _knowledge_mode(api, tmp_path, context):
        result = _promote(api, _request("current", context))
        assert result["outcome"] == "created"
    assert calls == ["service", "evidence", "event"]
    assert len(_fact_files(tmp_path / "knowledge-main")) == 1
    assert len(_event_files(tmp_path / "knowledge-main")) == 1


def test_t3_public_entry_rejects_cross_kind_evidence_and_private_fact(tmp_path):
    from app.ia.schema import PrivacyViolationError

    api = _load_api()
    context = _materialization_context(tmp_path)
    with _knowledge_mode(api, tmp_path, context):
        cross_kind = _request("current", context)
        cross_kind["event_id"] = "30000000-0000-4000-8000-000000000097"
        cross_kind["idempotency_key"] = "t3-cross-kind"
        cross_kind["fact"]["stable_id"] = "31000000-0000-4000-8000-000000000097"
        cross_kind["fact"]["provenance"][0]["evidence_uri"] = context["resource_uri"]
        with pytest.raises(api.evidence.EvidenceResolutionError):
            _promote(api, cross_kind)

        private = _request("current", context)
        private["event_id"] = "30000000-0000-4000-8000-000000000098"
        private["idempotency_key"] = "t3-private"
        private["fact"]["stable_id"] = "31000000-0000-4000-8000-000000000098"
        private["fact"]["fact_key"] = "private-fact"
        private["fact"]["metadata"] = copy.deepcopy(
            _fixture()["compatibility_mutations"]["private_metadata"]
        )
        with pytest.raises(PrivacyViolationError):
            _promote(api, private)

        assert _query(api, topic="repo-ops", mode="all")["count"] == 0
        assert not _fact_files(tmp_path / "knowledge-main")
        assert not _event_files(tmp_path / "knowledge-main")
