from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import orchestra_backup as backup


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _task_repo(root: Path, name: str) -> tuple[Path, Path]:
    repo = root / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "backup-test")
    _git(repo, "config", "user.email", "backup-test@example.invalid")
    (repo / "task.json").write_text('{"id":"V-1"}\n', encoding="utf-8")
    _git(repo, "add", "task.json")
    _git(repo, "commit", "-qm", "initial task")
    remote = root / f"{name}.git"
    _git(root, "init", "--bare", "-q", str(remote))
    _git(repo, "remote", "add", "backup", str(remote))
    return repo, remote


def test_task_store_push_scans_new_history_before_advancing_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    repo, remote = _task_repo(tmp_path, "tasks")
    monkeypatch.setattr(backup, "TASK_REMOTE_URL", str(remote))

    backup._scan_and_push_tasks(repo)
    safe_sha = _git(remote, "rev-parse", "refs/heads/main")
    secret = "github" + "_pat_" + "A" * 72
    (repo / "secret.json").write_text(json.dumps({"value": secret}), encoding="utf-8")
    _git(repo, "add", "secret.json")
    _git(repo, "commit", "-qm", "new record")

    with pytest.raises(RuntimeError, match="secret scan rejected push"):
        backup._scan_and_push_tasks(repo)

    assert _git(remote, "rev-parse", "refs/heads/main") == safe_sha


def test_daily_sqlite_backup_restores_and_matches_all_table_counts(tmp_path: Path):
    source = tmp_path / "source.db"
    connection = sqlite3.connect(source)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE sessions (id TEXT)")
    connection.execute("CREATE TABLE tm_tasks (id TEXT, status TEXT)")
    connection.executemany("INSERT INTO sessions VALUES (?)", [("s1",), ("s2",)])
    connection.executemany(
        "INSERT INTO tm_tasks VALUES (?, ?)", [("V-1", "done"), ("V-2", "new")]
    )
    connection.commit()

    archive, manifest_path = backup._make_daily_backup(source, tmp_path / "backups")
    connection.close()
    counts = backup._restore_drill(archive, manifest_path, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert counts == {"sessions": 2, "tm_tasks": 2}
    assert manifest["sqlite_integrity_check"] == "ok"
    assert manifest["sqlite_table_counts"] == counts
    assert backup._make_daily_backup(source, tmp_path / "backups") == (archive, manifest_path)
    assert not list((tmp_path / "backups").glob(".*.sqlite-wal"))
    assert not list((tmp_path / "backups").glob(".*.sqlite-shm"))


def test_laptop_upload_timeout_keeps_partial_for_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "archive.sqlite.zst"
    source.write_bytes(b"archive")
    calls = []

    def timed_out(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=124, stderr="", stdout="")

    monkeypatch.setattr(backup.subprocess, "run", timed_out)

    partial = Path("/mnt/data/orchestra-backups/archive.partial")
    assert backup._rsync_to_laptop(source, partial) is False
    assert calls[0][0:4] == ["timeout", "--signal=TERM", "--kill-after=5s", "450s"]
    assert "--partial" in calls[0]
    assert "--append-verify" in calls[0]


@pytest.mark.parametrize(
    ("previous_size", "next_size", "error", "message"),
    [
        (0, 5, backup.BackupError, "incomplete, 5 из 7 байт"),
        (7, 7, RuntimeError, "made no progress"),
    ],
)
def test_laptop_transfer_slice_requires_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    previous_size: int,
    next_size: int,
    error: type[Exception],
    message: str,
):
    archive = tmp_path / "archive.sqlite.zst"
    manifest = tmp_path / "archive.json"
    archive.write_bytes(b"archive")
    manifest.write_text("{}", encoding="utf-8")
    sizes = iter((previous_size, next_size))

    def ssh(command: str) -> str:
        if command.startswith("stat -c %s"):
            return str(next(sizes))
        if command.startswith("sha256sum"):
            raise RuntimeError("remote file missing")
        return ""

    monkeypatch.setattr(backup, "_ssh", ssh)
    monkeypatch.setattr(backup, "_sha256", lambda _path: "archive-sha")
    monkeypatch.setattr(backup, "_rsync_to_laptop", lambda *_args: False)

    with pytest.raises(error, match=message):
        backup._copy_to_laptop(archive, manifest)


def test_incomplete_laptop_upload_emits_backup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    archive = backup_dir / "orchestra-db-2026-10-08.sqlite.zst"
    manifest = backup_dir / "orchestra-db-2026-10-08.json"
    archive.write_bytes(b"x" * 1000)
    manifest.write_text("{}", encoding="utf-8")
    sizes = iter((100, 200))

    def ssh(command: str) -> str:
        if command.startswith("stat -c %s"):
            return str(next(sizes))
        if command.startswith("sha256sum"):
            raise RuntimeError("remote file missing")
        return ""

    monkeypatch.setattr(sys, "argv", ["orchestra_backup.py", "--daily"])
    monkeypatch.setattr(backup, "_service_paths", lambda: (tmp_path / "orchestra.db", tmp_path))
    monkeypatch.setattr(backup, "_make_daily_backup", lambda *_args: (archive, manifest))
    monkeypatch.setattr(backup, "_verify_archive", lambda *_args: {})
    monkeypatch.setattr(backup, "_ssh", ssh)
    monkeypatch.setattr(backup, "_sha256", lambda _path: "archive-sha")
    monkeypatch.setattr(backup, "_rsync_to_laptop", lambda *_args: False)
    monkeypatch.setattr(backup, "_laptop_tunnel_available", lambda: True)

    assert backup.main() == 1
    output = capsys.readouterr().err
    assert "BACKUP_FAILURE step=laptop" in output
    assert "incomplete, 200 из 1000 байт" in output


