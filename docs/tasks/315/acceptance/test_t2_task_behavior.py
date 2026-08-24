"""Frozen RED oracle for #315 T2: Git-canonical tasks + SQLite projection.

The smallest public seam frozen here is ``app.ia.task_store``:

* ``build_migration_manifest(snapshot) -> Mapping``;
* ``TaskStore(canonical_root=Path, projection_path=Path)`` with the methods
  listed in ``fixtures/t2_task_store_contract.json``;
* typed migration, identity, concurrency, provenance, projection-debt and
  excluded-domain errors listed in the same contract.

``TaskStore`` methods mirror the normalized behavior currently exposed through
``app.tm`` → ``app.routes.tm`` → MCP task_create/list/get/update, while adding
stable UUID/head receipts. Imports are inside tests, so absent production code
is a behavior failure after the independent harness controls pass.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
FIXTURE_PATH = HERE / "fixtures" / "t2_task_store_records.json"
CONTRACT_PATH = HERE / "fixtures" / "t2_task_store_contract.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture() -> dict:
    return _json(FIXTURE_PATH)


def _contract() -> dict:
    return _json(CONTRACT_PATH)


def _canonical_json(value: Mapping) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _load_api():
    module_name = _contract()["public_api"]["module"]
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        pytest.fail(f"#315 T2 missing behavior: cannot import {module_name}: {exc}")

    surface = _contract()["public_api"]
    for name in surface["callables"]:
        assert callable(getattr(module, name, None)), (
            f"#315 T2 missing behavior: {module_name}.{name} is not callable"
        )
    for name in surface["classes"]:
        assert isinstance(getattr(module, name, None), type), (
            f"#315 T2 missing behavior: {module_name}.{name} is not a class"
        )
    for name in surface["exceptions"]:
        error = getattr(module, name, None)
        assert isinstance(error, type) and issubclass(error, Exception), (
            f"#315 T2 missing behavior: {module_name}.{name} is not an exception"
        )
    for name in surface["task_store_methods"]:
        assert callable(getattr(module.TaskStore, name, None)), (
            f"#315 T2 missing behavior: TaskStore.{name} is not callable"
        )
    return module


def _build_manifest(api) -> dict:
    return api.build_migration_manifest(copy.deepcopy(_fixture()["snapshot"]))


def _stable_for_source(manifest: Mapping, source_row_id: int) -> str:
    matches = [
        task["stable_id"]
        for task in manifest["tasks"]
        if task["source_row"]["table"] == "tm_tasks"
        and task["source_row"]["row_id"] == source_row_id
    ]
    assert len(matches) == 1, f"source row {source_row_id} mapped {len(matches)} times"
    return matches[0]


def _materialize_events(events: Sequence[Mapping], manifest: Mapping) -> list[dict]:
    materialized = []
    for raw in events:
        event = copy.deepcopy(dict(raw))
        source_row_id = event.pop("task_source_row_id", None)
        if source_row_id is not None:
            event["stable_id"] = _stable_for_source(manifest, source_row_id)
        materialized.append(event)
    return materialized


def _new_store(api, tmp_path: Path):
    canonical_root = tmp_path / "canonical"
    projection_path = tmp_path / "projection.sqlite3"
    store = api.TaskStore(
        canonical_root=canonical_root,
        projection_path=projection_path,
    )
    manifest = _build_manifest(api)
    receipt = store.migrate(manifest)
    return store, manifest, receipt, canonical_root, projection_path


def _assert_subset(actual: Mapping, expected: Mapping) -> None:
    assert {key: actual[key] for key in expected} == dict(expected)


def _file_fingerprints(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _projection_columns(path: Path) -> set[str]:
    table = _contract()["projection"]["table"]
    with sqlite3.connect(path) as connection:
        return {
            row[1]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }


def _prepare_legacy_db(tmp_path: Path, monkeypatch):
    """Create isolated current tm_* state; never touch the production DB."""
    from app import db
    from app import tm

    db_path = tmp_path / "legacy.sqlite3"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    with tm._conn() as connection:
        connection.execute(
            """INSERT INTO tm_projects
               (id, name, prefix, scope, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "orchestra",
                "Orchestra",
                "ORC",
                "/scope-t2",
                "2026-08-24T00:00:00Z",
            ),
        )
    return tm


def _ia_mode(tm, mode: str, tmp_path: Path):
    configurator = getattr(tm, "ia_task_store_mode", None)
    assert callable(configurator), (
        "#315 T2 missing production hook: app.tm.ia_task_store_mode is not callable"
    )
    return configurator(
        mode=mode,
        canonical_root=tmp_path / f"canonical-{mode}",
        projection_path=tmp_path / f"projection-{mode}.sqlite3",
        cutoff="2026-08-24T05:00:00Z",
        source_head="git:cccccccccccccccccccccccccccccccccccccccc",
    )


