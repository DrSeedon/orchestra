"""Frozen behavior-level RED oracle for #315 T5 recovery and privacy.

The archive path is exercised through SessionManager -> AgentSession. Pack and replay use
their public seams against scratch roots only; no live database, service, or provider is used.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib
import importlib.util
import json
import shutil
import sqlite3
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest


HERE = Path(__file__).resolve().parent
FIXTURE_PATH = HERE / "fixtures" / "t5_recovery_records.json"
CONTRACT_PATH = HERE / "fixtures" / "t5_recovery_contract.json"
T3_ORACLE_PATH = HERE / "test_t3_promotion_behavior.py"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture() -> dict:
    return _json(FIXTURE_PATH)


def _contract() -> dict:
    return _json(CONTRACT_PATH)


def _t3_oracle_module():
    spec = importlib.util.spec_from_file_location("t3_oracle_for_t5", T3_ORACLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_t5_api() -> SimpleNamespace:
    modules = {}
    for module_name, surface in _contract()["public_api"].items():
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            pytest.fail(f"#315 T5 missing behavior: cannot import {module_name}: {exc}")
        for name in surface.get("callables", []):
            assert callable(getattr(module, name, None)), (
                f"#315 T5 missing behavior: {module_name}.{name} is not callable"
            )
        for name in surface.get("classes", []):
            cls = getattr(module, name, None)
            assert isinstance(cls, type), (
                f"#315 T5 missing behavior: {module_name}.{name} is not a class"
            )
            for method in surface.get("methods", []):
                assert callable(getattr(cls, method, None)), (
                    f"#315 T5 missing behavior: {name}.{method} is not callable"
                )
        for name in surface.get("exceptions", []):
            error = getattr(module, name, None)
            assert isinstance(error, type) and issubclass(error, Exception), (
                f"#315 T5 missing behavior: {module_name}.{name} is not an exception"
            )
        modules[module_name.replace(".", "_")] = module
    return SimpleNamespace(**modules)


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


def _materialize_source(tmp_path: Path, *, changed: bool = False) -> Path:
    root = tmp_path / ("canonical-b" if changed else "canonical-a")
    for item in _fixture()["canonical_objects"]:
        record = copy.deepcopy(item["record"])
        if changed and record["record_type"] == "task.state":
            record["title"] = "T5 rollback source B"
            record["updated_at"] = "2026-08-25T03:00:00Z"
            record["canonical_head"] = "git:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        _write_json(root / item["path"], record)
    return root


def _tree_snapshot(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _snapshot_head(snapshot: Mapping[str, str]) -> str:
    return f"sha256:{hashlib.sha256(_canonical_bytes(dict(snapshot))).hexdigest()}"


def _reference_pack(source_root: Path, pack_root: Path, *, alternate: bool = False) -> dict:
    snapshot = _tree_snapshot(source_root)
    paths = sorted(snapshot)
    if alternate:
        order = _fixture()["pack"]["alternate_order"]
        paths = [paths[index] for index in order]
    objects = []
    for relative in paths:
        source = source_root / relative
        target = pack_root / "objects" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        objects.append({
            "path": relative,
            "sha256": f"sha256:{snapshot[relative]}",
            "size": source.stat().st_size,
        })
    manifest = {
        "format": _fixture()["pack"]["format"],
        "schema_version": _fixture()["pack"]["schema_version"],
        "scope": _fixture()["pack"]["scope"],
        "created_at": _fixture()["pack"]["created_at"],
        "atomicity_claim": False,
        "canonical_head": _snapshot_head(snapshot),
        "objects": objects,
        "metadata": copy.deepcopy(_fixture()["pack"]["metadata"]),
    }
    _write_json(pack_root / "manifest.json", manifest)
    return manifest


def _reference_restore(pack_root: Path, target_root: Path) -> dict:
    manifest = _json(pack_root / "manifest.json")
    staged = {}
    for item in manifest["objects"]:
        source = pack_root / "objects" / item["path"]
        digest = f"sha256:{hashlib.sha256(source.read_bytes()).hexdigest()}"
        assert digest == item["sha256"]
        staged[item["path"]] = source.read_bytes()
    for relative, content in staged.items():
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return {
        "canonical_head": _snapshot_head(_tree_snapshot(target_root)),
        "object_count": len(staged),
    }


def _session_manager_fixture(api):
    cfg = _fixture()["session"]
    session = api.app_session.AgentSession(
        id=cfg["id"],
        name=cfg["name"],
        scope=cfg["scope"],
        cwd=cfg["cwd"],
        session_id=cfg["native_session_id"],
        system_prompt=cfg["safe_prompt"],
        backend_type="codex",
    )
    session._turn_logs = copy.deepcopy(_fixture()["messages"])
    local_logs = []
    session._log = lambda kind, content: local_logs.append({"type": kind, "content": content})
    session._persist = lambda: None

    async def drain_persist():
        return None

    session._drain_persist = drain_persist
    manager = api.app_manager.SessionManager()
    manager.sessions[session.id] = session
    return manager, session, local_logs


def _archive_dir(canonical_root: Path, receipt: Mapping) -> Path:
    return canonical_root / receipt["archive_path"]


def _secret_bytes() -> list[bytes]:
    return [value.encode("utf-8") for value in _fixture()["secret_sentinels"]]


def _assert_no_secrets_in_values(*values) -> None:
    rendered = _canonical_bytes(list(values))
    assert all(secret not in rendered for secret in _secret_bytes())


def _assert_no_secrets_in_roots(*roots: Path) -> None:
    files = [path for root in roots if root.exists() for path in root.rglob("*") if path.is_file()]
    assert files
    for path in files:
        content = path.read_bytes()
        assert all(secret not in content for secret in _secret_bytes()), path


def _assert_json_only(root: Path) -> None:
    files = [path for path in root.rglob("*") if path.is_file()]
    assert files
    forbidden = set(_contract()["forbidden_generated_extensions"])
    assert not [path for path in files if path.suffix.lower() in forbidden]


def _build_pack(api, source: Path, pack: Path, *, alternate: bool = False):
    paths = sorted(_tree_snapshot(source))
    order = None
    if alternate:
        order = [paths[index] for index in _fixture()["pack"]["alternate_order"]]
    return api.scripts_ia_pack.build_pack(
        source_root=source,
        pack_root=pack,
        scope=_fixture()["project_id"],
        metadata=copy.deepcopy(_fixture()["pack"]["metadata"]),
        object_order=order,
    )


def _restore_pack(api, pack: Path, target: Path, *, mode: str = "fail"):
    return api.scripts_ia_pack.restore_pack(
        pack_root=pack,
        target_root=target,
        expected_scope=_fixture()["project_id"],
        mode=mode,
    )


def test_t5_control_fixture_hash_denominators_and_t1_t4_compatibility_are_frozen():
    contract = _contract()
    fixture = _fixture()
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == contract["fixture_sha256"]
    for relative, expected in contract["compatibility_sha256"].items():
        assert hashlib.sha256(Path(relative).read_bytes()).hexdigest() == expected
    assert fixture["expected_denominators"] == {
        "messages": 3,
        "canonical_objects": 5,
        "secret_sentinels": 3,
        "controls": 4,
        "behavior_nodes": 7,
        "compound_mutants": 7,
    }
    assert len(fixture["compound_mutants"]) == 7


def test_t5_control_real_session_manager_and_nonempty_messages_are_reachable():
    from app import manager, session

    api = SimpleNamespace(app_manager=manager, app_session=session)
    owner, worker, local_logs = _session_manager_fixture(api)
    assert owner.get(worker.id) is worker
    assert len(worker._turn_logs) == 3
    assert worker.system_prompt == _fixture()["session"]["safe_prompt"]
    assert local_logs == []


def test_t5_control_canonical_state_privacy_and_projection_shapes_are_valid():
    from app.ia.schema import projection_payload, validate_record

    records = [item["record"] for item in _fixture()["canonical_objects"]]
    validated = [validate_record(record) for record in records]
    assert len(validated) == 5
    assert Counter(record["status"] for record in validated) == Counter({
        "tombstoned": 1,
        "current": 1,
        "historical": 2,
        "disputed": 1,
    })
    assert sum(record["tombstone"] for record in validated) == 1
    for record in validated:
        for sink in ("hot", "fts", "vector"):
            _assert_no_secrets_in_values(projection_payload(record, sink))


def test_t5_control_reference_pack_restore_is_nonempty_order_independent_and_atomic(tmp_path):
    source = _materialize_source(tmp_path)
    pack_a = tmp_path / "pack-a"
    pack_b = tmp_path / "pack-b"
    manifest_a = _reference_pack(source, pack_a)
    manifest_b = _reference_pack(source, pack_b, alternate=True)
    target_a = tmp_path / "target-a"
    target_b = tmp_path / "target-b"
    restored_a = _reference_restore(pack_a, target_a)
    restored_b = _reference_restore(pack_b, target_b)
    assert manifest_a["canonical_head"] == manifest_b["canonical_head"]
    assert restored_a == restored_b == {
        "canonical_head": manifest_a["canonical_head"],
        "object_count": 5,
    }
    assert _tree_snapshot(target_a) == _tree_snapshot(target_b) == _tree_snapshot(source)
    assert manifest_b["metadata"]["future_safe_field"] == {"revision": 2}
    assert manifest_b["atomicity_claim"] is False


@pytest.mark.asyncio
async def test_t5_manager_commits_archive_before_extraction_and_retry_is_idempotent(
    tmp_path,
    monkeypatch,
):
    api = _load_t5_api()
    manager, session, local_logs = _session_manager_fixture(api)
    canonical_root = tmp_path / "canonical"
    extraction_calls = []
    extraction_started = asyncio.Event()
    release_extraction = asyncio.Event()

    async def failing_extractor(archive):
        extraction_calls.append(archive["archive_id"])
        archive_dir = canonical_root / archive["archive_path"]
        assert (archive_dir / "record.json").is_file()
        assert (archive_dir / "messages.json").is_file()
        extraction_started.set()
        await release_extraction.wait()
        raise RuntimeError(_fixture()["compound_mutants"]["extraction_failure_deletes_archive"][
            "message"
        ])

    chain_calls = []
    original = api.app_session.AgentSession.commit_archive

    async def tracked(self, *args, **kwargs):
        chain_calls.append("session")
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(api.app_session.AgentSession, "commit_archive", tracked)
    with api.app_ia_recovery.recovery_mode(
        canonical_root=canonical_root,
        extraction_runner=failing_extractor,
        knowledge_service=None,
    ):
        receipt = await asyncio.wait_for(
            manager.commit_session_archive(
                session.id,
                project_id=_fixture()["project_id"],
                archive_id=_fixture()["session"]["archive_id"],
                idempotency_key=_fixture()["session"]["idempotency_key"],
                retention=_fixture()["session"]["retention"],
            ),
            timeout=1,
        )
        await asyncio.wait_for(extraction_started.wait(), timeout=1)
        assert set(_contract()["archive_receipt_required"]) <= set(receipt)
        archive_dir = _archive_dir(canonical_root, receipt)
        before_failure = _tree_snapshot(archive_dir)
        assert before_failure
        release_extraction.set()
        status = await api.app_ia_recovery.wait_extraction(receipt["archive_id"])
        assert status["status"] == "failed"
        assert _fixture()["compound_mutants"]["extraction_failure_deletes_archive"][
            "message"
        ] in status["error"]
        assert _tree_snapshot(archive_dir) == before_failure
        retry = await manager.commit_session_archive(
            session.id,
            project_id=_fixture()["project_id"],
            archive_id=_fixture()["session"]["archive_id"],
            idempotency_key=_fixture()["session"]["idempotency_key"],
            retention=_fixture()["session"]["retention"],
        )
    assert chain_calls == ["session", "session"]
    assert receipt["outcome"] == "created"
    assert receipt["archive_id"] == _fixture()["session"]["archive_id"]
    assert retry["outcome"] == "noop"
    assert retry["archive_id"] == receipt["archive_id"]
    assert len(list(archive_dir.parent.glob("*/record.json"))) == 1
    assert len(list(archive_dir.glob("events/*.json"))) == 1
    assert extraction_calls
    _assert_no_secrets_in_roots(archive_dir)
    _assert_no_secrets_in_values(receipt, retry, status, local_logs)


def test_t5_restore_requires_explicit_evidence_linked_idempotent_promotion(tmp_path):
    api = _load_t5_api()
    source = _materialize_source(tmp_path)
    pack = tmp_path / "pack"
    target = tmp_path / "restored"
    manifest = _build_pack(api, source, pack)
    restored = _restore_pack(api, pack, target)
    assert restored["canonical_head"] == manifest["canonical_head"]

    t3 = _t3_oracle_module()
    t3_api = t3._load_api()
    promotion_root = tmp_path / "promotion"
    promotion_root.mkdir(parents=True, exist_ok=False)
    context = t3._materialization_context(promotion_root)
    with t3._knowledge_mode(t3_api, promotion_root, context):
        assert t3._query(t3_api, topic="repo-ops")["count"] == 0
        request = t3._request("current", context)
        request["fact"]["metadata"]["restored_pack_head"] = restored["canonical_head"]
        created = t3._promote(t3_api, request)
        replay = t3._promote(t3_api, copy.deepcopy(request))
        assert created["outcome"] == "created"
        assert replay["outcome"] == "noop"
        fact = t3._query(t3_api, topic="repo-ops")["facts"][0]
        assert fact["provenance"]
        before = t3_api.knowledge.knowledge_head()
        with pytest.raises(t3_api.evidence.EvidenceResolutionError):
            t3._promote(t3_api, t3._request("source_less", context))
        assert t3_api.knowledge.knowledge_head() == before
    assert _fixture()["compound_mutants"]["source_less_promotion_after_restore"][
        "marker"
    ] not in json.dumps(fact)


def test_t5_pack_rejects_schema_scope_path_checksum_and_privacy_before_any_write(tmp_path):
    api = _load_t5_api()
    source = _materialize_source(tmp_path)
    clean_pack = tmp_path / "clean-pack"
    _build_pack(api, source, clean_pack)
    object_path = _fixture()["compound_mutants"]["partial_write_before_checksum_failure"][
        "corrupt_path"
    ]
    variants = []

    checksum_pack = tmp_path / "bad-checksum"
    shutil.copytree(clean_pack, checksum_pack)
    (checksum_pack / "objects" / object_path).write_bytes(b"corrupt")
    variants.append((checksum_pack, "checksum"))

    for name, field, value in (
        ("bad-schema", "schema_version", 99),
        ("bad-scope", "scope", "another-project"),
    ):
        variant = tmp_path / name
        shutil.copytree(clean_pack, variant)
        manifest = _json(variant / "manifest.json")
        manifest[field] = value
        _write_json(variant / "manifest.json", manifest)
        variants.append((variant, "schema" if field == "schema_version" else "scope"))

    bad_path = tmp_path / "bad-path"
    shutil.copytree(clean_pack, bad_path)
    manifest = _json(bad_path / "manifest.json")
    manifest["objects"][0]["path"] = "../outside.json"
    _write_json(bad_path / "manifest.json", manifest)
    variants.append((bad_path, "path"))

    private_pack = tmp_path / "bad-privacy"
    shutil.copytree(clean_pack, private_pack)
    manifest = _json(private_pack / "manifest.json")
    relative = manifest["objects"][0]["path"]
    secret_object = _json(private_pack / "objects" / relative)
    secret_object["metadata"] = {"nested": {"token": _fixture()["secret_sentinels"][0]}}
    _write_json(private_pack / "objects" / relative, secret_object)
    payload = (private_pack / "objects" / relative).read_bytes()
    manifest["objects"][0]["sha256"] = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    manifest["objects"][0]["size"] = len(payload)
    manifest["canonical_head"] = _snapshot_head({
        item["path"]: item["sha256"].removeprefix("sha256:")
        for item in manifest["objects"]
    })
    _write_json(private_pack / "manifest.json", manifest)
    variants.append((private_pack, "privacy"))

    for index, (variant, reason) in enumerate(variants):
        target = tmp_path / f"target-{index}"
        _write_json(target / "keep.json", {"keep": index})
        before = _tree_snapshot(target)
        with pytest.raises(api.scripts_ia_pack.PackValidationError, match=reason):
            _restore_pack(api, variant, target, mode="replace")
        assert _tree_snapshot(target) == before


def test_t5_valid_alternate_pack_restore_and_replay_reproduce_exact_heads(tmp_path):
    api = _load_t5_api()
    source = _materialize_source(tmp_path)
    pack = tmp_path / "pack-alternate"
    target = tmp_path / "target"
    manifest = _build_pack(api, source, pack, alternate=True)
    validated = api.scripts_ia_pack.validate_pack(
        pack_root=pack,
        expected_scope=_fixture()["project_id"],
    )
    restored = _restore_pack(api, pack, target)
    projection = tmp_path / "projection.sqlite3"
    replay = api.scripts_ia_replay.replay(
        canonical_root=target,
        projection_path=projection,
        vector_query=None,
    )
    assert validated["format"] == "ovpack"
    assert validated["atomicity_claim"] is False
    assert validated["metadata"]["future_safe_field"] == {"revision": 2}
    assert manifest["canonical_head"] == restored["canonical_head"] == replay[
        "canonical_head"
    ] == replay["projection_head"]
    assert replay["object_count"] == 5
    assert _tree_snapshot(target) == _tree_snapshot(source)
    assert projection.is_file()
    _assert_json_only(target)


def test_t5_replay_preserves_tombstone_retention_disputed_and_superseded(tmp_path):
    api = _load_t5_api()
    source = _materialize_source(tmp_path)
    pack = tmp_path / "pack"
    target = tmp_path / "target"
    _build_pack(api, source, pack)
    restored = _restore_pack(api, pack, target)
    projection = tmp_path / "projection.sqlite3"
    first = api.scripts_ia_replay.replay(
        canonical_root=target,
        projection_path=projection,
        vector_query=None,
    )
    second = api.scripts_ia_replay.replay(
        canonical_root=target,
        projection_path=projection,
        vector_query=None,
    )
    assert set(_contract()["replay_receipt_required"]) <= set(first)
    assert first == second
    assert first["canonical_head"] == restored["canonical_head"]
    assert first["projection_head"] == first["canonical_head"]
    assert first["tombstone_count"] == 1
    assert first["status_counts"] == {
        "current": 1,
        "disputed": 1,
        "historical": 2,
        "tombstoned": 1,
    }
    assert first["retention_counts"] == {
        "90d-cold": 1,
        "audit-only": 1,
        "project-default": 3,
    }
    records = [_json(path) for path in target.rglob("*.json")]
    assert any(record.get("tombstone") is True for record in records)
    assert {record.get("status") for record in records} >= {"historical", "disputed"}
    historical = next(
        record
        for record in records
        if record.get("record_type") == "knowledge.fact"
        and record.get("status") == "historical"
    )
    disputed = next(
        record
        for record in records
        if record.get("record_type") == "knowledge.fact"
        and record.get("status") == "disputed"
    )
    assert historical["metadata"]["superseded_by"] == disputed["stable_id"]
    assert disputed["supersedes"] == [historical["stable_id"]]
    assert disputed["disputed_by"]


@pytest.mark.asyncio
async def test_t5_secrets_never_reach_canonical_pack_agent_prompt_projection_or_logs(
    tmp_path,
):
    api = _load_t5_api()
    source = _materialize_source(tmp_path)
    manager, session, local_logs = _session_manager_fixture(api)
    extraction_payloads = []

    async def extractor(archive):
        payload = {
            "archive_id": archive["archive_id"],
            "candidate": "explicit-promotion-required",
        }
        extraction_payloads.append(payload)
        return payload

    with api.app_ia_recovery.recovery_mode(
        canonical_root=source,
        extraction_runner=extractor,
        knowledge_service=None,
    ):
        receipt = await manager.commit_session_archive(
            session.id,
            project_id=_fixture()["project_id"],
            archive_id=_fixture()["session"]["archive_id"],
            idempotency_key=_fixture()["session"]["idempotency_key"],
            retention=_fixture()["session"]["retention"],
        )
        status = await api.app_ia_recovery.wait_extraction(receipt["archive_id"])
    assert status["status"] == "completed"
    pack = tmp_path / "pack"
    target = tmp_path / "target"
    _build_pack(api, source, pack)
    restored = _restore_pack(api, pack, target)
    vector_calls = []

    def vector_query(request):
        vector_calls.append(copy.deepcopy(dict(request)))
        return {"indexed_head": None, "hits": []}

    projection = tmp_path / "projection.sqlite3"
    replay = api.scripts_ia_replay.replay(
        canonical_root=target,
        projection_path=projection,
        vector_query=vector_query,
    )
    _assert_no_secrets_in_roots(source, pack, target)
    _assert_no_secrets_in_values(
        receipt,
        status,
        restored,
        replay,
        extraction_payloads,
        session.system_prompt,
        local_logs,
        vector_calls,
    )
    projection_bytes = projection.read_bytes()
    assert all(secret not in projection_bytes for secret in _secret_bytes())
    assert _fixture()["redaction_marker"] in json.dumps(_json(
        _archive_dir(source, receipt) / "messages.json"
    ))
    assert not list(source.rglob("*.md"))


def test_t5_rollback_rejects_wrong_head_then_restores_exact_pack_head(tmp_path):
    api = _load_t5_api()
    source_a = _materialize_source(tmp_path)
    source_b = _materialize_source(tmp_path, changed=True)
    pack_a = tmp_path / "pack-a"
    pack_b = tmp_path / "pack-b"
    manifest_a = _build_pack(api, source_a, pack_a)
    manifest_b = _build_pack(api, source_b, pack_b)
    assert manifest_a["canonical_head"] != manifest_b["canonical_head"]
    target = tmp_path / "target"
    _restore_pack(api, pack_b, target)
    projection = tmp_path / "projection.sqlite3"
    current = api.scripts_ia_replay.replay(
        canonical_root=target,
        projection_path=projection,
        vector_query=None,
    )
    before_wrong = _tree_snapshot(target)
    wrong = _fixture()["compound_mutants"]["rollback_wrong_head"]["head"]
    with pytest.raises(api.scripts_ia_pack.PackValidationError):
        api.scripts_ia_replay.rollback(
            pack_root=pack_a,
            target_root=target,
            projection_path=projection,
            expected_scope=_fixture()["project_id"],
            expected_current_head=wrong,
        )
    assert _tree_snapshot(target) == before_wrong
    rolled = api.scripts_ia_replay.rollback(
        pack_root=pack_a,
        target_root=target,
        projection_path=projection,
        expected_scope=_fixture()["project_id"],
        expected_current_head=current["canonical_head"],
    )
    assert rolled["rollback_from_head"] == manifest_b["canonical_head"]
    assert rolled["canonical_head"] == rolled["projection_head"] == manifest_a[
        "canonical_head"
    ]
    assert _tree_snapshot(target) == _tree_snapshot(source_a)
