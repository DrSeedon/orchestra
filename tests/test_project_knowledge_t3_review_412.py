"""Regression oracles for the T3 Luna review findings (#412)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from app.ia import project_knowledge
from app.ia.project_knowledge import KnowledgeOwnerError, ProjectKnowledgeRouter
from scripts import activate_project_knowledge as activation


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo(root: Path) -> None:
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "seed")


def _ledger(tmp_path: Path, project_ids: tuple[str, ...] = ("a", "b")):
    projects = []
    registry_entries = []
    roots = {}
    for index, project_id in enumerate(project_ids, start=1):
        root = tmp_path / project_id
        _repo(root)
        stable_id = f"00000000-0000-4000-8000-{index:012d}"
        record = {
            "schema_version": 1,
            "record_type": "resource",
            "project_id": project_id,
            "stable_id": stable_id,
            "status": "current",
        }
        payload = json.dumps(record, sort_keys=True).encode()
        relative = f"docs/kb/records/evidence/{stable_id}.json"
        path = root / relative
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)
        digest = hashlib.sha256()
        digest.update(stable_id.encode() + b"\0" + payload + b"\0")
        records_sha256 = "sha256:" + digest.hexdigest()
        local_manifest = {
            "schema_version": 1,
            "project_id": project_id,
            "record_count": 1,
            "records_sha256": records_sha256,
            "records": [
                {
                    "stable_id": stable_id,
                    "destination_relative_path": relative,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            ],
        }
        (root / "docs/kb/manifest.json").write_text(
            json.dumps(local_manifest), encoding="utf-8"
        )
        projects.append(
            {
                "project_id": project_id,
                "repository_root": str(root),
                "record_count": 1,
                "records_sha256": records_sha256,
            }
        )
        registry_entries.append(
            {"canonical_project_id": project_id, "repository_root": str(root)}
        )
        roots[project_id] = root
    distribution = tmp_path / "distribution.json"
    distribution.write_text(
        json.dumps(
            {
                "status": "verified",
                "quarantine_count": 0,
                "total_record_count": len(projects),
                "projects": projects,
            }
        ),
        encoding="utf-8",
    )
    registry = tmp_path / "scope-registry.json"
    registry.write_text(
        json.dumps({"schema_version": 1, "entries": registry_entries}),
        encoding="utf-8",
    )
    return distribution, registry, roots


def test_t3_activation_rejects_incomplete_authoritative_project_map(tmp_path: Path):
    distribution, registry, _roots = _ledger(tmp_path)
    value = json.loads(distribution.read_text())
    value["projects"] = value["projects"][:1]
    value["total_record_count"] = 1
    distribution.write_text(json.dumps(value), encoding="utf-8")
    state = tmp_path / "owner.json"

    with pytest.raises(KnowledgeOwnerError, match="project map"):
        activation.activate(
            distribution_manifest=distribution,
            scope_registry_path=registry,
            engine_state_path=state,
        )
    assert not state.exists()


def test_t3_receipt_conflict_cannot_activate_owner(tmp_path: Path):
    distribution, registry, _roots = _ledger(tmp_path)
    state = tmp_path / "owner.json"
    receipt = tmp_path / "receipt.json"
    receipt.write_text("occupied\n", encoding="utf-8")

    with pytest.raises(KnowledgeOwnerError, match="receipt"):
        activation.activate(
            distribution_manifest=distribution,
            scope_registry_path=registry,
            engine_state_path=state,
            receipt_path=receipt,
        )
    assert not state.exists() or json.loads(state.read_text())["active_owner"] == "central"
    assert receipt.read_text(encoding="utf-8") == "occupied\n"


def test_t3_activation_rejects_record_filename_payload_identity_mismatch(tmp_path: Path):
    distribution, registry, roots = _ledger(tmp_path)
    project_manifest = json.loads((roots["a"] / "docs/kb/manifest.json").read_text())
    row = project_manifest["records"][0]
    path = roots["a"] / row["destination_relative_path"]
    record = json.loads(path.read_text())
    record["project_id"] = "b"
    payload = json.dumps(record, sort_keys=True).encode()
    path.write_bytes(payload)
    row["size"] = len(payload)
    row["sha256"] = hashlib.sha256(payload).hexdigest()
    digest = hashlib.sha256()
    digest.update(row["stable_id"].encode() + b"\0" + payload + b"\0")
    project_manifest["records_sha256"] = "sha256:" + digest.hexdigest()
    (roots["a"] / "docs/kb/manifest.json").write_text(json.dumps(project_manifest))
    global_manifest = json.loads(distribution.read_text())
    global_manifest["projects"][0]["records_sha256"] = project_manifest["records_sha256"]
    distribution.write_text(json.dumps(global_manifest))

    with pytest.raises(KnowledgeOwnerError, match="identity"):
        activation.activate(
            distribution_manifest=distribution,
            scope_registry_path=registry,
            engine_state_path=tmp_path / "owner.json",
        )


def _active_router(tmp_path: Path) -> tuple[ProjectKnowledgeRouter, Path]:
    root = tmp_path / "project"
    _repo(root)
    router = ProjectKnowledgeRouter(
        project_roots={"project": root},
        engine_state_path=tmp_path / "owner.json",
        central_reader=lambda _project, _stable: {},
    )
    router.activate({"project": _git(root, "rev-parse", "HEAD")})
    return router, root


def test_t3_record_write_failure_never_leaves_partial_final_file(
    tmp_path: Path, monkeypatch
):
    router, root = _active_router(tmp_path)
    stable_id = "00000000-0000-4000-8000-000000000099"
    monkeypatch.setattr(project_knowledge.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("disk")))

    with pytest.raises(OSError, match="disk"):
        router.write_record(
            "project",
            {
                "record_type": "resource",
                "project_id": "project",
                "stable_id": stable_id,
            },
        )
    assert not (root / f"docs/kb/records/evidence/{stable_id}.json").exists()


def test_t3_owner_state_and_fact_namespace_are_durable(tmp_path: Path, monkeypatch):
    root = tmp_path / "project"
    _repo(root)
    router = ProjectKnowledgeRouter(
        project_roots={"project": root},
        engine_state_path=tmp_path / "owner.json",
        central_reader=lambda _project, _stable: {},
    )
    fsync_calls = []
    original_fsync = project_knowledge.os.fsync
    monkeypatch.setattr(
        project_knowledge.os,
        "fsync",
        lambda descriptor: (fsync_calls.append(descriptor), original_fsync(descriptor))[1],
    )
    router.activate({"project": _git(root, "rev-parse", "HEAD")})
    assert len(fsync_calls) >= 2

    stable_id = "00000000-0000-4000-8000-000000000100"
    router.write_record(
        "project",
        {
            "record_type": "knowledge.fact",
            "project_id": "project",
            "stable_id": stable_id,
        },
    )
    assert (root / f"docs/kb/records/facts/{stable_id}.json").is_file()
    assert not (root / f"docs/kb/records/evidence/{stable_id}.json").exists()


def test_t3_post_replace_fsync_failure_restores_central_owner(
    tmp_path: Path, monkeypatch
):
    distribution, registry, roots = _ledger(tmp_path)
    state = tmp_path / "owner.json"
    ProjectKnowledgeRouter(
        project_roots=roots,
        engine_state_path=state,
        central_reader=lambda _project, _stable: {},
    )
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(
        project_knowledge,
        "_fsync_directory",
        lambda _path: (_ for _ in ()).throw(OSError("directory fsync")),
    )

    with pytest.raises(OSError, match="directory fsync"):
        activation.activate(
            distribution_manifest=distribution,
            scope_registry_path=registry,
            engine_state_path=state,
            receipt_path=receipt,
        )
    assert json.loads(state.read_text())["active_owner"] == "central"
    assert not receipt.exists()


def test_t3_receipt_final_path_is_never_visible_while_writing(
    tmp_path: Path, monkeypatch
):
    distribution, registry, _roots = _ledger(tmp_path)
    receipt = tmp_path / "receipt.json"
    original_fdopen = activation.os.fdopen

    def inspect_before_write(*args, **kwargs):
        opened = Path(activation.os.readlink(f"/proc/self/fd/{args[0]}")).name
        if receipt.name in opened:
            assert not receipt.exists(), "partial receipt became visible at its final path"
        return original_fdopen(*args, **kwargs)

    monkeypatch.setattr(activation.os, "fdopen", inspect_before_write)
    result = activation.activate(
        distribution_manifest=distribution,
        scope_registry_path=registry,
        engine_state_path=tmp_path / "owner.json",
        receipt_path=receipt,
    )
    assert result["status"] == "activated"
    assert receipt.is_file()


def test_t3_ledger_change_during_activation_is_rejected(tmp_path: Path, monkeypatch):
    distribution, registry, roots = _ledger(tmp_path)
    local_manifest = json.loads((roots["a"] / "docs/kb/manifest.json").read_text())
    record = roots["a"] / local_manifest["records"][0]["destination_relative_path"]
    original_head = activation._head
    mutated = False

    def mutate_after_first_digest(root: Path):
        nonlocal mutated
        if root == roots["a"] and not mutated:
            record.write_bytes(record.read_bytes() + b"\n")
            mutated = True
        return original_head(root)

    monkeypatch.setattr(activation, "_head", mutate_after_first_digest)
    state = tmp_path / "owner.json"
    with pytest.raises(KnowledgeOwnerError, match="(changed during activation|byte parity)"):
        activation.activate(
            distribution_manifest=distribution,
            scope_registry_path=registry,
            engine_state_path=state,
        )
    assert not state.exists() or json.loads(state.read_text())["active_owner"] == "central"