def _asgi_app():
    from fastapi import FastAPI

    from app.routes.tm import router

    app = FastAPI()
    app.include_router(router)
    return app


def _asgi_transport_api(app):
    """MCP fake ends at HTTP transport; route/app.tm remain production code."""
    import httpx

    async def call(method, path, **kwargs):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://t2.test",
        ) as client:
            response = await client.request(
                method,
                path,
                params=kwargs.get("params"),
                json=kwargs.get("json"),
            )
        return response.json()

    return call


def _assert_candidate_receipts(value: Mapping, *, mode: str) -> None:
    assert value["ia_mode"] == mode
    assert value["canonical_head"]
    assert value["projection_head"]
    assert value["canonical_head"] == value["projection_head"]
    assert value["stable_id"]
    uuid.UUID(value["stable_id"])
    assert isinstance(value["evidence_refs"], Sequence)


def _nested_field_names(value) -> set[str]:
    if isinstance(value, Mapping):
        return set(value) | {
            nested
            for child in value.values()
            for nested in _nested_field_names(child)
        }
    if isinstance(value, list):
        return {
            nested
            for child in value
            for nested in _nested_field_names(child)
        }
    return set()


def _assert_canonical_payloads_exclude_removed_domains(payloads: Sequence[Mapping]) -> None:
    contract = _contract()
    forbidden_names = set(contract["forbidden_canonical_field_names"])
    assert payloads, "canonical payload scope is unexpectedly empty"
    for payload in payloads:
        assert forbidden_names.isdisjoint(_nested_field_names(payload))
        rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        for forbidden_value in contract["forbidden_canonical_values"]:
            assert forbidden_value not in rendered


def test_t2_harness_fixture_hash_denominators_and_controls_are_frozen():
    """Positive control: all frozen inputs load without the production seam."""
    fixture = _fixture()
    contract = _contract()
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == contract["fixture_sha256"]
    snapshot = fixture["snapshot"]
    assert len(snapshot["projects"]) == fixture["expected_denominators"]["projects"]
    assert len(snapshot["tasks"]) == fixture["expected_denominators"]["tasks"]
    assert len(snapshot["evidence"]) == fixture["expected_denominators"]["evidence"]
    assert sum(len(task["git_commits"]) for task in snapshot["tasks"]) == (
        fixture["expected_denominators"]["commit_links"]
    )
    assert {task["par_number"] for task in snapshot["tasks"]} == {315, 316}
    scoped_315 = [task["project_id"] for task in snapshot["tasks"] if task["par_number"] == 315]
    assert scoped_315 == ["orchestra", "client-alpha"]


def test_t2_harness_audit_names_removed_field_but_canonical_scope_forbids_it():
    """Positive control: audit vocabulary and canonical payload scope are distinct."""
    contract = _contract()
    assert "tm_tasks.yougile_task_id" in contract["excluded_source_domains"]
    assert "yougile_task_id" in contract["forbidden_canonical_field_names"]
    canonical_payloads = [
        {"record_type": "task.state", "title": "safe task body"},
        {
            "record_type": "task.evidence",
            "canonical_path": "docs/tasks/315/research.md",
        },
        {"event_type": "task.updated", "changes": {"title": "safe event body"}},
    ]
    _assert_canonical_payloads_exclude_removed_domains(canonical_payloads)
    with pytest.raises(AssertionError):
        _assert_canonical_payloads_exclude_removed_domains(
            canonical_payloads + [{"yougile_task_id": "must be caught"}]
        )


def test_t2_harness_compound_collision_and_lww_mutants_are_material():
    """Positive control: global MAX+1 and LWW mutants really collide."""
    fixture = _fixture()
    collision = fixture["global_max_plus_one_collision"]
    assert len({event["stable_id"] for event in collision}) == 2
    assert len({event["contour_id"] for event in collision}) == 2
    assert len({(event["project_id"], event["display_number"]) for event in collision}) == 1

    lww = fixture["lww_conflict_events"]
    assert len({event["contour_id"] for event in lww}) == 2
    assert len({event["base_revision"] for event in lww}) == 1
    assert len({event["base_head"] for event in lww}) == 1
    changed_fields = [set(event["changes"]) for event in lww]
    assert changed_fields == [{"title"}, {"title"}]
    assert lww[0]["changes"]["title"] != lww[1]["changes"]["title"]


def test_t2_harness_db_bypass_and_provenance_mutants_are_material():
    """Positive control: bypass changes truth fields; evidence lacks every source field."""
    fixture = _fixture()
    bypass = fixture["db_second_truth_mutation"]
    assert bypass["replace"] == {
        "title": "T2_DB_BYPASS_MUST_NOT_WIN",
        "status": "cancelled",
    }
    assert bypass["extra_projection_metadata"]["backend_note"] == (
        "T2_SAFE_EXTRA_PROJECTION_METADATA"
    )
    source_less = fixture["source_less_evidence"]
    required = {"canonical_path", "anchor", "git_commit", "content_sha256"}
    assert required.isdisjoint(source_less)
    assert fixture["excluded_event"]["event_type"] == "payment.received"


