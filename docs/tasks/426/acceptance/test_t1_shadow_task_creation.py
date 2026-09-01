"""Frozen Phase-2 oracle for #426 T1.

The shadow owner may record candidate debt, but it must never hand a legacy-only
task to spawn/finalization. Candidate outcome is checked before compensation so an
ambiguous post-write error cannot be converted into a canonical-only task.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest


class _FailingCandidateStore:
    canonical_head = "canonical-head"
    projection_head = "canonical-head"

    def __init__(
        self,
        *,
        write_before_failure: bool = False,
        probe_error: BaseException | None = None,
        on_probe: Callable[[], None] | None = None,
        debt_failure: bool = False,
    ) -> None:
        self.write_before_failure = write_before_failure
        self.probe_error = probe_error
        self.on_probe = on_probe
        self.debt_failure = debt_failure
        self.records: dict[tuple[str, int], dict[str, Any]] = {}
        self.debts: list[dict[str, Any]] = []

    def task_create(self, **kwargs: Any) -> dict[str, Any]:
        if self.write_before_failure:
            project_id = str(kwargs["project_id"])
            display_number = int(kwargs["display_number"])
            self.records[(project_id, display_number)] = {
                "par": str(display_number),
                "project": project_id,
                "title": str(kwargs["title"]),
                "stable_id": "candidate-stable-id",
                "canonical_head": self.canonical_head,
                "projection_head": self.projection_head,
            }
        raise RuntimeError("candidate unavailable")

    def task_get(self, ref: str, project: str = "") -> dict[str, Any]:
        if self.on_probe is not None:
            self.on_probe()
        if self.probe_error is not None:
            raise self.probe_error
        record = self.records.get((project, int(ref)))
        if record is None:
            raise ValueError(f"{ref} not found")
        return dict(record)

    def record_debt(self, debt: dict[str, Any]) -> None:
        self.debts.append(dict(debt))
        if self.debt_failure:
            raise RuntimeError("debt writer unavailable")


def _task_module(tmp_path, monkeypatch):
    from app import db, tm

    isolated = tmp_path / "orchestra.db"
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(isolated))
    monkeypatch.setattr(db, "DB_PATH", isolated)
    db.init_db()
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/project")
    assert db.DB_PATH == isolated
    return tm


def _legacy_rows(tm) -> list[tuple]:
    with tm._conn() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                "SELECT id,project_id,par_number,title,status "
                "FROM tm_tasks ORDER BY id"
            ).fetchall()
        ]


def _create_decoy(tm) -> None:
    with tm._conn() as connection:
        tm.create_task(
            connection,
            "project",
            "must survive compensation",
            par_number=99,
            status="new",
        )


def _assert_only_decoy_remains(tm) -> None:
    assert _legacy_rows(tm) == [
        (1, "project", 99, "must survive compensation", "new"),
    ]


def test_t1_spawn_does_not_receive_or_leave_a_legacy_only_task(tmp_path, monkeypatch):
    tm = _task_module(tmp_path, monkeypatch)
    _create_decoy(tm)
    store = _FailingCandidateStore()

    with tm.ia_process_task_store_mode(store=store, mode="shadow"):
        with pytest.raises(
            RuntimeError,
            match="shadow task creation failed: RuntimeError: candidate unavailable",
        ):
            tm.create_task_for_scope("/project", "spawn allocation")

    _assert_only_decoy_remains(tm)
    assert store.debts == [{
        "reason": "candidate_write_failed",
        "exception_type": "RuntimeError",
        "message": "candidate unavailable",
    }]


def test_t1_non_new_create_is_compensated_by_exact_identity(tmp_path, monkeypatch):
    tm = _task_module(tmp_path, monkeypatch)
    _create_decoy(tm)
    store = _FailingCandidateStore()

    with tm.ia_process_task_store_mode(store=store, mode="shadow"):
        with pytest.raises(
            RuntimeError,
            match="shadow task creation failed: RuntimeError: candidate unavailable",
        ):
            tm.api_create_task("project", "already done", status="done")

    _assert_only_decoy_remains(tm)


def test_t1_ambiguous_post_write_failure_never_deletes_either_owner(tmp_path, monkeypatch):
    tm = _task_module(tmp_path, monkeypatch)
    _create_decoy(tm)
    store = _FailingCandidateStore(write_before_failure=True)

    with tm.ia_process_task_store_mode(store=store, mode="shadow"):
        with pytest.raises(
            RuntimeError,
            match="shadow task creation failed: RuntimeError: candidate unavailable",
        ):
            tm.api_create_task("project", "candidate exists", status="new")

    assert _legacy_rows(tm) == [
        (1, "project", 99, "must survive compensation", "new"),
        (2, "project", 100, "candidate exists", "new"),
    ]
    assert store.task_get("100", project="project")["title"] == "candidate exists"


@pytest.mark.parametrize("probe_error", [
    RuntimeError("candidate read unavailable"),
    KeyError("candidate identity unavailable"),
    ValueError("candidate read malformed"),
])
def test_t1_unreadable_candidate_preserves_legacy_and_fails_loud(
    tmp_path, monkeypatch, probe_error,
):
    tm = _task_module(tmp_path, monkeypatch)
    _create_decoy(tm)
    store = _FailingCandidateStore(probe_error=probe_error)

    with tm.ia_process_task_store_mode(store=store, mode="shadow"):
        with pytest.raises(
            RuntimeError,
            match="shadow task creation failed: RuntimeError: candidate unavailable",
        ):
            tm.api_create_task("project", "probe unreadable", status="new")

    assert _legacy_rows(tm) == [
        (1, "project", 99, "must survive compensation", "new"),
        (2, "project", 100, "probe unreadable", "new"),
    ]


@pytest.mark.parametrize("guard", ["bound", "revised", "committed", "reserved"])
def test_t1_compensation_refuses_a_changed_or_reserved_legacy_row(
    tmp_path, monkeypatch, guard,
):
    tm = _task_module(tmp_path, monkeypatch)
    _create_decoy(tm)
    mutated = False

    def mutate_created_row() -> None:
        nonlocal mutated
        if mutated:
            return
        mutated = True
        with tm._conn() as connection:
            task_id = connection.execute(
                "SELECT id FROM tm_tasks WHERE title='guarded allocation'"
            ).fetchone()[0]
            if guard == "bound":
                connection.execute(
                    "UPDATE tm_tasks SET worker_session_id='worker' WHERE id=?",
                    (task_id,),
                )
            elif guard == "revised":
                connection.execute(
                    "UPDATE tm_tasks SET sync_revision=1 WHERE id=?",
                    (task_id,),
                )
            elif guard == "committed":
                connection.execute(
                    "UPDATE tm_tasks SET git_commits='[\"abc\"]' WHERE id=?",
                    (task_id,),
                )
            else:
                connection.execute(
                    "INSERT INTO tm_task_reservations "
                    "(task_id,operation_id,kind,session_id,created_at) "
                    "VALUES (?,'operation','merge','worker','2026-09-01T00:00:00+00:00')",
                    (task_id,),
                )

    store = _FailingCandidateStore(on_probe=mutate_created_row)
    with tm.ia_process_task_store_mode(store=store, mode="shadow"):
        with pytest.raises(
            RuntimeError,
            match="shadow task creation failed: RuntimeError: candidate unavailable",
        ):
            tm.api_create_task("project", "guarded allocation", status="new")

    assert [row[3] for row in _legacy_rows(tm)] == [
        "must survive compensation",
        "guarded allocation",
    ]


def test_t1_compensation_precedes_fallible_debt_recording(tmp_path, monkeypatch):
    tm = _task_module(tmp_path, monkeypatch)
    _create_decoy(tm)
    store = _FailingCandidateStore(debt_failure=True)

    with tm.ia_process_task_store_mode(store=store, mode="shadow"):
        with pytest.raises(
            RuntimeError,
            match="shadow task creation failed: RuntimeError: candidate unavailable",
        ):
            tm.api_create_task("project", "debt failure", status="new")

    _assert_only_decoy_remains(tm)
    assert store.debts[0]["reason"] == "candidate_write_failed"
