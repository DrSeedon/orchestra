#!/usr/bin/env python3
"""Back up the live task store and SQLite database without importing service state."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TASK_REMOTE = "backup"
TASK_REMOTE_URL = "git@github.com:DrSeedon/orchestra-task-store-backup.git"
ZERO_SHA = "0" * 40
LAPTOP = "maxim@127.0.0.1"
LAPTOP_PORT = "2222"
LAPTOP_KEY = "/home/kesha/.ssh/tunnel_laptop"
LAPTOP_DIR = "/mnt/data/orchestra-backups"
LAPTOP_TRANSFER_SLICE_SECONDS = 450


class BackupError(RuntimeError):
    def __init__(self, step: str, detail: str):
        super().__init__(detail)
        self.step = step


def _run(args: list[str], *, input_text: str | None = None) -> str:
    result = subprocess.run(args, input=input_text, text=True, capture_output=True)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise RuntimeError(f"{args[0]} exited {result.returncode}: {detail}")
    return result.stdout


def _service_paths() -> tuple[Path, Path]:
    raw_pid = _run(
        ["systemctl", "show", "orchestra.service", "--property=MainPID", "--value"]
    ).strip()
    if not raw_pid.isdigit() or int(raw_pid) <= 0:
        raise RuntimeError("orchestra.service has no live MainPID")
    environ = Path(f"/proc/{raw_pid}/environ").read_bytes().split(b"\0")
    wanted = {b"ORCHESTRA_DB_PATH", b"ORCHESTRA_TASK_REPOSITORY"}
    values: dict[bytes, str] = {}
    for item in environ:
        key, separator, value = item.partition(b"=")
        if separator and key in wanted:
            values[key] = os.fsdecode(value)
    db_path = Path(values.get(b"ORCHESTRA_DB_PATH", ""))
    task_repo = Path(values.get(b"ORCHESTRA_TASK_REPOSITORY", ""))
    if not db_path.is_absolute() or not task_repo.is_absolute():
        raise RuntimeError("live process did not expose absolute DB and task-store paths")
    return db_path, task_repo


def _git(repo: Path, *args: str, input_text: str | None = None) -> str:
    return _run(["git", "-C", str(repo), *args], input_text=input_text)


def _scan_and_push_tasks(repo: Path) -> None:
    remote_url = _git(repo, "remote", "get-url", TASK_REMOTE).strip()
    if remote_url != TASK_REMOTE_URL:
        raise RuntimeError(f"unexpected task-store remote URL: {remote_url}")
    branch = _git(repo, "symbolic-ref", "--short", "HEAD").strip()
    if branch != "main":
        raise RuntimeError(f"task-store branch is {branch!r}, expected 'main'")
    local_sha = _git(repo, "rev-parse", "refs/heads/main").strip()
    refs = _git(repo, "ls-remote", "--heads", TASK_REMOTE, "refs/heads/main").split()
    remote_sha = refs[0] if refs else ZERO_SHA
    if remote_sha == local_sha:
        return

    scanner = Path(__file__).resolve().with_name("secret_scan.py")
    feed = f"refs/heads/main {local_sha} refs/heads/main {remote_sha}\n"
    result = subprocess.run(
        [sys.executable, str(scanner), "--pre-push"],
        cwd=repo,
        input=feed,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-3000:]
        raise RuntimeError(f"task-store secret scan rejected push: {detail}")
    _git(repo, "push", "--porcelain", TASK_REMOTE, f"{local_sha}:refs/heads/main")


def _table_counts(db_path: Path) -> dict[str, int]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=60)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts: dict[str, int] = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0])
        return counts
    finally:
        connection.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_path(archive: Path) -> Path:
    suffix = ".sqlite.zst"
    if not archive.name.endswith(suffix):
        raise ValueError(f"not an Orchestra SQLite backup: {archive.name}")
    return archive.with_name(archive.name[: -len(suffix)] + ".json")


def _verify_archive(archive: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("sha256_zstd") != _sha256(archive):
        raise RuntimeError(f"compressed backup checksum mismatch: {archive}")
    _run(["zstd", "-q", "-t", str(archive)])
    return manifest


def _retain_local(directory: Path, keep: int = 2) -> None:
    archives = sorted(
        directory.glob("orchestra-db-????-??-??.sqlite.zst"), reverse=True
    )
    for archive in archives[keep:]:
        manifest = _manifest_path(archive)
        archive.unlink()
        if manifest.exists():
            manifest.unlink()


def _make_daily_backup(db_path: Path, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    archive = directory / f"orchestra-db-{day}.sqlite.zst"
    manifest_path = _manifest_path(archive)
    if archive.exists() and manifest_path.exists():
        _verify_archive(archive, manifest_path)
        return archive, manifest_path
    if archive.exists():
        archive.unlink()
    if manifest_path.exists():
        manifest_path.unlink()

    fd, raw_temp = tempfile.mkstemp(prefix=f".{day}-", suffix=".sqlite", dir=directory)
    os.close(fd)
    raw_path = Path(raw_temp)
    compressed_fd, compressed_temp = tempfile.mkstemp(
        prefix=f".{day}-", suffix=".zst", dir=directory
    )
    os.close(compressed_fd)
    compressed_path = Path(compressed_temp)
    try:
        source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=60)
        target = sqlite3.connect(raw_path, timeout=60)
        try:
            source.execute("PRAGMA busy_timeout=60000")
            source.backup(target, pages=2048, sleep=0.1)
        finally:
            target.close()
            source.close()

        counts = _table_counts(raw_path)
        check = sqlite3.connect(f"file:{raw_path}?mode=ro", uri=True, timeout=60)
        try:
            integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            check.close()
        if integrity != "ok":
            raise RuntimeError(f"SQLite backup integrity_check failed: {integrity}")

        _run([
            "zstd", "-q", "-T1", "--long=27", "-5", "-f", "-o",
            str(compressed_path), str(raw_path),
        ])
        manifest = {
            "schema_version": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_db": str(db_path),
            "sqlite_integrity_check": integrity,
            "sqlite_table_counts": counts,
            "sqlite_bytes": raw_path.stat().st_size,
            "compressed_bytes": compressed_path.stat().st_size,
            "sha256_zstd": _sha256(compressed_path),
        }
        os.chmod(compressed_path, 0o600)
        os.replace(compressed_path, archive)
        _write_json_atomic(manifest_path, manifest)
        _verify_archive(archive, manifest_path)
        _retain_local(directory)
        return archive, manifest_path
    finally:
        raw_path.unlink(missing_ok=True)
        Path(f"{raw_path}-wal").unlink(missing_ok=True)
        Path(f"{raw_path}-shm").unlink(missing_ok=True)
        compressed_path.unlink(missing_ok=True)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def _ssh(remote_command: str) -> str:
    return _run([
        "ssh", "-i", LAPTOP_KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2",
        "-p", LAPTOP_PORT, LAPTOP, remote_command,
    ])


def _rsync_to_laptop(source: Path, remote_partial: Path) -> bool:
    ssh = " ".join([
        "ssh", "-i", shlex.quote(LAPTOP_KEY), "-o", "IdentitiesOnly=yes",
        "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2",
        "-p", LAPTOP_PORT,
    ])
    result = subprocess.run(
        [
            "timeout", "--signal=TERM", "--kill-after=5s",
            f"{LAPTOP_TRANSFER_SLICE_SECONDS}s", "rsync", "--quiet", "--partial",
            "--append-verify", "-e", ssh, str(source), f"{LAPTOP}:{remote_partial}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 124:
        return False
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise RuntimeError(f"rsync exited {result.returncode}: {detail}")
    return True


def _remote_size(path: Path) -> int:
    try:
        return int(_ssh(f"stat -c %s -- {shlex.quote(str(path))}").strip())
    except RuntimeError:
        return 0


def _copy_to_laptop(archive: Path, manifest_path: Path) -> None:
    name = archive.name
    manifest_name = manifest_path.name
    destination = Path(LAPTOP_DIR)
    _ssh(f"mkdir -p -m 700 {shlex.quote(str(destination))}")
    remote_archive = destination / name
    remote_manifest = destination / manifest_name
    for source, final in ((archive, remote_archive), (manifest_path, remote_manifest)):
        remote_partial = Path(str(final) + ".partial")
        local_hash = _sha256(source)
        try:
            remote_hash = _ssh(
                f"sha256sum -- {shlex.quote(str(final))}"
            ).split()[0]
        except RuntimeError:
            remote_hash = ""
        if remote_hash == local_hash:
            continue
        previous_size = _remote_size(remote_partial)
        if not _rsync_to_laptop(source, remote_partial):
            uploaded_size = _remote_size(remote_partial)
            if uploaded_size <= previous_size:
                raise RuntimeError(f"laptop transfer made no progress: {name}")
            raise BackupError(
                "laptop",
                f"incomplete, {uploaded_size} из {source.stat().st_size} байт",
            )
        uploaded_hash = _ssh(
            f"sha256sum -- {shlex.quote(str(remote_partial))}"
        ).split()[0]
        if uploaded_hash != local_hash:
            raise RuntimeError(f"laptop transfer checksum mismatch: {name}")
        _ssh(
            f"mv -f -- {shlex.quote(str(remote_partial))} {shlex.quote(str(final))}"
        )
    _ssh(f"zstd -q -t {shlex.quote(str(remote_archive))}")
    remote_script = """from pathlib import Path