def test_t2_harness_legacy_default_preserves_exact_current_app_tm_outputs(
    tmp_path,
    monkeypatch,
):
    """Positive control: current shared owner works before candidate wiring exists."""
    tm = _prepare_legacy_db(tmp_path, monkeypatch)
    created = tm.api_create_task(
        "orchestra",
        "Legacy control",
        price=12000,
        description="legacy description",
        assignee="legacy-worker",
        status="new",
        priority=1,
    )
    assert created == {
        "par": "1",
        "id": 1,
        "title": "Legacy control",
        "project": "orchestra",
        "price_rub": 12000,
        "status": "new",
    }
    assert tm.api_list_tasks(project="orchestra") == {
        "tasks": [
            {
                "par": "1",
                "title": "Legacy control",
                "project": "orchestra",
                "price": "12 000",
                "status": "new",
                "assignee": "legacy-worker",
                "priority": 1,
            }
        ],
        "count": 1,
    }
    detail = tm.api_get_task("#1", project="orchestra")
    assert set(detail) == set(_contract()["normalized_facade"]["get_fields"])
    _assert_subset(
        detail,
        {
            "par": "1",
            "title": "Legacy control",
            "description": "legacy description",
            "project": "orchestra",
            "price_rub": 12000,
            "status": "new",
            "assignee": "legacy-worker",
            "priority": 1,
            "commits": [],
            "sync_revision": 0,
        },
    )

    updated = tm.api_update_task(
        "1",
        title="Legacy updated",
        status="done",
        project="orchestra",
    )
    assert updated == {
        "par": "1",
        "project": "orchestra",
        "updated": ["title", "status"],
        "old_status": "new",
        "new_status": "done",
        "price_rub": 12000,
    }
    identity = tm.resolve_scoped_task_identity("/scope-t2", "1")
    status = tm.api_update_task_if_current(
        identity,
        status="in_progress",
        worker_session_id="legacy-session",
    )
    assert status == {
        "ok": True,
        "task_id": 1,
        "par": "1",
        "updated": ["status"],
        "new_status": "in_progress",
        "sync_revision": 2,
    }
    linked = tm.link_commits_to_task(
        "1",
        [{"hash": "9999999999999999999999999999999999999999"}],
        "orchestra",
    )
    assert linked == {"ok": True, "added": 1, "task_id": 1}
    assert tm.api_get_task("1", project="orchestra")["commits"] == [
        {"hash": "9999999999999999999999999999999999999999"}
    ]
    receipt_fields = set(_contract()["production_adapter"]["receipt_fields"])
    assert receipt_fields.isdisjoint(created)
    assert receipt_fields.isdisjoint(tm.api_get_task("1", project="orchestra"))


@pytest.mark.asyncio
async def test_t2_harness_asgi_and_mcp_reach_the_shared_app_tm_owner(
    tmp_path,
    monkeypatch,
):
    """Positive control: real route and MCP transport both reach app.tm today."""
    import httpx

    import app.mcp_stdio as mcp

    tm = _prepare_legacy_db(tmp_path, monkeypatch)
    app = _asgi_app()
    owner_calls = []
    real_create = tm.api_create_task

    def tracked_create(*args, **kwargs):
        owner_calls.append((args, kwargs))
        return real_create(*args, **kwargs)

    monkeypatch.setattr(tm, "api_create_task", tracked_create)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t2.test") as client:
        response = await client.post(
            "/api/tm/tasks",
            json={"title": "ASGI legacy control", "project": "orchestra"},
        )
    assert response.status_code == 200
    assert response.json()["title"] == "ASGI legacy control"

    monkeypatch.setattr(mcp, "SCOPE", "/scope-t2")
    monkeypatch.setattr(mcp, "_api", _asgi_transport_api(app))
    mcp_result = json.loads(
        await mcp.task_create(title="MCP legacy control", project="orchestra")
    )
    assert mcp_result["title"] == "MCP legacy control"
    assert [call[0][1] for call in owner_calls] == [
        "ASGI legacy control",
        "MCP legacy control",
    ]
    assert tm.api_list_tasks(project="orchestra")["count"] == 2


