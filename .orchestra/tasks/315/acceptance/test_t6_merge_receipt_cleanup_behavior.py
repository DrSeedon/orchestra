"""Frozen behavior-level RED oracle for #315 T6 merge receipts and cleanup gates."""

from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


HERE = Path(__file__).resolve().parent
FIXTURE_PATH = HERE / "fixtures" / "t6_merge_receipt_records.json"
CONTRACT_PATH = HERE / "fixtures" / "t6_merge_receipt_contract.json"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture() -> dict:
    return _json(FIXTURE_PATH)


def _contract() -> dict:
    return _json(CONTRACT_PATH)


def _canonical_bytes(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value) + b"\n")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_t6_api() -> SimpleNamespace:
    modules = {}
    for module_name, surface in _contract()["public_api"].items():
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            pytest.fail(f"#315 T6 missing behavior: cannot import {module_name}: {exc}")
        for name in surface.get("callables", []):
            assert callable(getattr(module, name, None)), (
                f"#315 T6 missing behavior: {module_name}.{name} is not callable"
            )
        for name in surface.get("exceptions", []):
            error = getattr(module, name, None)
            assert isinstance(error, type) and issubclass(error, Exception), (
                f"#315 T6 missing behavior: {module_name}.{name} is not an exception"
            )
        for name in surface.get("attributes", []):
            assert getattr(module, name, None) is not None, (
                f"#315 T6 missing behavior: {module_name}.{name} is absent"
            )
        modules[module_name.replace(".", "_")] = module
    return SimpleNamespace(**modules)


def _assert_receipt(receipt: dict, *, operation_id: str | None = None) -> None:
    fixture = _fixture()
    assert set(_contract()["receipt_required"]) <= set(receipt)
    assert receipt["receipt_status"] == "verified"
    assert receipt["operation_id"] == (operation_id or fixture["operation"]["operation_id"])
    assert receipt["target"]["branch"] == fixture["operation"]["target_branch"]
    assert receipt["target"]["before"] == fixture["operation"]["target_before"]
    assert receipt["target"]["commit"] == fixture["operation"]["target_after"]
    assert receipt["worker"]["branch"] == fixture["operation"]["worker_branch"]
    assert receipt["worker"]["head"] == fixture["operation"]["worker_head"]
    assert receipt["task"] == fixture["task"]
    assert receipt["evidence"] == fixture["evidence"]
    assert receipt["heads"] == fixture["heads"]
    assert receipt["acceptance"]["revision"] == fixture["acceptance"]["revision"]
    assert receipt["acceptance"]["oracle_hash"] == fixture["acceptance"]["oracle_hash"]


def _raw(kind: str) -> dict:
    fixture = _fixture()
    raw = copy.deepcopy(fixture["raw_outcomes"][kind])
    raw.update({
        "target_branch": fixture["operation"]["target_branch"],
        "target_before": fixture["operation"]["target_before"],
        "target_after": (
            fixture["operation"]["target_after"]
            if raw["commit_point"] == "target_committed"
            else fixture["operation"]["target_before"]
        ),
        "worker_branch": fixture["operation"]["worker_branch"],
        "worker_head": fixture["operation"]["worker_head"],
        "conflicts": [],
        "commits_merged": 1 if raw["commit_point"] == "target_committed" else 0,
        "linked_tasks": (
            {"#315": {"ok": True, "added": 1}}
            if kind == "succeeded" else {}
        ),
    })
    return raw


def _op_id(index: int) -> str:
    return f"86000000-0000-4000-8000-{index:012d}"


