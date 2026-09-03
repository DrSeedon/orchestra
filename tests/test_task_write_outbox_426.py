"""Frozen Phase-2 oracles for #426 bounded task-write projection delivery."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import sqlite3
import subprocess
import threading
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.ia.projections import SQLiteProjectionBackend
from app.ia.runtime import KnowledgeRuntime, KnowledgeRuntimeError, RuntimeConfig


def _evidence_records(count: int) -> list[dict]:
    return [
        {
            "record_type": "resource",
            "stable_id": f"resource-{index:05d}",
            "project_id": f"project-{index % 7}",
            "value": index,
        }
        for index in range(count)
    ]


def _runtime(tmp_path: Path, monkeypatch, *, evidence_count: int = 0):
    from app import db, tm

    database = tmp_path / "orchestra.db"
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(database))
    monkeypatch.setattr(db, "DB_PATH", database)
    db.init_db()
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/scope")
        tm.create_task(connection, "project", "seed", par_number=1)
        connection.commit()

    evidence = _evidence_records(evidence_count)
    calls = {"evidence": 0}

    def evidence_records(_owner):
        calls["evidence"] += 1
        return copy.deepcopy(evidence)

    monkeypatch.setattr(KnowledgeRuntime, "evidence_records", evidence_records)
    config = RuntimeConfig(
        state_root=tmp_path / "state",
        legacy_db_path=database,
        vector_db_path=tmp_path / "vector.db",
        scope_roots={},
        prompt_assembler=lambda *_args: "prompt",
    )
    owner = KnowledgeRuntime(config)
    current_records = [
        {
            "record_type": "task.state",
            "stable_id": f"current-{index:05d}",
            "project_id": f"project-{index % 7}",
            "display_number": index + 10,
            "title": f"current row {index}",
        }
        for index in range(evidence_count)
    ]
    SQLiteProjectionBackend(path=owner.paths["current_projection"]).replace_current(
        records=current_records,
        canonical_head=owner.state["projection_head"],
    )
    return owner, config, evidence, calls


def _outbox(owner: KnowledgeRuntime) -> list[tuple[Path, dict]]:
    root = owner.paths["canonical_root"] / "projection-outbox"
    entries = []
    for path in sorted(root.glob("*.json")):
        try:
            entries.append((path, json.loads(path.read_text())))
        except FileNotFoundError:
            continue
    return entries


def _ordered(entries: list[dict], first_head: str) -> list[dict]:
    remaining = list(entries)
    ordered = []
    cursor = first_head
    while remaining:
        matches = [
            entry for entry in remaining
            if entry.get("expected_projection_head") == cursor
        ]
        assert len(matches) == 1, "projection receipts are forked or disconnected"
        entry = matches[0]
        ordered.append(entry)
        remaining.remove(entry)
        cursor = entry["target_canonical_head"]
    return ordered


async def _http_create_and_update(owner: KnowledgeRuntime, *, after_create=None):
    from app import tm
    from app.routes.tm import router

    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    with tm.ia_process_task_store_mode(store=owner.task_store, mode="canonical"):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/tm/tasks",
                headers={"Idempotency-Key": "task-write-outbox-426"},
                json={"project": "project", "title": "created"},
            )
            if after_create is not None:
                after_create(created)
            updated = await client.put(
                "/api/tm/tasks/2",
                params={"project": "project"},
                json={"title": "updated"},
            )
    return created, updated


async def _http_create(owner: KnowledgeRuntime):
    from app import tm
    from app.routes.tm import router

    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    with tm.ia_process_task_store_mode(store=owner.task_store, mode="canonical"):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/tm/tasks",
                headers={"Idempotency-Key": "task-write-barrier-426"},
                json={"project": "project", "title": "barrier"},
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("evidence_count", [0, 20_000])
async def test_t1_post_and_put_do_constant_request_work_and_leave_durable_receipts(
    tmp_path, monkeypatch, evidence_count,
):
    from app import tm
    from app.ia import runtime as runtime_module

    owner, _config, evidence, calls = _runtime(
        tmp_path, monkeypatch, evidence_count=evidence_count,
    )
    initial_projection_head = owner.state["projection_head"]
    projection_calls = []
    original_update = SQLiteProjectionBackend.update_current_records

    def observe_projection(_backend, **kwargs):
        projection_calls.append(dict(kwargs))
        return {"projection_head": kwargs["canonical_head"]}

    monkeypatch.setattr(SQLiteProjectionBackend, "update_current_records", observe_projection)
    seed = next(iter(owner.task_store.states().values()))
    owner._record_task_head(
        owner.task_store.canonical_head,
        changed_records=[seed],
    )
    calls["evidence"] = 0
    projection_calls.clear()
    projection_opens = []
    original_projection_init = SQLiteProjectionBackend.__init__

    def observe_projection_init(backend, *args, **kwargs):
        projection_opens.append((args, kwargs))
        original_projection_init(backend, *args, **kwargs)

    monkeypatch.setattr(SQLiteProjectionBackend, "__init__", observe_projection_init)

    large_serializations = []
    original_bytes = runtime_module._bytes

    def observe_bytes(value):
        if isinstance(value, dict) and "evidence" in value:
            large_serializations.append(len(value["evidence"]))
        return original_bytes(value)

    monkeypatch.setattr(runtime_module, "_bytes", observe_bytes)
    sentinel = owner.paths["canonical_root"] / "evidence" / "untracked-sentinel.json"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("{}\n")

    def assert_post_committed(created_response):
        assert created_response.status_code == 200, created_response.text
        with tm._conn() as connection:
            legacy_created = tm.get_task_by_par(connection, 2, "project")
        canonical_created = owner.task_store.task_get("2", project="project")
        assert legacy_created["title"] == canonical_created["title"] == "created"
        post_receipts = _outbox(owner)
        assert post_receipts, "POST returned before creating a projection receipt"
        for path, _entry in post_receipts:
            relative = path.relative_to(owner.paths["canonical_root"])
            committed = subprocess.check_output(
                ["git", "-C", str(owner.paths["canonical_root"]), "show", f"HEAD:{relative}"],
            )
            assert committed == path.read_bytes()

    created, updated = await _http_create_and_update(
        owner,
        after_create=assert_post_committed,
    )

    assert created.status_code == 200, created.text
    assert updated.status_code == 200, updated.text
    with tm._conn() as connection:
        legacy = tm.get_task_by_par(connection, 2, "project")
    canonical = owner.task_store.task_get("2", project="project")
    assert legacy["title"] == canonical["title"] == "updated"
    assert calls["evidence"] == 0, "request path enumerated the evidence corpus"
    assert large_serializations == [], "request path serialized the evidence corpus"
    assert projection_opens == [], "request path opened the joined current projection"
    assert projection_calls == [], "response waited for joined-current projection I/O"
    assert owner.state["projection_head"] == initial_projection_head

    outbox = _outbox(owner)
    assert len(outbox) >= 3, "successful writes did not leave durable projection receipts"
    chain = _ordered([entry for _path, entry in outbox], initial_projection_head)
    assert chain[-1]["target_canonical_head"] == owner.state["canonical_head"]
    assert any(
        record.get("title") == "updated"
        for entry in chain
        for record in entry["records"]
    )
    normalized = [
        {
            key: value
            for key, value in record.items()
            if key not in {"canonical_head", "projection_head", "indexed_head", "source"}
        }
        for record in evidence
    ]
    expected_head = "sha256:" + hashlib.sha256(original_bytes({
        "task_head": owner.task_store.canonical_head,
        "knowledge_head": None,
        "evidence": sorted(
            normalized, key=lambda item: (item["project_id"], item["stable_id"]),
        ),
    })).hexdigest()
    assert owner.state["canonical_head"] == expected_head

    tracked = subprocess.check_output(
        ["git", "-C", str(owner.paths["canonical_root"]), "ls-files", "projection-outbox"],
        text=True,
    ).splitlines()
    assert len(tracked) == len(outbox)
    sentinel_status = subprocess.check_output(
        [
            "git", "-C", str(owner.paths["canonical_root"]), "status", "--short", "--",
            "evidence/untracked-sentinel.json",
        ],
        text=True,
    ).strip()
    assert sentinel_status == "?? evidence/untracked-sentinel.json"
    monkeypatch.setattr(SQLiteProjectionBackend, "__init__", original_projection_init)
    monkeypatch.setattr(SQLiteProjectionBackend, "update_current_records", original_update)


@pytest.mark.asyncio
async def test_t1_http_response_waits_for_projection_receipt_git_commit(tmp_path, monkeypatch):
    owner, _config, _evidence, _calls = _runtime(tmp_path, monkeypatch)
    owner._record_task_head(
        owner.task_store.canonical_head,
        changed_records=[next(iter(owner.task_store.states().values()))],
    )
    commit_entered = threading.Event()
    release_commit = threading.Event()
    original_git = owner._git
    blocked = False

    def block_commit(*args, **kwargs):
        nonlocal blocked
        if (
            not blocked
            and args[:2] == ("commit", "-qm")
            and args[-1] == "update canonical task generation"
        ):
            blocked = True
            commit_entered.set()
            if not release_commit.wait(3):
                raise RuntimeError("test did not release the outbox commit")
        return original_git(*args, **kwargs)

    monkeypatch.setattr(owner, "_git", block_commit)
    request = asyncio.create_task(_http_create(owner))
    try:
        assert await asyncio.to_thread(commit_entered.wait, 2)
        assert not request.done(), "HTTP response escaped before the receipt commit"
        receipts = _outbox(owner)
        assert receipts, "commit barrier was reached without a projection receipt"
    finally:
        release_commit.set()
    response = await request
    assert response.status_code == 200, response.text
    for path, _entry in _outbox(owner):
        relative = path.relative_to(owner.paths["canonical_root"])
        assert subprocess.check_output(
            ["git", "-C", str(owner.paths["canonical_root"]), "show", f"HEAD:{relative}"],
        ) == path.read_bytes()


@pytest.mark.asyncio
async def test_t1_outbox_git_failure_cannot_return_success(tmp_path, monkeypatch):
    owner, _config, _evidence, _calls = _runtime(tmp_path, monkeypatch)
    owner._record_task_head(
        owner.task_store.canonical_head,
        changed_records=[next(iter(owner.task_store.states().values()))],
    )
    original_git = owner._git

    def fail_projection_receipt_commit(*args, **kwargs):
        if args[:2] == ("commit", "-qm") and args[-1] == "update canonical task generation":
            raise KnowledgeRuntimeError("injected outbox Git commit failure")
        return original_git(*args, **kwargs)

    monkeypatch.setattr(owner, "_git", fail_projection_receipt_commit)
    created, _updated = await _http_create_and_update(owner)

    assert created.status_code != 200
    assert "injected outbox Git commit failure" in created.text


def _seed_outbox(owner: KnowledgeRuntime) -> tuple[str, list[str], list[dict]]:
    base = next(iter(owner.task_store.states().values()))
    initial = owner.state["projection_head"]
    targets = ["sha256:" + "a" * 64, "sha256:" + "b" * 64]
    entries = [
        {
            "schema_version": 1,
            "entry_id": "entry-a",
            "expected_projection_head": initial,
            "target_canonical_head": targets[0],
            "records": [{**base, "title": "A"}],
            "deleted_record_keys": [],
        },
        {
            "schema_version": 1,
            "entry_id": "entry-b",
            "expected_projection_head": targets[0],
            "target_canonical_head": targets[1],
            "records": [{**base, "title": "B"}],
            "deleted_record_keys": [],
        },
    ]
    root = owner.paths["canonical_root"] / "projection-outbox"
    root.mkdir(parents=True, exist_ok=True)
    # Reverse lexical order: a drainer that trusts filenames instead of the head chain fails.
    (root / "000-b.json").write_text(json.dumps(entries[1], sort_keys=True) + "\n")
    (root / "999-a.json").write_text(json.dumps(entries[0], sort_keys=True) + "\n")
    owner.state["canonical_head"] = targets[-1]
    owner.state["projection_head"] = initial
    owner._save_state()
    subprocess.run(
        ["git", "-C", str(owner.paths["canonical_root"]), "add", "projection-outbox"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(owner.paths["canonical_root"]), "commit", "-qm", "seed outbox"],
        check=True,
    )
    return initial, targets, entries


def _applied_markers(owner: KnowledgeRuntime) -> list[Path]:
    root = owner.paths["canonical_root"] / "projection-outbox-applied"
    return sorted(root.glob("*.json"))


def _projection_snapshot(path: Path) -> tuple[list[tuple], list[tuple], list[tuple]]:
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT record_key,record_type,stable_id,project_id,canonical_head,"
            "payload_sha256,payload_json,search_text FROM current_records ORDER BY record_key"
        ).fetchall()
        fts = connection.execute(
            "SELECT rowid,record_key,text FROM current_fts ORDER BY rowid"
        ).fetchall()
        meta = connection.execute(
            "SELECT singleton,projection_head,resource_manifest_sha256,resource_rows_sha256 "
            "FROM projection_meta ORDER BY singleton"
        ).fetchall()
    return [tuple(row) for row in rows], [tuple(row) for row in fts], [tuple(row) for row in meta]


async def _wait_until(predicate, *, attempts: int = 500) -> bool:
    for _attempt in range(attempts):
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


async def _cancel(task) -> None:
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_t2_restart_drains_linked_receipts_by_head_not_filename(tmp_path, monkeypatch):
    owner, config, _evidence, _calls = _runtime(tmp_path, monkeypatch)
    initial, targets, _entries = _seed_outbox(owner)
    restarted = KnowledgeRuntime(config)
    applied = []
    original_update = SQLiteProjectionBackend.update_current_records

    def observe_update(backend, **kwargs):
        applied.append(kwargs["canonical_head"])
        return original_update(backend, **kwargs)

    monkeypatch.setattr(SQLiteProjectionBackend, "update_current_records", observe_update)
    task = restarted.schedule_projection_repair()
    assert task is not None, "restart did not start the durable outbox drainer"
    try:
        drained = await _wait_until(lambda: not _outbox(restarted))
        assert drained, "durable projection receipts were not applied"
    finally:
        await _cancel(task)

    assert applied == targets
    assert restarted.state["projection_head"] == targets[-1]
    with sqlite3.connect(restarted.paths["current_projection"]) as connection:
        row = connection.execute(
            "SELECT payload_json FROM current_records WHERE record_type='task.state'"
        ).fetchone()
        fts = connection.execute(
            "SELECT f.record_key,f.text FROM current_fts AS f "
            "JOIN current_records AS r ON r.rowid=f.rowid "
            "WHERE r.record_type='task.state'"
        ).fetchall()
    assert json.loads(row[0])["title"] == "B"
    assert len(fts) == 1
    assert fts[0][0] == "task.state:" + json.loads(row[0])["stable_id"]
    assert "B" in fts[0][1]
    assert initial != targets[-1]


def test_t2_sqlite_commit_before_ack_replays_without_loss_or_overtake(tmp_path, monkeypatch):
    owner, config, _evidence, _calls = _runtime(tmp_path, monkeypatch)
    _initial, targets, entries = _seed_outbox(owner)
    outbox_root = owner.paths["canonical_root"] / "projection-outbox"
    outbox_root.chmod(0o500)
    restarted = KnowledgeRuntime(config)
    original_update = SQLiteProjectionBackend.update_current_records
    try:
        assert restarted._drain_projection_outbox_once() == "blocked"
        receipt = SQLiteProjectionBackend(
            path=restarted.paths["current_projection"]
        ).current_receipt(targets[0])
        assert receipt["projection_head"] == targets[0]
        assert len(_outbox(restarted)) == 2, "receipt was lost before durable acknowledgment"
        marker = restarted.paths["canonical_root"] / "projection-outbox-applied" / (
            entries[0]["entry_id"] + ".json"
        )
        assert marker.is_file(), "SQLite committed without an applied marker"
        relative = marker.relative_to(restarted.paths["canonical_root"])
        assert subprocess.check_output(
            ["git", "-C", str(restarted.paths["canonical_root"]), "show", f"HEAD:{relative}"],
        ) == marker.read_bytes(), "applied marker was not Git-committed before receipt removal"
    finally:
        outbox_root.chmod(0o700)

    replayed = KnowledgeRuntime(config)
    replay_apply = []

    def observe_replay(backend, **kwargs):
        replay_apply.append(kwargs["canonical_head"])
        return original_update(backend, **kwargs)

    monkeypatch.setattr(SQLiteProjectionBackend, "update_current_records", observe_replay)
    assert replayed._drain_projection_outbox_once() == "progress"
    assert replay_apply == [], "restart reapplied the already-committed A payload"
    assert replayed._drain_projection_outbox_once() == "progress"
    assert replayed._drain_projection_outbox_once() == "idle"

    assert replay_apply == [targets[1]], "restart reapplied or overtook the acknowledged SQLite head"
    assert replayed.state["projection_head"] == targets[-1]
    assert not _outbox(replayed)
    assert not _applied_markers(replayed)
    with sqlite3.connect(replayed.paths["current_projection"]) as connection:
        row = connection.execute(
            "SELECT payload_json FROM current_records WHERE record_type='task.state'"
        ).fetchone()
        fts = connection.execute(
            "SELECT f.record_key,f.text FROM current_fts AS f "
            "JOIN current_records AS r ON r.rowid=f.rowid "
            "WHERE r.record_type='task.state'"
        ).fetchall()
        head = connection.execute(
            "SELECT projection_head FROM projection_meta WHERE singleton=1"
        ).fetchone()[0]
    assert json.loads(row[0])["title"] == "B"
    assert len(fts) == 1
    assert fts[0][0] == "task.state:" + json.loads(row[0])["stable_id"]
    assert "B" in fts[0][1]
    assert head == targets[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["missing-fields", "fork", "cycle", "duplicate-target"])
async def test_t2_malformed_receipt_is_retained_as_visible_debt(
    tmp_path, monkeypatch, corruption,
):
    owner, config, _evidence, _calls = _runtime(tmp_path, monkeypatch)
    initial = owner.state["projection_head"]
    root = owner.paths["canonical_root"] / "projection-outbox"
    root.mkdir(parents=True, exist_ok=True)
    base = next(iter(owner.task_store.states().values()))
    target_a = "sha256:" + "a" * 64
    target_b = "sha256:" + "b" * 64
    if corruption == "missing-fields":
        entries = [{"schema_version": 1, "expected_projection_head": initial}]
    elif corruption == "fork":
        entries = [
            {
                "schema_version": 1,
                "entry_id": "fork-a",
                "expected_projection_head": initial,
                "target_canonical_head": target_a,
                "records": [{**base, "title": "A"}],
                "deleted_record_keys": [],
            },
            {
                "schema_version": 1,
                "entry_id": "fork-b",
                "expected_projection_head": initial,
                "target_canonical_head": target_b,
                "records": [{**base, "title": "B"}],
                "deleted_record_keys": [],
            },
        ]
    elif corruption == "cycle":
        entries = [
            {
                "schema_version": 1,
                "entry_id": "cycle-a",
                "expected_projection_head": target_b,
                "target_canonical_head": target_a,
                "records": [{**base, "title": "A"}],
                "deleted_record_keys": [],
            },
            {
                "schema_version": 1,
                "entry_id": "cycle-b",
                "expected_projection_head": target_a,
                "target_canonical_head": target_b,
                "records": [{**base, "title": "B"}],
                "deleted_record_keys": [],
            },
        ]
    else:
        entries = [
            {
                "schema_version": 1,
                "entry_id": "duplicate-a",
                "expected_projection_head": initial,
                "target_canonical_head": target_a,
                "records": [{**base, "title": "A"}],
                "deleted_record_keys": [],
            },
            {
                "schema_version": 1,
                "entry_id": "duplicate-b",
                "expected_projection_head": target_a,
                "target_canonical_head": target_a,
                "records": [{**base, "title": "B"}],
                "deleted_record_keys": [],
            },
        ]
    malformed_paths = []
    for index, entry in enumerate(entries):
        path = root / f"malformed-{index}.json"
        path.write_text(json.dumps(entry, sort_keys=True) + "\n")
        malformed_paths.append(path)
    subprocess.run(
        ["git", "-C", str(owner.paths["canonical_root"]), "add", "projection-outbox"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(owner.paths["canonical_root"]), "commit", "-qm", "malformed"],
        check=True,
    )
    before = _projection_snapshot(owner.paths["current_projection"])

    restarted = KnowledgeRuntime(config)
    task = restarted.schedule_projection_repair()
    assert task is not None, "restart ignored a durable malformed receipt"
    try:
        visible = await _wait_until(lambda: any(
            json.loads(path.read_text()).get("reason") == "projection_outbox_invalid"
            for path in (restarted.config.state_root / "debt").glob("*.json")
        ))
        assert visible, "malformed receipt did not become visible debt"
    finally:
        await _cancel(task)

    assert all(path.exists() for path in malformed_paths)
    assert _projection_snapshot(restarted.paths["current_projection"]) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("dirty_state", ["uncommitted-marker", "missing-receipt"])
async def test_t2_git_head_reconciles_dirty_runtime_paths_without_false_ack(
    tmp_path, monkeypatch, dirty_state,
):
    owner, config, _evidence, _calls = _runtime(tmp_path, monkeypatch)
    initial, targets, entries = _seed_outbox(owner)
    if dirty_state == "uncommitted-marker":
        marker = owner.paths["canonical_root"] / "projection-outbox-applied" / (
            entries[0]["entry_id"] + ".json"
        )
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"entry_id": entries[0]["entry_id"]}) + "\n")
    else:
        (owner.paths["canonical_root"] / "projection-outbox" / "999-a.json").unlink()

    restarted = KnowledgeRuntime(config)
    applied = []
    original_update = SQLiteProjectionBackend.update_current_records

    def observe_update(backend, **kwargs):
        applied.append(kwargs["canonical_head"])
        return original_update(backend, **kwargs)

    monkeypatch.setattr(SQLiteProjectionBackend, "update_current_records", observe_update)
    task = restarted.schedule_projection_repair()
    assert task is not None, "restart ignored Git HEAD/worktree outbox divergence"
    try:
        assert await _wait_until(
            lambda: not _outbox(restarted) and not _applied_markers(restarted)
        )
    finally:
        await _cancel(task)

    assert applied == targets
    debts = [
        json.loads(path.read_text())
        for path in (restarted.config.state_root / "debt").glob("*.json")
    ]
    assert any(item.get("reason") == "projection_outbox_worktree_diverged" for item in debts)
    assert restarted.state["projection_head"] != initial


@pytest.mark.asyncio
async def test_t2_concurrent_enqueue_during_sqlite_apply_extends_tail_without_deadlock(
    tmp_path, monkeypatch,
):
    owner, config, _evidence, _calls = _runtime(tmp_path, monkeypatch)
    initial, targets, _entries = _seed_outbox(owner)
    restarted = KnowledgeRuntime(config)
    sqlite_entered = threading.Event()
    release_sqlite = threading.Event()
    applied = []
    original_update = SQLiteProjectionBackend.update_current_records

    def block_first_update(backend, **kwargs):
        if not applied:
            sqlite_entered.set()
            if not release_sqlite.wait(3):
                raise RuntimeError("test did not release SQLite apply")
        applied.append(kwargs["canonical_head"])
        return original_update(backend, **kwargs)

    monkeypatch.setattr(SQLiteProjectionBackend, "update_current_records", block_first_update)
    task = restarted.schedule_projection_repair()
    assert task is not None, "restart did not start the durable outbox drainer"
    writer = None
    try:
        assert await asyncio.to_thread(sqlite_entered.wait, 2)
        record = next(iter(restarted.task_store.states().values()))
        writer = asyncio.create_task(asyncio.to_thread(
            restarted._record_task_head,
            "task-head-concurrent",
            changed_records=[{**record, "title": "concurrent"}],
        ))
        await asyncio.wait_for(writer, timeout=2)
        concurrent_target = restarted.state["canonical_head"]
        chain = _ordered(
            [entry for _path, entry in _outbox(restarted)],
            initial,
        )
        assert [entry["target_canonical_head"] for entry in chain] == [
            *targets,
            concurrent_target,
        ]
        release_sqlite.set()
        assert await _wait_until(lambda: not _outbox(restarted))
    finally:
        release_sqlite.set()
        if writer is not None and not writer.done():
            writer.cancel()
        await _cancel(task)

    assert applied == [*targets, concurrent_target]


@pytest.mark.asyncio
async def test_t2_long_lived_drainer_cancels_cleanly_while_idle(tmp_path, monkeypatch):
    owner, _config, _evidence, _calls = _runtime(tmp_path, monkeypatch)
    task = owner.schedule_projection_repair()
    assert task is not None, "lifespan received no long-lived projection drainer"
    await asyncio.sleep(0)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