def test_t2_manifest_is_deterministic_content_bound_and_excludes_removed_domains():
    api = _load_api()
    snapshot = _fixture()["snapshot"]
    manifest = _build_manifest(api)
    assert manifest == _build_manifest(api)
    assert manifest["manifest_version"] == 1
    assert manifest["source"] == snapshot["source"]
    assert manifest["denominators"] == _fixture()["expected_denominators"]
    assert manifest["excluded_sources"] == _contract()["excluded_source_domains"]
    assert len(manifest["tasks"]) == 3
    assert len(manifest["evidence"]) == 2

    stable_ids = []
    source_rows = []
    for task in manifest["tasks"]:
        source = task["source_row"]
        expected_uuid = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"orch://migration/task/{task['project_id']}/tm_tasks/{source['row_id']}",
        )
        assert task["stable_id"] == str(expected_uuid)
        assert task["record_type"] == "task.state"
        assert task["uri"] == (
            f"orch://project/{task['project_id']}/tasks/{task['stable_id']}/state"
        )
        assert task["display_ref"] == f"#{task['display_number']}"
        assert source["table"] == "tm_tasks"
        assert source["row_sha256"].startswith("sha256:")
        stable_ids.append(task["stable_id"])
        source_rows.append((source["table"], source["row_id"]))
    assert len(stable_ids) == len(set(stable_ids)) == 3
    assert len(source_rows) == len(set(source_rows)) == 3
    for evidence in manifest["evidence"]:
        assert evidence["record_type"] == "task.evidence"
        assert evidence["task_id"] in stable_ids
        assert evidence["canonical_path"]
        assert evidence["anchor"]
        assert evidence["git_commit"]
        assert evidence["content_sha256"].startswith("sha256:")

    # excluded_sources is audit metadata and intentionally names removed domains.
    # Only canonical task/evidence/event bodies are subject to the field/value ban.
    canonical_payloads = [
        *manifest["tasks"],
        *manifest["evidence"],
        *manifest.get("events", []),
    ]
    _assert_canonical_payloads_exclude_removed_domains(canonical_payloads)

    detached = copy.deepcopy(snapshot)
    built = api.build_migration_manifest(detached)
    detached["tasks"][0]["title"] = "mutated after build"
    assert built == manifest


def test_t2_migration_writes_per_task_json_and_current_sqlite_projection(tmp_path):
    api = _load_api()
    store, manifest, receipt, root, projection_path = _new_store(api, tmp_path)
    assert receipt["canonical_head"] == manifest["canonical_head"]
    assert receipt["projection_head"] == manifest["canonical_head"]
    assert receipt["task_count"] == 3
    assert receipt["event_count"] == 3
    assert receipt["evidence_count"] == 2

    layout = _contract()["canonical_layout"]
    assert (root / layout["manifest"].format(manifest_id=manifest["manifest_id"])).is_file()
    for task in manifest["tasks"]:
        state_path = root / layout["task_state"].format(**task)
        assert json.loads(state_path.read_text(encoding="utf-8"))["stable_id"] == task["stable_id"]
        event_paths = list(state_path.parent.joinpath("events").glob("*.json"))
        assert len(event_paths) == 1
    assert len(list(root.rglob("state.json"))) == 3
    assert len(list(root.rglob("events/*.json"))) == 3
    assert len(list(root.rglob("evidence/*.json"))) == 2
    assert not list(root.rglob("*.jsonl"))
    for path in root.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))

    columns = _projection_columns(projection_path)
    assert set(_contract()["projection"]["required_columns"]) <= columns
    table = _contract()["projection"]["table"]
    with sqlite3.connect(projection_path) as connection:
        count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    assert count == 3

    canonical_body_paths = [
        *root.rglob("state.json"),
        *root.rglob("events/*.json"),
        *root.rglob("evidence/*.json"),
    ]
    canonical_payloads = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in canonical_body_paths
    ]
    _assert_canonical_payloads_exclude_removed_domains(canonical_payloads)
    assert store.task_list(project="orchestra")["count"] == 2


def test_t2_manifest_migration_and_same_head_replay_are_idempotent(tmp_path):
    api = _load_api()
    store, manifest, first, root, projection_path = _new_store(api, tmp_path)
    before_files = _file_fingerprints(root)
    second = store.migrate(copy.deepcopy(manifest))
    replay_one = store.replay(head=first["canonical_head"])
    replay_two = store.replay(head=first["canonical_head"])
    assert second["canonical_head"] == first["canonical_head"]
    assert second["projection_head"] == first["projection_head"]
    assert replay_one == replay_two
    assert replay_two["canonical_head"] == first["canonical_head"]
    assert replay_two["projection_head"] == first["canonical_head"]
    assert _file_fingerprints(root) == before_files

    table = _contract()["projection"]["table"]
    with sqlite3.connect(projection_path) as connection:
        rows = connection.execute(
            f"SELECT stable_id, COUNT(*) FROM {table} GROUP BY stable_id"
        ).fetchall()
    assert len(rows) == 3
    assert all(count == 1 for _, count in rows)


