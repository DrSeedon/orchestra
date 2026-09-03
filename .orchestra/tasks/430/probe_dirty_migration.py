#!/usr/bin/env python3
"""Scratch proof that a forced layout commit preserves three dirty-worktree states."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app.orchestra_layout import migrate_project_layout_preserving_dirty


def git(repository: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        text=True,
        capture_output=True,
        check=check,
    )


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="orchestra-dirty-layout-") as directory:
        repository = Path(directory)
        source = repository / "docs/kb"
        source.mkdir(parents=True)
        (source / "modified.md").write_text("BASE MODIFIED\n", encoding="utf-8")
        (source / "deleted.md").write_text("BASE DELETED\n", encoding="utf-8")
        (source / "clean.md").write_text("CLEAN\n", encoding="utf-8")
        git(repository, "init", "-q")
        git(repository, "config", "user.email", "task430@example.invalid")
        git(repository, "config", "user.name", "task430")
        git(repository, "add", "-A")
        git(repository, "commit", "-qm", "old layout")

        (source / "modified.md").write_text("USER MODIFIED BYTES\n", encoding="utf-8")
        (source / "new.md").write_text("USER UNTRACKED BYTES\n", encoding="utf-8")
        (source / "deleted.md").unlink()
        before_status = git(repository, "status", "--short").stdout.splitlines()
        before_hashes = {
            "modified": sha(source / "modified.md"),
            "untracked": sha(source / "new.md"),
            "deleted": sha(source / "deleted.md"),
        }

        result = migrate_project_layout_preserving_dirty(repository)
        target = repository / ".orchestra/kb"
        after_status = git(repository, "status", "--short").stdout.splitlines()
        after_hashes = {
            "modified": sha(target / "modified.md"),
            "untracked": sha(target / "new.md"),
            "deleted": sha(target / "deleted.md"),
        }
        commit_stat = git(repository, "show", "--stat", "--oneline", "HEAD").stdout
        committed_modified = git(
            repository, "show", "HEAD:.orchestra/kb/modified.md"
        ).stdout
        committed_untracked = git(
            repository, "cat-file", "-e", "HEAD:.orchestra/kb/new.md", check=False
        ).returncode == 0

        assert before_hashes == after_hashes
        assert before_status == result["dirty_status_before"]
        assert after_status == result["dirty_status_after"]
        assert committed_modified == "BASE MODIFIED\n"
        assert committed_untracked is False
        print("SHA256_BEFORE=" + json.dumps(before_hashes, sort_keys=True))
        print("SHA256_AFTER=" + json.dumps(after_hashes, sort_keys=True))
        print("STATUS_BEFORE")
        print("\n".join(before_status))
        print("STATUS_AFTER")
        print("\n".join(after_status))
        print("MIGRATION_COMMIT_STAT")
        print(commit_stat.rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
