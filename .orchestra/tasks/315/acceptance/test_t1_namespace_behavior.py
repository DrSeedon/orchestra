"""Frozen RED oracle for #315 T1: typed namespace and privacy boundary.

Public production API frozen by this oracle:

``app.ia.namespace``
    ``build_uri(record) -> str``
    ``parse_uri(uri) -> address`` with ``record_type``, ``project_id``,
    ``stable_id`` and ``canonical_uri`` attributes
    ``NamespaceError`` for malformed/non-canonical namespace input

``app.ia.schema``
    ``validate_record(record) -> Mapping``
    ``validate_record_set(records) -> Sequence[Mapping]``
    ``classify_private_fields(record) -> Sequence[str]``
    ``projection_payload(record, sink) -> Mapping``
    ``canonical_bytes(record) -> bytes``
    ``canonical_content_head(record) -> 'sha256:<hex>'``
    typed ``RecordValidationError``, ``IdentityConflictError`` and
    ``PrivacyViolationError`` exceptions

The imports happen inside tests so the current missing implementation is a
behavior-test failure, never a collection-time ImportError or a path smoke.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest


HERE = Path(__file__).resolve().parent
FIXTURE_PATH = HERE / "fixtures" / "t1_namespace_records.json"
CONTRACT_PATH = HERE / "fixtures" / "t1_namespace_contract.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _contract() -> dict:
    return _json(CONTRACT_PATH)


def _records() -> dict[str, dict]:
    records = _json(FIXTURE_PATH)["records"]
    return {record["record_type"]: record for record in records}


def _load_module(name: str):
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        pytest.fail(f"#315 T1 missing behavior: cannot import {name}: {exc}")


def _api() -> SimpleNamespace:
    contract = _contract()["public_api"]
    modules = {
        name: _load_module(name)
        for name in ("app.ia.namespace", "app.ia.schema")
    }
    for module_name, surface in contract.items():
        module = modules[module_name]
        for name in surface["callables"]:
            assert callable(getattr(module, name, None)), (
                f"#315 T1 missing behavior: {module_name}.{name} is not callable"
            )
        for name in surface["exceptions"]:
            error = getattr(module, name, None)
            assert isinstance(error, type) and issubclass(error, Exception), (
                f"#315 T1 missing behavior: {module_name}.{name} is not an exception"
            )
    return SimpleNamespace(namespace=modules["app.ia.namespace"], schema=modules["app.ia.schema"])


def _delete_dotted_path(value: dict, dotted_path: str) -> None:
    parts = dotted_path.split(".")
    owner = value
    for part in parts[:-1]:
        owner = owner[part]
    del owner[parts[-1]]


def _lookup_dotted_path(value: Mapping, dotted_path: str):
    current = value
    for part in dotted_path.split("."):
        current = current[part]
    return current


def _expected_public_payload(record: Mapping) -> dict:
    public = copy.deepcopy(dict(record))
    for path in record["private_fields"]:
        _delete_dotted_path(public, path)
    return public


def _expected_canonical_bytes(record: Mapping) -> bytes:
    return json.dumps(
        _expected_public_payload(record),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _hidden_secret_mutation() -> dict:
    record = copy.deepcopy(_records()["task.state"])
    record["metadata"] = {
        "opaque": {
            "credential_material": _contract()["hidden_secret_sentinel"],
        }
    }
    return record


def _cross_kind_body_mutation() -> dict:
    records = _records()
    task = copy.deepcopy(records["task.state"])
    fact = records["knowledge.fact"]
    for name in (
        "topic_slug",
        "fact_key",
        "claim",
        "confidence",
        "valid_to",
        "observed_at",
        "refresh_after",
        "provenance",
        "disputed_by",
    ):
        task[name] = copy.deepcopy(fact[name])
    return task


def test_t1_harness_fixture_manifest_is_frozen_and_complete():
    """Positive control: fixture loading/counting does not touch production."""
    contract = _contract()
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == contract["fixture_sha256"]
    records = _records()
    assert tuple(records) == tuple(contract["record_types"])
    assert len(records) == 6
    assert all(record["uri"].startswith("orch://project/") for record in records.values())
    assert all(record["stable_id"] for record in records.values())


def test_t1_harness_compound_mutations_are_real_and_independent():
    """Positive control: both mutants are materially present before API calls."""
    contract = _contract()
    hidden = _hidden_secret_mutation()
    hidden_path = contract["hidden_secret_path"]
    assert _lookup_dotted_path(hidden, hidden_path) == contract["hidden_secret_sentinel"]
    assert hidden_path not in hidden["private_fields"]

    records = _records()
    cross_kind = _cross_kind_body_mutation()
    task = records["task.state"]
    assert cross_kind["record_type"] == task["record_type"]
    assert cross_kind["uri"] == task["uri"]
    assert cross_kind["stable_id"] == task["stable_id"]
    assert cross_kind["display_number"] == task["display_number"]
    assert cross_kind["topic_slug"] == records["knowledge.fact"]["topic_slug"]
    assert cross_kind["fact_key"] == records["knowledge.fact"]["fact_key"]


def test_t1_every_approved_kind_parses_and_round_trips_canonical_uri():
    api = _api()
    contract = _contract()
    for record_type, record in _records().items():
        built = api.namespace.build_uri(record)
        assert built == record["uri"]
        address = api.namespace.parse_uri(built)
        for attribute in contract["public_api"]["app.ia.namespace"]["parse_result_attributes"]:
            assert hasattr(address, attribute), f"parse_uri result lacks {attribute}"
        assert address.record_type == record_type
        assert address.project_id == record["project_id"]
        assert address.stable_id == record["stable_id"]
        assert address.canonical_uri == record["uri"]
        assert api.namespace.build_uri(api.schema.validate_record(record)) == built


@pytest.mark.parametrize(
    "uri",
    [
        "https://project/orchestra/resources/55555555-5555-4555-8555-555555555555",
        "orch://projects/orchestra/resources/55555555-5555-4555-8555-555555555555",
        "orch://project/orchestra/resources/../55555555-5555-4555-8555-555555555555",
        "orch://project/orchestra/resources/%2e%2e/55555555-5555-4555-8555-555555555555",
        "orch://project/orchestra/resources%2F55555555-5555-4555-8555-555555555555",
        "orch://project/orchestra/resources/%5C/55555555-5555-4555-8555-555555555555",
        "orch://project/orchestra//resources/55555555-5555-4555-8555-555555555555",
        "orch://project/orchestra/resources/55555555-5555-4555-8555-555555555555?copy=1",
        "orch://project/orchestra/resources/55555555-5555-4555-8555-555555555555#fragment",
        "orch://project/orchestra/unknown/55555555-5555-4555-8555-555555555555",
        "orch://project/orchestra/tasks/not-a-uuid/state",
    ],
)
def test_t1_invalid_noncanonical_and_traversal_uris_are_rejected(uri):
    api = _api()
    with pytest.raises(api.namespace.NamespaceError):
        api.namespace.parse_uri(uri)


def test_t1_schema_rejects_uri_body_kind_scope_and_identity_mismatch():
    api = _api()
    records = _records()

    wrong_kind_uri = copy.deepcopy(records["knowledge.fact"])
    wrong_kind_uri["uri"] = records["task.state"]["uri"]
    with pytest.raises(api.schema.RecordValidationError):
        api.schema.validate_record(wrong_kind_uri)

    wrong_scope = copy.deepcopy(records["resource"])
    wrong_scope["project_id"] = "client-alpha"
    with pytest.raises(api.schema.RecordValidationError):
        api.schema.validate_record(wrong_scope)

    wrong_identity = copy.deepcopy(records["skill"])
    wrong_identity["stable_id"] = "99999999-9999-4999-8999-999999999999"
    with pytest.raises(api.schema.RecordValidationError):
        api.schema.validate_record(wrong_identity)

    invalid_task_uuid = copy.deepcopy(records["task.state"])
    invalid_task_uuid["stable_id"] = "not-a-uuid"
    invalid_task_uuid["uri"] = "orch://project/orchestra/tasks/not-a-uuid/state"
    with pytest.raises(api.schema.RecordValidationError):
        api.schema.validate_record(invalid_task_uuid)


def test_t1_stable_identity_conflicts_but_display_number_is_project_scoped():
    api = _api()
    task = _records()["task.state"]

    same_identity = copy.deepcopy(task)
    same_identity["title"] = "conflicting active body"
    with pytest.raises(api.schema.IdentityConflictError):
        api.schema.validate_record_set([task, same_identity])

    same_project_number = copy.deepcopy(task)
    same_project_number["stable_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    same_project_number["uri"] = (
        "orch://project/orchestra/tasks/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/state"
    )
    with pytest.raises(api.schema.IdentityConflictError):
        api.schema.validate_record_set([task, same_project_number])

    other_project = copy.deepcopy(same_project_number)
    other_project["project_id"] = "client-alpha"
    other_project["uri"] = (
        "orch://project/client-alpha/tasks/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/state"
    )
    validated = api.schema.validate_record_set([task, other_project])
    assert isinstance(validated, Sequence)
    assert [item["display_number"] for item in validated] == [315, 315]
    assert [item["project_id"] for item in validated] == ["orchestra", "client-alpha"]


def test_t1_private_fields_are_classified_and_exactly_redacted_from_every_sink():
    api = _api()
    contract = _contract()
    resource = _records()["resource"]
    expected = _expected_public_payload(resource)

    assert tuple(api.schema.classify_private_fields(resource)) == (
        "metadata.auth.refresh_token",
        "operator_note",
    )
    projected = {
        sink: api.schema.projection_payload(resource, sink)
        for sink in contract["privacy_sinks"]
    }
    assert set(projected) == {"hot", "fts", "vector"}
    for payload in projected.values():
        assert payload == expected
        assert payload["stable_id"] == resource["stable_id"]
        assert payload["canonical_head"] == resource["canonical_head"]
        assert _lookup_dotted_path(payload, contract["safe_field_path"]) == (
            contract["safe_field_sentinel"]
        )
        rendered = json.dumps(payload, sort_keys=True)
        assert "T1_DECLARED_PRIVATE_NOTE_DO_NOT_PROJECT" not in rendered
        assert "T1_DECLARED_PRIVATE_TOKEN_DO_NOT_PROJECT" not in rendered


def test_t1_hidden_secret_in_generic_metadata_is_classified_and_rejected():
    api = _api()
    contract = _contract()
    hidden = _hidden_secret_mutation()
    assert contract["hidden_secret_path"] in api.schema.classify_private_fields(hidden)
    with pytest.raises(api.schema.PrivacyViolationError):
        api.schema.validate_record(hidden)
    for sink in contract["privacy_sinks"]:
        with pytest.raises(api.schema.PrivacyViolationError):
            api.schema.projection_payload(hidden, sink)


def test_t1_canonical_serialization_and_content_head_are_deterministic_and_public():
    api = _api()
    resource = _records()["resource"]
    expected = _expected_canonical_bytes(resource)
    actual = api.schema.canonical_bytes(resource)
    assert actual == expected
    assert actual == api.schema.canonical_bytes(dict(reversed(tuple(resource.items()))))

    expected_head = f"sha256:{hashlib.sha256(expected).hexdigest()}"
    assert api.schema.canonical_content_head(resource) == expected_head

    changed_private = copy.deepcopy(resource)
    changed_private["operator_note"] = "T1_DIFFERENT_PRIVATE_VALUE"
    changed_private["metadata"]["auth"]["refresh_token"] = "T1_DIFFERENT_PRIVATE_TOKEN"
    assert api.schema.canonical_bytes(changed_private) == expected
    assert api.schema.canonical_content_head(changed_private) == expected_head

    public = json.loads(actual)
    assert public["title"] == resource["title"]
    assert public["summary"] == resource["summary"]
    assert public["private_fields"] == resource["private_fields"]
    assert public["metadata"]["safe"] == resource["metadata"]["safe"]


def test_t1_valid_alternate_slug_and_field_order_are_equivalent():
    api = _api()
    alternate = copy.deepcopy(_records()["knowledge.fact"])
    alternate["stable_id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    alternate["topic_slug"] = "repo-ops-v2"
    alternate["fact_key"] = "merge-worker-wip-v2"
    alternate["uri"] = (
        "orch://project/orchestra/knowledge/topics/repo-ops-v2/facts/"
        "merge-worker-wip-v2/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    )
    reordered = dict(reversed(tuple(alternate.items())))

    assert api.namespace.build_uri(alternate) == alternate["uri"]
    assert api.namespace.build_uri(reordered) == alternate["uri"]
    assert api.schema.validate_record(alternate)["topic_slug"] == "repo-ops-v2"
    assert api.schema.validate_record(reordered)["fact_key"] == "merge-worker-wip-v2"
    assert api.schema.canonical_bytes(alternate) == api.schema.canonical_bytes(reordered)
    assert api.schema.canonical_content_head(alternate) == (
        api.schema.canonical_content_head(reordered)
    )


def test_t1_valid_task_envelope_cannot_accept_a_cross_kind_fact_body():
    api = _api()
    mutant = _cross_kind_body_mutation()
    assert api.namespace.build_uri(mutant) == mutant["uri"]
    with pytest.raises(api.schema.RecordValidationError):
        api.schema.validate_record(mutant)
