"""Evidence-backed promotion and canonical querying of typed knowledge facts."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from app.ia.evidence import EvidenceResolver
from app.ia.events import EventConflictError, FactEventLog
from app.ia.namespace import build_uri
from app.ia.schema import PrivacyViolationError, RecordValidationError, validate_record


class KnowledgeNotConfiguredError(RuntimeError):
    """Raised when the module-level entry point has no configured service."""


class PromotionConflictError(RuntimeError):
    """Raised when a fact update lacks an explicit conflict resolution."""


class PromotionValidationError(ValueError):
    """Raised when a promotion request does not satisfy the typed contract."""


class TopicResolutionError(ValueError):
    """Raised when a topic resolves to zero or multiple registry entries."""


_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_FACT_FIELDS = {
    "stable_id",
    "fact_key",
    "claim",
    "status",
    "confidence",
    "valid_from",
    "valid_to",
    "observed_at",
    "refresh_after",
    "provenance",
    "supersedes",
    "disputed_by",
    "metadata",
}
_REQUEST_FIELDS = {
    "event_id",
    "idempotency_key",
    "topic",
    "new_topic",
    "topic_summary",
    "aliases",
    "resolution",
    "fact",
}
_QUERY_MODES = {"current", "rejected", "superseded", "disputed", "all", "as_of"}
_ZERO_HEAD = "sha256:" + "0" * 64


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
        raise PromotionValidationError("knowledge data is not canonical JSON") from exc


def _detached(value: Any) -> Any:
    return json.loads(_canonical_bytes(value))


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionValidationError(f"cannot read canonical knowledge object: {path}") from exc
    if not isinstance(value, dict):
        raise PromotionValidationError(f"canonical knowledge object is not a mapping: {path}")
    return value


def _write_object(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(_canonical_bytes(value) + b"\n")
    temporary.replace(path)


def _canonical_uuid(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise PromotionValidationError(f"{name} must be a canonical UUID")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise PromotionValidationError(f"{name} must be a canonical UUID") from exc
    if str(parsed) != value:
        raise PromotionValidationError(f"{name} must be a canonical UUID")
    return value


def _timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise PromotionValidationError(f"{name} must be a timezone-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PromotionValidationError(f"{name} must be a timezone-aware timestamp") from exc
    if parsed.tzinfo is None:
        raise PromotionValidationError(f"{name} must be a timezone-aware timestamp")
    return parsed


def _operation(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        name: copy.deepcopy(event.get(name))
        for name in ("event_id", "idempotency_key", "project_id", "topic_slug", "request")
    }


class KnowledgeService:
    """Own the registry, evidence validation, fact events, and canonical reads."""

    def __init__(self, *, canonical_root: Path, registry_path: Path, task_store: Any) -> None:
        self.canonical_root = Path(canonical_root)
        self.canonical_root.mkdir(parents=True, exist_ok=True)
        supplied = _read_object(Path(registry_path))
        self._validate_registry(supplied)
        canonical_registry = self.canonical_root / "registry.json"
        if canonical_registry.exists():
            self._registry = _read_object(canonical_registry)
            self._validate_registry(self._registry)
        else:
            self._registry = supplied
            _write_object(canonical_registry, self._registry)
        self._write_topic_documents()
        self.evidence_resolver = EvidenceResolver(task_store)
        self.event_log = FactEventLog(self.canonical_root)

    @staticmethod
    def _validate_registry(registry: Mapping[str, Any]) -> None:
        if registry.get("registry_version") != 1 or not isinstance(registry.get("topics"), list):
            raise PromotionValidationError("topic registry has an unsupported shape")
        for topic in registry["topics"]:
            if not isinstance(topic, Mapping) or set(topic) != {
                "project_id",
                "topic_slug",
                "aliases",
                "summary",
            }:
                raise PromotionValidationError("topic registry entries use an invalid shape")
            for name in ("project_id", "topic_slug"):
                if not isinstance(topic[name], str) or _SLUG.fullmatch(topic[name]) is None:
                    raise PromotionValidationError(f"topic {name} is not a canonical slug")
            if not isinstance(topic["summary"], str) or not topic["summary"]:
                raise PromotionValidationError("topic summary must be a non-empty string")
            aliases = topic["aliases"]
            if (
                not isinstance(aliases, Sequence)
                or isinstance(aliases, (str, bytes))
                or any(not isinstance(alias, str) or _SLUG.fullmatch(alias) is None for alias in aliases)
                or len(aliases) != len(set(aliases))
            ):
                raise PromotionValidationError("topic aliases must be unique canonical slugs")

    def _write_topic_documents(self) -> None:
        topics = sorted(
            self._registry["topics"],
            key=lambda item: (item["project_id"], item["topic_slug"]),
        )
        readme = ["# Knowledge topic registry", ""]
        for topic in topics:
            aliases = ", ".join(topic["aliases"]) or "none"
            readme.append(
                f"- `{topic['project_id']}/{topic['topic_slug']}` (aliases: {aliases}) — "
                f"{topic['summary']}"
            )
            topic_path = (
                self.canonical_root
                / "projects"
                / topic["project_id"]
                / "knowledge"
                / "topics"
                / topic["topic_slug"]
                / "topic.md"
            )
            topic_path.parent.mkdir(parents=True, exist_ok=True)
            topic_path.write_text(
                f"# {topic['topic_slug']}\n\n{topic['summary']}\n\nAliases: {aliases}\n",
                encoding="utf-8",
            )
        (self.canonical_root / "README.md").write_text(
            "\n".join(readme) + "\n",
            encoding="utf-8",
        )

    def _resolve_topic(self, project_id: str, requested: str) -> dict[str, Any]:
        if not isinstance(requested, str) or _SLUG.fullmatch(requested) is None:
            raise TopicResolutionError("topic is not a canonical slug")
        matches = [
            topic
            for topic in self._registry["topics"]
            if topic["project_id"] == project_id
            and (topic["topic_slug"] == requested or requested in topic["aliases"])
        ]
        if len(matches) != 1:
            raise TopicResolutionError(
                f"topic {requested!r} resolved to {len(matches)} registry entries"
            )
        return copy.deepcopy(matches[0])

    def _new_topic(self, project_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        slug = request["topic"]
        if not isinstance(slug, str) or _SLUG.fullmatch(slug) is None:
            raise TopicResolutionError("new topic is not a canonical slug")
        collisions = [
            topic
            for topic in self._registry["topics"]
            if topic["project_id"] == project_id
            and (slug == topic["topic_slug"] or slug in topic["aliases"])
        ]
        aliases = request.get("aliases")
        summary = request.get("topic_summary")
        if collisions:
            raise TopicResolutionError("new topic already exists in the registry")
        if not isinstance(summary, str) or not summary:
            raise TopicResolutionError("new topics require a summary")
        if (
            not isinstance(aliases, Sequence)
            or isinstance(aliases, (str, bytes))
            or any(not isinstance(alias, str) or _SLUG.fullmatch(alias) is None for alias in aliases)
            or len(aliases) != len(set(aliases))
        ):
            raise TopicResolutionError("new topic aliases must be unique canonical slugs")
        names = {slug, *aliases}
        if any(
            names & {topic["topic_slug"], *topic["aliases"]}
            for topic in self._registry["topics"]
            if topic["project_id"] == project_id
        ):
            raise TopicResolutionError("new topic names collide with the registry")
        return {
            "project_id": project_id,
            "topic_slug": slug,
            "aliases": list(aliases),
            "summary": summary,
        }

    def _facts(self) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        for path in sorted(self.canonical_root.rglob("facts/*/*.json")):
            record = _read_object(path)
            try:
                record = dict(validate_record(record))
            except RecordValidationError as exc:
                raise PromotionValidationError(f"invalid canonical fact at {path}: {exc}") from exc
            facts.append(record)
        return facts

    @staticmethod
    def _state_head(
        registry: Mapping[str, Any],
        facts: Sequence[Mapping[str, Any]],
        events: Sequence[Mapping[str, Any]],
    ) -> str:
        fact_truth = []
        for fact in facts:
            value = copy.deepcopy(dict(fact))
            for name in ("canonical_head", "projection_head", "indexed_head"):
                value.pop(name, None)
            fact_truth.append(value)
        fact_truth.sort(key=lambda item: (item["project_id"], item["topic_slug"], item["stable_id"]))
        event_truth = []
        for event in events:
            value = copy.deepcopy(dict(event))
            for name in ("parent_head", "canonical_head", "projection_head"):
                value.pop(name, None)
            event_truth.append(value)
        event_truth.sort(key=lambda item: str(item["event_id"]))
        payload = {
            "registry": copy.deepcopy(dict(registry)),
            "facts": fact_truth,
            "events": event_truth,
        }
        return f"sha256:{hashlib.sha256(_canonical_bytes(payload)).hexdigest()}"

    def head(self) -> str:
        return self._state_head(self._registry, self._facts(), self.event_log.events())

    @staticmethod
    def _validate_request(request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise PromotionValidationError("promotion request must be a mapping")
        unknown = set(request) - _REQUEST_FIELDS
        required = {"event_id", "idempotency_key", "topic", "new_topic", "fact"}
        if unknown or required - request.keys():
            raise PromotionValidationError("promotion request has an invalid shape")
        value = _detached(dict(request))
        _canonical_uuid(value["event_id"], "event_id")
        if not isinstance(value["idempotency_key"], str) or not value["idempotency_key"]:
            raise PromotionValidationError("idempotency_key must be a non-empty string")
        if type(value["new_topic"]) is not bool:
            raise PromotionValidationError("new_topic must be a boolean")
        if not isinstance(value["fact"], dict) or set(value["fact"]) != _FACT_FIELDS:
            raise PromotionValidationError("fact request has an invalid shape")
        return value

    @staticmethod
    def _build_fact(raw: Mapping[str, Any], project_id: str, topic_slug: str) -> dict[str, Any]:
        stable_id = _canonical_uuid(raw["stable_id"], "fact.stable_id")
        if not isinstance(raw["fact_key"], str) or _SLUG.fullmatch(raw["fact_key"]) is None:
            raise PromotionValidationError("fact_key is not a canonical slug")
        if raw["status"] not in {"current", "rejected", "disputed"}:
            raise PromotionValidationError("promotion status is not canonical")
        for name in ("claim", "confidence"):
            if not isinstance(raw[name], str) or not raw[name]:
                raise PromotionValidationError(f"fact.{name} must be a non-empty string")
        valid_from = _timestamp(raw["valid_from"], "fact.valid_from")
        observed_at = _timestamp(raw["observed_at"], "fact.observed_at")
        refresh_after = _timestamp(raw["refresh_after"], "fact.refresh_after")
        if raw["valid_to"] is not None:
            valid_to = _timestamp(raw["valid_to"], "fact.valid_to")
            if valid_to <= valid_from:
                raise PromotionValidationError("fact valid_to must follow valid_from")
        if refresh_after < observed_at:
            raise PromotionValidationError("fact refresh_after precedes observation")
        for name in ("supersedes", "disputed_by"):
            value = raw[name]
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise PromotionValidationError(f"fact.{name} must be a string list")
        for superseded in raw["supersedes"]:
            _canonical_uuid(superseded, "fact.supersedes")
        if not isinstance(raw["metadata"], Mapping):
            raise PromotionValidationError("fact.metadata must be a mapping")

        fact = {
            "record_type": "knowledge.fact",
            "schema_version": 1,
            "stable_id": stable_id,
            "uri": "",
            "project_id": project_id,
            "created_at": raw["observed_at"],
            "updated_at": raw["observed_at"],
            "canonical_head": _ZERO_HEAD,
            "projection_head": _ZERO_HEAD,
            "indexed_head": None,
            "status": raw["status"],
            "private_fields": [],
            "tombstone": False,
            "retention": "project-default",
            "topic_slug": topic_slug,
            "fact_key": raw["fact_key"],
            "claim": raw["claim"],
            "confidence": raw["confidence"],
            "valid_from": raw["valid_from"],
            "valid_to": raw["valid_to"],
            "observed_at": raw["observed_at"],
            "refresh_after": raw["refresh_after"],
            "provenance": copy.deepcopy(raw["provenance"]),
            "supersedes": copy.deepcopy(raw["supersedes"]),
            "disputed_by": copy.deepcopy(raw["disputed_by"]),
            "metadata": copy.deepcopy(dict(raw["metadata"])),
        }
        fact["uri"] = build_uri(fact)
        try:
            return dict(validate_record(fact))
        except PrivacyViolationError:
            raise
        except RecordValidationError as exc:
            raise PromotionValidationError(f"fact record is invalid: {exc}") from exc

    @staticmethod
    def _event_replay(
        events: Sequence[Mapping[str, Any]], incoming: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        for existing in events:
            same_id = existing.get("event_id") == incoming["event_id"]
            same_key = existing.get("idempotency_key") == incoming["idempotency_key"]
            if not (same_id or same_key):
                continue
            if same_id and same_key and _operation(existing) == _operation(incoming):
                return existing
            raise EventConflictError("event identity or idempotency key already has another payload")
        return None

    @staticmethod
    def _plan_transition(
        facts: Sequence[Mapping[str, Any]],
        incoming: Mapping[str, Any],
        resolution: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        for existing in facts:
            if existing["stable_id"] == incoming["stable_id"]:
                raise PromotionConflictError("fact stable identity already exists")
        current = [
            copy.deepcopy(dict(fact))
            for fact in facts
            if fact["project_id"] == incoming["project_id"]
            and fact["topic_slug"] == incoming["topic_slug"]
            and fact["fact_key"] == incoming["fact_key"]
            and fact["status"] == "current"
        ]
        changed: list[dict[str, Any]] = [copy.deepcopy(dict(incoming))]
        if not current:
            if resolution:
                raise PromotionConflictError("resolution has no current fact to resolve")
            if incoming["status"] == "disputed":
                raise PromotionConflictError("a disputed fact requires an existing current claim")
            return [
                *(copy.deepcopy(dict(item)) for item in facts),
                changed[0],
            ], changed, "created"

        if resolution == "supersede" and incoming["status"] == "current":
            targets = {fact["stable_id"] for fact in current}
            if set(incoming["supersedes"]) != targets:
                raise PromotionConflictError("supersedes must name every current same-key fact")
            replacements: dict[str, dict[str, Any]] = {}
            incoming_start = _timestamp(incoming["valid_from"], "fact.valid_from")
            for old in current:
                if incoming_start <= _timestamp(old["valid_from"], "fact.valid_from"):
                    raise PromotionConflictError("superseding valid time must follow the old fact")
                old["status"] = "historical"
                old["valid_to"] = incoming["valid_from"]
                old["updated_at"] = incoming["observed_at"]
                old["metadata"] = copy.deepcopy(dict(old.get("metadata") or {}))
                old["metadata"]["superseded_by"] = incoming["stable_id"]
                replacements[old["stable_id"]] = old
                changed.append(old)
            result = [replacements.get(fact["stable_id"], copy.deepcopy(dict(fact))) for fact in facts]
            result.append(changed[0])
            return result, changed, "superseded"

        if resolution == "disputed" and incoming["status"] == "disputed":
            if incoming["supersedes"] or not incoming["disputed_by"]:
                raise PromotionConflictError("disputed facts require evidence and cannot supersede")
            replacements = {}
            for old in current:
                old["status"] = "disputed"
                old["updated_at"] = incoming["observed_at"]
                old["disputed_by"] = sorted({*old["disputed_by"], incoming["stable_id"]})
                old["metadata"] = copy.deepcopy(dict(old.get("metadata") or {}))
                old["metadata"]["disputed_with"] = incoming["stable_id"]
                replacements[old["stable_id"]] = old
                changed.append(old)
            result = [replacements.get(fact["stable_id"], copy.deepcopy(dict(fact))) for fact in facts]
            result.append(changed[0])
            return result, changed, "disputed"

        raise PromotionConflictError("same-key fact requires explicit supersede or disputed resolution")

    def _write_fact(self, fact: Mapping[str, Any]) -> None:
        path = (
            self.canonical_root
            / "projects"
            / fact["project_id"]
            / "knowledge"
            / "topics"
            / fact["topic_slug"]
            / "facts"
            / fact["fact_key"]
            / f"{fact['stable_id']}.json"
        )
        _write_object(path, fact)

    def promote(
        self,
        request: Mapping[str, Any],
        *,
        expected_head: str | None = None,
    ) -> Mapping[str, Any]:
        """Promote one evidence-backed fact through an immutable event."""

        parent_head = self.head()
        if expected_head is not None and expected_head != parent_head:
            raise PromotionConflictError(
                f"canonical head changed: expected {expected_head}, found {parent_head}"
            )
        value = self._validate_request(request)
        resolved = self.evidence_resolver.resolve(value["fact"]["provenance"])
        project_ids = {record["project_id"] for record in resolved}
        if len(project_ids) != 1:
            raise PromotionValidationError("fact provenance has no single project")
        project_id = next(iter(project_ids))

        registered = bool(value["new_topic"])
        topic = (
            self._new_topic(project_id, value)
            if registered
            else self._resolve_topic(project_id, value["topic"])
        )
        fact = self._build_fact(value["fact"], project_id, topic["topic_slug"])
        resolution = value.get("resolution") or ""
        if resolution not in {"", "supersede", "disputed"}:
            raise PromotionValidationError("unknown promotion resolution")
        if fact["status"] == "rejected" and (
            resolution
            or fact["supersedes"]
            or fact["disputed_by"]
            or not isinstance(fact["metadata"].get("rejection_reason"), str)
            or not fact["metadata"]["rejection_reason"]
        ):
            raise PromotionValidationError("rejected facts require only a non-empty rejection reason")
        if fact["status"] == "current" and resolution != "supersede" and fact["supersedes"]:
            raise PromotionValidationError("supersedes requires explicit supersede resolution")
        if fact["status"] != "disputed" and fact["disputed_by"]:
            raise PromotionValidationError("disputed_by is only valid for disputed facts")

        operation_event = {
            "event_id": value["event_id"],
            "idempotency_key": value["idempotency_key"],
            "project_id": project_id,
            "topic_slug": topic["topic_slug"],
            "request": value,
        }
        existing_events = list(self.event_log.events())
        replay = self._event_replay(existing_events, operation_event)
        if replay is not None:
            return {
                "outcome": "noop",
                "stable_id": fact["stable_id"],
                "canonical_head": parent_head,
                "projection_head": parent_head,
                "topic_registered": False,
            }

        facts = self._facts()
        next_facts, changed, outcome = self._plan_transition(facts, fact, resolution)
        next_registry = copy.deepcopy(self._registry)
        if registered:
            next_registry["topics"].append(copy.deepcopy(topic))
            self._validate_registry(next_registry)

        event = {
            **operation_event,
            "event_type": f"knowledge.fact-{outcome}",
            "stable_id": fact["stable_id"],
            "occurred_at": fact["observed_at"],
            "changed_fact_ids": sorted(item["stable_id"] for item in changed),
            "outcome": outcome,
        }
        next_head = self._state_head(next_registry, next_facts, [*existing_events, event])
        for item in changed:
            item["canonical_head"] = next_head
            item["projection_head"] = next_head
            validate_record(item)
        by_id = {item["stable_id"]: item for item in changed}
        next_facts = [by_id.get(item["stable_id"], item) for item in next_facts]
        event.update(
            parent_head=parent_head,
            canonical_head=next_head,
            projection_head=next_head,
        )

        self.event_log.append(event)
        for item in changed:
            self._write_fact(item)
        if registered:
            self._registry = next_registry
            _write_object(self.canonical_root / "registry.json", self._registry)
            self._write_topic_documents()
        if self._state_head(self._registry, next_facts, self.event_log.events()) != next_head:
            raise PromotionValidationError("canonical knowledge generation did not converge")
        return {
            "outcome": outcome,
            "stable_id": fact["stable_id"],
            "canonical_head": next_head,
            "projection_head": next_head,
            "topic_registered": registered,
        }

    def query(
        self,
        *,
        project_id: str,
        topic: str,
        mode: str = "current",
        fact_key: str = "",
        as_of: str | None = None,
        now: str | None = None,
    ) -> Mapping[str, Any]:
        """Query canonical facts by topic/status or valid-time interval."""

        if mode not in _QUERY_MODES:
            raise PromotionValidationError(f"unsupported query mode: {mode!r}")
        resolved = self._resolve_topic(project_id, topic)
        topic_slug = resolved["topic_slug"]
        self.event_log.events(project_id=project_id, topic_slug=topic_slug)
        facts = [
            fact
            for fact in self._facts()
            if fact["project_id"] == project_id
            and fact["topic_slug"] == topic_slug
            and (not fact_key or fact["fact_key"] == fact_key)
        ]
        if mode == "current":
            facts = [fact for fact in facts if fact["status"] == "current"]
        elif mode == "rejected":
            facts = [fact for fact in facts if fact["status"] == "rejected"]
        elif mode == "superseded":
            facts = [fact for fact in facts if fact["status"] == "historical"]
        elif mode == "disputed":
            facts = [fact for fact in facts if fact["status"] == "disputed"]
        elif mode == "as_of":
            instant = _timestamp(as_of, "as_of")
            facts = [
                fact
                for fact in facts
                if fact["status"] in {"current", "historical"}
                and _timestamp(fact["valid_from"], "valid_from") <= instant
                and (
                    fact["valid_to"] is None
                    or instant < _timestamp(fact["valid_to"], "valid_to")
                )
            ]

        debt: list[str] = []
        if now is not None:
            instant = _timestamp(now, "now")
            derived = []
            for fact in facts:
                value = copy.deepcopy(fact)
                if value["status"] == "current" and _timestamp(
                    value["refresh_after"], "refresh_after"
                ) <= instant:
                    value["status"] = "stale-needs-validation"
                    debt.append(value["stable_id"])
                derived.append(value)
            facts = derived
        facts.sort(key=lambda item: (item["valid_from"], item["stable_id"]))
        head = self.head()
        return {
            "project_id": project_id,
            "topic_slug": topic_slug,
            "mode": mode,
            "facts": copy.deepcopy(facts),
            "count": len(facts),
            "validation_debt": sorted(debt),
            "canonical_head": head,
            "projection_head": head,
        }


_ACTIVE_SERVICE: KnowledgeService | None = None


def _service() -> KnowledgeService:
    if _ACTIVE_SERVICE is None:
        raise KnowledgeNotConfiguredError("knowledge service is not configured")
    return _ACTIVE_SERVICE


@contextmanager
def knowledge_service_mode(
    *,
    canonical_root: Path,
    registry_path: Path,
    task_store: Any,
) -> Iterator[KnowledgeService]:
    """Temporarily configure the production module-level knowledge entry points."""

    global _ACTIVE_SERVICE
    previous = _ACTIVE_SERVICE
    service = KnowledgeService(
        canonical_root=canonical_root,
        registry_path=registry_path,
        task_store=task_store,
    )
    _ACTIVE_SERVICE = service
    try:
        yield service
    finally:
        _ACTIVE_SERVICE = previous


def knowledge_head() -> str:
    """Return the current canonical fact generation."""

    return _service().head()


def promote_fact(
    request: Mapping[str, Any],
    *,
    expected_head: str | None = None,
) -> Mapping[str, Any]:
    """Promote through the configured ``KnowledgeService`` owner."""

    return _service().promote(request, expected_head=expected_head)


def query_facts(
    *,
    project_id: str,
    topic: str,
    mode: str = "current",
    fact_key: str = "",
    as_of: str | None = None,
    now: str | None = None,
) -> Mapping[str, Any]:
    """Query through the configured ``KnowledgeService`` owner."""

    return _service().query(
        project_id=project_id,
        topic=topic,
        mode=mode,
        fact_key=fact_key,
        as_of=as_of,
        now=now,
    )
