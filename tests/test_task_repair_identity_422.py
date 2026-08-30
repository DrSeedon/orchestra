from datetime import datetime, timezone


class _CanonicalStore:
    canonical_head = "head"

    def __init__(self):
        self.state = {
            "stable_id": "stable-412",
            "project_id": "canonical-project",
            "display_number": 412,
            "display_ref": "#412",
            "title": "Task 412",
            "description": "",
            "price_rub": 0,
            "status": "in_progress",
            "assignee": "",
            "priority": 2,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "sync_revision": 0,
            "worker_session_id": None,
            "acceptance": {},
            "evidence_refs": [],
            "git_commit_refs": [],
        }

    def _states(self):
        return {self.state["stable_id"]: dict(self.state)}

    def _write_states(self, states, head):
        self.state = dict(next(iter(states.values())))
        self.canonical_head = head

    @staticmethod
    def _facade_detail(state):
        return {
            "stable_id": state["stable_id"],
            "par": str(state["display_number"]),
            "project": state["project_id"],
            "status": state["status"],
            "completed_at": state["completed_at"],
            "created_at": state["created_at"],
            "sync_revision": state["sync_revision"],
        }

    def task_update(self, ref, *, status="done", **_kwargs):
        self.state["status"] = status
        self.state["completed_at"] = datetime.now(timezone.utc).isoformat()
        self.state["sync_revision"] += 1
        return self._facade_detail(self.state)

    def task_get(self, ref, project=""):
        detail = self._facade_detail(self.state)
        detail["project"] = project
        return detail


class _MappedStore:
    def __init__(self):
        self._store = _CanonicalStore()
        self._canonical_to_legacy = {"canonical-project": "legacy-project"}

    @property
    def canonical_head(self):
        return self._store.canonical_head

    def task_update(self, ref, *, project="", **kwargs):
        assert project == "legacy-project"
        return self._store.task_update(ref, **kwargs)

    def task_get(self, ref, *, project=""):
        assert project == "legacy-project"
        return self._store.task_get(ref, project=project)


def test_repair_maps_canonical_project_to_legacy_identity():
    from app import tm
    from app.db import init_db

    init_db()
    with tm._conn() as connection:
        tm.ensure_project(connection, "legacy-project", scope="/legacy")
        task = tm.create_task(
            connection, "legacy-project", "Task 412", par_number=412, status="done",
        )
        tm.create_task(
            connection, "legacy-project", "Unrelated task", par_number=413, status="done",
        )
        connection.execute(
            "UPDATE tm_tasks SET completed_at=? WHERE id=?",
            ("2026-08-30T00:00:00+00:00", task["id"]),
        )

    result = tm.repair_shadow_task_drift(
        _MappedStore(),
        expected_refs=[{"project_id": "legacy-project", "par_number": 412}],
    )

    assert result["ok"] is True
    assert result["changed"] == 1


def test_unmapped_identity_error_names_both_project_ids():
    from app import tm
    from app.db import init_db

    init_db()
    with tm._conn() as connection:
        tm.ensure_project(connection, "legacy-project", scope="/legacy")
        task = tm.create_task(
            connection, "legacy-project", "Task 412", par_number=412, status="done",
        )
        connection.execute(
            "UPDATE tm_tasks SET completed_at=? WHERE id=?",
            ("2026-08-30T00:00:00+00:00", task["id"]),
        )

    store = _MappedStore()
    store._canonical_to_legacy = {}
    result = tm.repair_shadow_task_drift(
        store,
        expected_refs=[{"project_id": "legacy-project", "par_number": 412}],
    )

    assert result["ok"] is False
    assert "legacy-project" in result["errors"][0]["error"]
    assert "canonical-project" in result["errors"][0]["error"]
