from __future__ import annotations

from pathlib import Path

import pytest

from app.ia.runtime import KnowledgeRuntimeError, _RuntimeTaskStore
from app.ia.task_store import TaskStore, build_migration_manifest


def _snapshot(*tasks: dict) -> dict:
    return {
        "source": {
            "cutoff": "2026-08-26T00:00:00+00:00",
            "source_head": "sha256:legacy",
            "source_schema_sha256": "sha256:schema",
        },
        "projects": [{"id": "project", "scope": "/project"}],
        "tasks": list(tasks),
        "evidence": [],
        "clients": [],
        "payments": [],
        "payment_allocations": [],
        "sync_log": [],
    }


def _task(row_id: int, number: int, *, title: str) -> dict:
    return {
        "id": row_id,
        "project_id": "project",
        "par_number": number,
        "title": title,
        "description": "",
        "price_rub": 0,
        "status": "new",
        "assignee": "",
        "priority": 2,
        "created_at": "2026-08-26T00:00:00+00:00",
        "updated_at": "2026-08-26T00:00:00+00:00",
    }


def _facade(tmp_path: Path) -> _RuntimeTaskStore:
    store = TaskStore(
        canonical_root=tmp_path / "canonical",
        projection_path=tmp_path / "tasks.db",
    )
    store.migrate(build_migration_manifest(_snapshot(_task(1, 1, title="existing"))))
    return _RuntimeTaskStore(
        store=store,
        legacy_to_canonical={"project": "project"},
        debt_writer=lambda _debt: None,
        head_writer=lambda _head: None,
    )


def test_reconcile_creates_missing_legacy_task_and_is_idempotent(tmp_path):
    facade = _facade(tmp_path)
    legacy = [_task(1, 1, title="existing"), _task(2, 2, title="arrived during outage")]

    result = facade.reconcile_legacy_tasks(legacy)

    assert result["reconciled_count"] == 1
    state = next(
        value for value in facade.states().values()
        if value["project_id"] == "project" and value["display_number"] == 2
    )
    assert state["title"] == "arrived during outage"
    assert facade.reconcile_legacy_tasks(legacy)["reconciled_count"] == 0


def test_reconcile_still_rejects_canonical_identity_absent_from_legacy(tmp_path):
    facade = _facade(tmp_path)

    with pytest.raises(KnowledgeRuntimeError, match="extra=.*project.*1"):
        facade.reconcile_legacy_tasks([])