p=Path('/mnt/data/orchestra-backups')
files=sorted(p.glob('orchestra-db-????-??-??.sqlite.zst'), reverse=True)
for f in files[2:]:
    f.unlink()
    m=f.with_name(f.name[:-len('.sqlite.zst')] + '.json')
    m.unlink(missing_ok=True)
for f in p.glob('*.partial'):
    f.unlink()
"""
    _ssh(f"python3 -c {shlex.quote(remote_script)}")


def _daily() -> None:
    db_path, _task_repo = _service_paths()
    directory = db_path.parent / "backups"
    lock_path = directory / ".orchestra-backup.lock"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            archive, manifest = _make_daily_backup(db_path, directory)
        except Exception as error:
            raise BackupError("local-database", str(error)) from error
        try:
            _copy_to_laptop(archive, manifest)
        except BackupError:
            raise
        except Exception as error:
            raise BackupError("laptop", str(error)) from error


def _restore_drill(archive: Path, manifest_path: Path, temp_root: Path) -> dict[str, int]:
    manifest = _verify_archive(archive, manifest_path)
    with tempfile.TemporaryDirectory(prefix="orchestra-restore-", dir=temp_root) as temp:
        restored = Path(temp) / "restore.sqlite"
        _run(["zstd", "-q", "-d", "-f", str(archive), "-o", str(restored)])
        counts = _table_counts(restored)
        check = sqlite3.connect(f"file:{restored}?mode=ro", uri=True, timeout=60)
        try:
            integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            check.close()
        if integrity != "ok":
            raise RuntimeError(f"restored database integrity_check failed: {integrity}")
        if counts != manifest["sqlite_table_counts"]:
            raise RuntimeError("restored database table counts differ from manifest")
        return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--push-task-store", action="store_true")
    action.add_argument("--daily", action="store_true")
    action.add_argument("--restore-drill", nargs=2, metavar=("ARCHIVE", "MANIFEST"))
    parser.add_argument("--temp-root", type=Path, default=Path("/mnt/data"))
    args = parser.parse_args()
    step = "task-store-push" if args.push_task_store else "daily-backup"
    try:
        if args.push_task_store:
            _db_path, task_repo = _service_paths()
            _scan_and_push_tasks(task_repo)
        elif args.daily:
            _daily()
        else:
            archive, manifest = map(Path, args.restore_drill)
            counts = _restore_drill(archive, manifest, args.temp_root)
            print(json.dumps({"integrity_check": "ok", "sqlite_table_counts": counts}, sort_keys=True))
    except Exception as error:
        error_step = getattr(error, "step", step)
        print(
            f"BACKUP_FAILURE step={error_step} {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
