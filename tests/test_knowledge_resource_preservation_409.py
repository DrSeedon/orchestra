from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ia import knowledge
from app.ia.task_store import TaskStore, build_migration_manifest


FIXTURE = Path("docs/tasks/315/acceptance/fixtures/t2_task_store_records.json")


def test_claude_resource_import_links_once_without_rewriting_flat_record(tmp_path):
    canonical = tmp_path / "canonical"
    snapshot = copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8"))["snapshot"])
    store = TaskStore(
        canonical_root=canonical / "tasks",
        projection_path=tmp_path / "task-current.db",
    )
    store.migrate(build_migration_manifest(snapshot))
    task_id = store.task_get("315", project="orchestra")["stable_id"]

    source_root = tmp_path / "source"
    source_root.mkdir()
    source_path = source_root / "CLAUDE.md"
    source_path.write_text("Canonical agent rule.\n", encoding="utf-8")
    source_sha = f"sha256:{hashlib.sha256(source_path.read_bytes()).hexdigest()}"
    evidence_id = "3b000000-0000-4000-8000-000000000410"
    evidence_uri = (
        f"orch://project/orchestra/tasks/{task_id}/evidence/{evidence_id}"
    )

    flat_path = canonical / "evidence/orchestra/resource.json"
    flat_path.parent.mkdir(parents=True)
    flat_path.write_text(json.dumps({
        "record_type": "resource",
        "stable_id": "flat-resource",
        "uri": "orch://project/orchestra/resources/flat-resource",
        "source_path": "CLAUDE.md",
        "source_sha256": source_sha,
    }), encoding="utf-8")
    flat_before = flat_path.read_bytes()

    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"registry_version": 1, "topics": []}))
    request = {
        "operation": "import_evidence",
        "detail": "record",
        "payload": {"source": {
            "path": "CLAUDE.md",
            "class": "immutable-evidence",
            "project_id": "orchestra",
            "stable_id": evidence_id,
            "canonical_uri": evidence_uri,
            "git_commit": "1" * 40,
            "anchor": "1",
            "content_sha256": source_sha,
            "source_root": str(source_root),
        }},
    }
    with knowledge.knowledge_service_mode(
        canonical_root=canonical / "knowledge",
        registry_path=registry,
        task_store=store,
    ):
        first = knowledge.knowledge_api(request)
        second = knowledge.knowledge_api(request)

    assert first["outcome"] == "created"
    assert second["outcome"] == "noop"
    assert flat_path.read_bytes() == flat_before
    assert len(list((canonical / "evidence/orchestra").glob("*.json"))) == 1
    assert len(list((canonical / "tasks").rglob("evidence/*.json"))) == 3


@pytest.mark.parametrize("filename", ["README.md", "scratch.md", "AGENTS.md"])
def test_other_root_markdown_remains_outside_cold_archive(tmp_path, filename):
    source = tmp_path / filename
    source.write_text("Not an approved canonical source.\n", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"registry_version": 1, "topics": []}))
    task_root = tmp_path / "tasks"
    task_root.mkdir()
    service = knowledge.KnowledgeService(
        canonical_root=tmp_path / "knowledge",
        registry_path=registry,
        task_store=SimpleNamespace(canonical_root=task_root),
    )
    request = {
        "path": filename,
        "class": "immutable-evidence",
        "project_id": "orchestra",
        "stable_id": "3b000000-0000-4000-8000-000000000411",
        "canonical_uri": (
            "orch://project/orchestra/tasks/"
            "8b01850f-d6f2-504e-9c1d-390d9e55b5c5/evidence/"
            "3b000000-0000-4000-8000-000000000411"
        ),
        "git_commit": "1" * 40,
        "anchor": "1",
        "content_sha256": f"sha256:{hashlib.sha256(source.read_bytes()).hexdigest()}",
        "source_root": str(tmp_path),
    }

    with pytest.raises(
        knowledge.PromotionValidationError, match="outside the cold archive"
    ):
        service.import_evidence(request)
