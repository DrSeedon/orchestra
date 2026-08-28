"""Frozen Phase-2 acceptance oracles for project-local knowledge distribution (#412)."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_OWNER_ANCHOR = (
    "Project knowledge is canonical only inside the current repository's `docs/kb/`."
)
PART_SHA256 = {
    "part-1.json": "f60b6d536134834c68c9ef43cdeeaab70c67d5d0759a3f97d8645107bfee465c",
    "part-2.json": "357ee8354014942dc18f092a98106bd8652d208b01adaaa2dd806eb8b7f411b5",
    "part-3.json": "eceb8ba89246c00b8f834f4ceefdc34eb4ebb028bf63be4530bd638027fd6c20",
    "part-4.json": "94ee0a081b1531fb74c22d3fe6b82becc6f34fc2cf609501a1973a4611139980",
    "part-5.json": "478c70c1a008405c6483fd5aa6408b7055fccc07522d998a95f3f607dd92d91d",
}


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_refs(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "show-ref", "--head"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode in {0, 1}
    return result.stdout


def _worktree_snapshot(root: Path) -> dict:
    files = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.relative_to(root).parts:
            continue
        files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "files": files,
        "status": _git(root, "status", "--porcelain"),
        "refs": _git_refs(root),
        "config": _git(root, "config", "--local", "--list"),
    }


def _paths_snapshot(paths: tuple[Path, ...]) -> dict[str, str]:
    snapshot = {}
    for owner in paths:
        candidates = [owner] if owner.is_file() else sorted(
            path for path in owner.rglob("*") if path.is_file()
        )
        for path in candidates:
            snapshot[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _git_gate(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    gate_dir = tmp_path / "git-gate"
    gate_dir.mkdir()
    log = tmp_path / "git-commands.jsonl"
    wrapper = gate_dir / "git"
    wrapper.write_text(
        """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
index = 0
while index < len(args) and args[index].startswith('-'):
    index += 2 if args[index] in {'-C', '-c', '--git-dir', '--work-tree'} else 1
subcommand = args[index] if index < len(args) else ''
with open(os.environ['GIT_GATE_LOG'], 'a', encoding='utf-8') as stream:
    stream.write(json.dumps({'args': args, 'subcommand': subcommand}) + '\\n')
if subcommand in {'push', 'pull', 'fetch', 'remote', 'reset', 'rebase'}:
    raise SystemExit(97)
