from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
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


def test_laptop_upload_timeout_keeps_partial_for_next_daily_retry(
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
    archive = tmp_path / "orchestra-db-2026-10-08.sqlite.zst"
    manifest = tmp_path / "orchestra-db-2026-10-08.json"
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
    monkeypatch.setattr(backup, "_ssh", ssh)
    monkeypatch.setattr(backup, "_sha256", lambda _path: "archive-sha")
    monkeypatch.setattr(backup, "_rsync_to_laptop", lambda *_args: False)

    assert backup.main() == 1
    output = capsys.readouterr().err
    assert "BACKUP_FAILURE step=laptop" in output
    assert "incomplete, 200 из 1000 байт" in output