def _write_local_archives(db_path: Path, *dates: str) -> Path:
    directory = db_path.parent / "backups"
    directory.mkdir(parents=True)
    for day in dates:
        archive = directory / f"orchestra-db-{day}.sqlite.zst"
        archive.write_bytes(day.encode())
        backup._manifest_path(archive).write_text("{}", encoding="utf-8")
    return sorted(directory.glob("orchestra-db-????-??-??.sqlite.zst"), reverse=True)[0]


def _run_task_push(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "orchestra.db"
    monkeypatch.setattr(sys, "argv", ["orchestra_backup.py", "--push-task-store"])
    monkeypatch.setattr(backup, "_service_paths", lambda: (db_path, tmp_path / "tasks"))
    monkeypatch.setattr(backup, "_scan_and_push_tasks", lambda _repo: None)
    return db_path


def test_daily_is_silent_when_laptop_tunnel_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
):
    db_path = tmp_path / "orchestra.db"
    archive = tmp_path / "orchestra-db-2026-10-09.sqlite.zst"
    manifest = tmp_path / "orchestra-db-2026-10-09.json"
    archive.write_bytes(b"archive")
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["orchestra_backup.py", "--daily"])
    monkeypatch.setattr(backup, "_service_paths", lambda: (db_path, tmp_path / "tasks"))
    monkeypatch.setattr(backup, "_make_daily_backup", lambda *_args: (archive, manifest))
    monkeypatch.setattr(backup, "_laptop_tunnel_available", lambda: False, raising=False)
    monkeypatch.setattr(
        backup, "_copy_to_laptop", lambda *_args: pytest.fail("laptop was unreachable")
    )

    assert backup.main() == 0
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""


def test_hourly_task_push_syncs_latest_local_archive_when_laptop_has_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
):
    db_path = _run_task_push(tmp_path, monkeypatch)
    latest = _write_local_archives(db_path, "2026-10-08", "2026-10-09")
    copied: list[Path] = []
    monkeypatch.setattr(backup, "_laptop_tunnel_available", lambda: True, raising=False)
    monkeypatch.setattr(backup, "_laptop_manifest_contents", lambda *_args: None)
    monkeypatch.setattr(backup, "_verify_archive", lambda *_args: {})
    monkeypatch.setattr(backup, "_latest_laptop_backup_created_at", lambda: None, raising=False)
    monkeypatch.setattr(
        backup, "_copy_to_laptop", lambda archive, _manifest: copied.append(archive)
    )

    assert backup.main() == 0
    assert copied == [latest]
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""


def test_hourly_task_push_reports_laptop_copy_older_than_three_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
):
    db_path = _run_task_push(tmp_path, monkeypatch)
    latest = _write_local_archives(db_path, "2026-10-09")
    copied: list[Path] = []
    monkeypatch.setattr(backup, "_laptop_tunnel_available", lambda: True, raising=False)
    monkeypatch.setattr(backup, "_laptop_manifest_contents", lambda *_args: None)
    monkeypatch.setattr(backup, "_verify_archive", lambda *_args: {})
    monkeypatch.setattr(
        backup,
        "_latest_laptop_backup_created_at",
        lambda: datetime.now(timezone.utc) - timedelta(days=4),
        raising=False,
    )
    monkeypatch.setattr(
        backup, "_copy_to_laptop", lambda archive, _manifest: copied.append(archive)
    )

    assert backup.main() == 1
    assert copied == [latest]
    output = capsys.readouterr().err
    assert "BACKUP_FAILURE step=laptop" in output
    assert "older than 3 days" in output


def test_current_laptop_copy_skips_archive_integrity_and_hash_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    db_path = tmp_path / "orchestra.db"
    directory = db_path.parent / "backups"
    directory.mkdir()
    archive = directory / "orchestra-db-2026-10-09.sqlite.zst"
    archive.write_bytes(b"archive")
    manifest_path = backup._manifest_path(archive)
    manifest = json.dumps(
        {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "sha256_zstd": "archive-sha",
        },
        sort_keys=True,
        indent=2,
    ) + "\n"
    manifest_path.write_text(manifest, encoding="utf-8")
    ssh_calls: list[str] = []

    def ssh(command: str) -> str:
        ssh_calls.append(command)
        return manifest

    monkeypatch.setattr(backup, "_laptop_tunnel_available", lambda: True)
    monkeypatch.setattr(backup, "_ssh", ssh)
    monkeypatch.setattr(
        backup, "_verify_archive", lambda *_args: pytest.fail("archive was re-verified")
    )
    monkeypatch.setattr(backup, "_sha256", lambda *_args: pytest.fail("archive was re-hashed"))
    monkeypatch.setattr(
        backup,
        "_latest_laptop_backup_created_at",
        lambda: pytest.fail("a second remote query was made"),
    )
    monkeypatch.setattr(
        backup, "_copy_to_laptop", lambda *_args: pytest.fail("current copy was re-uploaded")
    )

    backup._sync_latest_laptop_backup(db_path)

    assert len(ssh_calls) == 1
    assert "test -f" in ssh_calls[0]
    assert "cat --" in ssh_calls[0]
    assert "sha256sum" not in ssh_calls[0]
    assert "zstd" not in ssh_calls[0]
