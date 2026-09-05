"""Lossless candidate/approval lifecycle between completed runs and project KB facts."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

from app.run_receipts import build_task_run_trace


_FACT_KEY = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_CONFIG_NAME = "knowledge-pipeline.json"
logger = logging.getLogger("orchestra.knowledge_pipeline")
_DEATH_CAPTURE_LOCK = threading.RLock()
_DEATH_CAPTURE_RESULTS: dict[tuple[str, str], dict] = {}


def knowledge_pipeline_configured(scope: str) -> bool:
    """Return true only for an explicit, readable project-local v1 opt-in marker."""
    if not str(scope or "").strip():
        return False
    marker = Path(scope).resolve() / ".orchestra" / _CONFIG_NAME
    try:
        raw = marker.read_text()
    except FileNotFoundError:
        return False
    except OSError as error:
        logger.warning(
            "KNOWLEDGE_PIPELINE_CONFIG_INVALID scope=%r reason=unreadable error=%s",
            scope, error,
        )
        return False
    try:
        document = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        logger.warning(
            "KNOWLEDGE_PIPELINE_CONFIG_INVALID scope=%r reason=invalid_json error=%s",
            scope, error,
        )
        return False
    if not isinstance(document, dict):
        logger.warning(
            "KNOWLEDGE_PIPELINE_CONFIG_INVALID scope=%r reason=not_an_object", scope,
        )
        return False
    if document.get("schema_version") != 1:
        logger.warning(
            "KNOWLEDGE_PIPELINE_CONFIG_INVALID scope=%r reason=unknown_schema_version",
            scope,
        )
        return False
    if "enabled" not in document:
        logger.warning(
            "KNOWLEDGE_PIPELINE_CONFIG_INVALID scope=%r reason=enabled_missing", scope,
        )
        return False
    if not isinstance(document["enabled"], bool):
        logger.warning(
            "KNOWLEDGE_PIPELINE_CONFIG_INVALID scope=%r reason=enabled_not_boolean", scope,
        )
        return False
    return document["enabled"] is True


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, text=True, check=True, capture_output=True
    ).stdout.strip()


def _worktree_root(path: Path) -> Path:
    probe = path if path.is_dir() else path.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return Path(_git(probe, "rev-parse", "--show-toplevel")).resolve()


def _require_clean(root: Path) -> None:
    dirty = _git(root, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise ValueError(f"knowledge candidate worktree is dirty: {dirty}")


def _untracked_kb_seed_paths(root: Path) -> list[Path]:
    status = _git(root, "status", "--porcelain", "--untracked-files=all")
    if not status:
        return []
    paths = []
    for line in status.splitlines():
        if not line.startswith("?? .orchestra/kb/"):
            raise ValueError(f"knowledge candidate worktree is dirty: {status}")
        paths.append(root / line[3:])
    return paths


def _commit_paths(root: Path, message: str, paths: list[Path]) -> str:
    relative = [path.resolve().relative_to(root).as_posix() for path in paths]
    subprocess.run(["git", "add", "--", *relative], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=root, check=True)
    _require_clean(root)
    return _git(root, "rev-parse", "HEAD")


def _source_manifest(rows: list[dict]) -> list[dict]:
    ordered = sorted(rows, key=lambda row: (str(row.get("ts") or ""), int(row.get("id") or 0)))
    manifest = []
    for row in ordered:
        item = {"id": int(row.get("id") or 0), "ts": str(row.get("ts") or "")}
        content = row.get("content")
        if content is None:
            item["gap"] = str(row.get("gap") or "SOURCE_UNAVAILABLE")
        else:
            raw = content if isinstance(content, bytes) else str(content).encode()
            item.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        manifest.append(item)
    return manifest


def _stable_source_id(receipt_id: str) -> str:
    return hashlib.sha256(receipt_id.encode()).hexdigest()


def create_task_candidate(
    receipt_id: str,
    *,
    source_loader: Callable[[dict], list[dict]],
    luna_extract: Callable[..., dict],
    prompt_sha256: str,
    candidate_dir: Path,
    task_state: dict,
) -> dict:
    """Create and commit one Luna candidate while leaving canonical KB untouched."""
    if not re.fullmatch(r"[0-9a-f]{64}", prompt_sha256):
        raise ValueError("prompt_sha256 must be a lowercase SHA-256")
    root = _worktree_root(candidate_dir)
    if not candidate_dir.resolve().is_relative_to(root):
        raise ValueError("candidate directory is outside its Git worktree")
    if _git(root, "branch", "--show-current") in {"", "main", "master"}:
        raise ValueError("knowledge candidates require a dedicated candidate branch")
    seed_paths = _untracked_kb_seed_paths(root)

    trace = build_task_run_trace(receipt_id)
    references = dict(trace.get("references") or {})
    sources = _source_manifest(source_loader(references))
    manifest = {
        "receipt_id": receipt_id,
        "run": trace.get("run") or {},
        "references": references,
        "reviews": trace.get("reviews") or [],
        "usage": trace.get("usage") or {},
        "gaps": list(trace.get("gaps") or []),
        "sources": sources,
    }
    candidate = luna_extract(
        model="luna", source_manifest=manifest, prompt_sha256=prompt_sha256,
    )
    if not isinstance(candidate, dict):
        raise ValueError("Luna candidate must be a mapping")
    document = {
        "schema_version": 1,
        "status": "pending_human",
        "receipt_id": receipt_id,
        "prompt_sha256": prompt_sha256,
        "model": "luna",
        "source_manifest": manifest,
        "candidate": candidate,
    }
    body = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    digest = hashlib.sha256(body).hexdigest()
    candidate_dir.mkdir(parents=True, exist_ok=True)
    source_id = _stable_source_id(receipt_id)
    candidate_path = candidate_dir / f"{source_id}.json"
    if candidate_path.exists():
        raise ValueError(f"candidate already exists: {candidate_path}")
    candidate_path.write_bytes(body)
    commit = _commit_paths(
        root, f"knowledge candidate {receipt_id}", [*seed_paths, candidate_path]
    )
    task_state["status"] = "knowledge_pending"
    return {
        "candidate_path": str(candidate_path),
        "source_id": source_id,
        "candidate_sha256": digest,
        "candidate_commit": commit,
        "status": "knowledge_pending",
    }


def _write_snapshot(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(body)
    temporary.replace(path)


def capture_worker_death_candidate(
    worker: dict,
    *,
    candidate_dir: Path,
    luna_extract: Callable[..., dict],
    prompt_sha256: str,
    retire_worker: Callable[[], None],
    snapshot_writer: Callable[[Path, str], None] | None = None,
) -> dict:
    """Persist complete worker state once, then and only then retire the worker."""
    if not re.fullmatch(r"[0-9a-f]{64}", prompt_sha256):
        raise ValueError("prompt_sha256 must be a lowercase SHA-256")
    receipt_id = str(worker.get("run_receipt_id") or "")
    if not receipt_id:
        raise ValueError("worker death capture requires run_receipt_id")
    source_id = _stable_source_id(receipt_id)
    candidate_dir = Path(candidate_dir).resolve()
    cache_key = (str(candidate_dir), source_id)
    with _DEATH_CAPTURE_LOCK:
        cached = _DEATH_CAPTURE_RESULTS.get(cache_key)
        if cached is not None:
            return dict(cached)

        context = str(worker.get("current_context") or "")
        memory_path = Path(str(worker.get("memory_path") or ""))
        memory = memory_path.read_bytes()
        trace = build_task_run_trace(receipt_id)
        manifest = {
            "source_id": source_id,
            "receipt_id": receipt_id,
            "worker_name": str(worker.get("name") or ""),
            "current_context": context,
            "current_context_sha256": hashlib.sha256(context.encode()).hexdigest(),
            "memory_path": str(memory_path),
            "memory_sha256": hashlib.sha256(memory).hexdigest(),
            "memory_hex": memory.hex(),
            "memory_text": memory.decode(errors="replace"),
            "run_trace": trace,
            "residual_references": trace.get("references") or {},
            "gaps": list(trace.get("gaps") or []),
        }
        candidate = luna_extract(
            model="luna", source_manifest=manifest, prompt_sha256=prompt_sha256,
        )
        document = {
            "schema_version": 1,
            "status": "pending_human",
            "model": "luna",
            "prompt_sha256": prompt_sha256,
            "source_manifest": manifest,
            "candidate": candidate,
        }
        body = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        snapshot = candidate_dir / f"{source_id}.md"
        (snapshot_writer or _write_snapshot)(snapshot, body)
        retire_worker()
        result = {
            "source_id": source_id,
            "source_snapshot": str(snapshot),
            "candidate_path": str(snapshot),
            "candidate_sha256": hashlib.sha256(body.encode()).hexdigest(),
        }
        _DEATH_CAPTURE_RESULTS[cache_key] = dict(result)
        return result


def _fact_line(fact_key: str, candidate: dict, receipt_id: str) -> str:
    claim = str(candidate.get("claim") or "").strip()
    if not claim:
        raise ValueError("approved candidate has no claim")
    evidence = json.dumps(candidate.get("evidence") or [], ensure_ascii=False, separators=(",", ":"))
    counter = json.dumps(
        candidate.get("counter_evidence") or [], ensure_ascii=False, separators=(",", ":")
    )
    reasoning = str(candidate.get("reasoning") or "").strip()
    date = datetime.now(timezone.utc).date().isoformat()
    return (
        f"- `fact:{fact_key}` — {claim} · search: `{fact_key}`, `{receipt_id}`"
        f" · evidence: {evidence}; reasoning: {reasoning}; counter-evidence: {counter}"
        f" · {date}, {receipt_id}\n"
    )


def _insert_fact(topic: Path, line: str) -> None:
    text = topic.read_text()
    if line.split("`", 2)[1] in text:
        raise ValueError("fact key already exists")
    for heading in ("## Established", "## Установлено"):
        marker = heading + "\n"
        if marker in text:
            offset = text.index(marker) + len(marker)
            topic.write_text(text[:offset] + "\n" + line + text[offset:])
            return
    raise ValueError("target topic has no Established section")


def resolve_task_candidate(
    candidate_path: Path,
    approval: dict,
    *,
    kb_root: Path,
    release_source: Callable[[], None],
    mark_done: Callable[[dict], None],
) -> dict:
    """Apply one content-bound human disposition, then release and close in that order."""
    candidate_path = Path(candidate_path).resolve()
    body = candidate_path.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    if approval.get("candidate_sha256") != digest:
        raise ValueError("candidate digest does not match human receipt")
    if approval.get("actor") != "orchestrator" or approval.get("revision") != 1:
        raise ValueError("human approval actor/revision is invalid")
    if approval.get("disposition") != "promote":
        raise ValueError("T3 supports only an explicit promote disposition")
    fact_key = str(approval.get("fact_key") or "")
    if not _FACT_KEY.fullmatch(fact_key):
        raise ValueError("fact_key must be kebab-case")
    target = PurePosixPath(str(approval.get("target_topic") or ""))
    if target.is_absolute() or ".." in target.parts or target.suffix != ".md":
        raise ValueError("target_topic must be a safe relative Markdown path")
    topic = (Path(kb_root).resolve() / target).resolve()
    if not topic.is_relative_to(Path(kb_root).resolve()) or not topic.is_file():
        raise ValueError("target topic is outside the KB or missing")
    root = _worktree_root(candidate_path.parent)
    if _worktree_root(topic.parent) != root:
        raise ValueError("candidate and target topic must share one candidate worktree")
    _require_clean(root)

    document = json.loads(body)
    receipt_id = str(document.get("receipt_id") or "")
    _insert_fact(topic, _fact_line(fact_key, dict(document["candidate"]), receipt_id))
    document.update(status="approved", approval=dict(approval))
    candidate_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    commit = _commit_paths(root, f"approve knowledge candidate {receipt_id}", [topic, candidate_path])
    release_source()
    completion = {
        "processing_complete": True,
        "release_safe": True,
        "semantic_complete": False,
    }
    mark_done(completion)
    return {"status": "done", "approval_commit": commit, "completion": completion}
