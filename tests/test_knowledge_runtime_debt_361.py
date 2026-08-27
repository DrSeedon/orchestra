"""#361: debt reasons are explicit policy, not one undifferentiated counter."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ia.projections import SQLiteProjectionBackend
from app.ia.runtime import KnowledgeRuntime, KnowledgeRuntimeError, _RuntimeTaskStore
from app.ia.task_store import TaskStore, build_migration_manifest


_PROMPT = "\n".join((
    "Use the single `knowledge` tool for canonical knowledge and evidence operations.",
    "Request progressive detail as `summary` < `record` < `evidence`.",
    "Use typed `orch://` identifiers for task, fact, evidence, session, resource, and skill references.",
    "Markdown files, SQLite, FTS, and vector hits are never independent truth.",
    "Historical Markdown and session archives are immutable cold evidence and are never regenerated.",
    "Canonical task, fact, evidence-reference, and session events are structured Git JSON.",
))


def _owner(tmp_path: Path) -> KnowledgeRuntime:
    tmp_path.mkdir(parents=True, exist_ok=True)
    head = "sha256:" + "1" * 64
    current = tmp_path / "current.db"
    SQLiteProjectionBackend(path=current).replace_current(records=[], canonical_head=head)
    legacy = tmp_path / "legacy.db"
    with sqlite3.connect(legacy) as connection:
        connection.execute(
            "CREATE TABLE sessions(id TEXT,session_id TEXT,status TEXT,system_prompt TEXT,prompt_overlay TEXT)"
        )
    vector = tmp_path / "vector.db"
    vector.write_bytes(b"retained")
    owner = object.__new__(KnowledgeRuntime)
    owner.config = SimpleNamespace(
        state_root=tmp_path,
        legacy_db_path=legacy,
        prompt_assembler=lambda _runtime, _role: _PROMPT,
    )
    owner.paths = {
        "canonical_root": tmp_path / "canonical",
        "current_projection": current,
        "task_projection": tmp_path / "task.db",
        "vector_projection": vector,
    }
    owner.state = {
        "canonical_head": head,
        "projection_head": head,
        "indexed_head": "sha256:" + "2" * 64,
        "debt_count": 0,
    }
    owner.task_store = SimpleNamespace(canonical_head="task-head", projection_head="task-head")
    owner.scope_registry = {}
    owner.query_for_scope = lambda _scope, _text, limit=1: {"count": 0}
    owner.parity = lambda: {"mismatch_count": 0, "mismatches": []}
    owner._ensure_vector_projection = lambda: None
    owner._gate_receipt = lambda name, detail: {"status": "verified", "gate": name, **detail}
    owner._connection = lambda: sqlite3.connect(legacy)
    return owner


def _debt(root: Path, name: str, reason: str) -> None:
    debt = root / "debt"
    debt.mkdir(exist_ok=True)
    (debt / f"{name}.json").write_text(json.dumps({"reason": reason}))


def test_t6_debt_reason_policy_keeps_information_visible_and_blocks_unknown_or_unavailable(
    tmp_path,
):
    owner = _owner(tmp_path)
    _debt(tmp_path, "info", "secret_candidate_in_evidence")
    owner.state["debt_count"] = 1

    gates = owner.verify_gates()
    summary = owner.debt_summary()
    assert gates["privacy"]["informational_debt_count"] == 1
    assert summary == {
        "total_count": 1,
        "blocking_count": 0,
        "informational_count": 1,
        "by_reason": {"secret_candidate_in_evidence": 1},
    }

    _debt(tmp_path, "blocking", "git_evidence_source_unavailable")
    owner.state["debt_count"] = 2
    with pytest.raises(KnowledgeRuntimeError, match="blocking runtime debt"):
        owner.verify_gates()

    _debt(tmp_path, "unknown", "future_reason_without_policy")
    with pytest.raises(KnowledgeRuntimeError, match="unknown runtime debt reason"):
        owner.debt_summary()


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def test_t6_scope_evidence_policy_distinguishes_none_broken_git_and_working_git(
    tmp_path, monkeypatch,
):
    non_git = tmp_path / "media"
    non_git.mkdir()
    owner = _owner(tmp_path / "none")
    owner.scope_registry = {
        str(non_git): {
            "scope": str(non_git),
            "canonical_project_id": "media",
            "repository_root": str(non_git),
            "evidence_mode": "none",
        }
    }
    owner._commit_canonical = lambda _message: None
    owner._save_state = lambda: None
    owner._import_scope_evidence()
    gates = owner.verify_gates()
    assert owner.state["evidence_less_scopes"] == [
        {"scope": str(non_git), "reason": "not_git_backed"}
    ]
    assert gates["projection"]["evidence_less_scopes"] == owner.state["evidence_less_scopes"]

    broken_root = tmp_path / "broken-git"
    broken_root.mkdir()
    broken = _owner(tmp_path / "broken")
    broken.scope_registry = {
        str(broken_root): {
            "scope": str(broken_root),
            "canonical_project_id": "broken",
            "repository_root": str(broken_root),
            "evidence_mode": "git",
        }
    }
    broken._commit_canonical = lambda _message: None
    broken._save_state = lambda: None
    broken._import_scope_evidence()
    assert broken.state["evidence_less_scopes"] == []
    with pytest.raises(KnowledgeRuntimeError, match="blocking runtime debt"):
        broken.verify_gates()

    git_root = tmp_path / "working-git"
    git_root.mkdir()
    subprocess.run(["git", "init", "-q", str(git_root)], check=True)
    _git(git_root, "config", "user.email", "test@example.invalid")
    _git(git_root, "config", "user.name", "Test")
    source = git_root / "README.md"
    source.write_text("# working evidence\n")
    (git_root / "SECOND.md").write_text("# second evidence\n")
    _git(git_root, "add", "README.md", "SECOND.md")
    _git(git_root, "commit", "-qm", "fixture")
    working = _owner(tmp_path / "working")
    (working.paths["canonical_root"]).mkdir(parents=True)
    working.scope_registry = {
        str(git_root): {
            "scope": str(git_root),
            "canonical_project_id": "working",
            "repository_root": str(git_root),
            "evidence_mode": "git",
        }
    }
    working._commit_canonical = lambda _message: None
    working._save_state = lambda: None
    working._import_scope_evidence()
    records = working.evidence_records()
    assert {record["source_path"] for record in records} == {"README.md", "SECOND.md"}
    assert {record["git_commit"] for record in records} == {_git(git_root, "rev-parse", "HEAD")}
    assert working.state["evidence_less_scopes"] == []

    # Startup repeats this import for every live scope. A content-addressed evidence record
    # that already exists must not read the same Git blob again.
    original_source_git = working._source_git

    def no_redundant_blob_read(root, *args, **kwargs):
        if args[:2] == ("cat-file", "blob"):
            pytest.fail("existing immutable evidence reread its Git blob")
        return original_source_git(root, *args, **kwargs)

    working._source_git = no_redundant_blob_read
    working._import_scope_evidence()

    working.task_store = SimpleNamespace(states=lambda: {})
    working.knowledge_service = None
    projection_records = working._projection_records()
    assert sorted(record["content"] for record in projection_records) == [
        "# second evidence\n",
        "# working evidence\n",
    ]
    from app.ia import runtime as runtime_module

    original_read_json = runtime_module._read_json

    def no_cached_evidence_reread(path):
        if "evidence" in Path(path).parts:
            pytest.fail("immutable evidence descriptors were reread after cache fill")
        return original_read_json(path)

    monkeypatch.setattr(runtime_module, "_read_json", no_cached_evidence_reread)
    cached = working.evidence_records()
    cached[0]["source_path"] = "caller mutation"
    assert "caller mutation" not in {
        record["source_path"] for record in working.evidence_records()
    }


def _resource(content: bytes) -> dict:
    return {
        "record_type": "resource",
        "schema_version": 1,
        "stable_id": "resource-1",
        "uri": "orch://project/project/resources/resource-1",
        "project_id": "project",
        "status": "current",
        "source_path": "README.md",
        "source_scope": "/project",
        "source_class": "immutable-evidence",
        "git_commit": "a" * 40,
        "git_blob": "b" * 40,
        "source_sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
        "storage": "cold-immutable-reference",
    }


def _task_record(title: str) -> dict:
    return {
        "record_type": "task.state",
        "schema_version": 1,
        "stable_id": "task-1",
        "project_id": "project",
        "display_number": 1,
        "title": title,
    }


def test_task_head_refresh_retains_verified_evidence_without_git_reads(tmp_path):
    owner = _owner(tmp_path)
    old_head = owner.state["canonical_head"]
    new_head = "sha256:" + "3" * 64
    content = b"# immutable evidence\n"
    resource = _resource(content)
    SQLiteProjectionBackend(path=owner.paths["current_projection"]).replace_current(
        records=[{**resource, "content": content.decode()}, _task_record("old")],
        canonical_head=old_head,
    )
    owner.state["canonical_head"] = new_head
    owner.task_store = SimpleNamespace(states=lambda: {"task-1": _task_record("new")})
    owner.knowledge_service = None
    owner.evidence_records = lambda: [resource]
    owner._evidence_contents = lambda _records: pytest.fail(
        "unchanged evidence must not be reread during a task-only refresh"
    )

    owner._refresh_current_projection()

    backend = SQLiteProjectionBackend(path=owner.paths["current_projection"])
    task = backend.search_current(
        project_id="project", text="", record_types=["task.state"], limit=10,
    )
    evidence = backend.search_current(
        project_id="project", text="", record_types=["resource"], limit=10,
    )
    assert task["projection_head"] == new_head
    assert task["items"][0]["title"] == "new"
    assert evidence["items"][0]["content"] == content.decode()
    with sqlite3.connect(owner.paths["current_projection"]) as connection:
        stored_resource_head = connection.execute(
            "SELECT canonical_head FROM current_records WHERE record_type='resource'"
        ).fetchone()[0]
    assert stored_resource_head == old_head


def test_task_head_refresh_rebuilds_when_evidence_digest_changed(tmp_path):
    owner = _owner(tmp_path)
    old_content = b"# old evidence\n"
    new_content = b"# new evidence\n"
    old_resource = _resource(old_content)
    new_resource = _resource(new_content)
    SQLiteProjectionBackend(path=owner.paths["current_projection"]).replace_current(
        records=[{**old_resource, "content": old_content.decode()}],
        canonical_head=owner.state["canonical_head"],
    )
    owner.state["canonical_head"] = "sha256:" + "4" * 64
    owner.task_store = SimpleNamespace(states=lambda: {})
    owner.knowledge_service = None
    owner.evidence_records = lambda: [new_resource]
    owner._evidence_contents = lambda _records: {"resource-1": new_content}

    owner._refresh_current_projection()

    evidence = SQLiteProjectionBackend(
        path=owner.paths["current_projection"]
    ).search_current(
        project_id="project", text="", record_types=["resource"], limit=10,
    )
    assert evidence["items"][0]["content"] == new_content.decode()


def test_projection_meta_upgrade_adds_resource_receipts(tmp_path):
    path = tmp_path / "old-projection.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE projection_meta (
                   singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                   projection_head TEXT NOT NULL
               )"""
        )
        connection.execute("INSERT INTO projection_meta VALUES (1, 'old')")

    backend = SQLiteProjectionBackend(path=path)

    with sqlite3.connect(path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(projection_meta)")
        }
    assert {"resource_manifest_sha256", "resource_rows_sha256"} <= columns