def test_t2_replayed_projection_preserves_normalized_list_and_get_facade(tmp_path):
    api = _load_api()
    store, manifest, receipt, _, projection_path = _new_store(api, tmp_path)
    listed = store.task_list(project="orchestra")
    assert listed == {
        "tasks": [
            {
                "par": "315",
                "title": "Canonical task boundary",
                "project": "orchestra",
                "price": "20 000",
                "status": "in_progress",
                "assignee": "worker-alpha",
                "priority": 1,
            },
            {
                "par": "316",
                "title": "Projection replay",
                "project": "orchestra",
                "price": "0",
                "status": "new",
                "assignee": "",
                "priority": 2,
            },
        ],
        "count": 2,
    }

    detail = store.task_get("#315", project="orchestra")
    _assert_subset(
        detail,
        {
            "par": "315",
            "title": "Canonical task boundary",
            "description": "Preserve this legacy task body.",
            "project": "orchestra",
            "price_rub": 20000,
            "status": "in_progress",
            "assignee": "worker-alpha",
            "priority": 1,
            "created_at": "2026-08-20T00:00:00Z",
            "completed_at": None,
            "commits": [
                {
                    "hash": "1111111111111111111111111111111111111111",
                    "subject": "#315: freeze architecture",
                }
            ],
            "sync_revision": 0,
        },
    )
    assert detail["stable_id"] == _stable_for_source(manifest, 101)
    assert detail["display_ref"] == "#315"
    assert detail["canonical_head"] == receipt["canonical_head"]
    assert detail["projection_head"] == receipt["projection_head"]
    assert detail["worker_session_id"] == "session-t2-alpha"
    assert detail["acceptance"] == {
        "command": "uv run python -m pytest docs/tasks/315/acceptance/test_t2_task_behavior.py -q",
        "manifest_paths": ["docs/tasks/315/acceptance/test_t2_task_behavior.py"],
        "required": True,
    }

    table = _contract()["projection"]["table"]
    with sqlite3.connect(projection_path) as connection:
        connection.execute(
            f"UPDATE {table} SET metadata_json=? WHERE stable_id=?",
            (
                json.dumps({"rank_hint": 0.5, "new_backend_field": "safe"}),
                detail["stable_id"],
            ),
        )
        connection.commit()
    assert store.task_list(project="orchestra") == listed
    _assert_subset(store.task_get("315", project="orchestra"), detail)


def test_t2_create_update_acceptance_worker_and_commit_facades_preserve_contract(tmp_path):
    api = _load_api()
    store, _, receipt, _, _ = _new_store(api, tmp_path)
    head = receipt["canonical_head"]

    created_orchestra = store.task_create(
        project_id="orchestra",
        title="Created through T2 facade",
        price=12000,
        description="new task body",
        assignee="worker-new",
        status="new",
        priority=2,
        expected_head=head,
        contour_id="central",
    )
    _assert_subset(
        created_orchestra,
        {
            "par": "317",
            "title": "Created through T2 facade",
            "project": "orchestra",
            "price_rub": 12000,
            "status": "new",
        },
    )
    uuid.UUID(created_orchestra["stable_id"])

    created_alpha = store.task_create(
        project_id="client-alpha",
        title="Project-local number control",
        price=0,
        description="",
        assignee="",
        status="new",
        priority=2,
        expected_head=created_orchestra["canonical_head"],
        contour_id="central",
    )
    assert created_alpha["par"] == "316"
    assert created_alpha["project"] == "client-alpha"

    updated = store.task_update(
        "315",
        project="orchestra",
        title="Updated canonical title",
        status="done",
        acceptance_command="uv run python -m pytest tests -q",
        acceptance_manifest=["tests", "pyproject.toml"],
        acceptance_required=True,
        expected_head=created_alpha["canonical_head"],
    )
    _assert_subset(
        updated,
        {
            "par": "315",
            "project": "orchestra",
            "old_status": "in_progress",
            "new_status": "done",
            "price_rub": 20000,
        },
    )
    assert set(updated["updated"]) == {"title", "status", "acceptance_oracle"}

    detail = store.task_get("315", project="orchestra")
    assert detail["title"] == "Updated canonical title"
    assert detail["acceptance"] == {
        "command": "uv run python -m pytest tests -q",
        "manifest_paths": ["pyproject.toml", "tests"],
        "required": True,
    }
    identity = {
        "stable_id": detail["stable_id"],
        "project_id": detail["project"],
        "display_number": int(detail["par"]),
        "sync_revision": detail["sync_revision"],
        "canonical_head": detail["canonical_head"],
    }
    status_result = store.task_update_if_current(
        identity,
        status="in_progress",
        worker_session_id="session-t2-reassigned",
    )
    assert status_result["ok"] is True
    assert status_result["new_status"] == "in_progress"
    detail = store.task_get("315", project="orchestra")
    assert detail["worker_session_id"] == "session-t2-reassigned"

    commit = {
        "hash": "3333333333333333333333333333333333333333",
        "subject": "#315: T2 implementation",
    }
    linked = store.link_commits_to_task(
        "315",
        [commit],
        project_id="orchestra",
        expected_head=detail["canonical_head"],
    )
    assert linked["ok"] is True and linked["added"] == 1
    duplicate = store.link_commits_to_task(
        "315",
        [commit],
        project_id="orchestra",
        expected_head=linked["canonical_head"],
    )
    assert duplicate["ok"] is True and duplicate["added"] == 0
    commits = store.task_get("315", project="orchestra")["commits"]
    assert [item["hash"] for item in commits] == [
        "1111111111111111111111111111111111111111",
        "3333333333333333333333333333333333333333",
    ]


