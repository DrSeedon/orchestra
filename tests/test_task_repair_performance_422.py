import time


class _BulkStore:
    def __init__(self, drift_refs):
        self.canonical_head = "bulk-head"
        self.task_get_calls = 0
        self.updated = []
        self._records = {}
        for number in range(1, 1501):
            drift = number in drift_refs
            self._records[number] = {
                "stable_id": f"stable-{number}",
                "project_id": "project",
                "display_number": number,
                "display_ref": f"#{number}",
                "title": f"Task {number}",
                "description": "",
                "price_rub": 0,
                "status": "in_progress" if drift else "done",
                "assignee": "",
                "priority": 2,
                "created_at": "2026-08-30T00:00:00+00:00",
                "completed_at": None if drift else "2026-08-30T00:00:01+00:00",
                "sync_revision": 0,
                "canonical_head": self.canonical_head,
                "projection_head": self.canonical_head,
                "worker_session_id": None,
                "acceptance": {},
                "evidence_refs": [],
                "git_commit_refs": [],
            }

    def _states(self):
        return {state["stable_id"]: dict(state) for state in self._records.values()}

    def _write_states(self, states, head):
        self.canonical_head = head
        self._records = {
            int(state["display_number"]): dict(state) for state in states.values()
        }

    @staticmethod
    def _facade_detail(state):
        return {
            "par": str(state["display_number"]),
            "project": state["project_id"],
            "title": state["title"],
            "description": state["description"],
            "price_rub": state["price_rub"],
            "status": state["status"],
            "assignee": state["assignee"],
            "priority": state["priority"],
            "created_at": state["created_at"],
            "completed_at": state["completed_at"],
            "sync_revision": state["sync_revision"],
        }

    def task_get(self, ref, project=""):
        self.task_get_calls += 1
        return self._facade_detail(self._records[int(ref)])

    def task_update(self, ref, *, status="done", **_kwargs):
        state = self._records[int(ref)]
        state["status"] = status
        state["completed_at"] = "2026-08-30T00:00:02+00:00"
        state["sync_revision"] += 1
        self.updated.append(int(ref))
        return self._facade_detail(state)


def test_bulk_repair_uses_bounded_reads_for_ten_refs():
    from app import tm
    from app.db import init_db

    drift_refs = set(range(1401, 1411))
    init_db()
    _seed_legacy_tasks(tm)
    store = _BulkStore(drift_refs)
    refs = [{"project_id": "project", "par_number": number} for number in drift_refs]

    started = time.perf_counter()
    result = tm.repair_shadow_task_drift(store, expected_refs=refs)
    elapsed = time.perf_counter() - started
    print(f"bulk_repair_elapsed_seconds={elapsed:.3f}")

    assert result["ok"] is True
    assert result["changed"] == 10
    assert store.updated == sorted(drift_refs)
    assert store.task_get_calls <= 20
    assert elapsed < 60


def _seed_legacy_tasks(tm):
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/scope")
        for number in range(1, 1501):
            tm.create_task(
                connection,
                "project",
                f"Task {number}",
                par_number=number,
                status="done",
            )
