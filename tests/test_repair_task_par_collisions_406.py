from __future__ import annotations

import json
import re
import sqlite3

from app.ia.task_store import TaskStore, build_migration_manifest


def _source_task(row_id: int, number: int, title: str, created_at: str) -> dict:
    return {
        "id": row_id,
        "project_id": "orchestra",
        "par_number": number,
        "title": title,
        "description": f"description: {title}",
        "price_rub": 0,
        "status": "new",
        "assignee": "",
        "priority": 2,
        "sync_revision": 0,
        "worker_session_id": None,
        "git_commits": [],
        "created_at": created_at,
        "updated_at": created_at,
        "completed_at": None,
        "acceptance_command": "",
        "acceptance_oracle_json": "{}",
    }


def _token(output: str) -> str:
    match = re.search(r"^SNAPSHOT_TOKEN=(\S+)$", output, re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_repair_refuses_stale_plan_then_renumbers_without_deleting(tmp_path, monkeypatch, capsys):
    from app import db, tm
    from scripts import repair_task_par_collisions as repair

    database = tmp_path / "orchestra.db"
    canonical_root = tmp_path / "canonical" / "tasks"
    projection = tmp_path / "task-current.db"
    repository = tmp_path / "project"
    repository.mkdir()
    monkeypatch.setattr(db, "DB_PATH", database)
    db.init_db()
    with tm._conn() as connection:
        tm.ensure_project(connection, "orchestra", scope=str(repository))
        old = tm.create_task(
            connection, "orchestra", "old committed task",
            description="description: old committed task", par_number=1,
        )
        tm.create_task(connection, "orchestra", "filler", par_number=2)
        mirror = tm.create_task(
            connection, "orchestra", "new collided task",
            description="description: new collided task", par_number=3,
        )
        connection.execute(
            "UPDATE tm_tasks SET created_at=?,updated_at=?,git_commits=? WHERE id=?",
            (
                "2026-08-26T00:00:00+00:00",
                "2026-08-26T00:00:00+00:00",
                json.dumps([{"hash": "a" * 40, "message": "old commit"}]),
                old["id"],
            ),
        )
        connection.execute(
            "UPDATE tm_tasks SET created_at=?,updated_at=? WHERE id=?",
            ("2026-08-26T02:00:00+00:00", "2026-08-26T02:00:00+00:00", mirror["id"]),
        )
        connection.commit()

    canonical_new = _source_task(
        900, 1, "new collided task", "2026-08-26T01:00:00+00:00",
    )
    store = TaskStore(canonical_root=canonical_root, projection_path=projection)
    store.migrate(build_migration_manifest({
        "source": {
            "cutoff": "2026-08-26T01:00:00+00:00",
            "source_head": "sha256:fixture",
            "source_schema_sha256": "sha256:fixture-schema",
        },
        "projects": [{"id": "orchestra", "scope": str(repository)}],
        "tasks": [canonical_new],
        "evidence": [],
    }))

    args = [
        "--legacy-db", str(database),
        "--canonical-root", str(canonical_root),
        "--projection", str(projection),
        "--project", "orchestra",
    ]
    assert repair.main(args) == 0
    stale_token = _token(capsys.readouterr().out)

    with tm._conn() as connection:
        tm.create_task(connection, "orchestra", "arrived after dry-run", par_number=4)
        connection.commit()

    assert repair.main([*args, "--apply", "--expected-snapshot", stale_token]) == 2
    refusal = capsys.readouterr().out
    assert "REFUSED: snapshot changed" in refusal
    assert "legacy added #4" in refusal
    assert store.task_get("1", project="orchestra")["title"] == "new collided task"

    assert repair.main(args) == 0
    fresh_token = _token(capsys.readouterr().out)
    assert repair.main([*args, "--apply", "--expected-snapshot", fresh_token]) == 0
    applied = capsys.readouterr().out
    assert "APPLIED #1 -> #5" in applied
    assert store.task_get("1", project="orchestra")["title"] == "old committed task"
    assert store.task_get("1", project="orchestra")["commits"] == [
        {"hash": "a" * 40, "message": "old commit"}
    ]
    assert store.task_get("5", project="orchestra")["title"] == "new collided task"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT par_number FROM tm_tasks WHERE id=?", (mirror["id"],)
        ).fetchone()[0] == 5

    assert repair.main(args) == 0
    clean_token = _token(capsys.readouterr().out)
    assert repair.main([*args, "--apply", "--expected-snapshot", clean_token]) == 0
    assert "NOOP: stores are already collision-free" in capsys.readouterr().out