def test_t2_two_contours_merge_disjoint_fields_and_preserve_both_events(tmp_path):
    api = _load_api()
    store, manifest, receipt, root, _ = _new_store(api, tmp_path)
    events = _materialize_events(_fixture()["two_contour_disjoint_events"], manifest)
    merged = store.apply_events(events, expected_head=receipt["canonical_head"])
    assert merged["status"] == "merged"
    assert set(merged["event_ids"]) == {event["event_id"] for event in events}
    detail = store.task_get("315", project="orchestra")
    assert detail["title"] == "Title written on contour A"
    assert detail["assignee"] == "worker-from-contour-b"
    event_files = {path.stem for path in root.rglob("events/*.json")}
    assert {event["event_id"] for event in events} <= event_files


def test_t2_same_field_concurrency_never_silently_loses_a_contour(tmp_path):
    api = _load_api()
    store, manifest, receipt, _, _ = _new_store(api, tmp_path)
    events = _materialize_events(_fixture()["lww_conflict_events"], manifest)
    before = store.task_get("315", project="orchestra")
    event_ids = {event["event_id"] for event in events}
    try:
        result = store.apply_events(events, expected_head=receipt["canonical_head"])
    except api.ConcurrentTaskUpdateError as exc:
        assert set(exc.event_ids) == event_ids
    else:
        assert result["status"] == "disputed"
        assert set(result["event_ids"]) == event_ids
    after = store.task_get("315", project="orchestra")
    assert after["title"] == before["title"]
    assert after["title"] not in {event["changes"]["title"] for event in events}


def test_t2_global_max_plus_one_collision_is_an_identity_conflict(tmp_path):
    api = _load_api()
    store, _, receipt, _, _ = _new_store(api, tmp_path)
    events = copy.deepcopy(_fixture()["global_max_plus_one_collision"])
    with pytest.raises(api.IdentityConflictError):
        store.apply_events(events, expected_head=receipt["canonical_head"])
    with pytest.raises((KeyError, ValueError)):
        store.task_get("317", project="orchestra")


def test_t2_projection_cannot_become_second_truth_but_safe_metadata_is_additive(tmp_path):
    api = _load_api()
    store, manifest, receipt, _, projection_path = _new_store(api, tmp_path)
    stable_id = _stable_for_source(manifest, 101)
    table = _contract()["projection"]["table"]
    bypass = _fixture()["db_second_truth_mutation"]

    with sqlite3.connect(projection_path) as connection:
        raw = connection.execute(
            f"SELECT payload_json FROM {table} WHERE stable_id=?", (stable_id,)
        ).fetchone()[0]
        payload = json.loads(raw)
        payload.update(bypass["replace"])
        payload_json = _canonical_json(payload).decode("utf-8")
        connection.execute(
            f"UPDATE {table} SET payload_json=?, payload_sha256=?, metadata_json=? "
            "WHERE stable_id=?",
            (
                payload_json,
                f"sha256:{hashlib.sha256(payload_json.encode()).hexdigest()}",
                json.dumps(bypass["extra_projection_metadata"], sort_keys=True),
                stable_id,
            ),
        )
        connection.commit()

    try:
        detail = store.task_get("315", project="orchestra")
    except api.ProjectionDebtError:
        pass
    else:
        assert detail["title"] == "Canonical task boundary"
        assert detail["status"] == "in_progress"
    repaired = store.replay(head=receipt["canonical_head"])
    assert repaired["projection_head"] == receipt["canonical_head"]
    detail = store.task_get("315", project="orchestra")
    assert detail["title"] == "Canonical task boundary"
    assert detail["status"] == "in_progress"

    with sqlite3.connect(projection_path) as connection:
        connection.execute(
            f"UPDATE {table} SET metadata_json=? WHERE stable_id=?",
            (json.dumps({"future_backend_field": {"version": 2}}), stable_id),
        )
        connection.commit()
    assert store.task_get("315", project="orchestra")["title"] == "Canonical task boundary"


