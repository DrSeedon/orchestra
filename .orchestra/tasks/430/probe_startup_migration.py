#!/usr/bin/env python3
"""Enter the real lifespan through the fleet hook with an isolated DB and Git project."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


class ProbeComplete(RuntimeError):
    pass


async def enter_startup(main_module) -> None:
    try:
        async with main_module.lifespan(main_module.app):
            raise AssertionError("probe must stop immediately after the migration hook")
    except ProbeComplete:
        return


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="orchestra-layout-startup-") as directory:
        root = Path(directory)
        repository = root / "project"
        (repository / "docs/kb").mkdir(parents=True)
        (repository / "docs/kb/fact.md").write_text("live startup\n", encoding="utf-8")
        git(repository, "init", "-q")
        git(repository, "config", "user.email", "task430@example.invalid")
        git(repository, "config", "user.name", "task430")
        git(repository, "add", "-A")
        git(repository, "commit", "-qm", "old layout")

        database = root / "fleet.db"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE tm_projects (id TEXT, scope TEXT)")
            connection.execute(
                "INSERT INTO tm_projects (id, scope) VALUES (?, ?)",
                ("probe", str(repository)),
            )

        os.environ["ORCHESTRA_DB_PATH"] = str(database)
        from app import db
        from app import main as main_module
        from app.ia import runtime

        assert db.DB_PATH == database
        main_module.init_db = lambda: None
        captured_migrations = {}

        def stop_before_knowledge_runtime():
            captured_migrations.update(main_module.app.state.layout_migrations)
            raise ProbeComplete

        runtime.production_runtime_config = stop_before_knowledge_runtime
        asyncio.run(enter_startup(main_module))

        result = captured_migrations["probe"]
        assert result["status"] == "migrated"
        assert (repository / ".orchestra/layout.json").is_file()
        assert (repository / ".orchestra/kb/fact.md").read_text(encoding="utf-8") == (
            "live startup\n"
        )
        assert not (repository / "docs/kb").exists()
        assert git(repository, "status", "--porcelain") == ""
        assert git(repository, "rev-list", "--count", "HEAD") == "2"
        print(
            json.dumps(
                {
                    "database": "isolated",
                    "fleet_projects": 1,
                    "knowledge_runtime_entered": False,
                    "migration_status": result["status"],
                    "repository_clean": True,
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
