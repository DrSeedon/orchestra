"""Reversible, generation-bound cutover from legacy documents to typed JSON."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class DocumentCutoverError(RuntimeError):
    """Raised when document ownership cannot advance without losing evidence."""


_REQUIRED_PROMPT_ANCHORS = (
    "Use the single `knowledge` tool for canonical knowledge and evidence operations.",
    "Request progressive detail as `summary` < `record` < `evidence`.",
    "Use typed `orch://` identifiers for task, fact, evidence, session, resource, and skill references.",
    "Markdown files, SQLite, FTS, and vector hits are never independent truth.",
    "Historical Markdown and session archives are immutable cold evidence and are never regenerated.",
    "Canonical task, fact, evidence-reference, and session events are structured Git JSON.",
)
_FORBIDDEN_LEGACY_DIRECTIVES = (
    "Read `docs/kb/README.md`",
    "Write `docs/tasks/<task-id>/research.md`",
    "Append the conclusion to its topic file in `docs/kb/`",
    "`search_memory(\"<goal + subsystem or symptom>\")`",
    "Durable knowledge goes to files in the repo",
    "Report in docs/tasks/<id>/report.md",
)
_REQUIRED_GATES = {
    "shadow_parity",
    "privacy",
    "rollback",
    "prompt_delivery",
    "live_cutover",
    "projection",
}
_REQUIRED_ENTRY_FIELDS = {
    "path",
    "source_class",
    "source_commit",
    "git_blob",
    "source_sha256",
    "size",
    "alias",
}
_RECEIPT_NAMESPACE = uuid.UUID("31500000-0000-4000-8000-000000000358")


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
        raise DocumentCutoverError("cutover data is not canonical JSON") from exc


def _detached(value: Any) -> Any:
    return json.loads(_canonical_bytes(value))


def _manifest_head(manifest: Mapping[str, Any]) -> str:
    body = copy.deepcopy(dict(manifest))
    body.pop("manifest_head", None)
    return "sha256:" + hashlib.sha256(_canonical_bytes(body)).hexdigest()


def _normalized_inventory(manifest: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, Mapping):
        raise DocumentCutoverError("inventory must be an object")
    entries = manifest.get("entries")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)) or not entries:
        raise DocumentCutoverError("inventory entries must be nonempty")
    normalized = []
    for entry in entries:
        if not isinstance(entry, Mapping) or not _REQUIRED_ENTRY_FIELDS <= set(entry):
            raise DocumentCutoverError("inventory entry is missing required fields")
        normalized.append({name: copy.deepcopy(entry[name]) for name in _REQUIRED_ENTRY_FIELDS})
    normalized.sort(key=lambda value: value["path"])
    if len(normalized) != len({entry["path"] for entry in normalized}):
        raise DocumentCutoverError("inventory contains duplicate paths")
    if len(normalized) != len({entry["alias"] for entry in normalized}):
        raise DocumentCutoverError("inventory contains duplicate aliases")
    class_counts: dict[str, int] = {}
    for entry in normalized:
        source_class = str(entry["source_class"])
        class_counts[source_class] = class_counts.get(source_class, 0) + 1
    if dict(sorted(class_counts.items())) != manifest.get("class_counts"):
        raise DocumentCutoverError("inventory class counts do not match its entries")
    if manifest.get("manifest_head") != _manifest_head(manifest):
        raise DocumentCutoverError("inventory manifest head is not content-bound")
    return {
        "schema_version": manifest.get("schema_version"),
        "project_id": manifest.get("project_id"),
        "source_commit": manifest.get("source_commit"),
        "class_counts": copy.deepcopy(manifest.get("class_counts")),
        "entries": normalized,
        "manifest_head": manifest.get("manifest_head"),
    }


def _git_source_bytes(root: Path, manifest: Mapping[str, Any]) -> dict[str, bytes] | None:
    try:
        inside = subprocess.check_output(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    if inside != "true":
        return None
    source_commit = str(manifest.get("source_commit") or "")
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", f"{source_commit}^{{commit}}"],
            cwd=root,
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
        raw_tree = subprocess.check_output(
            ["git", "ls-tree", "-r", "-z", "--format=%(objectname)%x09%(path)", commit],
            cwd=root,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise DocumentCutoverError("cannot read the inventory source commit") from exc
    if commit != source_commit:
        raise DocumentCutoverError("inventory source commit is not fully pinned")
    tree = {}
    for item in raw_tree.split(b"\0"):
        if item:
            blob, path = item.split(b"\t", 1)
            tree[path.decode("utf-8")] = blob.decode("ascii")
    entries = manifest["entries"]
    for entry in entries:
        if tree.get(entry["path"]) != entry["git_blob"]:
            raise DocumentCutoverError(f"frozen Git path/blob mismatch: {entry['path']}")

    process = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = "".join(f"{entry['git_blob']}\n" for entry in entries).encode("ascii")
    output, error = process.communicate(payload)
    if process.returncode != 0:
        raise DocumentCutoverError(
            f"cannot read frozen Git blobs: {error.decode('utf-8', errors='replace').strip()}"
        )
    result: dict[str, bytes] = {}
    offset = 0
    for entry in entries:
        try:
            header_end = output.index(b"\n", offset)
        except ValueError as exc:
            raise DocumentCutoverError("truncated frozen Git blob response") from exc
        header = output[offset:header_end].decode("ascii").split()
        if len(header) != 3 or header[:2] != [entry["git_blob"], "blob"]:
            raise DocumentCutoverError(f"unexpected frozen blob for {entry['path']}")
        size = int(header[2])
        start = header_end + 1
        end = start + size
        if output[end:end + 1] != b"\n":
            raise DocumentCutoverError(f"truncated frozen blob for {entry['path']}")
        result[entry["path"]] = output[start:end]
        offset = end + 1
    if offset != len(output):
        raise DocumentCutoverError("unexpected trailing frozen Git blob response")
    return result


def _source_bytes(context: "_CutoverContext", manifest: Mapping[str, Any]) -> dict[str, bytes]:
    values = _git_source_bytes(context.repository_root, manifest)
    if values is None:
        values = {}
        for entry in manifest["entries"]:
            path = context.repository_root / entry["path"]
            try:
                values[entry["path"]] = path.read_bytes()
            except OSError as exc:
                raise DocumentCutoverError(f"cannot read historical source: {entry['path']}") from exc
    for entry in manifest["entries"]:
        content = values[entry["path"]]
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if len(content) != entry["size"] or digest != entry["source_sha256"]:
            raise DocumentCutoverError(f"historical source bytes changed: {entry['path']}")
    return values


def _assert_json_only(root: Path) -> None:
    if not root.exists():
        return
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() != ".json"
    ]
    if offenders:
        raise DocumentCutoverError(f"canonical store contains non-JSON dual truth: {offenders}")


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(_canonical_bytes(value) + b"\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass
class _CutoverContext:
    canonical_root: Path
    repository_root: Path
    frozen_inventory: dict[str, Any]
    knowledge_request: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    prompt_assembler: Callable[[str, str], str]
    projection_probe: Callable[[], Mapping[str, Any]]
    receipt_writer: Callable[[Path, Mapping[str, Any]], Any]
    legacy_reader: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    projection_delete: Callable[[str], Any]
    active_owner: str = "legacy"
    shadow_owner: str | None = None
    generation: int = 1
    canonical_head: str | None = None
    prompt_delivery_head: str | None = None
    shadow_response: dict[str, Any] | None = None
    receipts: list[dict[str, Any]] = field(default_factory=list)


_ACTIVE_CUTOVER: ContextVar[_CutoverContext | None] = ContextVar(
    "ia_document_cutover", default=None,
)


def _context() -> _CutoverContext:
    context = _ACTIVE_CUTOVER.get()
    if context is None:
        raise DocumentCutoverError("document cutover owner is not configured")
    return context


@contextmanager
def document_cutover_mode(
    *,
    canonical_root: Path,
    repository_root: Path,
    frozen_inventory: Mapping[str, Any],
    knowledge_request: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    prompt_assembler: Callable[[str, str], str],
    projection_probe: Callable[[], Mapping[str, Any]],
    receipt_writer: Callable[[Path, Mapping[str, Any]], Any],
    legacy_reader: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    projection_delete: Callable[[str], Any],
) -> Iterator[None]:
    """Temporarily configure the sole document ownership state machine."""

    frozen = _detached(frozen_inventory)
    _normalized_inventory(frozen)
    context = _CutoverContext(
        canonical_root=Path(canonical_root),
        repository_root=Path(repository_root),
        frozen_inventory=frozen,
        knowledge_request=knowledge_request,
        prompt_assembler=prompt_assembler,
        projection_probe=projection_probe,
        receipt_writer=receipt_writer,
        legacy_reader=legacy_reader,
        projection_delete=projection_delete,
    )
    token = _ACTIVE_CUTOVER.set(context)
    try:
        yield
    finally:
        _ACTIVE_CUTOVER.reset(token)


def _prompt_receipt(context: _CutoverContext, runtime_matrix: Mapping[str, Any]) -> str:
    runtimes = runtime_matrix.get("runtimes")
    roles = runtime_matrix.get("roles")
    if not isinstance(runtimes, Sequence) or isinstance(runtimes, (str, bytes)) or not runtimes:
        raise DocumentCutoverError("runtime matrix has no runtimes")
    if not isinstance(roles, Sequence) or isinstance(roles, (str, bytes)) or not roles:
        raise DocumentCutoverError("runtime matrix has no roles")
    delivered = []
    for runtime in runtimes:
        for role in roles:
            prompt = context.prompt_assembler(str(runtime), str(role))
            if not isinstance(prompt, str) or not prompt.strip():
                raise DocumentCutoverError(f"empty assembled prompt for {runtime}/{role}")
            normalized = " ".join(prompt.split())
            for anchor in _REQUIRED_PROMPT_ANCHORS:
                if " ".join(anchor.split()) not in normalized:
                    raise DocumentCutoverError(
                        f"assembled prompt for {runtime}/{role} is missing cutover policy"
                    )
            for directive in _FORBIDDEN_LEGACY_DIRECTIVES:
                if " ".join(directive.split()) in normalized:
                    raise DocumentCutoverError(
                        f"assembled prompt for {runtime}/{role} contains a legacy directive"
                    )
            delivered.append({"runtime": runtime, "role": role, "prompt": normalized})
    return "sha256:" + hashlib.sha256(_canonical_bytes(delivered)).hexdigest()


def _probe(context: _CutoverContext) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        probe = context.projection_probe()
    except Exception as exc:
        raise DocumentCutoverError("projection/gate probe failed") from exc
    if not isinstance(probe, Mapping):
        raise DocumentCutoverError("projection/gate probe is not an object")
    gates = probe.get("gates")
    heads = probe.get("heads")
    if not isinstance(gates, Mapping) or not isinstance(heads, Mapping):
        raise DocumentCutoverError("projection/gate probe lacks gates or heads")
    return copy.deepcopy(dict(gates)), copy.deepcopy(dict(heads))


def _verified_gates(gates: Mapping[str, Any], required: set[str]) -> None:
    if not _REQUIRED_GATES <= required or not required <= set(gates):
        raise DocumentCutoverError("canonical cutover does not bind every required gate")
    for name in required:
        gate = gates.get(name)
        if not isinstance(gate, Mapping) or gate.get("status") != "verified":
            raise DocumentCutoverError(f"cutover gate is not verified: {name}")
    parity = gates["shadow_parity"]
    if (
        parity.get("mismatch_count") != 0
        or parity.get("legacy_normalized_head") != parity.get("canonical_normalized_head")
    ):
        raise DocumentCutoverError("shadow parity receipt is forged or mismatched")
    if gates["privacy"].get("secret_match_count") != 0:
        raise DocumentCutoverError("privacy gate found secret material")
    if gates["rollback"].get("replay_mismatch_count") != 0:
        raise DocumentCutoverError("rollback rehearsal does not reproduce legacy reads")
    if gates["prompt_delivery"].get("missing_runtime_count") != 0:
        raise DocumentCutoverError("prompt delivery gate has missing runtimes")
    if not gates["live_cutover"].get("receipt_id"):
        raise DocumentCutoverError("live cutover receipt is absent")
    projection = gates["projection"]
    if not projection.get("rebuildable"):
        raise DocumentCutoverError("projection is not declared rebuildable")


def _receipt(
    context: _CutoverContext,
    *,
    operation: str,
    from_owner: str,
    to_owner: str,
    from_generation: int,
    to_generation: int,
    inventory_head: str,
    heads: Mapping[str, Any],
) -> dict[str, Any]:
    receipt_id = str(uuid.uuid5(
        _RECEIPT_NAMESPACE,
        f"{operation}:{from_generation}:{to_generation}:{inventory_head}",
    ))
    receipt = {
        "schema_version": 1,
        "receipt_id": receipt_id,
        "receipt_status": "verified",
        "operation": operation,
        "from_owner": from_owner,
        "to_owner": to_owner,
        "from_generation": from_generation,
        "to_generation": to_generation,
        "inventory_head": inventory_head,
        "canonical_head": heads.get("canonical_head"),
        "projection_head": heads.get("projection_head"),
        "indexed_head": heads.get("indexed_head"),
        "prompt_delivery_head": context.prompt_delivery_head,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if not all(receipt[name] for name in (
        "canonical_head", "projection_head", "indexed_head", "prompt_delivery_head",
    )):
        raise DocumentCutoverError("cutover receipt lacks verified heads")
    path = context.canonical_root / "cutover-receipts" / f"{receipt_id}.json"
    try:
        context.receipt_writer(path, _detached(receipt))
    except Exception as exc:
        raise DocumentCutoverError("cutover receipt could not be made durable") from exc
    context.receipts.append(_detached(receipt))
    return receipt


def _shadow(context: _CutoverContext, request: Mapping[str, Any]) -> Mapping[str, Any]:
    inventory = request.get("inventory")
    normalized = _normalized_inventory(inventory)
    frozen = _normalized_inventory(context.frozen_inventory)
    if normalized != frozen:
        raise DocumentCutoverError("migration inventory differs from its frozen source inventory")
    if context.shadow_response is not None:
        if normalized["manifest_head"] != context.shadow_response["inventory_head"]:
            raise DocumentCutoverError("shadow retry changed inventory generation")
        return _detached(context.shadow_response)
    if request.get("expected_generation") != context.generation or context.generation != 1:
        raise DocumentCutoverError("shadow expected_generation mismatch")

    _assert_json_only(context.canonical_root)
    _source_bytes(context, inventory)
    context.prompt_delivery_head = _prompt_receipt(context, request.get("runtime_matrix") or {})
    gates, heads = _probe(context)
    _verified_gates(gates, _REQUIRED_GATES)

    imported = []
    for entry in normalized["entries"]:
        try:
            response = context.knowledge_request({
                "operation": "import_evidence",
                "detail": "evidence",
                "payload": {"entry": copy.deepcopy(entry)},
            })
        except Exception as exc:
            raise DocumentCutoverError(f"canonical import failed: {entry['path']}") from exc
        if not isinstance(response, Mapping) or response.get("uri") != entry["alias"]:
            raise DocumentCutoverError(f"canonical import did not bind alias: {entry['path']}")
        imported.append({
            "schema_version": 1,
            "uri": entry["alias"],
            "source": copy.deepcopy(entry),
            "canonical_import": copy.deepcopy(dict(response)),
        })
    for record in imported:
        record_id = record["uri"].rsplit("/", 1)[-1]
        _write_json(context.canonical_root / "documents" / f"{record_id}.json", record)
    _assert_json_only(context.canonical_root)

    receipt = _receipt(
        context,
        operation="shadow",
        from_owner="legacy",
        to_owner="shadow",
        from_generation=1,
        to_generation=2,
        inventory_head=normalized["manifest_head"],
        heads=heads,
    )
    context.shadow_owner = "canonical"
    context.generation = 2
    context.canonical_head = heads.get("canonical_head")
    context.shadow_response = {
        "operation": "shadow",
        "active_owner": "legacy",
        "shadow_owner": "canonical",
        "generation": 2,
        "inventory_head": normalized["manifest_head"],
        "receipt": receipt,
    }
    return _detached(context.shadow_response)


def _canonical(context: _CutoverContext, request: Mapping[str, Any]) -> Mapping[str, Any]:
    if context.shadow_response is None or context.active_owner != "legacy":
        raise DocumentCutoverError("canonical activation requires a completed shadow generation")
    if request.get("expected_generation") != context.generation:
        raise DocumentCutoverError("canonical expected_generation mismatch")
    required = request.get("required_gates")
    if not isinstance(required, Sequence) or isinstance(required, (str, bytes)):
        raise DocumentCutoverError("canonical activation must name required gates")
    required_set = {str(name) for name in required}
    context.prompt_delivery_head = _prompt_receipt(
        context,
        {
            "runtimes": ("claude", "codex", "grok", "harness"),
            "roles": ("orchestrator", "sub-orchestrator", "worker", "full-cycle", "reducer"),
        },
    )
    gates, heads = _probe(context)
    _verified_gates(gates, required_set)
    if request.get("remove_projection"):
        raise DocumentCutoverError("destructive projection deletion is not a cutover operation")
    receipt = _receipt(
        context,
        operation="canonical",
        from_owner="legacy",
        to_owner="canonical",
        from_generation=2,
        to_generation=3,
        inventory_head=context.shadow_response["inventory_head"],
        heads=heads,
    )
    context.active_owner = "canonical"
    context.generation = 3
    context.canonical_head = heads.get("canonical_head")
    return {
        "operation": "canonical",
        "active_owner": "canonical",
        "generation": 3,
        "inventory_head": context.shadow_response["inventory_head"],
        "receipt": receipt,
    }


def _resolve(context: _CutoverContext, request: Mapping[str, Any]) -> Mapping[str, Any]:
    if context.active_owner == "legacy":
        try:
            result = context.legacy_reader(_detached(request))
        except Exception as exc:
            raise DocumentCutoverError("legacy-compatible resolve failed") from exc
        if not isinstance(result, Mapping):
            raise DocumentCutoverError("legacy-compatible resolve returned no record")
        return {"source": "legacy", "items": [_detached(result)]}
    forbidden = {"reader", "path", "sqlite", "fts", "vector", "sql"}.intersection(request)
    if forbidden:
        raise DocumentCutoverError(
            f"canonical resolve forbids direct or projection fallback fields: {sorted(forbidden)}"
        )
    detail = request.get("detail", "summary")
    if detail not in {"summary", "record", "evidence"}:
        raise DocumentCutoverError("unsupported progressive detail level")
    try:
        result = context.knowledge_request({
            "operation": "query",
            "detail": detail,
            "payload": {"ref": request.get("ref")},
        })
    except Exception as exc:
        raise DocumentCutoverError("canonical knowledge resolve failed without fallback") from exc
    if not isinstance(result, Mapping) or result.get("source") != "canonical" or not result.get("items"):
        raise DocumentCutoverError("canonical knowledge resolve returned no canonical items")
    return _detached(result)


def _rollback(context: _CutoverContext, request: Mapping[str, Any]) -> Mapping[str, Any]:
    if context.active_owner != "canonical" or request.get("target_owner") != "legacy":
        raise DocumentCutoverError("rollback requires canonical owner and legacy target")
    if request.get("expected_generation") != context.generation:
        raise DocumentCutoverError("rollback expected_generation mismatch")
    gates, heads = _probe(context)
    _verified_gates(gates, _REQUIRED_GATES)
    receipt = _receipt(
        context,
        operation="rollback",
        from_owner="canonical",
        to_owner="legacy",
        from_generation=3,
        to_generation=4,
        inventory_head=context.shadow_response["inventory_head"],
        heads=heads,
    )
    context.active_owner = "legacy"
    context.generation = 4
    return {
        "operation": "rollback",
        "active_owner": "legacy",
        "generation": 4,
        "inventory_head": context.shadow_response["inventory_head"],
        "receipt": receipt,
    }


def cutover_api(request: Mapping[str, Any]) -> Mapping[str, Any]:
    """Dispatch state transitions and typed alias resolution to the configured owner."""

    if not isinstance(request, Mapping):
        raise DocumentCutoverError("cutover request must be an object")
    context = _context()
    operation = request.get("operation")
    if operation == "shadow":
        return _shadow(context, request)
    if operation == "canonical":
        return _canonical(context, request)
    if operation == "resolve":
        return _resolve(context, request)
    if operation == "rollback":
        return _rollback(context, request)
    if operation == "state":
        return {
            "active_owner": context.active_owner,
            "shadow_owner": context.shadow_owner,
            "generation": context.generation,
            "canonical_head": context.canonical_head,
            "inventory_head": context.frozen_inventory["manifest_head"],
        }
    raise DocumentCutoverError(f"unsupported cutover operation: {operation!r}")