def _admission() -> dict:
    fixture = _fixture()
    return {
        "target": {
            "branch": fixture["operation"]["target_branch"],
            "sha": fixture["operation"]["target_before"],
        },
        "oracle": {
            "source": "task",
            "task_id": "315",
            "revision": fixture["acceptance"]["revision"],
            "ref": fixture["operation"]["target_before"],
            "hash": fixture["acceptance"]["oracle_hash"],
            "command": "uv run python -m pytest docs/tasks/315/acceptance/test_t6_merge_receipt_cleanup_behavior.py -q",
            "required": True,
            "manifest": [{
                "path": "docs/tasks/315/acceptance/test_t6_merge_receipt_cleanup_behavior.py",
                "mode": "100644",
                "blob": "f" * 40,
            }],
        },
    }


def _session_row(worktree_path: Path) -> dict:
    op = _fixture()["operation"]
    return {
        "id": op["session_id"],
        "name": op["name"],
        "scope": op["scope"],
        "cwd": str(worktree_path),
        "model": "gpt-5.6-sol",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": str(worktree_path),
        "branch": op["worker_branch"],
        "base_branch": op["target_branch"],
        "is_orchestrator": False,
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "task_id": "315",
        "needs_switch": 0,
    }


def _finalization(operation_id: str) -> dict:
    fixture = _fixture()
    return {
        "stage": "PREPARED",
        "outcome": "continue",
        "operation_id": operation_id,
        "reservation_id": operation_id,
        "session_id": fixture["operation"]["session_id"],
        "scope": fixture["operation"]["scope"],
        "project_id": fixture["task"]["project_id"],
        "task": {
            "project_id": fixture["task"]["project_id"],
            "task_id": fixture["task"]["task_id"],
            "par_number": fixture["task"]["display_number"],
            "stable_id": fixture["task"]["stable_id"],
        },
        "next_task": None,
        "candidate_refs": [],
        "terminal_session": {"task_id": "315", "needs_switch": False},
        "target_branch": fixture["operation"]["target_branch"],
        "target_before": "",
        "target_after": "",
        "expected_tree": "",
        "worker_head": fixture["operation"]["worker_head"],
        "commits": {},
    }


