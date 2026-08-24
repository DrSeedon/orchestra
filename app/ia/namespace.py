"""Canonical ``orch://`` namespace construction and parsing."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID


class NamespaceError(ValueError):
    """Raised when an information-architecture URI is not canonical."""


_UUID_TEXT = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_SLUG_TEXT = r"[a-z0-9]+(?:-[a-z0-9]+)*"


@dataclass(frozen=True, slots=True)
class _NamespaceAddress:
    record_type: str
    project_id: str
    stable_id: str
    canonical_uri: str
    task_id: str | None = None
    topic_slug: str | None = None
    fact_key: str | None = None
    session_id: str | None = None


_ROUTES = (
    (
        "task.state",
        re.compile(
            rf"orch://project/(?P<project_id>{_SLUG_TEXT})/tasks/"
            rf"(?P<stable_id>{_UUID_TEXT})/state"
        ),
    ),
    (
        "task.evidence",
        re.compile(
            rf"orch://project/(?P<project_id>{_SLUG_TEXT})/tasks/"
            rf"(?P<task_id>{_UUID_TEXT})/evidence/(?P<stable_id>{_UUID_TEXT})"
        ),
    ),
    (
        "knowledge.fact",
        re.compile(
            rf"orch://project/(?P<project_id>{_SLUG_TEXT})/knowledge/topics/"
            rf"(?P<topic_slug>{_SLUG_TEXT})/facts/(?P<fact_key>{_SLUG_TEXT})/"
            rf"(?P<stable_id>{_UUID_TEXT})"
        ),
    ),
    (
        "session.history",
        re.compile(
            rf"orch://project/(?P<project_id>{_SLUG_TEXT})/sessions/"
            rf"(?P<session_id>{_UUID_TEXT})/history/(?P<stable_id>{_UUID_TEXT})"
        ),
    ),
    (
        "resource",
        re.compile(
            rf"orch://project/(?P<project_id>{_SLUG_TEXT})/resources/"
            rf"(?P<stable_id>{_UUID_TEXT})"
        ),
    ),
    (
        "skill",
        re.compile(
            rf"orch://project/(?P<project_id>{_SLUG_TEXT})/skills/"
            rf"(?P<stable_id>{_UUID_TEXT})"
        ),
    ),
)


def _text(record: Mapping, name: str) -> str:
    value = record.get(name)
    if not isinstance(value, str) or not value:
        raise NamespaceError(f"{name} must be a non-empty string")
    return value


def _slug(record: Mapping, name: str) -> str:
    value = _text(record, name)
    if re.fullmatch(_SLUG_TEXT, value) is None:
        raise NamespaceError(f"{name} is not a canonical slug")
    return value


def _uuid(record: Mapping, name: str) -> str:
    value = _text(record, name)
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise NamespaceError(f"{name} is not a UUID") from exc
    if str(parsed) != value:
        raise NamespaceError(f"{name} is not a canonical UUID")
    return value


def build_uri(record: Mapping) -> str:
    """Build the one canonical URI for a typed record address."""

    if not isinstance(record, Mapping):
        raise NamespaceError("record must be a mapping")
    record_type = _text(record, "record_type")
    project_id = _slug(record, "project_id")
    stable_id = _uuid(record, "stable_id")
    root = f"orch://project/{project_id}"

    if record_type == "task.state":
        uri = f"{root}/tasks/{stable_id}/state"
    elif record_type == "task.evidence":
        task_id = _uuid(record, "task_id")
        uri = f"{root}/tasks/{task_id}/evidence/{stable_id}"
    elif record_type == "knowledge.fact":
        topic_slug = _slug(record, "topic_slug")
        fact_key = _slug(record, "fact_key")
        uri = f"{root}/knowledge/topics/{topic_slug}/facts/{fact_key}/{stable_id}"
    elif record_type == "session.history":
        session_id = _uuid(record, "session_id")
        uri = f"{root}/sessions/{session_id}/history/{stable_id}"
    elif record_type == "resource":
        uri = f"{root}/resources/{stable_id}"
    elif record_type == "skill":
        uri = f"{root}/skills/{stable_id}"
    else:
        raise NamespaceError(f"unsupported record_type: {record_type!r}")

    parse_uri(uri)
    return uri


def parse_uri(uri: str) -> _NamespaceAddress:
    """Parse a canonical URI without decoding or normalizing unsafe input."""

    if not isinstance(uri, str):
        raise NamespaceError("URI must be a string")
    for record_type, pattern in _ROUTES:
        match = pattern.fullmatch(uri)
        if match is None:
            continue
        values = match.groupdict()
        stable_id = values["stable_id"]
        try:
            if str(UUID(stable_id)) != stable_id:
                raise ValueError
        except ValueError as exc:
            raise NamespaceError("URI contains a non-canonical UUID") from exc
        return _NamespaceAddress(
            record_type=record_type,
            project_id=values["project_id"],
            stable_id=stable_id,
            canonical_uri=uri,
            task_id=values.get("task_id"),
            topic_slug=values.get("topic_slug"),
            fact_key=values.get("fact_key"),
            session_id=values.get("session_id"),
        )
    raise NamespaceError("URI is malformed, unsafe, or non-canonical")
