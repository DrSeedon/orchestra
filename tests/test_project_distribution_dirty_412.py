"""Frozen dirty-worktree safety oracle approved during live T2 preflight (#412)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from app.ia import project_distribution as distribution


def _git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if check:
        assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _repo(root: Path) -> None:
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    for name in ("staged.txt", "unstaged.txt", "deleted.txt"):
        (root / name).write_text(f"base-{name}\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "seed")


def _snapshot(root: Path) -> dict:
    pathspec = ["--", ".", ":(exclude)docs/kb/**"]
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all", *pathspec],
        check=True,
        capture_output=True,
    ).stdout
    index = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--stage", "-z", *pathspec],
        check=True,
        capture_output=True,
    ).stdout
    tokens = [item for item in status.split(b"\0") if item]
    paths = []
    position = 0
    while position < len(tokens):
        item = tokens[position]
        code = item[:2]
        paths.append(os.fsdecode(item[3:]))
        position += 1
        if b"R" in code or b"C" in code:
            paths.append(os.fsdecode(tokens[position]))
            position += 1
    content = hashlib.sha256()
    for relative in sorted(set(paths)):
        path = root / relative
        content.update(os.fsencode(relative) + b"\0")
        content.update(
            hashlib.sha256(path.read_bytes()).digest() if path.is_file() else b"missing"
        )
    return {
        "status": status,
        "index": index,
        "content": content.digest(),
    }


def _central(root: Path, project_id: str) -> tuple[Path, str, str]:
    central = root / "central"
    _repo(central)
    stable_id = "00000000-0000-4000-8000-000000000777"
    record = {
        "project_id": project_id,
        "stable_id": stable_id,
        "record_type": "resource",
        "status": "current",
    }
    path = central / f"evidence/{project_id}/{stable_id}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    _git(central, "add", "evidence")
    _git(central, "commit", "-qm", "record")
    return central, _git(central, "rev-parse", "HEAD"), stable_id


def test_t2_dirty_foreign_worktree_and_index_are_byte_identical_after_commit(
    tmp_path: Path,
):
    project_id = "aperant"
    repo = tmp_path / "project"
    quarantine = tmp_path / "quarantine"
    _repo(repo)
    _repo(quarantine)
    central, head, _stable_id = _central(tmp_path, project_id)
    (repo / "staged.txt").write_text("staged-work\n", encoding="utf-8")
    _git(repo, "add", "staged.txt")
    (repo / "unstaged.txt").write_text("unstaged-work\n", encoding="utf-8")
    (repo / "deleted.txt").unlink()
    (repo / "untracked.bin").write_bytes(b"untracked\x00bytes")
    (repo / ".gitignore").write_text("docs/\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-qm", "ignore docs")
    # Recreate staged work after the setup commit.
    (repo / "staged.txt").write_text("staged-work-2\n", encoding="utf-8")
    _git(repo, "add", "staged.txt")
    before = _snapshot(repo)
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "canonical_project_id": project_id,
                        "repository_root": str(repo),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = distribution.distribute_project_knowledge(
        canonical_root=central,
        scope_registry_path=registry,
        quarantine_root=quarantine,
        expected_source_head=head,
        apply=True,
        commit=True,
    )
    assert _snapshot(repo) == before
    assert result["projects"][0]["force_add"] is True
    changed = _git(
        repo,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        result["projects"][0]["target_commit"],
    ).splitlines()
    assert changed and all(path.startswith("docs/kb/") for path in changed)
    assert not any(
        command in result["git_subcommands"]
        for command in ("stash", "clean", "reset", "checkout", "push")
    )


def test_t2_failure_preserves_dirty_foreign_snapshot(tmp_path: Path, monkeypatch):
    project_id = "dirty"
    repo = tmp_path / "project"
    quarantine = tmp_path / "quarantine"
    _repo(repo)
    _repo(quarantine)
    central, head, _stable_id = _central(tmp_path, project_id)
    (repo / "unstaged.txt").write_text("foreign-work\n", encoding="utf-8")
    before = _snapshot(repo)
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {"canonical_project_id": project_id, "repository_root": str(repo)}
                ],
            }
        ),
        encoding="utf-8",
    )

    original = distribution._materialize_group

    def fail_after_write(plans, **kwargs):
        original(plans, commit=False, **kwargs)
        raise distribution.DistributionError("interrupted")

    monkeypatch.setattr(distribution, "_materialize_group", fail_after_write)
    with pytest.raises(distribution.PartialDistributionError):
        distribution.distribute_project_knowledge(
            canonical_root=central,
            scope_registry_path=registry,
            quarantine_root=quarantine,
            expected_source_head=head,
            apply=True,
            commit=True,
        )
    assert _snapshot(repo) == before


def _dirty_fixture(tmp_path: Path, project_id: str = "dirty"):
    repo = tmp_path / "project"
    quarantine = tmp_path / "quarantine"
    _repo(repo)
    _repo(quarantine)
    central, head, stable_id = _central(tmp_path, project_id)
    (repo / "unstaged.txt").write_text("foreign-work\n", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {"canonical_project_id": project_id, "repository_root": str(repo)}
                ],
            }
        ),
        encoding="utf-8",
    )
    return repo, quarantine, central, registry, head, stable_id


def test_t2_uncommitted_mode_is_independently_verified_without_foreign_changes(
    tmp_path: Path,
):
    repo, quarantine, central, registry, head, stable_id = _dirty_fixture(tmp_path)
    before = _snapshot(repo)
    before_head = _git(repo, "rev-parse", "HEAD")

    applied = distribution.distribute_project_knowledge(
        canonical_root=central,
        scope_registry_path=registry,
        quarantine_root=quarantine,
        expected_source_head=head,
        apply=True,
        commit=False,
    )

    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert _snapshot(repo) == before
    assert (repo / f"docs/kb/records/evidence/{stable_id}.json").is_file()
    assert "commit" not in applied["git_subcommands"]
    verified = distribution.verify_project_knowledge_distribution(
        canonical_root=central,
        scope_registry_path=registry,
        quarantine_root=quarantine,
        expected_source_head=head,
    )
    assert verified["status"] == "verified"
    assert verified["projects"][0]["target_commit"] == before_head
    assert _snapshot(repo) == before


def test_t2_uncommitted_mode_resumes_idempotently_after_files_exist(tmp_path: Path):
    repo, quarantine, central, registry, head, stable_id = _dirty_fixture(tmp_path)
    before = _snapshot(repo)
    kwargs = {
        "canonical_root": central,
        "scope_registry_path": registry,
        "quarantine_root": quarantine,
        "expected_source_head": head,
        "apply": True,
        "commit": False,
    }

    first = distribution.distribute_project_knowledge(**kwargs)
    record = repo / f"docs/kb/records/evidence/{stable_id}.json"
    first_payload = record.read_bytes()
    second = distribution.distribute_project_knowledge(**kwargs)

    assert second["total_record_count"] == first["total_record_count"] == 1
    assert record.read_bytes() == first_payload
    assert _snapshot(repo) == before
    assert _git(repo, "rev-parse", "HEAD") == first["projects"][0]["before_head"]


def test_t2_matching_external_owner_commit_is_recorded_not_treated_as_ours(
    tmp_path: Path, monkeypatch
):
    repo, quarantine, central, registry, head, stable_id = _dirty_fixture(tmp_path)
    original = distribution._materialize_group

    def owner_auto_sync(plans, *, commit, commands):
        assert commit is False
        original(plans, commit=False, commands=commands)
        _git(repo, "add", "docs/kb")
        _git(repo, "commit", "-qm", "owner auto-sync")

    monkeypatch.setattr(distribution, "_materialize_group", owner_auto_sync)
    result = distribution.distribute_project_knowledge(
        canonical_root=central,
        scope_registry_path=registry,
        quarantine_root=quarantine,
        expected_source_head=head,
        apply=True,
        commit=False,
    )
    project = result["projects"][0]

    assert project["external_owner_commit"] is True
    assert project["before_head"] != project["target_commit"]
    assert project["index_sha256_before"] != project["index_sha256_after"]
    assert (repo / f"docs/kb/records/evidence/{stable_id}.json").is_file()
    assert _snapshot(repo)["status"] == b" M unstaged.txt\0"
