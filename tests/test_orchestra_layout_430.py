"""Frozen RED acceptance for task #430: project state moves under .orchestra/."""

# LEGACY_PATH_FIXTURE: old roots in this file are intentional negative controls.

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import shlex
import sqlite3
import subprocess
import sys
import uuid
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FINAL_DOC_FILES = {
    "banner.png",
    "dashboard.png",
    "orchestrator-vps-onboarding.md",
    "telegram-bot-api.service.template",
    "tg-local-api-setup.md",
}
MOVE_PREFIXES = {
    "docs/kb/": ".orchestra/kb/",
    "docs/tasks/": ".orchestra/tasks/",
    "docs/workers/": ".orchestra/workers/",
    "docs/archive/": ".orchestra/archive/",
    "pipelines/": ".orchestra/pipelines/",
    "docs/artifacts/": ".orchestra/artifacts/",
    "docs/experiments/": ".orchestra/experiments/",
    "docs/research/": ".orchestra/research/",
    "docs/reviews/": ".orchestra/reviews/",
    "docs/tg-media/": ".orchestra/tg-media/",
}
MOVE_FILES = {
    "docs/codex-field-guide.md": ".orchestra/guides/codex-field-guide.md",
    "docs/grok-field-guide.md": ".orchestra/guides/grok-field-guide.md",
    "docs/measuring.md": ".orchestra/guides/measuring.md",
    "docs/team-structure.md": ".orchestra/guides/team-structure.md",
    "docs/HANDOFF-from-laptop.md": ".orchestra/archive/HANDOFF-from-laptop.md",
    "docs/codex-full-review.md": ".orchestra/reviews/codex-full-review.md",
    "docs/codex-subscription-usage-research-2026-07.md": ".orchestra/research/codex-subscription-usage-research-2026-07.md",
    "docs/fork-analysis.md": ".orchestra/research/fork-analysis.md",
    "docs/proxy-speed-benchmark.md": ".orchestra/research/proxy-speed-benchmark.md",
    "docs/research-context-bug.md": ".orchestra/research/research-context-bug.md",
    "docs/research-context-full.md": ".orchestra/research/research-context-full.md",
    "docs/research-deepgram.md": ".orchestra/research/research-deepgram.md",
    "docs/research-multiproject.md": ".orchestra/research/research-multiproject.md",
    "docs/architecture.png": ".orchestra/artifacts/architecture.png",
    "docs/fleet-looping.png": ".orchestra/artifacts/fleet-looping.png",
}
FROZEN_EVIDENCE_MANIFEST_SHA256 = "83559af2e573185f5d685f25cefeeb8b94083819f59e91a9b4881e06ddb5b289"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=check,
    )


