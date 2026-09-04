"""Validation, privacy filtering, and canonical serialization for IA records."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.ia.privacy import SECRET_VALUE_PATTERN, key_looks_secret
from uuid import UUID

from app.ia.namespace import NamespaceError, build_uri, parse_uri


class RecordValidationError(ValueError):
    """Raised when a typed record does not satisfy its schema."""


class IdentityConflictError(RecordValidationError):
    """Raised when active records claim the same stable or display identity."""


class PrivacyViolationError(RecordValidationError):
    """Raised when secret-like content lacks an exact private declaration."""


_COMMON_FIELDS = {
    "record_type",
    "schema_version",
    "stable_id",
    "uri",
    "project_id",
    "created_at",
    "updated_at",
    "canonical_head",
    "projection_head",
    "indexed_head",
    "status",
    "private_fields",
    "tombstone",
    "retention",
}
_TYPE_FIELDS = {
    "task.state": {
        "display_number",
        "display_ref",
        "title",
        "priority",
        "assignee",
        "scope",
        "worker_session_id",
        "acceptance",
        "evidence_refs",
        "git_commit_refs",
        "valid_from",
        "supersedes",
    },
    "task.evidence": {
        "task_id",
        "kind",
        "canonical_path",
        "git_commit",
        "blob_sha",
        "anchor",
        "captured_at",
        "author_session_id",
        "source_urls",
        "content_sha256",
    },
    "knowledge.fact": {
        "topic_slug",
        "fact_key",
        "claim",
        "confidence",
        "valid_from",
        "valid_to",
        "observed_at",
        "refresh_after",
        "provenance",
        "supersedes",
        "disputed_by",
    },
    "session.history": {
        "session_id",
        "archive_id",
        "canonical_path",
        "source_log_ids",
        "summary_ref",
    },
    "resource": {"source_uri", "content_sha256", "title", "summary"},
    "skill": {
        "skill_name",
        "source_path",
        "runtime_compatibility",
        "content_sha256",
    },
}
_TYPE_OPTIONAL_FIELDS = {"resource": {"operator_note"}}
_EXTENSION_FIELDS = {"metadata"}
_DOTTED_PATH = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_GIT_COMMIT = re.compile(r"[0-9a-f]{40}")
_PRIVACY_SINKS = frozenset({"hot", "fts", "vector"})


def _require_string(record: Mapping, name: str) -> str:
    value = record.get(name)
    if not isinstance(value, str) or not value:
        raise RecordValidationError(f"{name} must be a non-empty string")
    return value


def _canonical_uuid(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise RecordValidationError(f"{name} must be a UUID string")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise RecordValidationError(f"{name} must be a UUID string") from exc
    if str(parsed) != value:
        raise RecordValidationError(f"{name} must be a canonical UUID string")
    return value


def _string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise RecordValidationError(f"{name} must be a sequence of strings")
    result = list(value)
    if any(not isinstance(item, str) for item in result):
        raise RecordValidationError(f"{name} must be a sequence of strings")
    return result


def _declared_private_fields(record: Mapping) -> tuple[str, ...]:
    fields = _string_list(record.get("private_fields"), "private_fields")
    if len(fields) != len(set(fields)):
        raise RecordValidationError("private_fields must not contain duplicates")
    for path in fields:
        if _DOTTED_PATH.fullmatch(path) is None:
            raise RecordValidationError(f"private field path is not canonical: {path!r}")
    return tuple(fields)


def _detected_private_fields(value: Any) -> set[str]:
    found: set[str] = set()

    def visit(current: Any, path: tuple[str, ...]) -> None:
        if isinstance(current, Mapping):
            for raw_key, child in current.items():
                if not isinstance(raw_key, str):
                    raise RecordValidationError("record keys must be strings")
                if not path and raw_key == "private_fields":
                    continue
                child_path = (*path, raw_key)
                dotted = ".".join(child_path)
                if key_looks_secret(raw_key):
                    found.add(dotted)
                if isinstance(child, str) and SECRET_VALUE_PATTERN.search(child):
                    found.add(dotted)
                visit(child, child_path)
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
            for index, child in enumerate(current):
                visit(child, (*path, str(index)))

    visit(value, ())
    return found


def _lookup_dotted_path(record: Mapping, path: str) -> Any:
    current: Any = record
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise RecordValidationError(f"private field path does not exist: {path!r}")
        current = current[part]
    return current


def classify_private_fields(record: Mapping) -> Sequence[str]:
    """Return sorted exact paths declared private or detected as secret-like."""

    if not isinstance(record, Mapping):
        raise RecordValidationError("record must be a mapping")
    declared = set(_declared_private_fields(record))
    return tuple(sorted(declared | _detected_private_fields(record)))


def _validate_privacy(record: Mapping) -> None:
    declared = set(_declared_private_fields(record))
    for path in declared:
        _lookup_dotted_path(record, path)
    undeclared = _detected_private_fields(record) - declared
    if undeclared:
        names = ", ".join(sorted(undeclared))
        raise PrivacyViolationError(f"secret-like fields are not declared private: {names}")


def _validate_common(record: Mapping) -> str:
    missing = _COMMON_FIELDS - record.keys()
    if missing:
        raise RecordValidationError(f"missing common fields: {', '.join(sorted(missing))}")
    record_type = _require_string(record, "record_type")
    if record_type not in _TYPE_FIELDS:
        raise RecordValidationError(f"unsupported record_type: {record_type!r}")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise RecordValidationError("schema_version must be 1")
    _canonical_uuid(record["stable_id"], "stable_id")
    for name in (
        "uri",
        "project_id",
        "created_at",
        "updated_at",
        "canonical_head",
        "status",
        "retention",
    ):
        _require_string(record, name)
    for name in ("projection_head", "indexed_head"):
        value = record[name]
        if value is not None and (not isinstance(value, str) or not value):
            raise RecordValidationError(f"{name} must be null or a non-empty string")
    if type(record["tombstone"]) is not bool:
        raise RecordValidationError("tombstone must be a boolean")
    _declared_private_fields(record)
    return record_type


def _validate_shape(record: Mapping, record_type: str) -> None:
    required = _COMMON_FIELDS | _TYPE_FIELDS[record_type]
    missing = required - record.keys()
    if missing:
        raise RecordValidationError(
            f"missing {record_type} fields: {', '.join(sorted(missing))}"
        )
    allowed = required | _TYPE_OPTIONAL_FIELDS.get(record_type, set()) | _EXTENSION_FIELDS
    extra = record.keys() - allowed
    if extra:
        raise RecordValidationError(
            f"fields forbidden for {record_type}: {', '.join(sorted(extra))}"
        )


def _validate_uri(record: Mapping, record_type: str) -> None:
    try:
        address = parse_uri(record["uri"])
        expected_uri = build_uri(record)
    except (KeyError, NamespaceError) as exc:
        raise RecordValidationError(f"invalid namespace address: {exc}") from exc
    if address.canonical_uri != expected_uri:
        raise RecordValidationError("URI does not match the record body")
    if (
        address.record_type != record_type
        or address.project_id != record["project_id"]
        or address.stable_id != record["stable_id"]
    ):
        raise RecordValidationError("URI type, project, or stable identity mismatch")


def _validate_acceptance(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "command",
        "manifest_paths",
        "required",
    }:
        raise RecordValidationError("acceptance must have command, manifest_paths, and required")
    if not isinstance(value["command"], str):
        raise RecordValidationError("acceptance.command must be a string")
    _string_list(value["manifest_paths"], "acceptance.manifest_paths")
    if type(value["required"]) is not bool:
        raise RecordValidationError("acceptance.required must be a boolean")


def _validate_hash(value: Any, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RecordValidationError(f"{name} must be a canonical sha256 digest")


def _validate_task(record: Mapping) -> None:
    if type(record["display_number"]) is not int or record["display_number"] <= 0:
        raise RecordValidationError("display_number must be a positive integer")
    if record["display_ref"] != f"#{record['display_number']}":
        raise RecordValidationError("display_ref must match display_number")
    for name in ("title", "assignee", "scope", "valid_from"):
        _require_string(record, name)
    if type(record["priority"]) is not int:
        raise RecordValidationError("priority must be an integer")
    _canonical_uuid(record["worker_session_id"], "worker_session_id")
    _validate_acceptance(record["acceptance"])
    for evidence_uri in _string_list(record["evidence_refs"], "evidence_refs"):
        try:
            address = parse_uri(evidence_uri)
        except NamespaceError as exc:
            raise RecordValidationError("evidence_refs contains an invalid URI") from exc
        if address.record_type != "task.evidence":
            raise RecordValidationError("evidence_refs must contain task evidence URIs")
    _string_list(record["git_commit_refs"], "git_commit_refs")
    if record["supersedes"] is not None:
        _canonical_uuid(record["supersedes"], "supersedes")


def _validate_evidence(record: Mapping) -> None:
    _canonical_uuid(record["task_id"], "task_id")
    _canonical_uuid(record["author_session_id"], "author_session_id")
    for name in ("kind", "canonical_path", "anchor", "captured_at"):
        _require_string(record, name)
    if not isinstance(record["git_commit"], str) or _GIT_COMMIT.fullmatch(
        record["git_commit"]
    ) is None:
        raise RecordValidationError("git_commit must be a lowercase 40-hex commit")
    _validate_hash(record["blob_sha"], "blob_sha")
    _validate_hash(record["content_sha256"], "content_sha256")
    _string_list(record["source_urls"], "source_urls")


def _validate_fact(record: Mapping) -> None:
    for name in (
        "topic_slug",
        "fact_key",
        "claim",
        "confidence",
        "valid_from",
        "observed_at",
        "refresh_after",
    ):
        _require_string(record, name)
    if record["valid_to"] is not None and not isinstance(record["valid_to"], str):
        raise RecordValidationError("valid_to must be null or a string")
    provenance = record["provenance"]
    if not isinstance(provenance, Sequence) or isinstance(provenance, (str, bytes)) or not provenance:
        raise RecordValidationError("provenance must be a non-empty sequence")
    expected = {"task_id", "evidence_uri", "path", "anchor", "git_commit", "measurement"}
    for item in provenance:
        if not isinstance(item, Mapping) or set(item) != expected:
            raise RecordValidationError("provenance entries must use the exact fact contract")
        task_id = _canonical_uuid(item["task_id"], "provenance.task_id")
        for name in ("path", "anchor", "measurement"):
            if not isinstance(item[name], str) or not item[name]:
                raise RecordValidationError(f"provenance.{name} must be a non-empty string")
        if not isinstance(item["git_commit"], str) or _GIT_COMMIT.fullmatch(
            item["git_commit"]
        ) is None:
            raise RecordValidationError("provenance.git_commit must be lowercase 40-hex")
        try:
            evidence = parse_uri(item["evidence_uri"])
        except (NamespaceError, TypeError) as exc:
            raise RecordValidationError("provenance.evidence_uri is invalid") from exc
        if (
            evidence.record_type != "task.evidence"
            or evidence.project_id != record["project_id"]
            or evidence.task_id != task_id
        ):
            raise RecordValidationError("provenance crosses task or project identity")
    _string_list(record["supersedes"], "supersedes")
    _string_list(record["disputed_by"], "disputed_by")


def _validate_session(record: Mapping) -> None:
    _canonical_uuid(record["session_id"], "session_id")
    archive_id = _canonical_uuid(record["archive_id"], "archive_id")
    if archive_id != record["stable_id"]:
        raise RecordValidationError("archive_id must equal stable_id")
    _require_string(record, "canonical_path")
    log_ids = record["source_log_ids"]
    if not isinstance(log_ids, Sequence) or isinstance(log_ids, (str, bytes)) or any(
        type(item) is not int for item in log_ids
    ):
        raise RecordValidationError("source_log_ids must be a sequence of integers")
    if record["summary_ref"] != record["uri"]:
        raise RecordValidationError("summary_ref must resolve to the same history record")


def _validate_resource(record: Mapping) -> None:
    for name in ("source_uri", "title", "summary"):
        _require_string(record, name)
    _validate_hash(record["content_sha256"], "content_sha256")
    if "operator_note" in record and not isinstance(record["operator_note"], str):
        raise RecordValidationError("operator_note must be a string")
    if "metadata" in record and not isinstance(record["metadata"], Mapping):
        raise RecordValidationError("metadata must be a mapping")


def _validate_skill(record: Mapping) -> None:
    for name in ("skill_name", "source_path"):
        _require_string(record, name)
    compatibility = _string_list(record["runtime_compatibility"], "runtime_compatibility")
    if not compatibility:
        raise RecordValidationError("runtime_compatibility must not be empty")
    _validate_hash(record["content_sha256"], "content_sha256")


_TYPE_VALIDATORS = {
    "task.state": _validate_task,
    "task.evidence": _validate_evidence,
    "knowledge.fact": _validate_fact,
    "session.history": _validate_session,
    "resource": _validate_resource,
    "skill": _validate_skill,
}


def validate_record(record: Mapping) -> Mapping:
    """Validate one record and return a detached mapping with the same content."""

    if not isinstance(record, Mapping):
        raise RecordValidationError("record must be a mapping")
    value = copy.deepcopy(dict(record))
    record_type = _validate_common(value)
    _validate_privacy(value)
    _validate_shape(value, record_type)
    _validate_uri(value, record_type)
    _TYPE_VALIDATORS[record_type](value)
    return value


def validate_record_set(records: Iterable[Mapping]) -> Sequence[Mapping]:
    """Validate records and reject conflicting active stable/display identities."""

    if isinstance(records, (str, bytes, Mapping)):
        raise RecordValidationError("records must be an iterable of mappings")
    validated = [validate_record(record) for record in records]
    identities: dict[tuple[str, str], Mapping] = {}
    task_numbers: dict[tuple[str, int], str] = {}
    for record in validated:
        if record["tombstone"]:
            continue
        identity = (record["project_id"], record["stable_id"])
        previous = identities.get(identity)
        if previous is not None and previous != record:
            raise IdentityConflictError(
                f"conflicting active body for {record['project_id']}:{record['stable_id']}"
            )
        identities[identity] = record
        if record["record_type"] == "task.state":
            display = (record["project_id"], record["display_number"])
            previous_id = task_numbers.get(display)
            if previous_id is not None and previous_id != record["stable_id"]:
                raise IdentityConflictError(
                    f"display #{record['display_number']} is already active in "
                    f"{record['project_id']}"
                )
            task_numbers[display] = record["stable_id"]
    return validated


def _delete_dotted_path(record: dict[str, Any], path: str) -> None:
    owner: Any = record
    parts = path.split(".")
    for part in parts[:-1]:
        owner = owner[part]
    del owner[parts[-1]]


def _public_payload(record: Mapping) -> dict[str, Any]:
    validated = dict(validate_record(record))
    public = copy.deepcopy(validated)
    for path in validated["private_fields"]:
        _delete_dotted_path(public, path)
    return public


def projection_payload(record: Mapping, sink: str) -> Mapping:
    """Return a public payload for one supported hot or search sink."""

    if sink not in _PRIVACY_SINKS:
        raise RecordValidationError(f"unsupported projection sink: {sink!r}")
    return _public_payload(record)


def canonical_bytes(record: Mapping) -> bytes:
    """Serialize the public record deterministically as compact UTF-8 JSON."""

    try:
        rendered = json.dumps(
            _public_payload(record),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise RecordValidationError("record is not canonical JSON data") from exc
    return rendered.encode("utf-8")


def canonical_content_head(record: Mapping) -> str:
    """Return the SHA-256 content head of the canonical public bytes."""

    return f"sha256:{hashlib.sha256(canonical_bytes(record)).hexdigest()}"