def test_matching_legacy_projection_head_seals_receipts_without_full_rebuild(tmp_path):
    owner = _owner(tmp_path)
    content = b"# immutable evidence\n"
    resource = _resource(content)
    task = _task_record("unchanged")
    backend = SQLiteProjectionBackend(path=owner.paths["current_projection"])
    backend.replace_current(
        records=[{**resource, "content": content.decode()}, task],
        canonical_head=owner.state["canonical_head"],
    )
    with sqlite3.connect(owner.paths["current_projection"]) as connection:
        connection.execute("ALTER TABLE projection_meta RENAME TO projection_meta_with_receipts")
        connection.execute(
            "CREATE TABLE projection_meta ("
            "singleton INTEGER PRIMARY KEY CHECK(singleton=1), projection_head TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO projection_meta SELECT singleton,projection_head "
            "FROM projection_meta_with_receipts"
        )
        connection.execute("DROP TABLE projection_meta_with_receipts")

    owner.task_store = SimpleNamespace(states=lambda: {"task-1": task})
    owner.knowledge_service = None
    owner.evidence_records = lambda: [resource]
    owner._evidence_contents = lambda _records: pytest.fail(
        "matching legacy projection must be sealed without a full rebuild"
    )

    owner._refresh_current_projection()

    with sqlite3.connect(owner.paths["current_projection"]) as connection:
        receipt = connection.execute(
            "SELECT projection_head,resource_manifest_sha256,resource_rows_sha256 "
            "FROM projection_meta WHERE singleton=1"
        ).fetchone()
    assert receipt[0] == owner.state["canonical_head"]
    assert receipt[1].startswith("sha256:")
    assert receipt[2].startswith("sha256:")
    stored = backend.search_current(
        project_id="project", text="", record_types=["resource"], limit=10,
    )
    assert stored["items"][0]["content"] == content.decode()