def _old_layout_repo(tmp_path: Path, name: str = "project") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "task430@example.invalid")
    _git(repo, "config", "user.name", "task430")
    (repo / ".gitignore").write_text("workers/\n", encoding="utf-8")
    for dirname in ("kb", "tasks", "workers", "archive"):
        destination = repo / "docs" / dirname
        destination.mkdir(parents=True)
        (destination / f"{dirname}.md").write_text(f"{dirname}\n", encoding="utf-8")
    (repo / "README.md").write_text("project\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "old layout")
    return repo


def _layout_module():
    module_path = ROOT / "app" / "orchestra_layout.py"
    assert module_path.is_file(), "T1 missing forced migration engine app/orchestra_layout.py"
    spec = importlib.util.spec_from_file_location("app.orchestra_layout", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _assert_repair_message(error: BaseException, code: str, repo: Path) -> list[str]:
    message = str(error)
    assert code in message
    command = error.repair_command
    assert message.count(command) == 1
    tokens = shlex.split(command)
    assert tokens[-2:] == ["--repair", str(repo.resolve())]
    assert Path(tokens[-3]).name == "migrate_orchestra_layout.py"
    assert Path(tokens[-3]).is_absolute()
    return tokens


def test_t1_forced_project_migration_is_committed_and_idempotent(tmp_path: Path):
    layout = _layout_module()
    repo = _old_layout_repo(tmp_path)
    before = int(_git(repo, "rev-list", "--count", "HEAD").stdout)

    result = layout.migrate_project_layout(repo, repair=False)

    assert result["status"] == "migrated"
    assert int(_git(repo, "rev-list", "--count", "HEAD").stdout) == before + 1
    assert _git(repo, "status", "--porcelain").stdout == ""
    assert (repo / ".orchestra" / "layout.json").is_file()
    for dirname in ("kb", "tasks", "workers", "archive"):
        assert (repo / ".orchestra" / dirname / f"{dirname}.md").read_text() == f"{dirname}\n"
        assert not (repo / "docs" / dirname).exists()
    ignored = _git(
        repo, "check-ignore", ".orchestra/workers/workers.md", check=False
    )
    assert ignored.returncode == 1, ignored.stdout

    second = layout.migrate_project_layout(repo, repair=False)
    assert second["status"] == "already_current"
    assert int(_git(repo, "rev-list", "--count", "HEAD").stdout) == before + 1
    assert _git(repo, "status", "--porcelain").stdout == ""


def test_t1_partial_missing_and_dirty_states_are_loud_and_repairable(tmp_path: Path):
    layout = _layout_module()
    partial = _old_layout_repo(tmp_path, "partial")
    (partial / ".orchestra").mkdir()
    _git(partial, "mv", "docs/kb", ".orchestra/kb")
    _git(partial, "commit", "-qm", "simulate interrupted migration")

    with pytest.raises(layout.LayoutMigrationError) as partial_error:
        layout.migrate_project_layout(partial, repair=False)
    repair_command = _assert_repair_message(
        partial_error.value, "ORCHESTRA_LAYOUT_PARTIAL", partial
    )
    repaired = subprocess.run(repair_command, text=True, capture_output=True)
    assert repaired.returncode == 0, repaired.stdout + repaired.stderr
    assert json.loads(repaired.stdout)["status"] == "repaired"
    assert _git(partial, "status", "--porcelain").stdout == ""

    missing = tmp_path / "missing"
    missing.mkdir()
    _git(missing, "init", "-q")
    with pytest.raises(layout.LayoutMigrationError) as missing_error:
        layout.require_project_layout(missing)
    missing_command = _assert_repair_message(
        missing_error.value, "ORCHESTRA_LAYOUT_MISSING", missing
    )
    missing_repair = subprocess.run(missing_command, text=True, capture_output=True)
    assert missing_repair.returncode == 2
    missing_result = json.loads(missing_repair.stdout)
    assert missing_result["status"] == "failed"
    assert missing_result["code"] == "ORCHESTRA_LAYOUT_MISSING"
    assert shlex.split(missing_result["repair_command"])[-2:] == [
        "--repair", str(missing.resolve())
    ]

    dirty_root = _old_layout_repo(tmp_path, "dirty-root")
    (dirty_root / "README.md").write_text("uncommitted user work\n", encoding="utf-8")
    dirty_tracked = _old_layout_repo(tmp_path, "dirty-tracked")
    (dirty_tracked / "docs/kb/kb.md").write_text("changed knowledge\n", encoding="utf-8")
    dirty_untracked = _old_layout_repo(tmp_path, "dirty-untracked")
    (dirty_untracked / "docs/kb/untracked.md").write_text("new knowledge\n", encoding="utf-8")
    clean = _old_layout_repo(tmp_path, "clean")
    dirty_repos = {
        "dirty-root": dirty_root,
        "dirty-tracked": dirty_tracked,
        "dirty-untracked": dirty_untracked,
    }
    before_status = {
        name: _git(repo, "status", "--porcelain").stdout
        for name, repo in dirty_repos.items()
    }
    dirty_files = {
        "dirty-root": dirty_root / "README.md",
        "dirty-tracked": dirty_tracked / "docs/kb/kb.md",
        "dirty-untracked": dirty_untracked / "docs/kb/untracked.md",
    }
    before_bytes = {name: path.read_bytes() for name, path in dirty_files.items()}
    fleet = layout.migrate_registered_projects({"clean": clean, **dirty_repos})
    assert fleet["clean"]["status"] == "migrated"
    for name, repo in dirty_repos.items():
        assert fleet[name]["status"] == "failed"
        assert fleet[name]["code"] == "ORCHESTRA_LAYOUT_DIRTY"
        assert shlex.split(fleet[name]["repair_command"])[-2:] == [
            "--repair", str(repo.resolve())
        ]
        assert (repo / "docs/kb").is_dir()
        assert not (repo / ".orchestra").exists()
        assert _git(repo, "status", "--porcelain").stdout == before_status[name]
        assert dirty_files[name].read_bytes() == before_bytes[name]


def test_t1_dirty_check_occurs_inside_repository_mutation_lock(tmp_path: Path, monkeypatch):
    layout = _layout_module()
    repo = _old_layout_repo(tmp_path, "race")

    @contextmanager
    def injecting_lock(_repo):
        (repo / "docs/kb/kb.md").write_text("raced after lock wait\n", encoding="utf-8")
        yield

    monkeypatch.setattr(layout, "repo_mutation_lock", injecting_lock)
    with pytest.raises(layout.LayoutMigrationError) as error:
        layout.migrate_project_layout(repo, repair=False)
    _assert_repair_message(error.value, "ORCHESTRA_LAYOUT_DIRTY", repo)
    assert (repo / "docs/kb/kb.md").read_text() == "raced after lock wait\n"
    assert not (repo / ".orchestra").exists()


def test_t4_startup_runs_migration_before_knowledge_runtime():
    tree = ast.parse((ROOT / "app" / "main.py").read_text(encoding="utf-8"))
    lifespan = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "lifespan"
    )
    calls = []
    for node in ast.walk(lifespan):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            calls.append((node.func.id, node.lineno))
        elif isinstance(node.func, ast.Attribute):
            calls.append((node.func.attr, node.lineno))
    migration_lines = [line for name, line in calls if name == "migrate_registered_project_layouts"]
    knowledge_lines = [line for name, line in calls if name == "knowledge_runtime_mode"]
    resume_lines = [line for name, line in calls if name == "auto_resume_all"]
    assert len(migration_lines) == 1, "T4 lifespan must invoke fleet migration exactly once"
    assert len(knowledge_lines) == 1
    assert len(resume_lines) == 1
    assert migration_lines[0] < knowledge_lines[0] < resume_lines[0]


def test_t3_pipeline_and_worker_memory_use_only_dot_orchestra(tmp_path: Path):
    from app import pipeline, prompting

    assert pipeline.PIPELINES_DIR == ROOT / ".orchestra" / "pipelines"
    repo = tmp_path / "repo"
    (repo / ".orchestra" / "workers").mkdir(parents=True)
    (repo / ".orchestra" / "layout.json").write_text("{}\n", encoding="utf-8")
    (repo / ".orchestra" / "workers" / "w.md").write_text("NEW\n", encoding="utf-8")
    (repo / "docs" / "workers").mkdir(parents=True)
    (repo / "docs" / "workers" / "w.md").write_text("OLD\n", encoding="utf-8")
    assert prompting.load_worker_memory("w", "worker", str(repo)) == "NEW"
    (repo / ".orchestra" / "layout.json").unlink()
    with pytest.raises(Exception, match="ORCHESTRA_LAYOUT_MISSING.*--repair"):
        prompting.load_worker_memory("w", "worker", str(repo))


def test_t3_task_guard_knowledge_owner_and_evidence_validator_use_new_root(tmp_path: Path):
    from app.ia.knowledge import KnowledgeService, PromotionValidationError
    from app.ia.project_distribution import _destination_row
    from app.ia.project_knowledge import ProjectKnowledgeRouter
    from app.tm import _next_par

    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE tm_tasks(project_id TEXT, par_number INTEGER)")
    connection.execute("CREATE TABLE tm_projects(id TEXT, scope TEXT)")
    connection.execute("INSERT INTO tm_tasks VALUES('p', 1)")
    connection.execute("INSERT INTO tm_projects VALUES('p', ?)", (str(tmp_path),))
    (tmp_path / ".orchestra" / "tasks" / "2").mkdir(parents=True)
    assert _next_par(connection, "p") == 3

    router = ProjectKnowledgeRouter(
        project_roots={"p": tmp_path},
        engine_state_path=tmp_path / "owner.json",
        central_reader=lambda *_: {},
    )
    record = {"project_id": "p", "stable_id": str(uuid.uuid4()), "record_type": "knowledge.fact"}
    assert router._record_path("p", record).relative_to(tmp_path).as_posix().startswith(
        ".orchestra/kb/records/"
    )

    owner = {"project_root": tmp_path}
    destination = _destination_row(
        owner,
        {"stable_id": str(uuid.uuid4()), "source_relative_path": "source", "size": 1, "sha256": "x"},
    )
    assert destination["destination_relative_path"].startswith(".orchestra/kb/records/")
    assert KnowledgeService._cold_source_path(".orchestra/tasks/1/research.md").parts[:2] == (
        ".orchestra", "tasks"
    )
    with pytest.raises(PromotionValidationError):
        KnowledgeService._cold_source_path("docs/tasks/1/research.md")


def _map_moved_path(old_path: str) -> str:
    if old_path in MOVE_FILES:
        return MOVE_FILES[old_path]
    for old_prefix, new_prefix in MOVE_PREFIXES.items():
        if old_path.startswith(old_prefix):
            return new_prefix + old_path[len(old_prefix):]
    raise AssertionError(f"unmapped pre-move path: {old_path}")


def _assert_all_moved_files_match_before_ref(before_ref: str, location_commit: str) -> int:
    sources = [prefix.rstrip("/") for prefix in MOVE_PREFIXES] + sorted(MOVE_FILES)
    raw = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-tree", "-r", "-z", before_ref, "--", *sources]
    )
    before = {}
    for item in raw.split(b"\0"):
        if not item:
            continue
        metadata, raw_path = item.split(b"\t", 1)
        mode, object_type, blob = metadata.decode().split()
        assert object_type == "blob"
        before[raw_path.decode()] = (mode, blob)
    assert len(before) >= 16_000

    current_raw = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-tree", "-r", "-z", location_commit, "--", ".orchestra"]
    )
    location_tree = {}
    for item in current_raw.split(b"\0"):
        if not item:
            continue
        metadata, raw_path = item.split(b"\t", 1)
        mode, object_type, blob = metadata.decode().split()
        assert object_type == "blob"
        location_tree[raw_path.decode()] = (mode, blob)

    targets = [_map_moved_path(old_path) for old_path in before]
    for (old_path, (old_mode, old_blob)), target in zip(before.items(), targets, strict=True):
        assert location_tree.get(target) == (old_mode, old_blob), (old_path, target)

    for old_path in (
        "docs/kb/README.md",
        "docs/tasks/430/plan.md",
        "pipelines/default/prompts/roles/orchestrator.md",
    ):
        new_path = _map_moved_path(old_path)
        old_blob = before[old_path][1]
        old_bytes = subprocess.check_output(["git", "-C", str(ROOT), "cat-file", "blob", old_blob])
        new_bytes = subprocess.check_output(
            ["git", "-C", str(ROOT), "show", f"{location_commit}:{new_path}"]
        )
        assert len(new_bytes) == len(old_bytes)
        assert new_bytes.count(b"\n") == old_bytes.count(b"\n")
        assert hashlib.sha256(new_bytes).digest() == hashlib.sha256(old_bytes).digest()
    return len(before)


