"""Regression coverage for the explicit shadow-drift repair pass (#422)."""

import pytest


def _setup_tasks():
    from app import tm
    from app.db import init_db

    init_db()
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/scope")
        first = tm.create_task(
            connection, "project", "First", par_number=412,
            status="done",
        )
        second = tm.create_task(
            connection, "project", "Second", par_number=413,
            status="done",
        )
        connection.execute(
            "UPDATE tm_tasks SET completed_at=?, sync_revision=3 WHERE id=?",
            ("2026-08-30T00:00:12+00:00", first["id"]),
        )
        connection.execute(
            "UPDATE tm_tasks SET completed_at=?, sync_revision=7 WHERE id=?",
            ("2026-08-30T00:00:13+00:00", second["id"]),
        )
    return first, second


class _Store:
    def __init__(self, *, failing=()):
        self.states = {
            412: {
                "project": "project", "par": "412", "status": "in_progress",
                "completed_at": None, "sync_revision": 2,
            },
            413: {
                "project": "project", "par": "413", "status": "in_progress",
                "completed_at": None, "sync_revision": 6,
            },
        }
        self.failing = set(failing)
        self.updated = []

    def task_get(self, ref, project=""):
        return dict(self.states[int(ref)])

    def task_update(self, ref, *, status="done", **_kwargs):
        par = int(ref)
        if par in self.failing:
            raise RuntimeError(f"canonical task {par} unavailable")
        state = self.states[par]
        self.updated.append(par)
        state.update(
            status=status,
            completed_at=f"2026-08-30T00:00:{par - 400:02d}+00:00",
            sync_revision=state["sync_revision"] + 1,
        )
        return dict(state)


def test_repair_updates_expected_shadow_drift_and_reports_snapshots():
    from app import tm

    first, second = _setup_tasks()
    store = _Store()
    result = tm.repair_shadow_task_drift(
        store,
        expected_refs=[{"project_id": "project", "par_number": 412},
                       {"project_id": "project", "par_number": 413}],
    )

    assert result["ok"] is True
    assert result["changed"] == 2
    assert {item["ref"]["par_number"] for item in result["items"]} == {412, 413}
    assert all(item["before"]["needs_repair"] is True for item in result["items"])
    assert all(item["after"]["needs_repair"] is False for item in result["items"])
    assert all(item["after"]["canonical"]["status"] == "done" for item in result["items"])
    assert all(item["after"]["canonical"]["completed_at"] for item in result["items"])
    with tm._conn() as connection:
        assert tm.get_task_by_id(connection, first["id"])["completed_at"]
        assert tm.get_task_by_id(connection, second["id"])["completed_at"]


def test_repair_is_idempotent_and_explicit_on_repeat():
    from app import tm

    _setup_tasks()
    store = _Store()
    store.states[413].update(
        status="done", completed_at="2026-08-30T00:00:13+00:00",
        sync_revision=7,
    )
    refs = [{"project_id": "project", "par_number": 412}]
    first = tm.repair_shadow_task_drift(store, expected_refs=refs)
    second = tm.repair_shadow_task_drift(store, expected_refs=refs)

    assert first["changed"] == 1
    assert second == {"ok": True, "changed": 0, "idempotent": True, "items": []}


def test_repair_refuses_empty_or_mismatched_fresh_list():
    from app import tm

    _setup_tasks()
    store = _Store()
    with pytest.raises(ValueError, match="empty"):
        tm.repair_shadow_task_drift(store, expected_refs=[])
    with pytest.raises(ValueError, match="invalid task reference"):
        tm.repair_shadow_task_drift(
            store, expected_refs=[{"project_id": "project", "par_number": True}],
        )
    with pytest.raises(ValueError, match="invalid task reference"):
        tm.repair_shadow_task_drift(
            store, expected_refs=[{"project_id": "project", "par_number": 412.9}],
        )
    with pytest.raises(ValueError, match="drift list changed"):
        tm.repair_shadow_task_drift(
            store,
            expected_refs=[{"project_id": "project", "par_number": 999}],
        )


