from __future__ import annotations


def test_vps_floor_is_shared_by_canonical_and_legacy_while_foreign_scope_is_unchanged(
    tmp_path, monkeypatch,
):
    from app import db, tm

    isolated = tmp_path / "orchestra.db"
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(isolated))
    monkeypatch.setattr(db, "DB_PATH", isolated)
    db.init_db()
    with tm._conn() as connection:
        tm.ensure_project(
            connection,
            "orchestra",
            scope="/home/kesha/orchestra",
        )
        tm.ensure_project(connection, "foreign", scope="/foreign/project")

    with tm.ia_task_store_mode(
        mode="canonical",
        canonical_root=tmp_path / "canonical",
        projection_path=tmp_path / "task-current.db",
        cutoff="2026-09-01T00:00:00+00:00",
        source_head="source-435",
    ) as store:
        vps = tm.api_create_task("orchestra", "VPS range")
        canonical = store.task_get(vps["par"], project="orchestra")

    foreign = tm.api_create_task("foreign", "Foreign range")

    assert int(vps["par"]) >= 500
    assert canonical["par"] == vps["par"]
    assert foreign["par"] == "1"
    with tm._conn() as connection:
        rows = connection.execute(
            "SELECT project_id,par_number FROM tm_tasks ORDER BY project_id"
        ).fetchall()
    assert [(row["project_id"], row["par_number"]) for row in rows] == [
        ("foreign", 1),
        ("orchestra", int(vps["par"])),
    ]