def test_t3_repository_move_has_content_receipt_and_no_old_roots():
    for path in (
        ".orchestra/kb/README.md",
        ".orchestra/tasks/430/plan.md",
        ".orchestra/workers/move-dot-orchestra.md",
        ".orchestra/archive",
        ".orchestra/pipelines/default/pipeline.yaml",
    ):
        assert (ROOT / path).exists(), f"T3 missing moved path: {path}"
    for path in ("docs/kb", "docs/tasks", "docs/workers", "docs/archive", "pipelines"):
        assert not (ROOT / path).exists(), f"T3 old root remains: {path}"

    receipt_path = ROOT / ".orchestra" / "tasks" / "430" / "move-receipt.json"
    assert receipt_path.is_file(), "T3 missing per-file move preservation receipt"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert len(receipt["before_ref"]) == 40
    location_commit = receipt["location_runtime_commit"]
    assert _git(ROOT, "rev-parse", f"{location_commit}^").stdout.strip() == receipt["before_ref"]
    assert _git(
        ROOT, "merge-base", "--is-ancestor", receipt["merged_main_ref"], receipt["before_ref"],
        check=False,
    ).returncode == 0
    assert _git(ROOT, "merge-base", receipt["before_ref"], "main").stdout.strip() == receipt[
        "merged_main_ref"
    ]
    independently_checked = _assert_all_moved_files_match_before_ref(
        receipt["before_ref"], location_commit
    )
    verifier = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_orchestra_move.py"),
            "--root", str(ROOT),
            "--before-ref", receipt["before_ref"],
            "--after-ref", location_commit,
            "--json",
        ],
        text=True,
        capture_output=True,
    )
    assert verifier.returncode == 0, verifier.stdout + verifier.stderr
    live_receipt = json.loads(verifier.stdout)
    assert live_receipt["mismatches"] == []
    assert receipt["mismatches"] == []
    assert receipt["checked_files"] == live_receipt["checked_files"] == independently_checked
    assert receipt["fields"] == ["mode", "lines", "bytes", "sha256"]
    assert (
        ROOT / ".orchestra/pipelines/default/prompts/roles/orchestrator.md"
    ).read_text(encoding="utf-8").count("artifact-reading") == 2


