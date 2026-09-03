#!/usr/bin/env python3
"""Import extracted KB evidence and promote the resulting canonical facts."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_SOURCE_FIELDS = {
    "statement",
    "reason",
    "decided_at",
    "evidence",
    "source_file",
    "source_lines",
    "status",
    "topic",
}
OPTIONAL_SOURCE_FIELDS = {"kind"}
DEFAULT_TASK_MAP = {1: 399, 2: 400, 3: 401, 4: 402, 5: 403}
FACT_NAMESPACE = uuid.UUID("d9313850-7015-4b90-95fa-2303237ec836")
EVIDENCE_NAMESPACE = uuid.UUID("d9b36282-236c-4745-8c11-d69e199f2769")
EVENT_NAMESPACE = uuid.UUID("bb457ae7-5781-4aa4-9aaf-cc3130b70dd6")
EXTRACTED_AT = "2026-08-26T00:00:00+00:00"
CYRILLIC = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
    "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
})


@dataclass(frozen=True)
class SourceFact:
    part: int
    position: int
    value: dict[str, Any]


@dataclass(frozen=True)
class ReadyFact:
    source: SourceFact
    stable_id: str
    evidence_id: str
    topic_slug: str
    task_id: str
    project: str
    resource: dict[str, Any]


class RequestFailure(RuntimeError):
    pass


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def load_facts(directory: Path) -> list[SourceFact]:
    result: list[SourceFact] = []
    paths = sorted(directory.glob("part-*.json"))
    if not paths:
        raise ValueError(f"no part-*.json files in {directory}")
    for path in paths:
        match = re.fullmatch(r"part-(\d+)\.json", path.name)
        if match is None:
            continue
        part = int(match.group(1))
        values = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(values, list):
            raise ValueError(f"{path}: expected a JSON array")
        for position, value in enumerate(values, start=1):
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{position}: expected a JSON object")
            result.append(SourceFact(part=part, position=position, value=value))
    return result


def stable_fact_id(value: dict[str, Any]) -> str:
    identity = "\n".join((
        str(value.get("source_file") or ""),
        str(value.get("source_lines") or ""),
        str(value.get("statement") or ""),
    ))
    return str(uuid.uuid5(FACT_NAMESPACE, identity))


def stable_evidence_id(fact_id: str) -> str:
    return str(uuid.uuid5(EVIDENCE_NAMESPACE, fact_id))


def _topic_base(value: str) -> str:
    transliterated = value.casefold().translate(CYRILLIC)
    cleaned = re.sub(r"[^a-z0-9]+", "-", transliterated).strip("-")
    if not cleaned:
        cleaned = hashlib.sha256(value.encode()).hexdigest()[:12]
    return f"kb-{cleaned[:52].rstrip('-')}"


def topic_slugs(labels: set[str]) -> dict[str, str]:
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for label in labels:
        groups[_topic_base(label)].append(label)
    result = {}
    for base, values in groups.items():
        for label in sorted(values):
            suffix = ""
            if len(values) > 1:
                suffix = "-" + hashlib.sha256(label.encode()).hexdigest()[:8]
            result[label] = base[: 63 - len(suffix)].rstrip("-") + suffix
    return result


def parse_task_map(raw: str) -> dict[int, int]:
    result = {}
    for item in raw.split(","):
        left, separator, right = item.partition("=")
        if not separator:
            raise ValueError(f"invalid task map item: {item!r}")
        result[int(left)] = int(right)
    return result


def _task_states(canonical_root: Path, project: str) -> dict[int, dict[str, Any]]:
    result = {}
    root = canonical_root / "tasks/projects" / project / "tasks"
    for path in root.glob("*/state.json"):
        value = _json(path)
        number = int(value.get("display_number") or 0)
        if number in result:
            raise ValueError(f"duplicate canonical task #{number}")
        stable_id = str(value.get("stable_id") or "")
        identity_errors = []
        try:
            if str(uuid.UUID(stable_id)) != stable_id:
                raise ValueError
        except ValueError:
            identity_errors.append("stable_id")
        if stable_id != path.parent.name:
            identity_errors.append("path")
        if value.get("project_id") != project:
            identity_errors.append("project_id")
        if value.get("record_type") != "task.state":
            identity_errors.append("record_type")
        if value.get("uri") != f"orch://project/{project}/tasks/{stable_id}/state":
            identity_errors.append("uri")
        value["_identity_errors"] = identity_errors
        result[number] = value
    return result


def _resources(canonical_root: Path, project: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for path in (canonical_root / "evidence" / project).glob("*.json"):
        value = _json(path)
        if value.get("record_type") == "resource" and value.get("source_path"):
            result[str(value["source_path"])].append(value)
    return result


def resource_inventory(canonical_root: Path, project: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    paths = sorted((canonical_root / "evidence" / project).glob("*.json"))
    for path in paths:
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return len(paths), f"sha256:{digest.hexdigest()}"


def _fact_records(canonical_root: Path, project: str) -> dict[str, dict[str, Any]]:
    facts = {}
    for path in (canonical_root / "knowledge/projects" / project).glob(
        "topics/*/facts/*/*.json"
    ):
        try:
            facts[path.stem] = _json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            facts[path.stem] = {"_unreadable": True}
    return facts


def _existing_evidence_ids(canonical_root: Path, project: str) -> set[str]:
    evidence = {
        path.stem
        for path in (canonical_root / "tasks/projects" / project).glob(
            "tasks/*/evidence/*.json"
        )
    }
    return evidence


def _contains(record: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(record.get(name) == value for name, value in expected.items())


def _resource_identity_valid(record: dict[str, Any], project: str) -> bool:
    stable_id = str(record.get("stable_id") or "")
    try:
        if str(uuid.UUID(stable_id)) != stable_id:
            return False
    except ValueError:
        return False
    return (
        record.get("project_id") == project
        and record.get("uri") == f"orch://project/{project}/resources/{stable_id}"
    )


def _completion_state(
    item: ReadyFact,
    canonical_root: Path,
    fact_records: dict[str, dict[str, Any]],
) -> str:
    fact = fact_records.get(item.stable_id)
    if fact is None:
        return "missing"
    expected_fact = {
        **_fact_payload(item),
        "record_type": "knowledge.fact",
        "project_id": item.project,
        "topic_slug": item.topic_slug,
    }
    if not _contains(fact, expected_fact):
        return "conflict"

    source = import_request(item, Path.cwd(), item.project)
    evidence_uri = source["canonical_uri"]
    expected_task_evidence = {
        "record_type": "task.evidence",
        "stable_id": item.evidence_id,
        "uri": evidence_uri,
        "task_id": item.task_id,
        "project_id": item.project,
        "kind": source["class"],
        "canonical_path": source["path"],
        "anchor": source["anchor"],
        "git_commit": source["git_commit"],
        "content_sha256": source["content_sha256"],
    }
    task_evidence_path = canonical_root / (
        f"tasks/projects/{item.project}/tasks/{item.task_id}/evidence/{item.evidence_id}.json"
    )
    if task_evidence_path.is_file():
        try:
            if not _contains(_json(task_evidence_path), expected_task_evidence):
                return "conflict"
        except (OSError, ValueError, json.JSONDecodeError):
            return "conflict"
    else:
        return "incomplete"
    task_state_path = task_evidence_path.parents[1] / "state.json"
    if evidence_uri not in (_json(task_state_path).get("evidence_refs") or []):
        return "incomplete"

    knowledge_ref_path = canonical_root / (
        f"knowledge/projects/{item.project}/evidence/{item.evidence_id}.json"
    )
    expected_ref = {
        "record_type": "knowledge.evidence-ref",
        "stable_id": item.evidence_id,
        "uri": evidence_uri,
        "project_id": item.project,
        "source_path": source["path"],
        "source_class": source["class"],
        "source_sha256": source["content_sha256"],
        "git_commit": source["git_commit"],
        "anchor": source["anchor"],
        "storage": "cold-immutable-reference",
    }
    if knowledge_ref_path.is_file():
        try:
            if not _contains(_json(knowledge_ref_path), expected_ref):
                return "conflict"
        except (OSError, ValueError, json.JSONDecodeError):
            return "conflict"
    else:
        return "incomplete"
    index_path = canonical_root / "knowledge/archive-index.json"
    if not index_path.is_file():
        return "incomplete"
    try:
        archive_index = _json(index_path)
        if archive_index.get("index_version") != 1:
            return "conflict"
        raw_entries = archive_index.get("evidence_refs")
        if not isinstance(raw_entries, list) or any(
            not isinstance(entry, dict) for entry in raw_entries
        ):
            return "conflict"
        entries = [
            entry for entry in raw_entries if entry.get("stable_id") == item.evidence_id
        ]
    except (OSError, ValueError, json.JSONDecodeError):
        return "conflict"
    expected_entry = {
        "stable_id": item.evidence_id,
        "uri": evidence_uri,
        "project_id": item.project,
        "source_path": source["path"],
        "source_sha256": source["content_sha256"],
    }
    if not entries:
        return "incomplete"
    return "complete" if entries == [expected_entry] else "conflict"


def _known_topics(canonical_root: Path, project: str) -> set[str]:
    path = canonical_root / "knowledge/registry.json"
    if not path.is_file():
        return set()
    registry = _json(path)
    return {
        str(topic["topic_slug"])
        for topic in registry.get("topics") or []
        if topic.get("project_id") == project
    }


def _source_error(value: dict[str, Any], repo_root: Path) -> list[str]:
    reasons = []
    fields = set(value)
    if fields - REQUIRED_SOURCE_FIELDS - OPTIONAL_SOURCE_FIELDS:
        reasons.append("invalid_source_fields")
    if REQUIRED_SOURCE_FIELDS - fields:
        reasons.append("missing_source_fields")
    for name in ("statement", "evidence", "source_file", "source_lines", "topic"):
        if not isinstance(value.get(name), str) or not value[name].strip():
            reasons.append(f"empty_{name}")
    if value.get("status") not in {"current", "rejected"}:
        reasons.append("invalid_status")
    if "kind" in value and value["kind"] not in {"rule", "state", "lesson"}:
        reasons.append("invalid_kind")
    if value.get("decided_at") is not None and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", str(value["decided_at"])
    ) is None:
        reasons.append("invalid_decided_at")
    source = repo_root / str(value.get("source_file") or "")
    try:
        source.resolve().relative_to(repo_root.resolve())
    except ValueError:
        reasons.append("source_outside_repo")
    if not source.is_file():
        reasons.append("source_file_missing")
    return reasons


def _fact_payload(item: ReadyFact) -> dict[str, Any]:
    value = item.source.value
    decided = value.get("decided_at")
    valid_from = f"{decided}T00:00:00+00:00" if decided else EXTRACTED_AT
    reason = value.get("reason")
    metadata = {
        "reason": reason,
        "decided_at": decided,
        "valid_from_basis": "source_decided_at" if decided else "extraction_observed_at",
        "evidence": value["evidence"],
        "source_file": value["source_file"],
        "source_lines": value["source_lines"],
        "kind": value.get("kind"),
        "topic_label": value["topic"],
        "source_resource_uri": item.resource["uri"],
    }
    if value["status"] == "rejected":
        metadata["rejection_reason"] = reason or value["evidence"]
    return {
        "stable_id": item.stable_id,
        "fact_key": f"fact-{item.stable_id}",
        "claim": value["statement"],
        "status": value["status"],
        "confidence": "verified",
        "valid_from": valid_from,
        "valid_to": None,
        "observed_at": EXTRACTED_AT,
        "refresh_after": "9999-12-31T00:00:00+00:00",
        "provenance": [{
            "task_id": item.task_id,
            "evidence_uri": (
                f"orch://project/{item.project}/tasks/{item.task_id}/evidence/{item.evidence_id}"
            ),
            "path": value["source_file"],
            "anchor": value["source_lines"],
            "git_commit": item.resource["git_commit"],
            "measurement": value["evidence"],
        }],
        "supersedes": [],
        "disputed_by": [],
        "metadata": metadata,
    }


def promotion_request(item: ReadyFact, *, new_topic: bool) -> dict[str, Any]:
    request = {
        "event_id": str(uuid.uuid5(EVENT_NAMESPACE, item.stable_id)),
        "idempotency_key": f"kb-extract:{item.stable_id}",
        "topic": item.topic_slug,
        "new_topic": new_topic,
        "fact": _fact_payload(item),
    }
    if new_topic:
        request.update(
            topic_summary=f"Извлечённая тема: {item.source.value['topic']}.",
            aliases=[],
        )
    return request


def import_request(item: ReadyFact, repo_root: Path, project: str) -> dict[str, Any]:
    value = item.source.value
    return {
        "path": value["source_file"],
        "class": "immutable-evidence",
        "project_id": project,
        "stable_id": item.evidence_id,
        "canonical_uri": (
            f"orch://project/{project}/tasks/{item.task_id}/evidence/{item.evidence_id}"
        ),
        "git_commit": item.resource["git_commit"],
        "anchor": value["source_lines"],
        "content_sha256": item.resource["source_sha256"],
        "source_root": str(repo_root.resolve()),
    }


def preflight(
    facts: list[SourceFact],
    *,
    repo_root: Path,
    canonical_root: Path,
    project: str,
    task_map: dict[int, int],
) -> tuple[list[ReadyFact], dict[str, list[str]]]:
    from app.ia.knowledge import KnowledgeService

    tasks = _task_states(canonical_root, project)
    resources = _resources(canonical_root, project)
    slugs = topic_slugs({str(fact.value.get("topic") or "") for fact in facts})
    identity_counts = collections.Counter(stable_fact_id(fact.value) for fact in facts)
    ready = []
    rejected: dict[str, list[str]] = {}
    for source in facts:
        value = source.value
        fact_id = stable_fact_id(value)
        reasons = _source_error(value, repo_root)
        if identity_counts[fact_id] > 1:
            reasons.append("duplicate_stable_id")
        task_number = task_map.get(source.part)
        task = tasks.get(task_number or -1)
        expected_output = f"part-{source.part}.json"
        if task_number is None:
            reasons.append("task_map_missing")
        elif task is None:
            reasons.append("canonical_task_not_found")
        elif task.get("_identity_errors"):
            reasons.append("canonical_task_record_invalid")
        elif expected_output not in str(task.get("title") or ""):
            reasons.append("canonical_task_identity_mismatch")

        source_path = str(value.get("source_file") or "")
        source_file = repo_root / source_path
        matches = []
        if source_file.is_file():
            digest = f"sha256:{hashlib.sha256(source_file.read_bytes()).hexdigest()}"
            matches = [
                record for record in resources.get(source_path, [])
                if record.get("source_sha256") == digest
                and re.fullmatch(r"[0-9a-f]{40}", str(record.get("git_commit") or ""))
            ]
        if not matches:
            reasons.append("current_source_evidence_missing")
        if reasons:
            rejected[f"part-{source.part}:{source.position}:{fact_id}"] = sorted(set(reasons))
            continue
        if any(not _resource_identity_valid(record, project) for record in matches):
            rejected[f"part-{source.part}:{source.position}:{fact_id}"] = [
                "resource_identity_invalid"
            ]
            continue
        resource = sorted(matches, key=lambda item: (
            str(item["git_commit"]), str(item["stable_id"])
        ))[-1]
        candidate = ReadyFact(
            source=source,
            stable_id=fact_id,
            evidence_id=stable_evidence_id(fact_id),
            topic_slug=slugs[value["topic"]],
            task_id=str(task["stable_id"]),
            project=project,
            resource=resource,
        )
        try:
            KnowledgeService._cold_source_path(import_request(
                candidate, repo_root, project
            )["path"])
            request = promotion_request(candidate, new_topic=False)
            KnowledgeService._validate_request(request)
            KnowledgeService._build_fact(request["fact"], project, candidate.topic_slug)
        except (ImportError, TypeError, ValueError) as exc:
            rejected[f"part-{source.part}:{source.position}:{fact_id}"] = [
                f"invalid_fact_payload:{type(exc).__name__}:{exc}"
            ]
            continue
        ready.append(candidate)
    return ready, rejected


class KnowledgeClient:
    def __init__(self, *, url: str, timeout: float) -> None:
        token = os.environ.get("INTERNAL_TOKEN", "")
        session = os.environ.get("ORCHESTRA_SESSION_ID", "")
        proof = os.environ.get("ORCHESTRA_MCP_PROOF", "")
        if not token or not session or not proof:
            raise RequestFailure(
                "--apply requires INTERNAL_TOKEN, ORCHESTRA_SESSION_ID and ORCHESTRA_MCP_PROOF"
            )
        self.url = url.rstrip("/") + "/api/knowledge"
        self.timeout = timeout
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Orchestra-Session-Id": session,
            "X-Orchestra-Mcp-Proof": proof,
        }

    def call(self, operation: str, *, detail: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({
            "operation": operation,
            "detail": detail,
            "payload": payload,
        }, ensure_ascii=False).encode()
        request = urllib.request.Request(
            self.url, data=body, headers=self.headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            try:
                error = json.loads(raw).get("error", {})
                message = f"{error.get('code', exc.code)}: {error.get('message', raw)}"
            except ValueError:
                message = f"HTTP {exc.code}: {raw}"
            raise RequestFailure(message) from exc
        except (OSError, ValueError) as exc:
            raise RequestFailure(f"{type(exc).__name__}: {exc}") from exc
        if not isinstance(result, dict):
            raise RequestFailure("knowledge response is not a JSON object")
        return result


def _default_canonical_root() -> Path:
    configured = os.environ.get("ORCHESTRA_KNOWLEDGE_CANONICAL_ROOT", "")
    candidates = [
        Path(configured) if configured else Path("__missing__"),
        Path.home() / ".local/state/orchestra/knowledge-v1/canonical",
        Path("data/knowledge-v1/canonical"),
    ]
    return next((path for path in candidates if path.is_dir()), candidates[1])


def _reason_counts(rejected: dict[str, list[str]]) -> collections.Counter[str]:
    return collections.Counter(reason for reasons in rejected.values() for reason in reasons)


def _apply_succeeded(
    failures: list[tuple[str, str]],
    inventory_unchanged: bool,
    complete_count: int,
    expected_count: int,
) -> bool:
    return not failures and inventory_unchanged and complete_count == expected_count


def _print_failures(failures: list[tuple[str, str]]) -> None:
    if not failures:
        return
    print("failures:")
    for identity, reason in failures:
        print(f"  {identity}: {reason}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--facts-dir", type=Path, default=Path(".orchestra/tasks/kb-extract"))
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--canonical-root", type=Path, default=_default_canonical_root())
    parser.add_argument("--project", default="orchestra")
    parser.add_argument("--task-map", default="1=399,2=400,3=401,4=402,5=403")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--expected-count", type=int, default=764)
    parser.add_argument("--progress-every", type=int, default=50)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--url", default=os.environ.get("ORCHESTRA_URL", "http://127.0.0.1:8888"))
    args = parser.parse_args(argv)

    try:
        facts = load_facts(args.facts_dir)
        if not args.limit and len(facts) != args.expected_count:
            raise ValueError(
                f"expected {args.expected_count} facts, found {len(facts)}"
            )
        if args.limit < 0 or args.progress_every < 1:
            raise ValueError("--limit must be non-negative and --progress-every must be positive")
        if args.limit:
            facts = facts[: args.limit]
        task_map = parse_task_map(args.task_map)
        ready, rejected = preflight(
            facts,
            repo_root=args.source_root,
            canonical_root=args.canonical_root,
            project=args.project,
            task_map=task_map,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"fatal={type(exc).__name__}: {exc}")
        return 2

    fact_records = _fact_records(args.canonical_root, args.project)
    existing_evidence = _existing_evidence_ids(args.canonical_root, args.project)
    already = []
    pending = []
    for item in ready:
        state = _completion_state(item, args.canonical_root, fact_records)
        if state == "complete":
            already.append(item)
        elif state == "conflict":
            identity = f"part-{item.source.part}:{item.source.position}:{item.stable_id}"
            rejected[identity] = ["existing_canonical_conflict"]
        else:
            pending.append(item)
    evidence_needed = len(pending)
    statuses = collections.Counter(str(fact.value.get("status")) for fact in facts)
    inventory_before = resource_inventory(args.canonical_root, args.project)
    print(f"mode={'apply' if args.apply else 'dry-run'}")
    print(
        f"loaded={len(facts)} status_current={statuses['current']} "
        f"status_rejected={statuses['rejected']} topics={len({item.topic_slug for item in ready})}"
    )
    print(
        f"ready_to_write={len(pending)} already_exists={len(already)} "
        f"preflight_rejected={len(rejected)}"
    )
    print(
        f"evidence_imports_needed={evidence_needed} "
        f"task_evidence_files_present={sum(item.evidence_id in existing_evidence for item in pending)}"
    )
    print(f"resource_inventory={inventory_before[0]} {inventory_before[1]}")
    for reason, count in sorted(_reason_counts(rejected).items()):
        print(f"rejected_reason[{reason}]={count}")

    if rejected:
        _print_failures([(identity, ",".join(reasons)) for identity, reasons in rejected.items()])
        return 2
    if not args.apply:
        return 0

    try:
        client = KnowledgeClient(url=args.url, timeout=args.timeout)
    except RequestFailure as exc:
        print(f"fatal={exc}")
        return 2

    known_topics = _known_topics(args.canonical_root, args.project)
    created = noops = imported = import_noops = 0
    failures: list[tuple[str, str]] = []
    sample: ReadyFact | None = None
    for index, item in enumerate(pending, start=1):
        identity = f"part-{item.source.part}:{item.source.position}:{item.stable_id}"
        try:
            imported_result = client.call(
                "import_evidence",
                detail="record",
                payload={"source": import_request(item, args.source_root, args.project)},
            )
            if imported_result.get("outcome") == "created":
                imported += 1
            else:
                import_noops += 1
            promoted = client.call(
                "promote",
                detail="record",
                payload={"request": promotion_request(
                    item, new_topic=item.topic_slug not in known_topics
                )},
            )
            if promoted.get("outcome") == "noop":
                noops += 1
            else:
                created += 1
            known_topics.add(item.topic_slug)
            sample = sample or item
        except RequestFailure as exc:
            failures.append((identity, str(exc)))
        if index % args.progress_every == 0 or index == len(pending):
            print(
                f"progress={index}/{len(pending)} facts_created={created} "
                f"facts_noop={noops} failed={len(failures)}"
            )

    inventory_after = resource_inventory(args.canonical_root, args.project)
    inventory_unchanged = inventory_after == inventory_before
    final_records = _fact_records(args.canonical_root, args.project)
    canonical_batch_count = sum(item.stable_id in final_records for item in ready)
    canonical_complete_count = sum(
        _completion_state(item, args.canonical_root, final_records) == "complete"
        for item in ready
    )
    print(
        f"result facts_created={created} facts_noop={noops} "
        f"evidence_created={imported} evidence_noop={import_noops} failed={len(failures)}"
    )
    print(f"canonical_batch_facts={canonical_batch_count}")
    print(f"canonical_batch_complete={canonical_complete_count}")
    print(
        f"resource_inventory_after={inventory_after[0]} {inventory_after[1]} "
        f"unchanged={str(inventory_unchanged).lower()}"
    )
    if sample is not None:
        try:
            verification = client.call(
                "query",
                detail="record",
                payload={"topic": sample.topic_slug, "mode": "all"},
            )
            item = next(
                value for value in verification.get("items", [])
                if value.get("stable_id") == sample.stable_id
            )
            print("verification=" + json.dumps({
                "topic": sample.topic_slug,
                "claim": item["claim"],
                "reason": item["metadata"]["reason"],
                "evidence": item["metadata"]["evidence"],
            }, ensure_ascii=False, sort_keys=True))
        except (RequestFailure, KeyError, StopIteration) as exc:
            failures.append(("verification", f"{type(exc).__name__}: {exc}"))
    _print_failures(failures)
    return 0 if _apply_succeeded(
        failures, inventory_unchanged, canonical_complete_count, len(ready)
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