def _asgi_transport(router):
    import httpx
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    async def call(method: str, path: str, payload: dict | None = None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t6.test") as client:
            response = await client.request(method, path, json=payload)
        return response.status_code, response.json()

    return call


async def _run_harness(
    api,
    tmp_path: Path,
    monkeypatch,
    *,
    operation_id: str,
    execute_override=None,
    late_worker_head: str = "",
    target_drift: bool = False,
    receipt_writer=None,
    task_override: dict | None = None,
    evidence_override: dict | None = None,
    heads_override: dict | None = None,
    replay_same: bool = False,
):
    import app.acceptance as acceptance
    import app.db as dbmod
    import app.merge_test_gate as merge_test_gate
    import app.rag_service as rag_service
    import app.tm as tm
    import app.workspace as workspace
    from app.manager import SessionManager
    from app.session import AgentSession

    operations = api.app_merge_operations
    sessions = api.app_routes_sessions
    worktree = tmp_path / "worker"
    worktree.mkdir(parents=True)
    db_path = tmp_path / "merge.sqlite3"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    dbmod.init_db()
    dbmod.save_session(_session_row(worktree))
    operations._runner_tasks.clear()

    local_manager = SessionManager()
    row = _session_row(worktree)
    live = AgentSession(
        id=row["id"],
        name=row["name"],
        scope=row["scope"],
        cwd=row["cwd"],
        model=row["model"],
        status=sessions.AgentStatus.IDLE,
        worktree_path=row["worktree_path"],
        branch=row["branch"],
        base_branch=row["base_branch"],
        task_id=row["task_id"],
    )
    live._persist = lambda: None
    local_manager.sessions[live.id] = live
    monkeypatch.setattr(sessions, "manager", local_manager)

    current_head = {"value": _fixture()["operation"]["worker_head"]}
    workspace_calls = []
    lifecycle_calls = []
    cleanup_calls = []
    ordering = []

    monkeypatch.setattr(
        workspace,
        "inspect_worktree_identity",
        lambda _path: (_fixture()["operation"]["worker_branch"], current_head["value"]),
    )
    monkeypatch.setattr(
        workspace,
        "classify_head_drift",
        lambda *_args, **_kwargs: {
            "class": "BENIGN_ADVANCE" if late_worker_head else "SAME",
            "actual_branch": _fixture()["operation"]["worker_branch"],
            "actual_head": late_worker_head or current_head["value"],
            "reason": "late advance" if late_worker_head else "",
        },
    )

    def merge_workspace(*args, **kwargs):
        workspace_calls.append(copy.deepcopy(kwargs))
        if target_drift:
            return {
                **_raw("failed"),
                "code": "TARGET_HEAD_CHANGED",
                "target_recheck": {
                    "expected": _fixture()["operation"]["target_before"],
                    "actual": "9" * 40,
                    "matched": False,
                },
            }
        if kwargs.get("resolve_refs"):
            kwargs["resolve_refs"](["315"])
        if kwargs.get("prepare"):
            kwargs["prepare"](_fixture()["operation"]["target_before"], "e" * 40)
        ordering.append("workspace")
        raw = _raw("succeeded")
        raw["merged_commits"] = {
            "#315": [{"hash": _fixture()["operation"]["target_after"], "subject": "#315: t6"}]
        }
        raw["target_recheck"] = {
            "expected": _fixture()["operation"]["target_before"],
            "actual": _fixture()["operation"]["target_before"],
            "matched": True,
        }
        return raw

    monkeypatch.setattr(workspace, "merge_worktree_to_main", merge_workspace)
    monkeypatch.setattr(
        workspace,
        "switch_worktree_branch",
        lambda *_args, **_kwargs: {
            "ok": True,
            "state": "switched",
            "branch": _fixture()["operation"]["worker_branch"],
        },
    )
    monkeypatch.setattr(workspace, "remove_worktree", lambda *_a, **_k: cleanup_calls.append("worktree"))

    async def persist_lifecycle(*_args, **_kwargs):
        receipt = api.app_ia_merge_receipts.get_merge_receipt(operation_id)
        _assert_receipt(receipt, operation_id=operation_id)
        lifecycle_calls.append("persist")
        ordering.append("lifecycle")

    async def remove_worker(*_args, **_kwargs):
        cleanup_calls.append("archive")

    monkeypatch.setattr(local_manager, "persist_lifecycle", persist_lifecycle)
    monkeypatch.setattr(local_manager, "remove", remove_worker)

    monkeypatch.setattr(
        tm,
        "resolve_scoped_task_identities",
        lambda *_args, **_kwargs: {
            "project_id": _fixture()["task"]["project_id"],
            "canonical_refs": ["#315"],
            "tasks": [{
                "project_id": _fixture()["task"]["project_id"],
                "id": _fixture()["task"]["task_id"],
                "par_number": _fixture()["task"]["display_number"],
                "stable_id": _fixture()["task"]["stable_id"],
            }],
        },
    )
    monkeypatch.setattr(tm, "prepare_merge_finalization", lambda **_kwargs: _finalization(operation_id))
    monkeypatch.setattr(tm, "release_merge_finalization", lambda *_a, **_k: None)

    def finalize_merge_outcome(_payload):
        receipt = api.app_ia_merge_receipts.get_merge_receipt(operation_id)
        _assert_receipt(receipt, operation_id=operation_id)
        ordering.append("receipt-before-task-finalization")
        return {
            "ok": True,
            "links": {
                "#315": {
                    "ok": True,
                    "added": 1,
                    "stable_id": _fixture()["task"]["stable_id"],
                    "canonical_head": _fixture()["heads"]["canonical_head"],
                    "projection_head": _fixture()["heads"]["projection_head"],
                    "evidence_refs": [_fixture()["evidence"]["manifest_uri"]],
                }
            },
        }

    monkeypatch.setattr(tm, "finalize_merge_outcome", finalize_merge_outcome)
    monkeypatch.setattr(acceptance, "evaluate_pinned_oracle", lambda *_a, **_k: {
        "status": "passed", "reason": "", "exit_code": 0, "output": "", "command": "oracle",
    })
    monkeypatch.setattr(merge_test_gate, "evaluate_test_gate", lambda *_a, **_k: {
        "status": "passed", "reason": "", "exit_code": 0, "output": "",
        "tests": ["t6"], "mapped_files": ["t6"], "target_ref": "main",
        "target_sha": _fixture()["operation"]["target_before"],
    })
    monkeypatch.setattr(merge_test_gate, "describe_progress", lambda _value: "")

    def schedule_backfill(_scope):
        ordering.append("rag")
        return "accepted"

    monkeypatch.setattr(rag_service, "schedule_backfill", schedule_backfill)
    monkeypatch.setattr(rag_service, "is_enabled", lambda: True)
    monkeypatch.setattr(operations, "ensure_operation_runner", lambda _operation_id: None)
    monkeypatch.setattr(operations, "_prepare_admission_snapshot", lambda *_a, **_k: _admission())

    if execute_override is not None:
        monkeypatch.setattr(sessions, "execute_merge_session", execute_override)

    task_value = copy.deepcopy(task_override or _fixture()["task"])
    evidence_value = copy.deepcopy(evidence_override or _fixture()["evidence"])
    heads_value = copy.deepcopy(heads_override or _fixture()["heads"])
    receipt_root = tmp_path / "receipts"
    sentinel = receipt_root / "evidence-sentinel.json"
    _write_json(sentinel, _fixture()["evidence"])
    sentinel_before = hashlib.sha256(sentinel.read_bytes()).hexdigest()
    transport = _asgi_transport(api.app_routes_merge_operations.router)
    payload = {
        "operation_id": operation_id,
        "name": _fixture()["operation"]["name"],
        "scope": _fixture()["operation"]["scope"],
        "target": _fixture()["operation"]["target_branch"],
        "task_outcome": _fixture()["operation"]["task_outcome"],
        "merge_schema_version": 2,
    }
    with api.app_ia_merge_receipts.merge_receipt_mode(
        canonical_root=receipt_root,
        task_resolver=lambda _payload: copy.deepcopy(task_value),
        evidence_resolver=lambda _task: copy.deepcopy(evidence_value),
        head_resolver=lambda: copy.deepcopy(heads_value),
        receipt_writer=receipt_writer,
    ):
        accepted_status, accepted_payload = await transport(
            "POST", "/api/merge-operations", payload,
        )
        assert accepted_status == 202
        assert accepted_payload["result"]["operation_state"] == "PENDING"
        await operations._run_operation(operation_id)
        status, result_payload = await transport(
            "GET", f"/api/merge-operations/{operation_id}", None,
        )
        assert status == 200
        receipt = api.app_ia_merge_receipts.get_merge_receipt(operation_id)
        replay_payload = None
        if replay_same:
            replay_status, replay_payload = await transport(
                "POST", "/api/merge-operations", payload,
            )
            assert replay_status == 200
    return {
        "result": result_payload["result"],
        "receipt": receipt,
        "receipt_root": receipt_root,
        "sentinel_before": sentinel_before,
        "sentinel_after": (
            hashlib.sha256(sentinel.read_bytes()).hexdigest()
            if sentinel.is_file() else None
        ),
        "workspace_calls": workspace_calls,
        "lifecycle_calls": lifecycle_calls,
        "cleanup_calls": cleanup_calls,
        "ordering": ordering,
        "transport": transport,
        "payload": payload,
        "replay": replay_payload,
    }


def test_t6_control_fixture_hash_denominators_t1_t5_and_298_are_frozen():
    contract = _contract()
    fixture = _fixture()
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == contract["fixture_sha256"]
    for mapping in (contract["compatibility_sha256"], contract["deferred_298_sha256"]):
        for relative, expected in mapping.items():
            assert hashlib.sha256(Path(relative).read_bytes()).hexdigest() == expected
    assert not Path("app/model_router.py").exists()
    assert fixture["expected_denominators"] == {
        "controls": 5,
        "behavior_nodes": 6,
        "compound_mutants": 7,
        "receipt_task_count": 1,
        "receipt_evidence_count": 1,
        "terminal_states": 4,
    }


@pytest.mark.asyncio
async def test_t6_control_current_operation_states_and_capability_are_distinct():
    import app.merge_operations as operations
    from app.routes.merge_operations import merge_operation_capabilities

    states = {
        name: operations.normalize_merge_result(
            _fixture()["operation"]["operation_id"],
            _raw(name),
            {"target": "main", "next_task_id": ""},
            rag_enabled=True,
        )["operation_state"]
        for name in ("succeeded", "partial", "unknown", "failed")
    }
    assert states == {
        "succeeded": "SUCCEEDED",
        "partial": "PARTIAL",
        "unknown": "UNKNOWN",
        "failed": "FAILED",
    }
    capability = await merge_operation_capabilities()
    assert capability["capability"] == "operation-v1"
    assert capability["merge_schema_version"] == 2


def test_t6_control_operation_harness_session_db_and_workspace_boundary_execute(
    tmp_path,
    monkeypatch,
):
    import app.db as dbmod
    import app.merge_operations as operations
    import app.workspace as workspace
    from app.manager import SessionManager
    from app.session import AgentSession

    worktree = tmp_path / "worker"
    worktree.mkdir()
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "merge-control.sqlite3")
    dbmod.init_db()
    dbmod.save_session(_session_row(worktree))
    operations._runner_tasks.clear()
    monkeypatch.setattr(
        workspace,
        "inspect_worktree_identity",
        lambda _path: (
            _fixture()["operation"]["worker_branch"],
            _fixture()["operation"]["worker_head"],
        ),
    )
    snapshot = operations._session_snapshot(_fixture()["operation"]["session_id"])
    assert snapshot["worker_head"] == _fixture()["operation"]["worker_head"]
    manager = SessionManager()
    session = AgentSession(
        id=snapshot["session_id"],
        name=snapshot["name"],
        scope=snapshot["scope"],
        cwd=str(worktree),
        worktree_path=str(worktree),
        branch=snapshot["worker_branch"],
        base_branch=snapshot["base_branch"],
        task_id=snapshot["task_id"],
    )
    manager.sessions[session.id] = session
    assert manager.get(session.id) is session
    request = operations.normalize_request(
        name=snapshot["name"],
        scope=snapshot["scope"],
        target=snapshot["base_branch"],
        task_outcome="continue",
        merge_schema_version=2,
    )
    snapshot["admission"] = _admission()
    operation_id = _op_id(99)
    result, created, status = operations.accept_operation_snapshot(
        operation_id=operation_id,
        request=request,
        accepted=snapshot,
    )
    assert created is True and status == 202
    assert result["operation_state"] == "PENDING"
    assert operations.claim_operation(operation_id, "t6-control-owner") is True
    assert operations.get_operation_record(operation_id)["state"] == "RUNNING"