def _task_projection_snapshot() -> dict:
    timestamp = "2026-08-26T00:00:00+00:00"
    return {
        "source": {
            "cutoff": timestamp,
            "source_head": "sha256:" + "a" * 64,
            "source_schema_sha256": "sha256:" + "b" * 64,
        },
        "projects": [{"id": "orchestra", "scope": "/repo"}],
        "tasks": [{
            "id": 1,
            "par_number": 405,
            "project_id": "orchestra",
            "title": "projection recovery",
            "description": "",
            "price_rub": 0,
            "status": "new",
            "assignee": "",
            "sync_revision": 0,
            "worker_session_id": None,
            "git_commits": [],
            "created_at": timestamp,
            "updated_at": timestamp,
            "completed_at": None,
            "priority": 2,
            "acceptance_command": "",
            "acceptance_oracle_json": {},
        }],
        "evidence": [],
        "clients": [],
        "payments": [],
        "payment_allocations": [],
        "sync_log": [],
    }


def test_idempotent_post_commit_link_rebuilds_deleted_task_projection(tmp_path):
    projection = tmp_path / "task-current.db"
    store = TaskStore(canonical_root=tmp_path / "tasks", projection_path=projection)
    store.migrate(build_migration_manifest(_task_projection_snapshot()))
    commit = {"hash": "c" * 40, "message": "#405: projection recovery"}
    store.link_commits_to_task("405", [commit], "orchestra")
    facade = _RuntimeTaskStore(
        store=store,
        legacy_to_canonical={"orchestra": "orchestra"},
        debt_writer=lambda _debt: None,
        head_writer=lambda _head: None,
    )
    projection.unlink()

    result = facade.link_commits_to_task("405", [commit], "orchestra")

    assert result["ok"] is True
    assert result["added"] == 0
    assert projection.is_file()
    assert facade.projection_head == facade.canonical_head