def test_t2_source_less_evidence_and_removed_domain_events_fail_closed(tmp_path):
    api = _load_api()
    store, manifest, receipt, _, _ = _new_store(api, tmp_path)
    source_less = copy.deepcopy(_fixture()["source_less_evidence"])
    source_less["task_id"] = _stable_for_source(manifest, source_less.pop("task_source_row_id"))
    with pytest.raises(api.ProvenanceError):
        store.link_evidence_to_task(
            "315",
            source_less,
            project_id="orchestra",
            expected_head=receipt["canonical_head"],
        )
    detail = store.task_get("315", project="orchestra")
    assert len(detail["evidence_refs"]) == 1

    excluded = _materialize_events([_fixture()["excluded_event"]], manifest)
    with pytest.raises(api.UnsupportedDomainError):
        store.apply_events(excluded, expected_head=receipt["canonical_head"])


def test_t2_rollback_and_forward_replay_reproduce_exact_canonical_heads(tmp_path):
    api = _load_api()
    store, _, initial, _, _ = _new_store(api, tmp_path)
    old_head = initial["canonical_head"]
    original_title = store.task_get("315", project="orchestra")["title"]
    updated = store.task_update(
        "315",
        project="orchestra",
        title="Title at the forward head",
        expected_head=old_head,
    )
    new_head = updated["canonical_head"]
    assert new_head != old_head

    rolled_back = store.replay(head=old_head)
    assert rolled_back["canonical_head"] == old_head
    assert rolled_back["projection_head"] == old_head
    assert store.task_get("315", project="orchestra")["title"] == original_title

    rolled_forward = store.replay(head=new_head)
    assert rolled_forward["canonical_head"] == new_head
    assert rolled_forward["projection_head"] == new_head
    assert store.task_get("315", project="orchestra")["title"] == "Title at the forward head"


def test_t2_shadow_mode_real_app_tm_entrypoints_call_task_store_and_keep_parity(
    tmp_path,
    monkeypatch,
):
    """Removing app.tm -> TaskStore wiring must fail despite green direct-store tests."""
    tm = _prepare_legacy_db(tmp_path, monkeypatch)
    baseline = tm.api_create_task(
        "orchestra",
        "Shadow baseline",
        price=20000,
        description="shadow legacy body",
        assignee="worker-shadow",
        status="new",
        priority=1,
    )
    legacy_list = tm.api_list_tasks(project="orchestra")
    legacy_get = tm.api_get_task("1", project="orchestra")

    with _ia_mode(tm, "shadow", tmp_path):
        shadow_list = tm.api_list_tasks(project="orchestra")
        assert shadow_list["tasks"] == legacy_list["tasks"]
        assert shadow_list["count"] == legacy_list["count"]
        assert shadow_list["ia_mode"] == "shadow"
        assert shadow_list["shadow_match"] is True
        assert shadow_list["canonical_head"] == shadow_list["projection_head"]

        shadow_get = tm.api_get_task("1", project="orchestra")
        for field in _contract()["normalized_facade"]["get_fields"]:
            assert shadow_get[field] == legacy_get[field]
        _assert_candidate_receipts(shadow_get, mode="shadow")

        created = tm.api_create_task(
            "orchestra",
            "Created through shared owner",
            price=0,
            description="candidate mirror body",
            assignee="",
            status="new",
            priority=2,
        )
        _assert_subset(
            created,
            {
                "par": "2",
                "title": "Created through shared owner",
                "project": "orchestra",
                "price_rub": 0,
                "status": "new",
            },
        )
        _assert_candidate_receipts(created, mode="shadow")

        updated = tm.api_update_task(
            "1",
            title="Shadow updated",
            status="done",
            project="orchestra",
            acceptance_command="uv run python -m pytest tests -q",
            acceptance_manifest=["tests", "pyproject.toml"],
            acceptance_required=True,
            acceptance_actor={
                "session_id": "orchestrator-shadow",
                "name": "orchestrator",
                "role": "orchestrator",
                "scope": "/scope-t2",
            },
        )
        assert set(updated["updated"]) == {"title", "status", "acceptance_oracle"}
        _assert_candidate_receipts(updated, mode="shadow")

        identity = tm.resolve_scoped_task_identity("/scope-t2", "1")
        status = tm.api_update_task_if_current(
            identity,
            status="in_progress",
            worker_session_id="session-shadow-candidate",
        )
        assert status["ok"] is True
        assert status["new_status"] == "in_progress"
        _assert_candidate_receipts(status, mode="shadow")

        linked = tm.link_commits_to_task(
            "1",
            [{"hash": "8888888888888888888888888888888888888888"}],
            "orchestra",
        )
        assert linked["ok"] is True and linked["added"] == 1
        _assert_candidate_receipts(linked, mode="shadow")

        final = tm.api_get_task("1", project="orchestra")
        assert final["title"] == "Shadow updated"
        assert final["worker_session_id"] == "session-shadow-candidate"
        assert final["commits"][-1]["hash"] == "8888888888888888888888888888888888888888"
        assert final["acceptance"] == {
            "command": "uv run python -m pytest tests -q",
            "manifest_paths": ["pyproject.toml", "tests"],
            "required": True,
        }

    assert baseline["id"] == 1
    state_files = list((tmp_path / "canonical-shadow").rglob("state.json"))
    assert len(state_files) == 2
    assert len(list((tmp_path / "canonical-shadow").rglob("events/*.json"))) >= 6


