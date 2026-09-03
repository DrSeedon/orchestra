import sqlite3
import tempfile
from pathlib import Path


def main() -> None:
    from app import db, tm

    with tempfile.TemporaryDirectory() as raw:
        db.DB_PATH = Path(raw) / "paid-status.db"
        db.init_db()
        with tm._conn() as conn:
            tm.ensure_project(conn, "proj", scope="/scope")
            conn.execute(
                "INSERT INTO tm_tasks "
                "(par_number, project_id, title, description, price_rub, paid_rub, status, "
                "assignee, sync_revision, worker_session_id, git_commits, created_at, updated_at, "
                "acceptance_command, acceptance_oracle_json) "
                "VALUES (1, 'proj', 'legacy paid', '', 100, 100, 'paid', '', 0, NULL, '[]', "
                "'now', 'now', '', '{}')"
            )
            conn.commit()

        listed = tm.api_list_tasks(project="proj")
        assert any(t["par"] == "1" and t["status"] == "paid" for t in listed["tasks"])
        assert tm.api_get_task("1", project="proj")["status"] == "paid"

        try:
            with tm._conn() as conn:
                tm.create_task(conn, "proj", "new paid", status="paid")
        except ValueError:
            pass
        else:
            raise AssertionError("create_task(status='paid') must be rejected")

        with tm._conn() as conn:
            task = tm.create_task(conn, "proj", "new", status="new")
            identity = {
                "id": task["id"],
                "project_id": "proj",
                "par_number": task["par_number"],
                "sync_revision": task["sync_revision"],
            }
        try:
            tm.api_update_task(str(task["par_number"]), status="paid", project="proj")
        except ValueError:
            pass
        else:
            raise AssertionError("api_update_task(status='paid') must be rejected")
        try:
            tm.api_update_task_if_current(identity, status="paid")
        except ValueError:
            pass
        else:
            raise AssertionError("api_update_task_if_current(status='paid') must be rejected")


if __name__ == "__main__":
    main()