@pytest.mark.asyncio
async def test_t6_control_309_surfaces_and_426_recovery_remain_exact(monkeypatch):
    root = Path.cwd()
    for index, relative in enumerate((
        "docs/tasks/309/acceptance/test_t1_progress_ui_removed.py",
        "docs/tasks/309/acceptance/test_t2_legacy_merge_handler_removed.py",
        "docs/tasks/309/acceptance/test_t3_single_model_refresh_route.py",
        "docs/tasks/309/acceptance/test_t4_proxy_tunnel_owner_removed.py",
        "docs/tasks/309/acceptance/test_t7_route_snapshot_removed_surfaces.py",
    )):
        _load_module(root / relative, f"t6_surface_{index}").main()

    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.delenv("DASHBOARD_USER", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    with TestClient(app, raise_server_exceptions=False) as client:
        legacy = client.post(
            "/api/sessions/t6-worker/merge",
            json={"scope": _fixture()["operation"]["scope"]},
        )
        capability = client.get("/api/merge-operations/capabilities")
    assert legacy.status_code == 426
    assert legacy.json()["error"]["code"] == "MERGE_OPERATION_REQUIRED"
    assert capability.status_code == 200
    assert capability.json()["capability"] == "operation-v1"
    session_source = Path("app/session.py").read_text(encoding="utf-8")
    assert "progress_pct" in session_source and "progress_status" in session_source


def test_t6_control_receipt_shape_valid_alternate_and_forgery_detector_are_material():
    fixture = _fixture()
    receipt = {
        "schema_version": 1,
        "receipt_id": fixture["receipt"]["receipt_id"],
        "receipt_status": "verified",
        "operation_id": fixture["operation"]["operation_id"],
        "target": {
            "branch": fixture["operation"]["target_branch"],
            "before": fixture["operation"]["target_before"],
            "commit": fixture["operation"]["target_after"],
        },
        "worker": {
            "branch": fixture["operation"]["worker_branch"],
            "head": fixture["operation"]["worker_head"],
        },
        "task": fixture["task"],
        "evidence": fixture["evidence"],
        "heads": fixture["heads"],
        "acceptance": {
            "revision": fixture["acceptance"]["revision"],
            "oracle_hash": fixture["acceptance"]["oracle_hash"],
            "manifest_count": fixture["acceptance"]["manifest_count"],
        },
        "created_at": "2026-08-25T04:00:00Z",
        "metadata": fixture["valid_alternate"]["metadata"],
    }
    receipt = {key: receipt[key] for key in fixture["valid_alternate"]["field_order"]} | {
        "worker": receipt["worker"],
        "created_at": receipt["created_at"],
        "metadata": receipt["metadata"],
    }
    _assert_receipt(receipt)
    forged = copy.deepcopy(receipt)
    forged["task"]["stable_id"] = fixture["compound_mutants"]["forged_task_evidence_head"][
        "stable_id"
    ]
    with pytest.raises(AssertionError):
        _assert_receipt(forged)


@pytest.mark.asyncio
async def test_t6_success_receipt_precedes_finalization_and_retry_is_idempotent(
    tmp_path,
    monkeypatch,
):
    api = _load_t6_api()
    result = await _run_harness(
        api,
        tmp_path,
        monkeypatch,
        operation_id=_fixture()["operation"]["operation_id"],
        replay_same=True,
    )
    assert result["result"]["operation_state"] == "SUCCEEDED"
    _assert_receipt(result["receipt"])
    assert result["result"][_contract()["operation_result_receipt_field"]][
        "receipt_id"
    ] == result["receipt"]["receipt_id"]
    assert result["ordering"] == [
        "workspace",
        "receipt-before-task-finalization",
        "lifecycle",
        "rag",
    ]
    assert result["cleanup_calls"] == []
    assert result["sentinel_after"] == result["sentinel_before"]
    assert result["lifecycle_calls"] == ["persist"]
    assert result["workspace_calls"][0]["expected_worker_head"] == _fixture()["operation"][
        "worker_head"
    ]
    receipt_files = list(result["receipt_root"].rglob("merge-receipts/*.json"))
    assert len(receipt_files) == 1
    before = receipt_files[0].read_bytes()
    assert result["replay"]["result"]["operation_state"] == "SUCCEEDED"
    assert receipt_files[0].read_bytes() == before
    assert len(list(result["receipt_root"].rglob("merge-receipts/*.json"))) == 1


@pytest.mark.asyncio
async def test_t6_partial_unknown_failed_remain_distinct_through_operation_route(
    tmp_path,
    monkeypatch,
):
    api = _load_t6_api()
    observed = {}
    for index, kind in enumerate(("partial", "unknown", "failed"), start=2):
        raw = _raw(kind)

        async def execute(**_kwargs):
            return copy.deepcopy(raw)

        run = await _run_harness(
            api,
            tmp_path / kind,
            monkeypatch,
            operation_id=_op_id(index),
            execute_override=execute,
        )
        observed[kind] = run["result"]["operation_state"]
        assert run["cleanup_calls"] == []
    assert observed == {"partial": "PARTIAL", "unknown": "UNKNOWN", "failed": "FAILED"}


@pytest.mark.asyncio
async def test_t6_receipt_write_failure_blocks_success_task_finalization_and_cleanup(
    tmp_path,
    monkeypatch,
):
    api = _load_t6_api()

    def fail_receipt(*_args, **_kwargs):
        raise OSError(_fixture()["compound_mutants"]["success_before_receipt"]["marker"])

    run = await _run_harness(
        api,
        tmp_path,
        monkeypatch,
        operation_id=_op_id(5),
        receipt_writer=fail_receipt,
    )
    assert run["result"]["operation_state"] in {"PARTIAL", "UNKNOWN", "FAILED"}
    assert run["result"]["operation_state"] != "SUCCEEDED"
    assert "receipt-before-task-finalization" not in run["ordering"]
    assert run["lifecycle_calls"] == []
    assert run["cleanup_calls"] == []
    assert run["sentinel_after"] == run["sentinel_before"]


@pytest.mark.asyncio
async def test_t6_forged_task_evidence_or_head_never_authorizes_success(tmp_path, monkeypatch):
    api = _load_t6_api()
    mutant = _fixture()["compound_mutants"]["forged_task_evidence_head"]
    variants = [
        ({**_fixture()["task"], "stable_id": mutant["stable_id"]}, None, None),
        (None, {**_fixture()["evidence"], "manifest_head": mutant["evidence_head"]}, None),
        (None, None, {**_fixture()["heads"], "projection_head": mutant["projection_head"]}),
    ]
    for index, (task, evidence, heads) in enumerate(variants, start=6):
        run = await _run_harness(
            api,
            tmp_path / str(index),
            monkeypatch,
            operation_id=_op_id(index),
            task_override=task,
            evidence_override=evidence,
            heads_override=heads,
        )
        assert run["result"]["operation_state"] != "SUCCEEDED"
        assert run["lifecycle_calls"] == []
        assert run["cleanup_calls"] == []


@pytest.mark.asyncio
async def test_t6_late_worker_head_and_target_drift_cannot_enter_receipt(tmp_path, monkeypatch):
    api = _load_t6_api()
    late = _fixture()["compound_mutants"]["late_worker_head_injection"]["head"]
    late_run = await _run_harness(
        api,
        tmp_path / "late",
        monkeypatch,
        operation_id=_op_id(9),
        late_worker_head=late,
    )
    assert late_run["workspace_calls"][0]["expected_worker_head"] == _fixture()["operation"][
        "worker_head"
    ]
    assert late not in json.dumps(late_run["receipt"])

    drift_run = await _run_harness(
        api,
        tmp_path / "drift",
        monkeypatch,
        operation_id=_op_id(10),
        target_drift=True,
    )
    assert drift_run["result"]["operation_state"] == "FAILED"
    assert drift_run["receipt"] is None
    assert drift_run["cleanup_calls"] == []


@pytest.mark.asyncio
async def test_t6_rag_or_partial_fallback_cannot_manufacture_success_or_receipt(
    tmp_path,
    monkeypatch,
):
    api = _load_t6_api()
    for index, kind in enumerate(("partial", "succeeded"), start=11):
        raw = _raw(kind)
        raw["rag_backfill_status"] = "accepted"

        async def execute(**_kwargs):
            return copy.deepcopy(raw)

        run = await _run_harness(
            api,
            tmp_path / kind,
            monkeypatch,
            operation_id=_op_id(index),
            execute_override=execute,
        )
        assert run["result"]["operation_state"] != "SUCCEEDED"
        assert run["receipt"] is None
        assert run["cleanup_calls"] == []