def test_corrupt_disposable_projections_rebuild_from_canonical(tmp_path, monkeypatch):
    task_projection = tmp_path / "task-current.db"
    store = TaskStore(canonical_root=tmp_path / "tasks", projection_path=task_projection)
    store.migrate(build_migration_manifest(_task_projection_snapshot()))
    task_projection.write_bytes(b"not a sqlite database")
    task_sidecars = [Path(f"{task_projection}{suffix}") for suffix in ("-journal", "-wal", "-shm")]
    for sidecar in task_sidecars:
        sidecar.write_bytes(b"stale task projection sidecar")
    facade = _RuntimeTaskStore(
        store=store,
        legacy_to_canonical={"orchestra": "orchestra"},
        debt_writer=lambda _debt: None,
        head_writer=lambda _head: None,
    )

    detail = facade.task_get("405", project="orchestra")

    assert detail["title"] == "projection recovery"
    with sqlite3.connect(task_projection) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT count(*) FROM ia_task_projection").fetchone()[0] == 1
    assert not any(sidecar.exists() for sidecar in task_sidecars)

    content = b"# canonical evidence\n"
    resource = _resource(content)
    current_owner = _owner(tmp_path / "current-corrupt")
    current_owner.task_store = SimpleNamespace(states=lambda: {})
    current_owner.knowledge_service = None
    current_owner.evidence_records = lambda: [resource]
    current_owner._evidence_contents = lambda _records: {"resource-1": content}
    current_owner.paths["current_projection"].write_bytes(b"not a sqlite database")

    current_owner._refresh_current_projection()

    stored = SQLiteProjectionBackend(
        path=current_owner.paths["current_projection"]
    ).search_current(
        project_id="project", text="", record_types=["resource"], limit=1,
    )
    assert stored["items"][0]["content"] == content.decode()

    interrupted = _owner(tmp_path / "current-interrupted")
    interrupted.task_store = SimpleNamespace(states=lambda: {})
    interrupted.knowledge_service = None
    interrupted.evidence_records = lambda: []
    interrupted._evidence_contents = lambda _records: {}
    interrupted_path = interrupted.paths["current_projection"]
    with sqlite3.connect(interrupted_path) as connection:
        connection.execute("DROP TABLE current_records")
        connection.execute("CREATE TABLE current_records (bad_column TEXT)")
    before = interrupted_path.read_bytes()
    replace_current = SQLiteProjectionBackend.replace_current

    def fail_temporary_rebuild(backend, **kwargs):
        if backend.path != interrupted_path:
            raise sqlite3.OperationalError("injected rebuild interruption")
        return replace_current(backend, **kwargs)

    monkeypatch.setattr(SQLiteProjectionBackend, "replace_current", fail_temporary_rebuild)
    with pytest.raises(sqlite3.OperationalError, match="injected rebuild interruption"):
        interrupted._refresh_current_projection()

    assert interrupted_path.read_bytes() == before
    with sqlite3.connect(interrupted_path) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert not list(interrupted_path.parent.glob(f".{interrupted_path.name}.*.rebuild*"))


