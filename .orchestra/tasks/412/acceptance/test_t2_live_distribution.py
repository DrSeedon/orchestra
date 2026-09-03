"""Independent, read-only delivery oracle for the live #412 distribution."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
MANIFEST = ROOT / "docs/tasks/412/distribution-manifest.json"
GIT_COMMAND_LOG = ROOT / "docs/tasks/412/git-command-log.jsonl"
EXPECTED = {
    "orchestra": (12_759, Path("/mnt/data/Projects/Python/orchestra")),
    "cog-second-brain-77dd306ac2a0": (5_106, Path("/home/maxim/Рабочий стол/Cursor/COG-second-brain")),
    "scope-mnt-data-projects-comfy-image-pipeline-11e5d3b4b1f9": (1_728, Path("/mnt/data/Projects/comfy-image-pipeline")),
    "seedon": (321, Path("/mnt/data/Projects/Python/seedon")),
    "sensar-5e197e867bb2": (180, Path("/home/maxim/Рабочий стол/Cursor/Sensar")),
    "tradingcryptobot": (177, Path("/mnt/data/Projects/Python/TradingCryptoBot")),
    "mnt-data-projects-python-claude-code-game-master-ccdad4e9b586": (152, Path("/mnt/data/Projects/Python/Claude-Code-Game-Master")),
    "mnt-data-projects-python-aperant-0972b1340a75": (112, Path("/mnt/data/Projects/Python/Aperant")),
    "kesha-tg-bot": (96, Path("/mnt/data/Projects/Python/kesha-tg-bot")),
    "polus": (86, Path("/home/maxim/polus")),
    "university": (77, Path("/mnt/data/Projects/University")),
    "vpn-service-7c16d6f598b1": (75, Path("/mnt/data/Projects/Python/VPN-Service")),
    "parsing-hub": (43, Path("/mnt/data/Projects/Python/Parsing")),
    "stargate-tactics": (12, Path("/mnt/data/Projects/Python/stargate-tactics")),
    "mnt-data-projects-unity-defaultprojectunity-317002a674e4": (10, Path("/mnt/data/Projects/Unity/DefaultProjectUnity")),
    "mnt-data-projects-python-games-b14eae05bed5": (9, Path("/mnt/data/Projects/Python/games")),
    "webview-c212de852078": (5, Path("/mnt/data/Projects/Python/WebView")),
    "mnt-data-media-30494f74a194": (0, Path("/mnt/data/media")),
}


def _run(*args: str, cwd: Path | None = None, text: bool = True):
    return subprocess.run(
        list(args), cwd=cwd, check=True, capture_output=True, text=text
    ).stdout


def _git(root: Path, *args: str) -> str:
    return _run("git", "-C", str(root), *args).strip()


def _git_bytes(root: Path, *args: str) -> bytes:
    return _run("git", "-C", str(root), *args, text=False)


def _records_digest(records: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for stable_id, payload in sorted(records.items()):
        digest.update(stable_id.encode())
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _source_records(central: Path, source_head: str, project_id: str) -> dict[str, bytes]:
    prefix = f"evidence/{project_id}/"
    raw = _git_bytes(
        central,
        "ls-tree",
        "-r",
        "-z",
        "--name-only",
        source_head,
        "--",
        prefix,
    )
    paths = [item.decode() for item in raw.split(b"\0") if item]
    records = {}
    for path in paths:
        stable_id = Path(path).stem
        records[stable_id] = _git_bytes(central, "show", f"{source_head}:{path}")
    return records


def _manifest_records(root: Path, project_manifest: dict) -> dict[str, bytes]:
    records = {}
    for row in project_manifest["records"]:
        relative = row["destination_relative_path"]
        payload = (root / relative).read_bytes()
        assert len(payload) == row["size"]
        assert hashlib.sha256(payload).hexdigest() == row["sha256"]
        assert Path(relative).parts[:2] == ("docs", "kb")
        records[row["stable_id"]] = payload
    return records


def _assert_no_git_mutation(project: dict) -> None:
    assert project["local_refs_sha256_before"] == project["local_refs_sha256_after"]
    assert project["before_head"] == project["target_commit"]
    assert project["index_sha256_before"] == project["index_sha256_after"]
    assert project["local_config_sha256_before"] == project["local_config_sha256_after"]
    assert project["foreign_snapshot_before"] == project["foreign_snapshot_after"]
    forbidden = {
        "add", "checkout", "clean", "commit", "fetch", "hash-object", "merge",
        "pull", "push", "read-tree", "rebase", "remote", "reset", "stash",
        "switch", "update-index",
    }
    assert not forbidden.intersection(project["git_subcommands"])


def test_t2_live_distribution_matches_frozen_manifest(tmp_path: Path):
    from app.ia.runtime import production_runtime_config

    config = production_runtime_config()
    state_root = Path(config.state_root)
    central = state_root / "canonical"
    assert MANIFEST.is_file(), "T2 distribution manifest missing"
    assert GIT_COMMAND_LOG.is_file(), "T2 external Git command log missing"
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    git_commands = [
        json.loads(line) for line in GIT_COMMAND_LOG.read_text(encoding="utf-8").splitlines()
    ]
    assert git_commands
    assert {item["run_id"] for item in git_commands} == {manifest["run_id"]}
    forbidden = {
        "add", "checkout", "clean", "commit", "fetch", "hash-object", "merge",
        "pull", "push", "read-tree", "rebase", "remote", "reset", "stash",
        "switch", "update-index",
    }
    assert not forbidden.intersection(
        item["subcommand"] for item in git_commands
    )
    assert manifest["schema_version"] == 1
    assert manifest["status"] == "verified"
    assert "records" not in manifest, "T2 global receipt must not retain foreign record details"
    assert manifest["total_record_count"] == 20_948
    assert manifest["quarantine_count"] == 0
    assert Path(manifest["source_state_root"]).resolve() == state_root.resolve()
    assert _git(central, "rev-parse", "HEAD") == manifest["source_head"]
    assert hashlib.sha256((state_root / "scope-registry.json").read_bytes()).hexdigest() == manifest["scope_registry_sha256"]

    projects = manifest["projects"]
    assert len(projects) == len({item["project_id"] for item in projects}) == 18
    actual_mapping = {
        item["project_id"]: (
            item["record_count"], Path(item["repository_root"]).resolve()
        )
        for item in projects
    }
    assert actual_mapping == {
        project_id: (count, path.resolve())
        for project_id, (count, path) in EXPECTED.items()
    }
    assert sum(item["record_count"] for item in projects) == 20_948

    all_stable_ids = set()
    for project in projects:
        project_id = project["project_id"]
        repo = Path(project["repository_root"])
        assert project["manifest_relative_path"] == "docs/kb/manifest.json"
        _assert_no_git_mutation(project)

        manifest_blob = (repo / project["manifest_relative_path"]).read_bytes()
        project_manifest = json.loads(manifest_blob)
        assert project_manifest["project_id"] == project_id
        assert len(project_manifest["records"]) == project["record_count"]

        source_records = _source_records(central, manifest["source_head"], project_id)
        target_records = _manifest_records(repo, project_manifest)
        assert source_records == target_records
        independent_digest = _records_digest(source_records)
        assert independent_digest == project_manifest["records_sha256"] == project["records_sha256"]
        assert all_stable_ids.isdisjoint(source_records)
        all_stable_ids.update(source_records)

        assert (repo / "docs/kb/.gitattributes").is_file()
        assert (repo / "docs/kb/manifest.json").is_file()
        assert project["target_dirty_outside_docs_kb"] == 0
    assert len(all_stable_ids) == 20_948

    aperant = next(
        item for item in projects
        if item["project_id"] == "mnt-data-projects-python-aperant-0972b1340a75"
    )
    assert aperant["force_add"] is True
    assert all(
        item["force_add"] is False
        for item in projects
        if item["project_id"] != aperant["project_id"]
    )
    assert aperant["target_dirty_path_count"] == 0
    assert not any(item["subcommand"] in {"add", "update-index"} for item in git_commands)
    assert manifest["external_owner_events"] == [
        {
            "project_id": "cog-second-brain-77dd306ac2a0",
            "before_head": "db096da109f5af6349e54fa17890c6c5c6150303",
            "after_head": "20707ebb0172ea323805f7131e8098dfb1362bd2",
            "commit_subject": "auto-sync 2026-08-28 12:25",
            "content_parity": True,
            "actor": "project-owned cron",
        }
    ]
