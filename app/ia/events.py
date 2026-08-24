"""Append-only event ownership for promoted knowledge facts."""

from __future__ import annotations

import copy
import json
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class EventConflictError(RuntimeError):
    """Raised when an event identity or idempotency key changes payload."""


_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EventConflictError("fact event is not canonical JSON") from exc


def _read_event(path: Path) -> dict[str, Any]:
    try:
        event = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EventConflictError(f"cannot read canonical fact event: {path}") from exc
    if not isinstance(event, dict):
        raise EventConflictError(f"canonical fact event is not an object: {path}")
    return event


def _operation(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        name: copy.deepcopy(event.get(name))
        for name in ("event_id", "idempotency_key", "project_id", "topic_slug", "request")
    }


class FactEventLog:
    """Store one immutable JSON object per promotion event."""

    def __init__(self, canonical_root: Path) -> None:
        self._root = Path(canonical_root)

    def events(
        self,
        *,
        project_id: str = "",
        topic_slug: str = "",
    ) -> Sequence[Mapping[str, Any]]:
        """Return detached canonical events in deterministic path order."""

        records: list[dict[str, Any]] = []
        for path in sorted(self._root.rglob("events/*.json")):
            event = _read_event(path)
            if project_id and event.get("project_id") != project_id:
                continue
            if topic_slug and event.get("topic_slug") != topic_slug:
                continue
            records.append(copy.deepcopy(event))
        return records

    def append(self, event: Mapping[str, Any]) -> Mapping[str, Any]:
        """Append a content-bound event, returning ``noop`` for an exact replay."""

        if not isinstance(event, Mapping):
            raise EventConflictError("fact event must be a mapping")
        value = json.loads(_canonical_bytes(dict(event)))
        required = {
            "event_id",
            "idempotency_key",
            "event_type",
            "project_id",
            "topic_slug",
            "request",
            "parent_head",
            "canonical_head",
            "projection_head",
            "outcome",
        }
        if required - value.keys():
            raise EventConflictError("fact event envelope is incomplete")
        try:
            if str(uuid.UUID(value["event_id"])) != value["event_id"]:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise EventConflictError("event_id must be a canonical UUID") from exc
        if not isinstance(value["idempotency_key"], str) or not value["idempotency_key"]:
            raise EventConflictError("idempotency_key must be a non-empty string")
        if any(
            not isinstance(value[name], str) or _SLUG.fullmatch(value[name]) is None
            for name in ("project_id", "topic_slug")
        ):
            raise EventConflictError("event project and topic must be canonical slugs")

        for existing in self.events():
            same_id = existing.get("event_id") == value["event_id"]
            same_key = existing.get("idempotency_key") == value["idempotency_key"]
            if not (same_id or same_key):
                continue
            if _operation(existing) == _operation(value) and same_id and same_key:
                result = copy.deepcopy(dict(existing))
                result["outcome"] = "noop"
                return result
            raise EventConflictError("event identity or idempotency key already has another payload")

        path = (
            self._root
            / "projects"
            / value["project_id"]
            / "knowledge"
            / "topics"
            / value["topic_slug"]
            / "events"
            / f"{value['event_id']}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(_canonical_bytes(value) + b"\n")
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            existing = _read_event(path)
            if _operation(existing) == _operation(value):
                result = copy.deepcopy(existing)
                result["outcome"] = "noop"
                return result
            raise EventConflictError("event id was concurrently claimed") from exc
        finally:
            if temporary.exists():
                temporary.unlink()
        return copy.deepcopy(value)