class _ParityStore:
    def __init__(self):
        self.canonical_head = "task-head-before"
        self.projection_head = self.canonical_head
        self.states = {
            "stable-361": {
                "stable_id": "stable-361",
                "project_id": "orchestra",
                "display_number": 361,
                "title": "knowledge cutover",
                "description": "",
                "price_rub": 0,
                "status": "new",
                "assignee": "",
                "priority": 2,
            }
        }
        self.applied = []

    def _states(self):
        return self.states

    def apply_events(self, events, *, expected_head=None):
        assert expected_head == self.canonical_head
        self.applied = list(events)
        for event in events:
            self.states[event["stable_id"]].update(event["changes"])
        self.canonical_head = "task-head-after"
        self.projection_head = self.canonical_head
        return {"canonical_head": self.canonical_head, "projection_head": self.projection_head}


def test_t6_task_parity_is_field_exact_and_reconciles_legacy_zero_without_identity_rewrite(
    tmp_path,
):
    legacy = tmp_path / "legacy.db"
    with sqlite3.connect(legacy) as connection:
        connection.execute(
            "CREATE TABLE tm_tasks(project_id TEXT,par_number INTEGER,title TEXT,description TEXT,"
            "price_rub INTEGER,status TEXT,assignee TEXT,priority INTEGER,updated_at TEXT)"
        )
        connection.execute(
            "INSERT INTO tm_tasks VALUES(?,?,?,?,?,?,?,?,?)",
            ("orchestra", 361, "knowledge cutover", "", 0, "in_progress", "", 0,
             "2026-08-26T00:00:00+00:00"),
        )
    store = _ParityStore()
    facade = _RuntimeTaskStore(
        store=store,
        legacy_to_canonical={"orchestra": "orchestra"},
        debt_writer=lambda _debt: None,
        head_writer=lambda _head: None,
    )
    owner = object.__new__(KnowledgeRuntime)
    owner.task_store = facade
    def connection():
        value = sqlite3.connect(legacy)
        value.row_factory = sqlite3.Row
        return value
    owner._connection = connection

    mismatch = owner.parity()
    assert mismatch == {
        "mismatch_count": 1,
        "mismatches": ["orchestra:361"],
        "field_mismatch_counts": {"priority": 1, "status": 1},
    }

    facade.reconcile_legacy_tasks([
        {
            "project_id": "orchestra",
            "par_number": 361,
            "title": "knowledge cutover",
            "description": "",
            "price_rub": 0,
            "status": "in_progress",
            "assignee": "",
            "priority": 0,
            "updated_at": "2026-08-26T00:00:00+00:00",
        }
    ])
    assert store.applied[0]["changes"] == {"priority": 0, "status": "in_progress"}
    assert store.applied[0]["stable_id"] == "stable-361"
    assert owner.parity() == {
        "mismatch_count": 0,
        "mismatches": [],
        "field_mismatch_counts": {},
    }