def test_t4_all_fleet_receipts_precede_global_prompt_activation():
    from app.pipeline import DEFAULT_PIPELINE, build_system_prompt, known_roles

    prompts = {
        role: build_system_prompt(DEFAULT_PIPELINE, role)
        for role in known_roles(DEFAULT_PIPELINE)
    }
    assert prompts
    for role, prompt in prompts.items():
        assert ".orchestra/kb" in prompt, role
        assert ".orchestra/tasks" in prompt, role
        assert ".orchestra/workers" in prompt, role
        assert "docs/kb" not in prompt, role
        assert "docs/tasks" not in prompt, role
        assert "docs/workers" not in prompt, role
    memory_prompt = (ROOT / ".orchestra/pipelines/default/prompts/modules/memory-search.md").read_text(
        encoding="utf-8"
    )
    for anchor in (
        "ORCHESTRA_LAYOUT_MISSING",
        "ORCHESTRA_LAYOUT_PARTIAL",
        "scripts/migrate_orchestra_layout.py",
        "--repair",
        "Never fall back",
    ):
        assert anchor in memory_prompt

    fleet = json.loads(
        (ROOT / ".orchestra/tasks/430/fleet-run/final-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert fleet["projects"] == fleet["current"] == fleet["status_preserved"] == 13
    assert fleet["failed"] == fleet["preserve_journals"] == fleet["preserve_stashes"] == 0
    release = json.loads(
        (ROOT / ".orchestra/tasks/430/release-receipt.json").read_text(encoding="utf-8")
    )
    assert release["fleet_receipt_commit"] != release["prompt_activation_commit"]
    assert _git(
        ROOT,
        "merge-base",
        "--is-ancestor",
        release["fleet_receipt_commit"],
        release["prompt_activation_commit"],
        check=False,
    ).returncode == 0


def test_t2_dead_docker_and_stale_frontend_links_are_gone():
    assert not (ROOT / "Dockerfile").exists()
    assert not (ROOT / "docker-compose.yml").exists()
    assert not (ROOT / "docs" / "portfolio").exists()
    bootstrap = (ROOT / "app" / "bootstrap.py").read_text(encoding="utf-8")
    assert "Dockerfile" not in bootstrap
    assert "docker-compose" not in bootstrap
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/portfolio" not in readme
    for relative in (
        "app/static/js/app.js",
        "app/static/js/chat.js",
        "app/templates/dashboard.html",
    ):
        assert "docs/tasks/" not in (ROOT / relative).read_text(encoding="utf-8")


def test_t3_docs_contains_only_external_reader_artifacts():
    observed = {
        path.relative_to(ROOT / "docs").as_posix()
        for path in (ROOT / "docs").rglob("*")
        if path.is_file()
    }
    assert observed == FINAL_DOC_FILES
    for image in ("banner.png", "dashboard.png"):
        assert f"docs/{image}" in (ROOT / "README.md").read_text(encoding="utf-8")


def _assert_all_historical_evidence_bindings() -> tuple[int, str]:
    required = {"stable_id", "git_commit", "source_path", "git_blob", "source_sha256"}
    records = []
    for record_path in sorted((ROOT / ".orchestra/kb/records").rglob("*.json")):
        value = json.loads(record_path.read_text(encoding="utf-8"))
        if required <= set(value):
            records.append({key: str(value[key]) for key in sorted(required)})
    assert len(records) >= 12_759
    frozen_bytes = (
        ROOT / ".orchestra/tasks/430/evidence-bindings-frozen.json"
    ).read_bytes()
    assert hashlib.sha256(frozen_bytes).hexdigest() == FROZEN_EVIDENCE_MANIFEST_SHA256
    frozen = json.loads(frozen_bytes)
    assert frozen["schema_version"] == 1
    assert frozen["count"] == len(frozen["bindings"]) == 12_759
    current_binding_hashes = {}
    for record in records:
        stable_id = record["stable_id"]
        current_binding_hashes[stable_id] = hashlib.sha256(
            json.dumps(
                record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    for stable_id, expected_hash in frozen["bindings"].items():
        assert current_binding_hashes.get(stable_id) == expected_hash, stable_id

    by_commit = defaultdict(list)
    for record in records:
        by_commit[record["git_commit"]].append(record)
    for commit, commit_records in by_commit.items():
        raw = subprocess.check_output(
            [
                "git", "-C", str(ROOT), "ls-tree", "-r", "-z",
                "--format=%(objectname)%x09%(path)", commit,
            ]
        )
        tree = {}
        for item in raw.split(b"\0"):
            if item:
                blob, path = item.split(b"\t", 1)
                tree[path.decode()] = blob.decode()
        for record in commit_records:
            assert tree.get(record["source_path"]) == record["git_blob"], record["stable_id"]

    blobs = sorted({record["git_blob"] for record in records})
    batch = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "--batch"],
        input=b"".join(blob.encode() + b"\n" for blob in blobs),
        capture_output=True,
        check=True,
    ).stdout
    contents = {}
    offset = 0
    for expected in blobs:
        header_end = batch.index(b"\n", offset)
        blob, object_type, raw_size = batch[offset:header_end].decode().split()
        assert (blob, object_type) == (expected, "blob")
        size = int(raw_size)
        start = header_end + 1
        end = start + size
        assert batch[end:end + 1] == b"\n"
        contents[blob] = batch[start:end]
        offset = end + 1
    assert offset == len(batch)
    for record in records:
        digest = "sha256:" + hashlib.sha256(contents[record["git_blob"]]).hexdigest()
        assert digest == record["source_sha256"], record["stable_id"]

    return frozen["count"], frozen["binding_set_sha256"]


def test_t5_classified_path_audit_is_clean_and_historical_evidence_resolves():
    checker = ROOT / "scripts" / "check_orchestra_paths.py"
    assert checker.is_file(), "T5 missing classified live/historical/negative path checker"
    result = subprocess.run(
        [sys.executable, str(checker), "--root", str(ROOT), "--json"],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout)
    checked, binding_set = _assert_all_historical_evidence_bindings()
    assert summary["live_old_path_occurrences"] == 0
    assert summary["historical_path_blob_sha_checked"] == checked
    assert summary["historical_binding_set_sha256"] == binding_set
    assert summary["historical_path_blob_sha_mismatches"] == 0
    assert summary["negative_guard_occurrences"] > 0
    assert summary["deferred_prompt_occurrences"] == 0
    assert summary["unclassified_old_path_occurrences"] == 0
