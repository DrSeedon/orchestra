from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.ia import knowledge
from app.ia.evidence import EvidenceResolutionError
from app.ia.task_store import TaskStore, build_migration_manifest


FIXTURE = Path(".orchestra/tasks/315/acceptance/fixtures/t2_task_store_records.json")
EVIDENCE_ID = "3b000000-0000-4000-8000-000000000409"


def _setup(tmp_path: Path):
    snapshot = copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8"))["snapshot"])
    store = TaskStore(
        canonical_root=tmp_path / "tasks",
        projection_path=tmp_path / "task-current.db",
    )
    store.migrate(build_migration_manifest(snapshot))
    owner_task = store.task_get("315", project="orchestra")["stable_id"]
    other_task = store.task_get("316", project="orchestra")["stable_id"]

    source_root = tmp_path / "source"
    source_path = source_root / ".orchestra/kb/repo-ops.md"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("Evidence imported for #409.\n", encoding="utf-8")
    evidence_uri = (
        f"orch://project/orchestra/tasks/{owner_task}/evidence/{EVIDENCE_ID}"
    )
    source = {
        "path": ".orchestra/kb/repo-ops.md",
        "class": "immutable-evidence",
        "project_id": "orchestra",
        "stable_id": EVIDENCE_ID,
        "canonical_uri": evidence_uri,
        "git_commit": "1" * 40,
        "anchor": "1-1",
        "content_sha256": f"sha256:{hashlib.sha256(source_path.read_bytes()).hexdigest()}",
        "source_root": str(source_root),
    }
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "registry_version": 1,
        "topics": [{
            "project_id": "orchestra",
            "topic_slug": "repo-ops",
            "aliases": [],
            "summary": "Repository operations.",
        }],
    }), encoding="utf-8")
    return store, owner_task, other_task, source, registry


def _promotion(task_id: str, evidence_uri: str) -> dict:
    return {
        "event_id": "40000000-0000-4000-8000-000000000409",
        "idempotency_key": "t409-imported-evidence-is-promotable",
        "topic": "repo-ops",
        "new_topic": False,
        "fact": {
            "stable_id": "41000000-0000-4000-8000-000000000409",
            "fact_key": "imported-evidence-is-promotable",
            "claim": "Imported evidence can support a promoted fact.",
            "status": "current",
            "confidence": "verified",
            "valid_from": "2026-08-26T00:00:00+00:00",
            "valid_to": None,
            "observed_at": "2026-08-26T00:00:00+00:00",
            "refresh_after": "2027-08-26T00:00:00+00:00",
            "provenance": [{
                "task_id": task_id,
                "evidence_uri": evidence_uri,
                "path": ".orchestra/kb/repo-ops.md",
                "anchor": "1-1",
                "git_commit": "1" * 40,
                "measurement": "Evidence imported for #409.",
            }],
            "supersedes": [],
            "disputed_by": [],
            "metadata": {"reason": "The import must create owned task evidence."},
        },
    }


def test_imported_evidence_can_immediately_support_promotion(tmp_path):
    store, owner_task, _, source, registry = _setup(tmp_path)
    with knowledge.knowledge_service_mode(
        canonical_root=tmp_path / "knowledge",
        registry_path=registry,
        task_store=store,
    ):
        imported = knowledge.knowledge_api({
            "operation": "import_evidence",
            "detail": "record",
            "payload": {"source": source},
        })
        promoted = knowledge.knowledge_api({
            "operation": "promote",
            "detail": "evidence",
            "payload": {"request": _promotion(owner_task, source["canonical_uri"])},
        })

    assert imported["outcome"] == "created"
    assert promoted["outcome"] == "created"
    assert promoted["item"]["evidence"][0]["uri"] == source["canonical_uri"]
    assert source["canonical_uri"] in store.task_get(
        "315", project="orchestra"
    )["evidence_refs"]


def test_import_does_not_weaken_foreign_task_rejection(tmp_path):
    store, _, other_task, source, registry = _setup(tmp_path)
    with knowledge.knowledge_service_mode(
        canonical_root=tmp_path / "knowledge",
        registry_path=registry,
        task_store=store,
    ):
        knowledge.knowledge_api({
            "operation": "import_evidence",
            "detail": "record",
            "payload": {"source": source},
        })
        with pytest.raises(EvidenceResolutionError, match="record or task identity"):
            knowledge.knowledge_api({
                "operation": "promote",
                "detail": "record",
                "payload": {
                    "request": _promotion(other_task, source["canonical_uri"]),
                },
            })