def test_t2_shadow_mode_surfaces_legacy_candidate_mismatch_instead_of_ignoring_it(
    tmp_path,
    monkeypatch,
):
    api = _load_api()
    tm = _prepare_legacy_db(tmp_path, monkeypatch)
    tm.api_create_task("orchestra", "Mismatch baseline")

    with _ia_mode(tm, "shadow", tmp_path):
        first = tm.api_get_task("1", project="orchestra")
        _assert_candidate_receipts(first, mode="shadow")
        with tm._conn() as connection:
            connection.execute(
                """UPDATE tm_tasks
                   SET title='T2_HOOK_REMOVED_MUTATION',
                       sync_revision=sync_revision+1
                   WHERE id=1"""
            )
        try:
            mismatch = tm.api_get_task("1", project="orchestra")
        except api.ProjectionDebtError as exc:
            assert "T2_HOOK_REMOVED_MUTATION" in str(exc) or str(exc)
        else:
            assert mismatch["ia_mode"] == "shadow"
            assert mismatch["shadow_match"] is False
            assert mismatch["projection_debt"]
            assert mismatch["canonical_head"]
            assert mismatch["projection_head"]


def test_t2_canonical_mode_uses_task_store_as_owner_and_resets_to_legacy(
    tmp_path,
    monkeypatch,
):
    tm = _prepare_legacy_db(tmp_path, monkeypatch)
    tm.api_create_task("orchestra", "Canonical baseline", description="original")
    receipt_fields = set(_contract()["production_adapter"]["receipt_fields"])

    with _ia_mode(tm, "canonical", tmp_path):
        updated = tm.api_update_task(
            "1",
            title="Canonical owner title",
            project="orchestra",
        )
        _assert_candidate_receipts(updated, mode="canonical")
        with tm._conn() as connection:
            connection.execute(
                """UPDATE tm_tasks
                   SET title='T2_LEGACY_SECOND_TRUTH_ATTEMPT',
                       sync_revision=sync_revision+1
                   WHERE id=1"""
            )
        detail = tm.api_get_task("1", project="orchestra")
        assert detail["ia_mode"] == "canonical"
        assert detail["title"] == "Canonical owner title"
        assert detail["title"] != "T2_LEGACY_SECOND_TRUTH_ATTEMPT"
        assert detail["projection_debt"]
        _assert_candidate_receipts(detail, mode="canonical")

    legacy_again = tm.api_get_task("1", project="orchestra")
    assert receipt_fields.isdisjoint(legacy_again)
    assert "ia_mode" not in legacy_again


@pytest.mark.asyncio
async def test_t2_shadow_asgi_and_mcp_paths_share_app_tm_and_task_store(
    tmp_path,
    monkeypatch,
):
    """HTTP/MCP bypass of app.tm fails owner-call and canonical-artifact assertions."""
    import httpx

    import app.mcp_stdio as mcp

    tm = _prepare_legacy_db(tmp_path, monkeypatch)
    app = _asgi_app()
    owner_calls = []
    real_create = tm.api_create_task

    def tracked_create(*args, **kwargs):
        owner_calls.append((args, kwargs))
        return real_create(*args, **kwargs)

    monkeypatch.setattr(tm, "api_create_task", tracked_create)
    with _ia_mode(tm, "shadow", tmp_path):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://t2.test",
        ) as client:
            created_response = await client.post(
                "/api/tm/tasks",
                json={"title": "ASGI shadow task", "project": "orchestra"},
            )
            listed_response = await client.get(
                "/api/tm/tasks",
                params={"project": "orchestra"},
            )
        assert created_response.status_code == 200
        created = created_response.json()
        _assert_candidate_receipts(created, mode="shadow")
        assert listed_response.status_code == 200
        listed = listed_response.json()
        assert listed["count"] == 1
        assert listed["ia_mode"] == "shadow"
        assert listed["shadow_match"] is True

        monkeypatch.setattr(mcp, "SCOPE", "/scope-t2")
        monkeypatch.setattr(mcp, "_api", _asgi_transport_api(app))
        mcp_created = json.loads(
            await mcp.task_create(title="MCP shadow task", project="orchestra")
        )
        _assert_candidate_receipts(mcp_created, mode="shadow")
        assert mcp_created["task_id"]

    assert [call[0][1] for call in owner_calls] == [
        "ASGI shadow task",
        "MCP shadow task",
    ]
    assert len(list((tmp_path / "canonical-shadow").rglob("state.json"))) == 2