def test_repair_continues_after_one_record_error():
    from app import tm

    _setup_tasks()
    result = tm.repair_shadow_task_drift(
        _Store(failing={412}),
        expected_refs=[{"project_id": "project", "par_number": 412},
                       {"project_id": "project", "par_number": 413}],
    )

    assert result["ok"] is False
    assert result["changed"] == 1
    assert result["errors"][0]["ref"] == {
        "project_id": "project", "par_number": 412,
    }
    assert result["errors"][0]["error"] == (
        "RuntimeError: canonical task 412 unavailable"
    )
    assert result["errors"][0]["state"] == "committed_unknown"
    assert result["errors"][0]["before"]["needs_repair"] is True
    assert result["errors"][0]["after"]["needs_repair"] is True


def test_repair_scan_error_is_reported_without_mutating_any_record():
    from app import tm

    _setup_tasks()

    class BrokenScan(_Store):
        def task_get(self, ref, project=""):
            if int(ref) == 412:
                raise RuntimeError("canonical scan unavailable")
            return super().task_get(ref, project)

    store = BrokenScan()
    result = tm.repair_shadow_task_drift(
        store,
        expected_refs=[{"project_id": "project", "par_number": 412},
                       {"project_id": "project", "par_number": 413}],
    )

    assert result["ok"] is False
    assert result["changed"] == 0
    assert result["reason"] == "fresh scan failed; no records were mutated"
    assert result["errors"][0]["ref"] == {
        "project_id": "project", "par_number": 412,
    }
    assert store.updated == []


def test_repair_ignores_independent_revision_differences():
    from app import tm

    first, _second = _setup_tasks()
    with tm._conn() as connection:
        connection.execute(
            "UPDATE tm_tasks SET sync_revision=0 WHERE id=?", (first["id"],)
        )
    store = _Store()
    result = tm.repair_shadow_task_drift(
        store,
        expected_refs=[{"project_id": "project", "par_number": 412},
                       {"project_id": "project", "par_number": 413}],
    )

    assert result["ok"] is True
    assert result["changed"] == 2
    assert store.updated == [412, 413]


def test_repair_compensates_canonical_mutation_that_fails_mid_record():
    from app import tm

    _setup_tasks()

    class MutatingFailure(_Store):
        canonical_head = "head-422"

        def _states(self):
            return {"stable-412": dict(self.states[412])}

        def _write_states(self, states, _head):
            restored = states["stable-412"]
            self.states[412] = dict(restored)

        def task_update(self, ref, *, status="done", **kwargs):
            result = super().task_update(ref, status=status, **kwargs)
            if int(ref) == 412:
                raise RuntimeError("canonical write committed then failed")
            return result

    store = MutatingFailure()
    result = tm.repair_shadow_task_drift(
        store,
        expected_refs=[{"project_id": "project", "par_number": 412},
                       {"project_id": "project", "par_number": 413}],
    )

    assert result["ok"] is False
    assert result["changed"] == 1
    assert result["errors"][0]["state"] == "rolled_back"
    assert store.states[412]["status"] == "in_progress"
    assert store.states[412]["sync_revision"] == 2


def test_repair_rejects_done_canonical_record_without_completion_time():
    from app import tm

    _setup_tasks()

    class MissingCompletion(_Store):
        def task_update(self, ref, *, status="done", **kwargs):
            result = super().task_update(ref, status=status, **kwargs)
            self.states[int(ref)]["completed_at"] = None
            return result

    store = MissingCompletion()
    result = tm.repair_shadow_task_drift(
        store,
        expected_refs=[{"project_id": "project", "par_number": 412},
                       {"project_id": "project", "par_number": 413}],
    )

    assert result["ok"] is False
    assert result["changed"] == 0
    assert len(result["errors"]) == 2
    assert all(item["error"] == "post-repair verification failed" for item in result["errors"])


def test_repair_rejects_non_done_canonical_record_with_completion_time():
    from app import tm

    _setup_tasks()

    class MissingDoneStatus(_Store):
        def task_update(self, ref, *, status="done", **kwargs):
            result = super().task_update(ref, status=status, **kwargs)
            self.states[int(ref)]["status"] = "in_progress"
            return result

    result = tm.repair_shadow_task_drift(
        MissingDoneStatus(),
        expected_refs=[{"project_id": "project", "par_number": 412},
                       {"project_id": "project", "par_number": 413}],
    )

    assert result["ok"] is False
    assert result["changed"] == 0
    assert len(result["errors"]) == 2
