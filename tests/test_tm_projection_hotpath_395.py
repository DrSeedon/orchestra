"""Frozen Phase-2 acceptance oracles for #395 projection hot paths."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ia.projections import SQLiteProjectionBackend, projection_mode, query_current
from app.ia.runtime import _RuntimeTaskStore
from app.ia.task_store import TaskStore, build_migration_manifest
from tests.test_knowledge_runtime_debt_361 import (
    _owner,
    _resource,
    _task_projection_snapshot,
    _task_record,
)


def _projection_owner(tmp_path: Path):
    owner = _owner(tmp_path)
    content = b"# immutable evidence\n"
    resource = _resource(content)
    old = _task_record("old")
    unchanged = {**_task_record("unchanged"), "stable_id": "task-2", "display_number": 2}
    SQLiteProjectionBackend(path=owner.paths["current_projection"]).replace_current(
        records=[{**resource, "content": content.decode()}, old, unchanged],
        canonical_head=owner.state["canonical_head"],
    )
    owner.knowledge_service = None
    owner.evidence_records = lambda: [resource]
    owner._save_state = lambda: None
    owner._commit_canonical = lambda _message: None
    return owner, resource, old, unchanged


@pytest.mark.parametrize("receipts", ["present", "cleared"])
def test_t1_startup_readiness_never_scans_projection_rows(
    tmp_path,
    monkeypatch,
    receipts,
):
    owner, resource, old, unchanged = _projection_owner(tmp_path)
    owner.task_store = SimpleNamespace(states=lambda: {
        old["stable_id"]: old,
        unchanged["stable_id"]: unchanged,
    })
    if receipts == "cleared":
        with sqlite3.connect(owner.paths["current_projection"]) as connection:
            connection.execute(
                "UPDATE projection_meta SET "
                "resource_manifest_sha256='',resource_rows_sha256='' WHERE singleton=1"
            )

    from app.ia import projections

    def forbidden(*_args, **_kwargs):
        pytest.fail("startup readiness entered an O(N) projection scan")

    monkeypatch.setattr(projections, "_stored_resource_rows", forbidden)
    monkeypatch.setattr(projections, "_resource_fts_is_exact", forbidden)

    result = owner._refresh_current_projection()

    if receipts == "cleared":
        debts = [json.loads(path.read_text()) for path in (tmp_path / "debt").glob("*.json")]
        assert any(item["reason"] == "projection_receipt_unsealed" for item in debts)
        assert result["repair_required"] is True
    else:
        assert result["repair_required"] is False


def test_t2_task_store_mutation_updates_one_projection_row(tmp_path, monkeypatch):
    projection = tmp_path / "task-current.db"
    store = TaskStore(canonical_root=tmp_path / "tasks", projection_path=projection)
    store.migrate(build_migration_manifest(_task_projection_snapshot()))
    old_state = next((tmp_path / "tasks").rglob("state.json"))
    old_bytes = old_state.read_bytes()

    monkeypatch.setattr(
        store,
        "_rebuild_projection",
        lambda _states: pytest.fail("task mutation rebuilt the whole task projection"),
    )

    result = store.task_create(
        project_id="orchestra",
        title="targeted projection update",
        display_number=406,
        expected_head=store.canonical_head,
    )

    assert old_state.read_bytes() == old_bytes
    with sqlite3.connect(projection) as connection:
        assert connection.execute("SELECT count(*) FROM ia_task_projection").fetchone()[0] == 2
        projection_head = connection.execute(
            "SELECT projection_head FROM ia_task_projection_meta WHERE singleton=1"
        ).fetchone()[0]
    assert projection_head == result["canonical_head"]


def test_t2_joined_current_mutation_updates_named_task_and_fts_only(tmp_path, monkeypatch):
    owner, resource, old, unchanged = _projection_owner(tmp_path)
    changed = {**old, "title": "new"}
    path = owner.paths["current_projection"]
    with sqlite3.connect(path) as connection:
        before = {
            row[0]: tuple(row[1:])
            for row in connection.execute(
                "SELECT record_key,payload_sha256,payload_json,search_text "
                "FROM current_records WHERE record_key IN ('resource:resource-1','task.state:task-2')"
            )
        }

    class MutationStore:
        canonical_head = "task-head-old"

        def task_create(self, **_kwargs):
            self.canonical_head = "task-head-new"
            return {
                "par": "1",
                "task_id": "task-1",
                "canonical_head": self.canonical_head,
                "changed_records": [changed],
            }

        def states(self):
            return {"task-1": changed, "task-2": unchanged}

        def _states(self):
            return self.states()

    candidate = MutationStore()
    facade = _RuntimeTaskStore(
        store=candidate,
        legacy_to_canonical={"legacy": "project"},
        debt_writer=owner._record_debt,
        head_writer=owner._record_task_head,
    )
    owner.task_store = facade

    monkeypatch.setattr(
        SQLiteProjectionBackend,
        "replace_current_retaining_resources",
        lambda *_args, **_kwargs: pytest.fail("task mutation entered bulk retained refresh"),
    )
    monkeypatch.setattr(
        SQLiteProjectionBackend,
        "replace_current",
        lambda *_args, **_kwargs: pytest.fail("task mutation entered full projection rebuild"),
    )

    facade.task_create(project_id="legacy", title="new")

    backend = SQLiteProjectionBackend(path=path)
    task = backend.search_current(
        project_id="project", text="", record_types=["task.state"], limit=10,
    )
    assert {item["stable_id"]: item["title"] for item in task["items"]} == {
        "task-1": "new",
        "task-2": "unchanged",
    }
    with sqlite3.connect(path) as connection:
        after = {
            row[0]: tuple(row[1:])
            for row in connection.execute(
                "SELECT record_key,payload_sha256,payload_json,search_text "
                "FROM current_records WHERE record_key IN ('resource:resource-1','task.state:task-2')"
            )
        }
        fts_counts = dict(connection.execute(
            "SELECT record_key,count(*) FROM current_fts "
            "WHERE record_key LIKE 'task.state:%' GROUP BY record_key"
        ))
    assert after == before
    assert fts_counts == {"task.state:task-1": 1, "task.state:task-2": 1}


def test_t2_projection_failure_keeps_old_receipt_and_records_debt(tmp_path, monkeypatch):
    owner, resource, old, unchanged = _projection_owner(tmp_path)
    old_head = owner.state["projection_head"]
    owner.task_store = SimpleNamespace(states=lambda: {
        old["stable_id"]: {**old, "title": "new"},
        unchanged["stable_id"]: unchanged,
    })
    owner.knowledge_service = None
    monkeypatch.setattr(
        owner,
        "_refresh_current_projection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            sqlite3.OperationalError("injected targeted projection failure")
        ),
    )

    try:
        owner._record_task_head("task-head-new")
    except sqlite3.OperationalError:
        pass

    assert owner.state["canonical_head"] != old_head
    assert owner.state["projection_head"] == old_head
    debts = [json.loads(path.read_text()) for path in (tmp_path / "debt").glob("*.json")]
    assert any(item["reason"] == "current_projection_update_failed" for item in debts)


def test_t2_targeted_sqlite_failure_rolls_back_rows_fts_and_receipt(tmp_path):
    assert hasattr(SQLiteProjectionBackend, "update_current_records")
    path = tmp_path / "current.db"
    old_head = "sha256:" + "1" * 64
    new_head = "sha256:" + "2" * 64
    old = _task_record("old")
    changed = {**old, "title": "new"}
    backend = SQLiteProjectionBackend(path=path)
    backend.replace_current(records=[old], canonical_head=old_head)
    with sqlite3.connect(path) as connection:
        before_rows = connection.execute(
            "SELECT * FROM current_records ORDER BY record_key"
        ).fetchall()
        before_fts = connection.execute(
            "SELECT record_key,text FROM current_fts ORDER BY record_key"
        ).fetchall()
        connection.executescript(
            """CREATE TRIGGER fail_targeted_insert BEFORE INSERT ON current_records
               WHEN NEW.record_key='task.state:task-1'
               BEGIN SELECT RAISE(ABORT, 'injected targeted failure'); END;
               CREATE TRIGGER fail_targeted_update BEFORE UPDATE ON current_records
               WHEN NEW.record_key='task.state:task-1'
               BEGIN SELECT RAISE(ABORT, 'injected targeted failure'); END;"""
        )

    with pytest.raises(sqlite3.Error, match="injected targeted failure"):
        backend.update_current_records(
            records=[changed],
            deleted_record_keys=[],
            expected_head=old_head,
            canonical_head=new_head,
        )

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT projection_head FROM projection_meta WHERE singleton=1"
        ).fetchone()[0] == old_head
        assert connection.execute(
            "SELECT * FROM current_records ORDER BY record_key"
        ).fetchall() == before_rows
        assert connection.execute(
            "SELECT record_key,text FROM current_fts ORDER BY record_key"
        ).fetchall() == before_fts


def test_t2_restart_derives_debt_from_canonical_projection_head_gap(tmp_path, monkeypatch):
    owner, resource, old, unchanged = _projection_owner(tmp_path)
    observed_head = owner.state["projection_head"]
    expected_head = "sha256:" + "9" * 64
    owner.state["canonical_head"] = expected_head
    owner.task_store = SimpleNamespace(states=lambda: {
        old["stable_id"]: {**old, "title": "new"},
        unchanged["stable_id"]: unchanged,
    })

    def forbidden(*_args, **_kwargs):
        pytest.fail("restart repaired a canonical/projection crash gap inline")

    monkeypatch.setattr(
        SQLiteProjectionBackend, "replace_current_retaining_resources", forbidden,
    )
    monkeypatch.setattr(SQLiteProjectionBackend, "replace_current", forbidden)

    result = owner._refresh_current_projection()

    assert result["repair_required"] is True
    debts = [json.loads(path.read_text()) for path in (tmp_path / "debt").glob("*.json")]
    assert any(
        item["reason"] == "projection_head_mismatch"
        and item["expected_head"] == expected_head
        and item["observed_head"] == observed_head
        for item in debts
    )


def test_t2_interrupted_canonical_generation_leaves_recoverable_pending_marker(
    tmp_path,
    monkeypatch,
):
    from app.ia import task_store as task_store_module

    projection = tmp_path / "task-current.db"
    canonical_root = tmp_path / "tasks"
    store = TaskStore(canonical_root=canonical_root, projection_path=projection)
    store.migrate(build_migration_manifest(_task_projection_snapshot()))
    receipt_path = canonical_root / "current-head.json"
    pending_path = canonical_root / "pending-generation.json"
    assert receipt_path.is_file(), "canonical head receipt is missing"
    old_receipt = receipt_path.read_bytes()
    original_write_json = task_store_module._write_json

    def interrupt_before_commit(path, value):
        if Path(path) == receipt_path and receipt_path.read_bytes() == old_receipt:
            raise OSError("injected crash before canonical head commit")
        return original_write_json(path, value)

    monkeypatch.setattr(task_store_module, "_write_json", interrupt_before_commit)
    with pytest.raises(OSError, match="injected crash"):
        store.task_create(
            project_id="orchestra",
            title="interrupted generation",
            display_number=406,
            expected_head=store.canonical_head,
        )

    assert receipt_path.read_bytes() == old_receipt
    assert pending_path.is_file()
    reopened = TaskStore(canonical_root=canonical_root, projection_path=projection)
    pending = reopened.pending_generation()
    assert pending["parent_head"] == json.loads(old_receipt)["canonical_head"]
    assert pending["intended_head"] != pending["parent_head"]
    assert pending["changed_stable_ids"]

    recovered = reopened.recover_pending_generation()

    assert recovered["outcome"] == "completed"
    assert recovered["canonical_head"] == pending["intended_head"]
    assert recovered["projection_head"] == pending["parent_head"]
    assert recovered["projection_debt"] == {
        "reason": "task_projection_head_mismatch",
        "expected_head": pending["intended_head"],
        "observed_head": pending["parent_head"],
    }
    assert not pending_path.exists()
    assert json.loads(receipt_path.read_text())["canonical_head"] == pending["intended_head"]
    states = [json.loads(path.read_text()) for path in canonical_root.rglob("state.json")]
    assert any(state["title"] == "interrupted generation" for state in states)
    events = [json.loads(path.read_text()) for path in canonical_root.rglob("events/*.json")]
    assert any(event["canonical_head"] == pending["intended_head"] for event in events)


@pytest.mark.parametrize("reader", ["task_list", "task_get"])
def test_t3_task_reads_finish_while_writer_critical_section_is_held(monkeypatch, reader):
    writer_entered = threading.Event()
    release_writer = threading.Event()
    reader_finished = threading.Event()
    errors: list[BaseException] = []

    class BlockingStore:
        canonical_head = "head"
        projection_head = "head"

        def task_create(self, **_kwargs):
            writer_entered.set()
            if not release_writer.wait(3):
                raise RuntimeError("test failed to release writer")
            return {"canonical_head": "head", "par": "1"}

        def task_list(self, **_kwargs):
            return {"tasks": [], "count": 0}

        def task_get(self, *_args, **_kwargs):
            return {"par": "1", "title": "snapshot"}

    facade = _RuntimeTaskStore(
        store=BlockingStore(),
        legacy_to_canonical={"project": "project"},
        debt_writer=lambda _debt: None,
        head_writer=lambda _head, **_kwargs: None,
    )
    monkeypatch.setattr("app.ia.runtime._ensure_task_projection", lambda _store: None)

    def run_writer():
        try:
            facade.task_create(project_id="project", title="writer")
        except BaseException as error:  # pragma: no branch - collected for the assertion
            errors.append(error)

    def run_reader():
        try:
            if reader == "task_list":
                facade.task_list(project="project")
            else:
                facade.task_get("1", project="project")
        except BaseException as error:  # pragma: no branch - collected for the assertion
            errors.append(error)
        finally:
            reader_finished.set()

    writer_thread = threading.Thread(target=run_writer)
    reader_thread = threading.Thread(target=run_reader)
    writer_thread.start()
    assert writer_entered.wait(2)
    reader_thread.start()
    finished_before_release = reader_finished.wait(1)
    release_writer.set()
    writer_thread.join(3)
    reader_thread.join(3)

    assert not errors
    assert finished_before_release, f"{reader} waited behind the writer RLock"


@pytest.mark.parametrize("reader", ["task_list", "task_get"])
def test_t3_task_reads_use_projection_not_canonical_state_files(tmp_path, monkeypatch, reader):
    store = TaskStore(
        canonical_root=tmp_path / "tasks",
        projection_path=tmp_path / "task-current.db",
    )
    store.migrate(build_migration_manifest(_task_projection_snapshot()))
    monkeypatch.setattr(
        store,
        "_states",
        lambda: pytest.fail("request-time task read opened canonical state files"),
    )

    if reader == "task_list":
        result = store.task_list(project="orchestra")
        assert result["count"] == 1
        assert result["tasks"][0]["par"] == "405"
    else:
        result = store.task_get("405", project="orchestra")
        assert result["title"] == "projection recovery"


def test_t3_canonical_api_reads_do_not_open_legacy_owner(monkeypatch):
    from app import tm

    class CanonicalReads:
        canonical_head = "canonical-head"
        projection_head = "canonical-head"

        def task_list(self, **_kwargs):
            return {"tasks": [{"par": "1", "title": "canonical"}], "count": 1}

        def task_get(self, *_args, **_kwargs):
            return {
                "par": "1",
                "title": "canonical",
                "project": "project",
                "price_rub": 0,
                "status": "new",
                "assignee": "",
                "priority": 2,
                "description": "",
                "created_at": "2026-08-27T00:00:00+00:00",
                "completed_at": None,
                "commits": [],
                "sync_revision": 0,
            }

    def forbidden(*_args, **_kwargs):
        pytest.fail("canonical API read opened the legacy owner")

    monkeypatch.setattr(tm, "_legacy_api_list_tasks", forbidden)
    monkeypatch.setattr(tm, "_legacy_api_get_task", forbidden)
    with tm.ia_process_task_store_mode(store=CanonicalReads(), mode="canonical"):
        listed = tm.api_list_tasks(project="project")
        detail = tm.api_get_task("1", project="project")

    assert listed["tasks"][0]["title"] == "canonical"
    assert detail["title"] == "canonical"


def test_t3_sqlite_reader_observes_one_old_snapshot_during_targeted_write(tmp_path):
    assert hasattr(SQLiteProjectionBackend, "update_current_records")
    path = tmp_path / "current.db"
    old_head = "sha256:" + "1" * 64
    new_head = "sha256:" + "2" * 64
    first = _task_record("old")
    second = {**_task_record("unchanged"), "stable_id": "task-2", "display_number": 2}
    backend = SQLiteProjectionBackend(path=path)
    backend.replace_current(records=[first, second], canonical_head=old_head)
    writer_started = threading.Event()
    writer_errors: list[BaseException] = []

    reader = sqlite3.connect(path, isolation_level=None)
    reader.row_factory = sqlite3.Row
    reader.execute("BEGIN")
    observed_head = reader.execute(
        "SELECT projection_head FROM projection_meta WHERE singleton=1"
    ).fetchone()[0]

    def write_new_snapshot():
        writer_started.set()
        try:
            backend.update_current_records(
                records=[{**first, "title": "new"}],
                deleted_record_keys=[],
                expected_head=old_head,
                canonical_head=new_head,
            )
        except BaseException as error:  # pragma: no branch - asserted after join
            writer_errors.append(error)

    writer = threading.Thread(target=write_new_snapshot)
    writer.start()
    assert writer_started.wait(2)
    observed = {
        row["stable_id"]: json.loads(row["payload_json"])["title"]
        for row in reader.execute(
            "SELECT stable_id,payload_json FROM current_records "
            "WHERE record_type='task.state' ORDER BY stable_id"
        )
    }
    reader.execute("COMMIT")
    reader.close()
    writer.join(5)

    assert not writer_errors
    assert observed_head == old_head
    assert observed == {"task-1": "old", "task-2": "unchanged"}
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT projection_head FROM projection_meta WHERE singleton=1"
        ).fetchone()[0] == new_head
        assert json.loads(connection.execute(
            "SELECT payload_json FROM current_records WHERE stable_id='task-1'"
        ).fetchone()[0])["title"] == "new"


def test_t4_stale_current_read_falls_back_without_projection_repair(tmp_path, monkeypatch):
    task_root = tmp_path / "tasks" / "orchestra" / "398"
    task_root.mkdir(parents=True)
    canonical = {
        "stable_id": "task-398",
        "uri": "orch://project/orchestra/tasks/task-398",
        "record_type": "task",
        "project_id": "orchestra",
        "status": "current",
        "content": "canonical truth",
    }
    (task_root / "state.json").write_text(json.dumps(canonical))
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    task_store = SimpleNamespace(canonical_root=tmp_path / "tasks", canonical_head="task-head")
    knowledge_service = SimpleNamespace(
        canonical_root=knowledge_root,
        head=lambda: "knowledge-head",
        _facts=lambda: [],
    )
    projection = tmp_path / "current.db"
    SQLiteProjectionBackend(path=projection).replace_current(
        records=[{**canonical, "content": "stale"}],
        canonical_head="stale-head",
    )
    before = projection.read_bytes()

    monkeypatch.setattr(
        SQLiteProjectionBackend,
        "replace_current",
        lambda *_args, **_kwargs: pytest.fail("ordinary read attempted O(N) projection repair"),
    )
    with projection_mode(
        projection_path=projection,
        task_store=task_store,
        knowledge_service=knowledge_service,
        legacy_root=tmp_path / "legacy",
        legacy_log_db=tmp_path / "legacy.db",
    ):
        result = query_current(
            operation="query", detail="record", project_id="orchestra", limit=1,
        )

    assert projection.read_bytes() == before
    assert result["items"][0]["content"] == "canonical truth"
    assert result["items"][0]["source"] == "canonical-fallback"
    assert any(item["reason"] == "projection_stale_no_repair" for item in result["debt"])


@pytest.mark.parametrize("corruption", ["payload", "fts"])
def test_t4_corrupt_current_data_is_never_served_before_background_validation(
    tmp_path,
    monkeypatch,
    corruption,
):
    task_root = tmp_path / "tasks" / "orchestra" / "398"
    task_root.mkdir(parents=True)
    canonical = {
        "stable_id": "task-398",
        "uri": "orch://project/orchestra/tasks/task-398",
        "record_type": "task",
        "project_id": "orchestra",
        "status": "current",
        "content": "canonical truth",
    }
    (task_root / "state.json").write_text(json.dumps(canonical))
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    task_store = SimpleNamespace(canonical_root=tmp_path / "tasks", canonical_head="task-head")
    knowledge_service = SimpleNamespace(
        canonical_root=knowledge_root,
        head=lambda: "knowledge-head",
        _facts=lambda: [],
    )
    projection = tmp_path / "current.db"

    with projection_mode(
        projection_path=projection,
        task_store=task_store,
        knowledge_service=knowledge_service,
        legacy_root=tmp_path / "legacy",
        legacy_log_db=tmp_path / "legacy.db",
    ) as backend:
        from app.ia import projections

        canonical_head, canonical_records = projections._canonical_records(
            projections._context()
        )
        backend.replace_current(
            records=canonical_records,
            canonical_head=canonical_head,
        )
        with sqlite3.connect(projection) as connection:
            if corruption == "payload":
                affected = connection.execute(
                    "UPDATE current_records SET payload_json=? WHERE stable_id='task-398'",
                    ('{"content":"CORRUPT"}',),
                ).rowcount
            else:
                affected = connection.execute("DELETE FROM current_fts").rowcount
        assert affected == 1, f"{corruption} corruption touched {affected} rows"
        before = projection.read_bytes()
        monkeypatch.setattr(
            SQLiteProjectionBackend,
            "replace_current",
            lambda *_args, **_kwargs: pytest.fail(
                "corrupt ordinary read attempted inline projection repair"
            ),
        )
        result = query_current(
            operation="query",
            detail="record",
            project_id="orchestra",
            text="canonical",
            limit=1,
        )

    assert projection.read_bytes() == before
    assert result["items"][0]["content"] == "canonical truth"
    assert result["items"][0]["source"] == "canonical-fallback"
    assert any(item["reason"] == "projection_corrupt_no_repair" for item in result["debt"])
