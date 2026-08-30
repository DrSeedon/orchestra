from datetime import datetime, timezone
import json
from pathlib import Path


class _DoneWithoutCompletion:
    def __init__(self):
        self.state = {
            "project": "project",
            "par": "412",
            "status": "done",
            "completed_at": None,
            "sync_revision": 0,
        }

    def task_get(self, ref, project=""):
        return dict(self.state)

    def task_update(self, ref, *, status="done", completed_at=None, **_kwargs):
        if status != self.state["status"]:
            self.state["status"] = status
        if completed_at is not None:
            self.state["completed_at"] = completed_at
        self.state["sync_revision"] += 1
        return dict(self.state)


def test_repair_fills_missing_canonical_completion_for_done_task():
    from app import tm
    from app.db import init_db

    init_db()
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/scope")
        task = tm.create_task(
            connection, "project", "Task 412", par_number=412, status="done",
        )
        completed_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            "UPDATE tm_tasks SET completed_at=? WHERE id=?",
            (completed_at, task["id"]),
        )

    result = tm.repair_shadow_task_drift(
        _DoneWithoutCompletion(),
        expected_refs=[{"project_id": "project", "par_number": 412}],
    )

    assert result["ok"] is True
    assert result["changed"] == 1
    assert result["items"][0]["after"]["canonical"]["completed_at"] == completed_at


def test_task_store_done_update_fills_missing_completion(tmp_path):
    from app.ia.task_store import TaskStore, build_migration_manifest

    fixture = Path("docs/tasks/315/acceptance/fixtures/t2_task_store_records.json")
    snapshot = json.loads(fixture.read_text(encoding="utf-8"))["snapshot"]
    store = TaskStore(
        canonical_root=tmp_path / "tasks",
        projection_path=tmp_path / "task-current.db",
    )
    store.migrate(build_migration_manifest(snapshot))
    states = store._states()
    task = next(
        state
        for state in states.values()
        if state["display_number"] == 315 and state["project_id"] == "orchestra"
    )
    task["status"] = "done"
    task["completed_at"] = None
    store._write_states(states, store.canonical_head)

    store.task_update("315", project="orchestra", status="done")

    assert store.task_get("315", project="orchestra")["completed_at"]