os.execv(os.environ['REAL_GIT'], [os.environ['REAL_GIT'], *args])
""",
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
    env = os.environ.copy()
    env.update(
        PATH=str(gate_dir) + os.pathsep + env.get("PATH", ""),
        REAL_GIT=subprocess.run(
            ["which", "git"], check=True, capture_output=True, text=True
        ).stdout.strip(),
        GIT_GATE_LOG=str(log),
    )
    return gate_dir, log, env


def _init_repo(root: Path, *, remote: Path | None = None) -> str:
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "seed")
    head = _git(root, "rev-parse", "HEAD")
    if remote is not None:
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        _git(root, "remote", "add", "origin", str(remote))
        _git(root, "push", "-q", "-u", "origin", "main")
    return head


def _record(project_id: str, stable_id: str, source_path: str) -> bytes:
    value = {
        "git_blob": "a" * 40,
        "git_commit": "b" * 40,
        "project_id": project_id,
        "record_type": "resource",
        "schema_version": 1,
        "source_class": "immutable-evidence",
        "source_path": source_path,
        "source_scope": f"/old/{project_id}",
        "source_sha256": "sha256:" + "c" * 64,
        "stable_id": stable_id,
        "status": "current",
        "storage": "cold-immutable-reference",
        "uri": f"orch://project/{project_id}/resources/{stable_id}",
    }
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode() + b"\n"


def _distribution_module():
    spec = importlib.util.find_spec("app.ia.project_distribution")
    assert spec is not None, "T1 missing app.ia.project_distribution"
    return importlib.import_module("app.ia.project_distribution")


def _project_knowledge_module():
    spec = importlib.util.find_spec("app.ia.project_knowledge")
    assert spec is not None, "T3 missing app.ia.project_knowledge"
    return importlib.import_module("app.ia.project_knowledge")


def _cleanup_module():
    spec = importlib.util.find_spec("app.ia.project_cleanup")
    assert spec is not None, "T5 missing app.ia.project_cleanup"
    return importlib.import_module("app.ia.project_cleanup")


def test_t1_byte_preserving_distribution_is_scoped_and_manifested(tmp_path: Path):
    _distribution_module()
    script = Path("scripts/distribute_project_knowledge.py")
    assert script.is_file(), "T1 missing distribution CLI"

    central = tmp_path / "central"
    repo_a, repo_b = tmp_path / "project-a", tmp_path / "project-b"
    remote_a = tmp_path / "project-a.git"
    quarantine = tmp_path / "orphans"
    central_head = _init_repo(central)
    base_a = _init_repo(repo_a, remote=remote_a)
    base_b = _init_repo(repo_b)
    _init_repo(quarantine)

    inputs = {
        ("project-a", "00000000-0000-4000-8000-000000000001"): _record(
            "project-a", "00000000-0000-4000-8000-000000000001", "docs/kb/a.md"
        ),
        ("project-b", "00000000-0000-4000-8000-000000000002"): _record(
            "project-b", "00000000-0000-4000-8000-000000000002", "docs/kb/b.md"
        ),
        ("orphan", "00000000-0000-4000-8000-000000000003"): _record(
            "orphan", "00000000-0000-4000-8000-000000000003", "docs/kb/o.md"
        ),
    }
    for (project_id, stable_id), payload in inputs.items():
        path = central / "evidence" / project_id / f"{stable_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    _git(central, "add", "evidence")
    _git(central, "commit", "-qm", "records")
    source_head = _git(central, "rev-parse", "HEAD")

    registry = tmp_path / "scope-registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "canonical_project_id": "project-a",
                        "repository_root": str(repo_a),
                    },
                    {
                        "canonical_project_id": "project-b",
                        "repository_root": str(repo_b),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    common = [
        sys.executable,
        str(script),
        "--canonical-root",
        str(central),
        "--scope-registry",
        str(registry),
        "--quarantine-root",
        str(quarantine),
        "--expected-source-head",
        source_head,
        "--json",
    ]
    _gate_dir, command_log, gated_env = _git_gate(tmp_path)
    before = {
        "source_head": _git(central, "rev-parse", "HEAD"),
        "a_head": _git(repo_a, "rev-parse", "HEAD"),
        "b_head": _git(repo_b, "rev-parse", "HEAD"),
        "a_refs": _git_refs(repo_a),
        "b_refs": _git_refs(repo_b),
        "remote_refs": _git_refs(remote_a),
        "a_config": _git(repo_a, "config", "--local", "--list"),
        "b_config": _git(repo_b, "config", "--local", "--list"),
        "central_tree": _worktree_snapshot(central),
        "a_tree": _worktree_snapshot(repo_a),
        "b_tree": _worktree_snapshot(repo_b),
        "quarantine_tree": _worktree_snapshot(quarantine),
        "registry_sha256": hashlib.sha256(registry.read_bytes()).hexdigest(),
    }
    dry_run = subprocess.run(
        [*common, "--dry-run"], check=True, capture_output=True, text=True, env=gated_env
    )
    dry = json.loads(dry_run.stdout)
    assert dry["mode"] == "dry-run"
    assert not (repo_a / "docs/kb").exists()
    assert not (repo_b / "docs/kb").exists()
    assert _git(central, "rev-parse", "HEAD") == before["source_head"]
    assert _git_refs(repo_a) == before["a_refs"]
    assert _git_refs(repo_b) == before["b_refs"]
    assert _worktree_snapshot(central) == before["central_tree"]
    assert _worktree_snapshot(repo_a) == before["a_tree"]
    assert _worktree_snapshot(repo_b) == before["b_tree"]
    assert _worktree_snapshot(quarantine) == before["quarantine_tree"]
    assert hashlib.sha256(registry.read_bytes()).hexdigest() == before["registry_sha256"]

    applied = subprocess.run(
        [*common, "--apply", "--commit"],
        check=True,
        capture_output=True,
        text=True,
        env=gated_env,
    )
    result = json.loads(applied.stdout)
    verified = subprocess.run(
        [*common, "--verify"], check=True, capture_output=True, text=True, env=gated_env
    )
    assert json.loads(verified.stdout)["status"] == "verified"

    assert result["total_record_count"] == 3
    assert result["quarantine_count"] == 1
    assert result["source_head"] == source_head
    assert len(result["records"]) == 3
    for (project_id, stable_id), payload in inputs.items():
        owner = (
            {"project-a": repo_a, "project-b": repo_b}.get(project_id)
            or quarantine / project_id
        )
        destination = owner / "docs/kb/records/evidence" / f"{stable_id}.json"
        assert destination.read_bytes() == payload
        local_manifest = json.loads((owner / "docs/kb/manifest.json").read_text())
        assert local_manifest["project_id"] == project_id
        assert any(item["stable_id"] == stable_id for item in local_manifest["records"])
        row = next(item for item in result["records"] if item["stable_id"] == stable_id)
        assert row["sha256"] == hashlib.sha256(payload).hexdigest()

    for repo, base in ((repo_a, base_a), (repo_b, base_b)):
        assert _git(repo, "status", "--porcelain") == ""
        changed = _git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
        assert changed
        assert all(path.startswith("docs/kb/") for path in changed.splitlines())
        assert _git(repo, "rev-parse", "HEAD") != base

    assert _git(central, "status", "--porcelain") == ""
    assert _git(central, "rev-parse", "HEAD") == source_head
    assert _git_refs(remote_a) == before["remote_refs"]
    assert _git(repo_a, "config", "--local", "--list") == before["a_config"]
    assert _git(repo_b, "config", "--local", "--list") == before["b_config"]
    executed = [json.loads(line) for line in command_log.read_text().splitlines()]
    forbidden = {"push", "pull", "fetch", "remote", "reset", "rebase"}
    assert not forbidden.intersection(item["subcommand"] for item in executed)
    assert {"rev-parse", "status", "add", "commit"} <= {
        item["subcommand"] for item in executed
    }
    assert central_head != source_head


def test_t3_owner_switch_is_global_and_project_isolated(tmp_path: Path):
    module = _project_knowledge_module()
    assert hasattr(module, "ProjectKnowledgeRouter"), "T3 missing ProjectKnowledgeRouter"
    assert hasattr(module, "KnowledgeOwnerError"), "T3 missing KnowledgeOwnerError"

    repo_a, repo_b = tmp_path / "a", tmp_path / "b"
    _init_repo(repo_a)
    _init_repo(repo_b)
    (repo_a / ".gitignore").write_text("docs/kb/\n", encoding="utf-8")
    _git(repo_a, "add", ".gitignore")
    _git(repo_a, "commit", "-qm", "ignore local knowledge")
    id_a = "00000000-0000-4000-8000-00000000000a"
    id_b = "00000000-0000-4000-8000-00000000000b"
    record_a = repo_a / f"docs/kb/records/evidence/{id_a}.json"
    record_b = repo_b / f"docs/kb/records/evidence/{id_b}.json"
    record_a.parent.mkdir(parents=True)
    record_b.parent.mkdir(parents=True)
    record_a.write_bytes(_record("a", id_a, "docs/kb/a.md"))
    record_b.write_bytes(_record("b", id_b, "docs/kb/b.md"))
    assert _git(repo_a, "check-ignore", "docs/kb/records/evidence/" + id_a + ".json")
    assert _git(repo_a, "ls-files", "docs/kb") == ""
    assert _git(repo_b, "ls-files", "docs/kb") == ""

    engine_state = tmp_path / "owner.json"
    central_records = {("a", "central"): {"project_id": "a", "stable_id": "central"}}
    router = module.ProjectKnowledgeRouter(
        project_roots={"a": repo_a, "b": repo_b},
        engine_state_path=engine_state,
        central_reader=lambda project_id, stable_id: central_records[(project_id, stable_id)],
    )
    assert router.read_record("a", "central")["stable_id"] == "central"
    state_before = engine_state.read_bytes()
    good_heads = {
        name: _git(root, "rev-parse", "HEAD")
        for name, root in {"a": repo_a, "b": repo_b}.items()
    }
    bad_maps = (
        {"a": good_heads["a"]},
        {**good_heads, "extra": "0" * 40},
        {"a": good_heads["a"], "b": "0" * 40},
    )
    for bad in bad_maps:
        with pytest.raises(module.KnowledgeOwnerError, match="project (head|map)"):
            router.activate(bad)
        assert router.active_owner == "central"
        assert engine_state.read_bytes() == state_before
        fresh = module.ProjectKnowledgeRouter(
            project_roots={"a": repo_a, "b": repo_b},
            engine_state_path=engine_state,
            central_reader=lambda project_id, stable_id: central_records[(project_id, stable_id)],
        )
        assert fresh.active_owner == "central"

    router.activate(good_heads)
    assert router.active_owner == "project-local"
    assert router.read_record("a", id_a)["project_id"] == "a"
    with pytest.raises(module.KnowledgeOwnerError, match="cross-project"):
        router.read_record("a", id_b)
    assert router.read_record("a", "central")["stable_id"] == "central"
    new_id = "00000000-0000-4000-8000-00000000000c"
    router.write_record(
        "a",
        {
            "project_id": "a",
            "stable_id": new_id,
            "record_type": "resource",
            "status": "current",
        },
    )
    assert (repo_a / f"docs/kb/records/evidence/{new_id}.json").is_file()
    assert not (repo_b / f"docs/kb/records/evidence/{new_id}.json").exists()
    fresh = module.ProjectKnowledgeRouter(
        project_roots={"a": repo_a, "b": repo_b},
        engine_state_path=engine_state,
        central_reader=lambda project_id, stable_id: central_records[(project_id, stable_id)],
    )
    assert fresh.active_owner == "project-local"
    assert fresh.read_record("a", new_id)["stable_id"] == new_id
    from app.ia.runtime import KnowledgeRuntime

    runtime = object.__new__(KnowledgeRuntime)
    runtime.project_knowledge = fresh
    runtime.state = {
        "canonical_head": "central-head",
        "projection_head": "central-head",
        "indexed_head": None,
    }
    items, debt = runtime._query_evidence("a", id_a, 1)
    assert debt == []
    assert items[0]["stable_id"] == id_a
    assert items[0]["source"] == "project-local-filesystem"
    runtime.scope_registry = {"/scope-a": {"canonical_project_id": "a"}}
    runtime._connection = lambda: pytest.fail(
        "project-local result must be preferred before legacy logs"
    )
    query = runtime.query_for_scope("/scope-a", id_a, limit=1, detail="record")
    assert query["items"][0]["stable_id"] == id_a
    assert query["project_knowledge_owner"] == "project-local"
    assert hasattr(module, "project_knowledge_mode")
    assert hasattr(module, "active_project_knowledge")
    with module.project_knowledge_mode(fresh):
        assert module.active_project_knowledge() is fresh


@pytest.mark.xfail(strict=True, reason="T4 не реализован, оракул заморожен заранее")
def test_t4_extracted_facts_convert_one_to_one_and_idempotently(tmp_path: Path):
    from scripts import kb_promote_facts as script

    assert hasattr(script, "write_project_fact_records"), (
        "T4 missing write_project_fact_records"
    )
    facts_dir = Path("docs/tasks/kb-extract")
    source_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in facts_dir.glob("part-*.json")
    }
    assert source_hashes == PART_SHA256
    source_facts = script.load_facts(facts_dir)
    assert len(source_facts) == 764
    expected = {script.stable_fact_id(item.value): item.value for item in source_facts}
    assert len(expected) == 764

    def provenance_resolver(source_fact):
        stable_id = script.stable_fact_id(source_fact.value)
        evidence_id = script.stable_evidence_id(stable_id)
        task_id = f"00000000-0000-4000-8000-{source_fact.part:012d}"
        return {
            "task_id": task_id,
            "evidence_uri": f"orch://project/orchestra/tasks/{task_id}/evidence/{evidence_id}",
            "git_commit": "d" * 40,
        }

    first = script.write_project_fact_records(
        facts_dir=facts_dir,
        source_root=Path.cwd(),
        destination_root=tmp_path / "docs/kb",
        project_id="orchestra",
        provenance_resolver=provenance_resolver,
    )
    second = script.write_project_fact_records(
        facts_dir=facts_dir,
        source_root=Path.cwd(),
        destination_root=tmp_path / "docs/kb",
        project_id="orchestra",
        provenance_resolver=provenance_resolver,
    )
    records = [json.loads(path.read_text()) for path in (tmp_path / "docs/kb/records/facts").rglob("*.json")]
    assert len(records) == 764
    actual = {item["stable_id"]: item for item in records}
    assert set(actual) == set(expected)
    for stable_id, source in expected.items():
        item = actual[stable_id]
        assert item["claim"] == source["statement"]
        assert item["status"] == source["status"]
        assert item["fact_key"] == f"fact-{stable_id}"
        assert item["metadata"]["reason"] == source["reason"]
        assert item["metadata"]["decided_at"] == source["decided_at"]
        assert item["metadata"]["evidence"] == source["evidence"]
        assert item["metadata"]["source_file"] == source["source_file"]
        assert item["metadata"]["source_lines"] == source["source_lines"]
        assert item["metadata"]["topic_label"] == source["topic"]
        assert item["metadata"].get("kind") == source.get("kind")
        assert item["provenance"][0]["path"] == source["source_file"]
        assert item["provenance"][0]["anchor"] == source["source_lines"]
        assert item["provenance"][0]["measurement"] == source["evidence"]
        source_fact = next(value for value in source_facts if script.stable_fact_id(value.value) == stable_id)
        expected_provenance = provenance_resolver(source_fact)
        assert item["provenance"][0]["task_id"] == expected_provenance["task_id"]
        assert item["provenance"][0]["evidence_uri"] == expected_provenance["evidence_uri"]
        assert item["provenance"][0]["git_commit"] == expected_provenance["git_commit"]
    assert sum(item["status"] == "current" for item in records) == 689
    assert sum(item["status"] == "rejected" for item in records) == 75
    assert sum(item["metadata"]["decided_at"] is None for item in records) == 275
    assert sum(item["metadata"]["reason"] is None for item in records) == 397
    assert first["created"] == 764
    assert first["canonical_head"] == second["canonical_head"]
    assert second["created"] == 0
    assert source_hashes == {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in facts_dir.glob("part-*.json")
    }


@pytest.mark.xfail(strict=True, reason="T5 не реализован, оракул заморожен заранее")
def test_t5_cleanup_refuses_without_parity_and_preserves_engine_state(
    tmp_path: Path, monkeypatch
):
    module = _cleanup_module()
    from app import rag
    assert hasattr(module, "cleanup_central_project_data"), (
        "T5 missing cleanup_central_project_data"
    )
    assert hasattr(module, "CleanupError"), "T5 missing CleanupError"

    state_root = tmp_path / "knowledge-v1"
    central = state_root / "canonical"
    _init_repo(central)
    stable_id = "00000000-0000-4000-8000-000000000005"
    payload = _record("foreign", stable_id, "docs/kb/foreign.md")
    record = central / f"evidence/foreign/{stable_id}.json"
    record.parent.mkdir(parents=True)
    record.write_bytes(payload)
    task_state = central / "tasks/projects/foreign/tasks/t/state.json"
    task_state.parent.mkdir(parents=True)
    task_state.write_text('{"project_id":"foreign"}\n', encoding="utf-8")
    _git(central, "add", "evidence", "tasks")
    _git(central, "commit", "-qm", "foreign data")
    source_head = _git(central, "rev-parse", "HEAD")

    project_repo = tmp_path / "project"
    before_head = _init_repo(project_repo)
    destination = project_repo / f"docs/kb/records/evidence/{stable_id}.json"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(payload)
    records_digest = hashlib.sha256(
        stable_id.encode() + b"\0" + payload + b"\0"
    ).hexdigest()
    local_manifest = {
        "schema_version": 1,
        "project_id": "foreign",
        "records_sha256": "sha256:" + records_digest,
        "records": [
            {
                "stable_id": stable_id,
                "destination_relative_path": f"docs/kb/records/evidence/{stable_id}.json",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
    }
    (project_repo / "docs/kb/manifest.json").write_text(
        json.dumps(local_manifest, sort_keys=True), encoding="utf-8"
    )
    _git(project_repo, "add", "docs/kb")
    _git(project_repo, "commit", "-qm", "local knowledge")
    target_commit = _git(project_repo, "rev-parse", "HEAD")

    registry = state_root / "scope-registry.json"
    registry.write_text('{"schema_version":1,"entries":[]}\n', encoding="utf-8")
    runtime_state = state_root / "runtime-state.json"
    runtime_state.write_text('{"active_owner":"central","generation":3}\n', encoding="utf-8")
    receipts = state_root / "receipts/gate.json"
    receipts.parent.mkdir()
    receipts.write_text('{"status":"verified"}\n', encoding="utf-8")
    current = state_root / "current.db"
    with sqlite3.connect(current) as connection:
        connection.execute(
            "CREATE TABLE current_records(record_key TEXT PRIMARY KEY, project_id TEXT, payload_json TEXT)"
        )
        connection.execute("CREATE VIRTUAL TABLE current_fts USING fts5(record_key UNINDEXED, text)")
        connection.executemany(
            "INSERT INTO current_records VALUES (?, ?, '{}')",
            (("o", "orchestra"), ("f", "foreign")),
        )
        connection.executemany(
            "INSERT INTO current_fts(record_key, text) VALUES (?, ?)",
            (("o", "orchestra current"), ("f", "foreign current")),
        )
    vector = tmp_path / "vec.db"
    memory = rag.RagMemory(path=vector)
    monkeypatch.setattr(
        memory,
        "_embed",
        lambda texts, is_query: [[0.0] * rag.DIM for _ in texts],
    )
    memory.index_file("orchestra", "o.md", "orchestra knowledge " * 30)
    memory.index_file("foreign", "f.md", "foreign knowledge " * 30)
    memory.index_log("orchestra", 1, "agent_msg", "o", "orchestra log " * 30)
    memory.index_log("foreign", 2, "agent_msg", "f", "foreign log " * 30)
    memory.conn.close()
    engine_db = tmp_path / "orchestra.db"
    with sqlite3.connect(engine_db) as connection:
        connection.execute("CREATE TABLE sessions(id TEXT PRIMARY KEY, scope TEXT)")
        connection.execute("CREATE TABLE usage_snapshots(id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO sessions VALUES ('s', '/foreign')")
        connection.execute("INSERT INTO usage_snapshots VALUES (1, 'quota')")

    distribution_path = tmp_path / "distribution.json"
    distribution = {
        "schema_version": 1,
        "status": "prepared",
        "source_head": source_head,
        "total_record_count": 1,
        "quarantine_count": 0,
        "projects": [
            {
                "project_id": "foreign",
                "repository_root": str(project_repo),
                "before_head": before_head,
                "target_commit": target_commit,
                "manifest_relative_path": "docs/kb/manifest.json",
                "record_count": 1,
                "records_sha256": local_manifest["records_sha256"],
            }
        ],
    }
    distribution_path.write_text(json.dumps(distribution, sort_keys=True), encoding="utf-8")
    owner_state = runtime_state
    fact_receipt = tmp_path / "facts.json"
    fact_receipt.write_text('{"status":"prepared"}\n', encoding="utf-8")

    protected = (
        registry,
        receipts,
        engine_db,
        distribution_path,
        owner_state,
        fact_receipt,
    )
    refusal_scope = (tmp_path,)
    before_refusal = _paths_snapshot(refusal_scope)

    with pytest.raises(module.CleanupError, match="verified"):
        module.cleanup_central_project_data(
            state_root=state_root,
            distribution_manifest_path=distribution_path,
            owner_state_path=owner_state,
            fact_receipt_path=fact_receipt,
            current_db=current,
            vector_db=vector,
            engine_db=engine_db,
    )
    assert record.exists() and task_state.exists()
    assert _paths_snapshot(refusal_scope) == before_refusal

    def write_verified_receipts() -> None:
        distribution_path.write_text(json.dumps(distribution, sort_keys=True), encoding="utf-8")
        manifest_sha = hashlib.sha256(distribution_path.read_bytes()).hexdigest()
        owner_state.write_text(
            json.dumps(
                {
                    "active_owner": "project-local",
                    "generation": 4,
                    "distribution_manifest_sha256": manifest_sha,
                }
            ),
            encoding="utf-8",
        )
        fact_receipt.write_text(
            json.dumps(
                {
                    "status": "verified",
                    "input_count": 764,
                    "output_count": 764,
                    "distribution_manifest_sha256": manifest_sha,
                }
            ),
            encoding="utf-8",
        )

    distribution["status"] = "verified"
    distribution["quarantine_count"] = 1
    write_verified_receipts()
    before_quarantine_refusal = _paths_snapshot(refusal_scope)
    with pytest.raises(module.CleanupError, match="quarantine"):
        module.cleanup_central_project_data(
            state_root=state_root,
            distribution_manifest_path=distribution_path,
            owner_state_path=owner_state,
            fact_receipt_path=fact_receipt,
            current_db=current,
            vector_db=vector,
            engine_db=engine_db,
        )
    assert _paths_snapshot(refusal_scope) == before_quarantine_refusal

    distribution["quarantine_count"] = 0
    _git(project_repo, "commit", "--allow-empty", "-qm", "head drift")
    drift_head = _git(project_repo, "rev-parse", "HEAD")
    write_verified_receipts()
    before_drift_refusal = _paths_snapshot(refusal_scope)
    with pytest.raises(module.CleanupError, match="head drift"):
        module.cleanup_central_project_data(
            state_root=state_root,
            distribution_manifest_path=distribution_path,
            owner_state_path=owner_state,
            fact_receipt_path=fact_receipt,
            current_db=current,
            vector_db=vector,
            engine_db=engine_db,
        )
    assert _paths_snapshot(refusal_scope) == before_drift_refusal

    distribution["projects"][0]["target_commit"] = drift_head
    distribution["projects"][0]["records_sha256"] = "sha256:" + "0" * 64
    write_verified_receipts()
    before_parity_refusal = _paths_snapshot(refusal_scope)
    with pytest.raises(module.CleanupError, match="parity"):
        module.cleanup_central_project_data(
            state_root=state_root,
            distribution_manifest_path=distribution_path,
            owner_state_path=owner_state,
            fact_receipt_path=fact_receipt,
            current_db=current,
            vector_db=vector,
            engine_db=engine_db,
        )
    assert record.exists() and task_state.exists()
    assert _paths_snapshot(refusal_scope) == before_parity_refusal

    distribution["projects"][0]["records_sha256"] = local_manifest["records_sha256"]
    write_verified_receipts()
    success_protected = _paths_snapshot(protected)
    module.cleanup_central_project_data(
        state_root=state_root,
        distribution_manifest_path=distribution_path,
        owner_state_path=owner_state,
        fact_receipt_path=fact_receipt,
        current_db=current,
        vector_db=vector,
        engine_db=engine_db,
    )
    assert not record.exists()
    assert not task_state.exists()
    assert success_protected == _paths_snapshot(protected)
    with sqlite3.connect(current) as connection:
        assert connection.execute(
            "SELECT project_id FROM current_records ORDER BY project_id"
        ).fetchall() == [("orchestra",)]
        assert connection.execute(
            "SELECT text FROM current_fts ORDER BY text"
        ).fetchall() == [("orchestra current",)]
    check = rag.RagMemory(path=vector, readonly=True)
    assert check.conn.execute("SELECT project FROM files").fetchall() == [("orchestra",)]
    assert check.conn.execute("SELECT project FROM vec_files").fetchall() == [("orchestra",)]
    assert check.conn.execute("SELECT count(*) FROM file_chunks").fetchone()[0] == 1
    assert check.conn.execute("SELECT count(*) FROM fts_files").fetchone()[0] == 1
    assert check.conn.execute("SELECT project FROM logs_indexed").fetchall() == [("orchestra",)]
    assert check.conn.execute("SELECT project FROM vec_logs").fetchall() == [("orchestra",)]
    assert check.conn.execute("SELECT count(*) FROM log_chunks").fetchone()[0] == 1
    assert check.conn.execute("SELECT count(*) FROM fts_logs").fetchone()[0] == 1
    check.conn.close()


@pytest.mark.xfail(strict=True, reason="T6 не реализован, оракул заморожен заранее")
def test_t6_prompt_and_cutover_deliver_project_local_owner():
    from app.ia import cutover
    from app.pipeline import DEFAULT_PIPELINE, build_system_prompt

    forbidden = tuple(getattr(cutover, "_FORBIDDEN_LEGACY_DIRECTIVES", ()))
    required = tuple(getattr(cutover, "_REQUIRED_PROMPT_ANCHORS", ()))
    assert not any("docs/kb" in item for item in forbidden), (
        "T6 cutover still forbids docs/kb directives"
    )
    assert PROJECT_OWNER_ANCHOR in required, "T6 cutover missing project-local owner anchor"
    prompts = {}
    for role in ("orchestrator", "sub-orchestrator", "worker", "full-cycle", "reducer"):
        prompts[role] = build_system_prompt(DEFAULT_PIPELINE, role)
        assert PROJECT_OWNER_ANCHOR in prompts[role], role
        assert "docs/kb/README.md" in prompts[role], role
    append_anchor = "Append the conclusion to its topic file in `docs/kb/`"
    assert append_anchor in prompts["full-cycle"]
    assert append_anchor not in prompts["worker"]
