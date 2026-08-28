"""Regression oracles for blocking findings from the T1 Luna review (#412)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.ia import project_distribution as distribution


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repo(root: Path, *, remote: Path | None = None) -> str:
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "seed")
    if remote is not None:
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        _git(root, "remote", "add", "origin", str(remote))
        _git(root, "push", "-q", "-u", "origin", "main")
    return _git(root, "rev-parse", "HEAD")


def _payload(project_id: str, stable_id: str) -> bytes:
    return json.dumps(
        {
            "project_id": project_id,
            "stable_id": stable_id,
            "record_type": "resource",
            "status": "current",
        },
        sort_keys=True,
    ).encode() + b"\n"


def _fixture(tmp_path: Path, projects: tuple[str, ...]):
    central = tmp_path / "central"
    quarantine = tmp_path / "quarantine"
    _repo(central)
    _repo(quarantine)
    repos = {}
    entries = []
    for index, project_id in enumerate(projects, start=1):
        repo = tmp_path / project_id
        _repo(repo)
        repos[project_id] = repo
        entries.append(
            {"canonical_project_id": project_id, "repository_root": str(repo)}
        )
        stable_id = f"00000000-0000-4000-8000-{index:012d}"
        path = central / f"evidence/{project_id}/{stable_id}.json"
        path.parent.mkdir(parents=True)
        path.write_bytes(_payload(project_id, stable_id))
    if projects:
        _git(central, "add", "evidence")
        _git(central, "commit", "-qm", "records")
    registry = tmp_path / "scope-registry.json"
    registry.write_text(
        json.dumps({"schema_version": 1, "entries": entries}), encoding="utf-8"
    )
    return central, quarantine, repos, registry, _git(central, "rev-parse", "HEAD")


def _run(central: Path, quarantine: Path, registry: Path, head: str, **kwargs):
    return distribution.distribute_project_knowledge(
        canonical_root=central,
        scope_registry_path=registry,
        quarantine_root=quarantine,
        expected_source_head=head,
        apply=kwargs.pop("apply", False),
        commit=kwargs.pop("commit", False),
        **kwargs,
    )


def test_review_t1_rejects_symlinked_quarantine_project(tmp_path: Path):
    central, quarantine, _repos, registry, _head = _fixture(tmp_path, ())
    stable_id = "00000000-0000-4000-8000-000000000009"
    path = central / f"evidence/orphan/{stable_id}.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(_payload("orphan", stable_id))
    _git(central, "add", "evidence")
    _git(central, "commit", "-qm", "orphan")
    outside = tmp_path / "outside"
    outside.mkdir()
    (quarantine / "orphan").symlink_to(outside, target_is_directory=True)
    _git(quarantine, "add", "orphan")
    _git(quarantine, "commit", "-qm", "committed symlink")
    with pytest.raises(distribution.DistributionError, match="quarantine.*escape|symlink"):
        _run(central, quarantine, registry, _git(central, "rev-parse", "HEAD"))


def test_review_t1_rejects_symlinked_manifest_parent_for_zero_record_project(
    tmp_path: Path,
):
    central, quarantine, repos, registry, head = _fixture(tmp_path, ("empty",))
    evidence = central / "evidence/empty"
    for path in evidence.glob("*.json"):
        path.unlink()
    _git(central, "rm", "-qr", "evidence/empty")
    _git(central, "commit", "-qm", "zero records")
    outside = tmp_path / "outside"
    outside.mkdir()
    (repos["empty"] / "docs").symlink_to(outside, target_is_directory=True)
    _git(repos["empty"], "add", "docs")
    _git(repos["empty"], "commit", "-qm", "committed symlink")
    with pytest.raises(distribution.DistributionError, match="manifest.*escape|symlink"):
        _run(central, quarantine, registry, _git(central, "rev-parse", "HEAD"))


def test_review_t1_does_not_overwrite_file_created_after_preflight(
    tmp_path: Path, monkeypatch
):
    central, quarantine, repos, registry, head = _fixture(tmp_path, ("a",))
    original = distribution._project_plan

    def race(*args, **kwargs):
        plan = original(*args, **kwargs)
        row = plan["manifest"]["records"][0]
        destination = repos["a"] / row["destination_relative_path"]
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"concurrent\n")
        return plan

    monkeypatch.setattr(distribution, "_project_plan", race)
    with pytest.raises(distribution.DistributionError, match="conflict|concurrent"):
        _run(central, quarantine, registry, head, apply=True, commit=True)
    assert next((repos["a"] / "docs/kb/records/evidence").glob("*.json")).read_bytes() == b"concurrent\n"


def test_review_t1_refuses_destination_ref_drift(tmp_path: Path, monkeypatch):
    central, quarantine, repos, registry, head = _fixture(tmp_path, ("a",))
    original = distribution._project_plan

    def drift(*args, **kwargs):
        plan = original(*args, **kwargs)
        _git(repos["a"], "commit", "--allow-empty", "-qm", "concurrent")
        return plan

    monkeypatch.setattr(distribution, "_project_plan", drift)
    with pytest.raises(distribution.DistributionError, match="ref drift|HEAD drift"):
        _run(central, quarantine, registry, head, apply=True, commit=True)
    assert not (repos["a"] / "docs/kb").exists()


def test_review_t1_reports_partial_commit_if_later_repo_fails(
    tmp_path: Path, monkeypatch
):
    central, quarantine, repos, registry, head = _fixture(tmp_path, ("a", "b"))
    original = distribution._materialize_group

    def fail_second(plans, **kwargs):
        if plans[0]["project_id"] == "b":
            raise distribution.DistributionError("second repository failed")
        return original(plans, **kwargs)

    monkeypatch.setattr(distribution, "_materialize_group", fail_second)
    with pytest.raises(distribution.PartialDistributionError) as caught:
        _run(central, quarantine, registry, head, apply=True, commit=True)
    assert caught.value.partial_result["committed_projects"] == ["a"]
    assert _git(repos["a"], "log", "-1", "--format=%s").startswith("#412:")
    assert _git(repos["b"], "log", "-1", "--format=%s") == "seed"


def test_review_t1_rejects_non_uuid_evidence_filename(tmp_path: Path):
    central, quarantine, _repos, registry, _head = _fixture(tmp_path, ())
    path = central / "evidence/orphan/bad\nname.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(_payload("orphan", "bad\nname"))
    _git(central, "add", "evidence")
    _git(central, "commit", "-qm", "bad name")
    with pytest.raises(distribution.DistributionError, match="stable_id|filename"):
        _run(central, quarantine, registry, _git(central, "rev-parse", "HEAD"))


def test_review_t1_remote_probe_is_explicit_and_receipt_cannot_dirty_managed_repo(
    tmp_path: Path,
):
    central, quarantine, repos, registry, head = _fixture(tmp_path, ("a",))
    result = _run(central, quarantine, registry, head)
    assert "ls-remote" not in result["git_subcommands"]

    receipt = repos["a"] / "docs/kb/unsafe-receipt.json"
    command = [
        sys.executable,
        "scripts/distribute_project_knowledge.py",
        "--canonical-root",
        str(central),
        "--scope-registry",
        str(registry),
        "--quarantine-root",
        str(quarantine),
        "--expected-source-head",
        head,
        "--dry-run",
        "--receipt-path",
        str(receipt),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    assert completed.returncode == 2
    assert "receipt" in completed.stderr
    assert not receipt.exists()


def test_review_t1_multiple_orphans_share_one_quarantine_commit(tmp_path: Path):
    central, quarantine, _repos, registry, _head = _fixture(tmp_path, ())
    for index, project_id in enumerate(("orphan-a", "orphan-b"), start=1):
        stable_id = f"00000000-0000-4000-8000-{index + 20:012d}"
        path = central / f"evidence/{project_id}/{stable_id}.json"
        path.parent.mkdir(parents=True)
        path.write_bytes(_payload(project_id, stable_id))
    _git(central, "add", "evidence")
    _git(central, "commit", "-qm", "two orphans")
    result = _run(
        central,
        quarantine,
        registry,
        _git(central, "rev-parse", "HEAD"),
        apply=True,
        commit=True,
    )
    assert result["quarantine_count"] == 2
    assert {item["project_id"] for item in result["projects"]} == {
        "orphan-a",
        "orphan-b",
    }
    assert _git(quarantine, "rev-list", "--count", "HEAD") == "2"
    assert (quarantine / "orphan-a/docs/kb/manifest.json").is_file()
    assert (quarantine / "orphan-b/docs/kb/manifest.json").is_file()


def test_review_t1_forces_noninteractive_remote_probe(
    tmp_path: Path, monkeypatch
):
    remote = tmp_path / "remote.git"
    central, quarantine, repos, registry, head = _fixture(tmp_path, ("a",))
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(repos["a"], "remote", "add", "origin", str(remote))
    _git(repos["a"], "push", "-q", "-u", "origin", "main")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "1")
    original = distribution.subprocess.run

    def inspect(*args, **kwargs):
        command = args[0]
        if "ls-remote" in command:
            assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
            assert "-oBatchMode=yes" in kwargs["env"]["GIT_SSH_COMMAND"]
            assert "-oStrictHostKeyChecking=yes" in kwargs["env"]["GIT_SSH_COMMAND"]
        return original(*args, **kwargs)

    monkeypatch.setattr(distribution.subprocess, "run", inspect)
    result = distribution.distribute_project_knowledge(
        canonical_root=central,
        scope_registry_path=registry,
        quarantine_root=quarantine,
        expected_source_head=head,
        apply=False,
        commit=False,
        probe_remotes=True,
    )
    assert result["projects"][0]["remote_refs_before"]


def test_review_t1_post_apply_snapshot_failure_is_partial(
    tmp_path: Path, monkeypatch
):
    central, quarantine, repos, registry, head = _fixture(tmp_path, ("a",))

    def fail(*args, **kwargs):
        raise distribution.DistributionError("post-apply snapshot failed")

    monkeypatch.setattr(distribution, "_public_project", fail)
    with pytest.raises(distribution.PartialDistributionError) as caught:
        _run(central, quarantine, registry, head, apply=True, commit=True)
    assert caught.value.partial_result["committed_projects"] == ["a"]
    assert _git(repos["a"], "log", "-1", "--format=%s").startswith("#412:")


def test_review_t1_detects_hook_side_ref_and_config_mutation(tmp_path: Path):
    central, quarantine, repos, registry, head = _fixture(tmp_path, ("a",))
    marker = tmp_path / "hook-ran"
    hook = repos["a"] / ".git/hooks/pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        "git update-ref refs/heads/side HEAD\n"
        "git config review.changed yes\n"
        f"touch {marker}\n",
        encoding="utf-8",
    )
    hook.chmod(0o700)
    _run(central, quarantine, registry, head, apply=True, commit=True)
    assert not marker.exists()
    assert subprocess.run(
        [
            "git",
            "-C",
            str(repos["a"]),
            "show-ref",
            "--verify",
            "--quiet",
            "refs/heads/side",
        ]
    ).returncode == 1
    assert subprocess.run(
        ["git", "-C", str(repos["a"]), "config", "--get", "review.changed"],
        capture_output=True,
        text=True,
    ).returncode == 1


def test_review_t1_receipt_conflict_fails_before_any_commit(tmp_path: Path):
    central, quarantine, repos, registry, head = _fixture(tmp_path, ("a",))
    base = _git(repos["a"], "rev-parse", "HEAD")
    receipt = tmp_path / "receipt.json"
    receipt.write_text("occupied\n", encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/distribute_project_knowledge.py",
            "--canonical-root",
            str(central),
            "--scope-registry",
            str(registry),
            "--quarantine-root",
            str(quarantine),
            "--expected-source-head",
            head,
            "--apply",
            "--commit",
            "--receipt-path",
            str(receipt),
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert _git(repos["a"], "rev-parse", "HEAD") == base


def test_review_t1_commits_raw_bytes_despite_clean_filter(tmp_path: Path):
    central, quarantine, repos, registry, head = _fixture(tmp_path, ("a",))
    repo = repos["a"]
    (repo / ".gitattributes").write_text(
        "docs/kb/records/evidence/*.json filter=mutate\n", encoding="utf-8"
    )
    _git(repo, "config", "filter.mutate.clean", "sed s/current/mutated/g")
    _git(repo, "config", "filter.mutate.smudge", "cat")
    _git(repo, "add", ".gitattributes")
    _git(repo, "commit", "-qm", "filter")
    result = _run(central, quarantine, registry, head, apply=True, commit=True)
    project = result["projects"][0]
    row = next(
        item for item in result["records"] if item["project_id"] == "a"
    )
    committed = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "show",
            f"{project['target_commit']}:{row['destination_relative_path']}",
        ],
        check=True,
        capture_output=True,
    ).stdout
    source = subprocess.run(
        ["git", "-C", str(central), "show", f"{head}:{row['source_relative_path']}"],
        check=True,
        capture_output=True,
    ).stdout
    assert committed == source


def test_review_t1_receipt_io_error_reports_partial_after_commit(tmp_path: Path):
    central, quarantine, repos, registry, head = _fixture(tmp_path, ("a",))
    base = _git(repos["a"], "rev-parse", "HEAD")
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/distribute_project_knowledge.py",
            "--canonical-root",
            str(central),
            "--scope-registry",
            str(registry),
            "--quarantine-root",
            str(quarantine),
            "--expected-source-head",
            head,
            "--apply",
            "--commit",
            "--receipt-path",
            "/proc/orchestra-412-receipt.json",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 3
    partial = json.loads(completed.stderr.splitlines()[-1])
    assert partial["status"] == "partial"
    assert partial["committed_projects"] == ["a"]
    assert _git(repos["a"], "rev-parse", "HEAD") != base


def test_t2_registry_drift_before_first_write_is_refused(tmp_path: Path, monkeypatch):
    central, quarantine, repos, registry, head = _fixture(tmp_path, ("a",))
    original = distribution._source_records

    def drift(*args, **kwargs):
        records = original(*args, **kwargs)
        registry.write_bytes(registry.read_bytes() + b"\n")
        return records

    monkeypatch.setattr(distribution, "_source_records", drift)
    with pytest.raises(distribution.DistributionError, match="scope registry drift"):
        _run(central, quarantine, registry, head, apply=True, commit=False)
    assert not (repos["a"] / "docs/kb").exists()
