#!/usr/bin/env python3
"""Live-shaped, read-only-source migration oracle for #425."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def scalar(connection: sqlite3.Connection, query: str, params: tuple = ()) -> int:
    return int(connection.execute(query, params).fetchone()[0])


def main() -> int:
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    production = Path(common).resolve().parent / "data/orchestra.db"
    if not production.is_file():
        raise AssertionError(f"#425 live backup source missing: {production}")

    source = sqlite3.connect(f"file:{production}?mode=ro", uri=True)
    try:
        production_sessions_before = scalar(source, "SELECT COUNT(*) FROM sessions")
        namespace_tasks_before = scalar(
            source, "SELECT COUNT(*) FROM tm_tasks WHERE project_id='orchestra'"
        )
        links_before = scalar(
            source,
            """SELECT COUNT(*) FROM portfolio_task_links
               WHERE project_id='orchestra' AND removed_at IS NULL""",
        )
        with tempfile.TemporaryDirectory(prefix=".live-backup-", dir=Path(__file__).parent) as raw:
            backup_path = Path(raw) / "orchestra.db"
            backup = sqlite3.connect(backup_path)
            try:
                source.backup(backup)
            finally:
                backup.close()

            os.environ["ORCHESTRA_DB_PATH"] = str(backup_path)
            sys.path.insert(0, str(ROOT))
            from app import db, portfolio

            db.DB_PATH = backup_path
            db.init_db()
            db.init_db()
            payload = portfolio.list_projects("")
            project = next(
                item for item in payload["projects"] if item["id"] == "orchestra"
            )
            with sqlite3.connect(backup_path) as migrated:
                copied_sessions_after = scalar(migrated, "SELECT COUNT(*) FROM sessions")
                links_after = scalar(
                    migrated,
                    """SELECT COUNT(*) FROM portfolio_task_links
                       WHERE project_id='orchestra' AND removed_at IS NULL""",
                )
                columns = {
                    row[1]
                    for row in migrated.execute(
                        "PRAGMA table_info(portfolio_projects)"
                    ).fetchall()
                }
                assert "task_namespace_id" in columns, (
                    "#425 T1 missing behavior: task_namespace_id migration"
                )
                source_id = migrated.execute(
                    "SELECT task_namespace_id FROM portfolio_projects WHERE id='orchestra'"
                ).fetchone()[0]

            print(
                "#425 live backup invariant: "
                f"namespace_tasks={namespace_tasks_before} payload_tasks={len(project['tasks'])} "
                f"links={links_before}->{links_after} "
                f"production_sessions={production_sessions_before} "
                f"copied_sessions={copied_sessions_after} source={source_id}"
            )
            assert namespace_tasks_before >= 274, (
                "#425 live corpus unexpectedly lost the measured 274-task baseline"
            )
            assert links_before == links_after == 0, (
                "#425 migration synthesized task links instead of using primary namespace"
            )
            assert copied_sessions_after == production_sessions_before
            assert source_id == "orchestra"
            assert len(project["tasks"]) == namespace_tasks_before, (
                "#425 T1 missing behavior: namespace tasks are not visible when links=0"
            )
    finally:
        source.close()
        check = sqlite3.connect(f"file:{production}?mode=ro", uri=True)
        try:
            production_sessions_after = scalar(check, "SELECT COUNT(*) FROM sessions")
        finally:
            check.close()
        print(
            "#425 production sessions invariant: "
            f"before={production_sessions_before} after={production_sessions_after}"
        )
        assert production_sessions_after == production_sessions_before
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
