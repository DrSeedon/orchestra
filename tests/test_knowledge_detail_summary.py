from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.ia.projections import SQLiteProjectionBackend, projection_mode, query_current


def _projection(tmp_path: Path, content: str):
    task_root = tmp_path / "tasks" / "orchestra" / "398"
    task_root.mkdir(parents=True)
    (task_root / "state.json").write_text(
        json.dumps(
            {
                "stable_id": "task-398",
                "uri": "orch://project/orchestra/tasks/task-398",
                "record_type": "task",
                "project_id": "orchestra",
                "status": "current",
                "content": content,
            },
            ensure_ascii=False,
        )
    )
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    task_store = SimpleNamespace(canonical_root=tmp_path / "tasks", canonical_head="task-head")
    knowledge_service = SimpleNamespace(
        canonical_root=knowledge_root,
        head=lambda: "knowledge-head",
        _facts=lambda: [],
    )
    return task_store, knowledge_service


def test_summary_detail_bounds_content_and_preserves_identity(tmp_path):
    content = "restart watchdog pidfd " + "x" * 69_980
    task_store, knowledge_service = _projection(tmp_path, content)

    with projection_mode(
        projection_path=tmp_path / "current.db",
        task_store=task_store,
        knowledge_service=knowledge_service,
        legacy_root=tmp_path / "legacy",
        legacy_log_db=tmp_path / "legacy.db",
    ):
        result = query_current(
            operation="query",
            detail="summary",
            project_id="orchestra",
            limit=1,
        )

    item = result["items"][0]
    assert len(item["content"]) <= 1_000
    assert item["content"] == content[:300]
    assert item["content_length"] == len(content)
    assert item["stable_id"] == "task-398"
    assert item["uri"] == "orch://project/orchestra/tasks/task-398"
    assert item["record_type"] == "task"
    assert item["status"] == "current"
    assert item["project_id"] == "orchestra"
    assert item["canonical_head"] == result["canonical_head"]
    assert item["projection_head"] == result["projection_head"]
    assert item["indexed_head"] is None


def test_record_and_evidence_details_keep_full_content(tmp_path):
    content = "full evidence " + "y" * 69_986
    task_store, knowledge_service = _projection(tmp_path, content)

    with projection_mode(
        projection_path=tmp_path / "current.db",
        task_store=task_store,
        knowledge_service=knowledge_service,
        legacy_root=tmp_path / "legacy",
        legacy_log_db=tmp_path / "legacy.db",
    ):
        for detail in ("record", "evidence"):
            result = query_current(
                operation="query",
                detail=detail,
                project_id="orchestra",
                limit=1,
            )
            assert result["items"][0]["content"] == content
