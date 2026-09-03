"""Unit tests for app.tm task-number allocation."""

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    return tmp_path


def _insert_legacy_project(conn, project_id, prefix, scope=None):
    from app.tm import _now

    conn.execute(
        "INSERT INTO tm_projects (id, name, prefix, scope, created_at) VALUES (?, ?, ?, ?, ?)",
        (project_id, project_id, prefix, scope, _now()),
    )


def _create_case_variant_tasks(conn, *, price=100, status="new"):
    from app import tm

    _insert_legacy_project(conn, "Seedon", "UPR", "/upper")
    _insert_legacy_project(conn, "seedon", "LOW", "/lower")
    upper = tm.create_task(
        conn, "Seedon", "upper", price_rub=price, status=status, par_number=1,
    )
    lower = tm.create_task(
        conn, "seedon", "lower", price_rub=price, status=status, par_number=1,
    )
    return upper, lower


def test_next_par_skips_existing_docs_tasks_dir(db):
    """Occupied .orchestra/tasks/<n>/ must not be issued even when free in DB."""
    from app import tm

    repo = db / "repo"
    occupied = repo / ".orchestra" / "tasks" / "1"
    occupied.mkdir(parents=True)

    with tm._conn() as conn:
        tm.ensure_project(conn, "proj", scope=str(repo))
        # DB empty → MAX+1 would be 1, but dir 1 exists
        task = tm.create_task(conn, "proj", "fresh research")
        assert task["par_number"] == 2


def test_next_par_skips_dir_beyond_db_max(db):
    """After DB max N, skip N+1 if that directory already exists on disk."""
    from app import tm

    repo = db / "repo"
    (repo / ".orchestra" / "tasks" / "2").mkdir(parents=True)

    with tm._conn() as conn:
        tm.ensure_project(conn, "proj", scope=str(repo))
        tm.create_task(conn, "proj", "first", par_number=1)
        task = tm.create_task(conn, "proj", "second auto")
        assert task["par_number"] == 3


def test_next_par_ignores_db_absence_of_dir_task(db):
    """Directory occupancy is filesystem fact, not a DB row."""
    from app import tm

    repo = db / "repo"
    # dirs 1 and 2 exist; no tm_tasks rows
    for n in (1, 2):
        (repo / ".orchestra" / "tasks" / str(n)).mkdir(parents=True)

    with tm._conn() as conn:
        tm.ensure_project(conn, "proj", scope=str(repo))
        task = tm.create_task(conn, "proj", "only fs matters")
        assert task["par_number"] == 3


def test_explicit_par_number_still_honoured(db):
    """Caller-supplied par_number is not rewritten by dir checks."""
    from app import tm

    repo = db / "repo"
    (repo / ".orchestra" / "tasks" / "5").mkdir(parents=True)

    with tm._conn() as conn:
        tm.ensure_project(conn, "proj", scope=str(repo))
        task = tm.create_task(conn, "proj", "import", par_number=5)
        assert task["par_number"] == 5


def test_project_resolution_preserves_exact_legacy_case_variants(db):
    from app import tm

    with tm._conn() as conn:
        _insert_legacy_project(conn, "Seedon", "UPR", "/upper")
        _insert_legacy_project(conn, "seedon", "LOW", "/lower")
        before = [
            tuple(row)
            for row in conn.execute(
                "SELECT * FROM tm_projects WHERE id IN ('Seedon', 'seedon') ORDER BY id"
            ).fetchall()
        ]

        assert tm.ensure_project(conn, "Seedon")["id"] == "Seedon"
        assert tm.ensure_project(conn, "seedon")["id"] == "seedon"
        tm.create_task(conn, "Seedon", "upper", par_number=1)
        tm.create_task(conn, "seedon", "lower", par_number=1)
        after = [
            tuple(row)
            for row in conn.execute(
                "SELECT * FROM tm_projects WHERE id IN ('Seedon', 'seedon') ORDER BY id"
            ).fetchall()
        ]

    assert after == before


def test_project_resolution_rejects_ambiguous_nonexact_alias_before_create(db):
    from app import tm

    with tm._conn() as conn:
        _insert_legacy_project(conn, "Seedon", "UPR", "/upper")
        _insert_legacy_project(conn, "seedon", "LOW", "/lower")

    with pytest.raises(ValueError, match="Ambiguous project"):
        tm.api_create_task("SEEDON", "must not exist", scope="/lower")

    with tm._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tm_projects").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM tm_tasks").fetchone()[0] == 0


def test_project_resolution_reuses_unique_alias_and_canonicalizes_new_id(db):
    from app import tm

    with tm._conn() as conn:
        _insert_legacy_project(conn, "Seedon", "UPR", "/upper")
        assert tm.ensure_project(conn, "seedon")["id"] == "Seedon"
        created = tm.ensure_project(conn, "MixedCase", name="Display Name", scope="/mixed")
        reused = tm.ensure_project(conn, "MIXEDCASE")
        rows = conn.execute(
            "SELECT id, name FROM tm_projects ORDER BY id"
        ).fetchall()

    assert created["id"] == "mixedcase"
    assert created["name"] == "Display Name"
    assert reused["id"] == "mixedcase"
    assert [(row["id"], row["name"]) for row in rows] == [
        ("Seedon", "Seedon"),
        ("mixedcase", "Display Name"),
    ]


def test_api_create_uses_resolved_exact_project_without_rebinding_scope(db):
    from app import tm

    with tm._conn() as conn:
        _insert_legacy_project(conn, "Seedon", "UPR", "/upper")
        _insert_legacy_project(conn, "seedon", "LOW", "/lower")

    result = tm.api_create_task("Seedon", "upper", scope="/lower")

    assert result["project"] == "Seedon"
    with tm._conn() as conn:
        task = tm.get_task_by_id(conn, result["id"])
        assert task["project_id"] == "Seedon"
        assert tm.get_project_by_scope(conn, "/lower")["id"] == "seedon"
        assert conn.execute("SELECT COUNT(*) FROM tm_projects").fetchone()[0] == 2


def test_api_create_reuses_unique_project_alias(db):
    from app import tm

    with tm._conn() as conn:
        _insert_legacy_project(conn, "Seedon", "UPR", "/upper")

    result = tm.api_create_task("seedon", "same project", scope="/upper")

    assert result["project"] == "Seedon"
    with tm._conn() as conn:
        assert tm.get_task_by_id(conn, result["id"])["project_id"] == "Seedon"
        assert conn.execute("SELECT COUNT(*) FROM tm_projects").fetchone()[0] == 1




def test_task_core_requires_project_and_rejects_foreign_prefix(db):
    from app import tm

    with tm._conn() as conn:
        upper, lower = _create_case_variant_tasks(conn)

    with pytest.raises(ValueError, match="project authority is required"):
        tm.api_get_task("1")
    with pytest.raises(ValueError, match="project authority is required"):
        tm.api_update_task("1", title="unqualified")
    with pytest.raises(ValueError, match="not authoritative project"):
        tm.api_get_task("UPR-1", project="seedon")
    with pytest.raises(ValueError, match="not authoritative project"):
        tm.api_update_task("UPR-1", title="escaped", project="seedon")

    with tm._conn() as conn:
        assert tm.get_task_by_id(conn, upper["id"])["title"] == "upper"
        assert tm.get_task_by_id(conn, lower["id"])["title"] == "lower"


def test_unqualified_core_update_fails_before_side_effects(db):
    from app import tm

    with tm._conn() as conn:
        project = tm.ensure_project(conn, "only-project")
        task = tm.create_task(conn, project["id"], "original", par_number=99)

    with pytest.raises(ValueError, match="project authority is required"):
        tm.api_update_task("99", title="unqualified")

    with tm._conn() as conn:
        row = tm.get_task_by_id(conn, task["id"])
        assert (row["title"], row["sync_revision"]) == ("original", 0)


def test_acceptance_command_update_changes_revision_once_and_can_clear(db):
    from app import tm

    with tm._conn() as conn:
        project = tm.ensure_project(conn, "proj", scope=str(db))
        task = tm.create_task(
            conn,
            project["id"],
            "acceptance recovery",
            par_number=383,
            acceptance_command="definitely-not-a-command",
        )
        before = tm.get_task_by_id(conn, task["id"])

    result = tm.api_update_task(
        "383",
        project="proj",
        acceptance_command="  python3 -c 'raise SystemExit(0)'  ",
    )

    assert result["updated"] == ["acceptance_command"]
    assert set(result) == {"par", "project", "updated"}
    with tm._conn() as conn:
        corrected = tm.get_task_by_id(conn, task["id"])
    assert corrected["acceptance_command"] == "python3 -c 'raise SystemExit(0)'"
    assert corrected["sync_revision"] == before["sync_revision"] + 1
    assert corrected["updated_at"] != before["updated_at"]

    omitted = tm.api_update_task("383", project="proj")
    assert omitted["updated"] == []
    with tm._conn() as conn:
        unchanged = tm.get_task_by_id(conn, task["id"])
    assert unchanged["acceptance_command"] == corrected["acceptance_command"]
    assert unchanged["sync_revision"] == corrected["sync_revision"]
    assert unchanged["updated_at"] == corrected["updated_at"]

    cleared = tm.api_update_task("383", project="proj", acceptance_command="")
    assert cleared["updated"] == ["acceptance_command"]
    with tm._conn() as conn:
        after_clear = tm.get_task_by_id(conn, task["id"])
    assert after_clear["acceptance_command"] == ""
    assert after_clear["sync_revision"] == corrected["sync_revision"] + 1


def test_acceptance_command_update_rejects_wrong_project_and_task(db):
    from app import tm

    with tm._conn() as conn:
        project = tm.ensure_project(conn, "proj", scope=str(db / "proj"))
        tm.ensure_project(conn, "other", scope=str(db / "other"))
        task = tm.create_task(
            conn,
            project["id"],
            "scoped acceptance",
            par_number=383,
            acceptance_command="original",
        )

    with pytest.raises(ValueError, match="not found"):
        tm.api_update_task(
            "383", project="other", acceptance_command="python3 -c 'pass'",
        )
    with pytest.raises(ValueError, match="not found"):
        tm.api_update_task(
            "999", project="proj", acceptance_command="python3 -c 'pass'",
        )

    with tm._conn() as conn:
        unchanged = tm.get_task_by_id(conn, task["id"])
    assert unchanged["acceptance_command"] == "original"
    assert unchanged["sync_revision"] == 0


def test_combined_acceptance_and_status_update_keeps_status_metadata(db):
    from app import tm

    with tm._conn() as conn:
        project = tm.ensure_project(conn, "proj", scope=str(db))
        tm.create_task(
            conn,
            project["id"],
            "combined update",
            par_number=383,
            acceptance_command="original",
        )

    result = tm.api_update_task(
        "383",
        project="proj",
        status="in_progress",
        acceptance_command="python3 -c 'pass'",
    )

    assert result["updated"] == ["acceptance_command", "status"]
    assert result["old_status"] == "new"
    assert result["new_status"] == "in_progress"
    assert result["price_rub"] == 0






def test_commit_link_rejects_blank_authority_before_opening_db(monkeypatch):
    from app import tm

    monkeypatch.setattr(
        tm,
        "_conn",
        lambda: (_ for _ in ()).throw(AssertionError("DB must not open")),
    )

    with pytest.raises(ValueError, match="project authority is required"):
        tm.link_commits_to_task("1", [{"hash": "a" * 40}], "")


def test_commit_link_is_scoped_and_rejects_foreign_prefix(db):
    import json
    from app import tm

    with tm._conn() as conn:
        upper, lower = _create_case_variant_tasks(conn)

    with pytest.raises(ValueError, match="not authoritative project"):
        tm.link_commits_to_task("UPR-1", [{"hash": "a" * 40}], "seedon")
    result = tm.link_commits_to_task("1", [{"hash": "b" * 40}], "seedon")

    assert result == {"ok": True, "added": 1, "task_id": lower["id"]}
    with tm._conn() as conn:
        upper_row = tm.get_task_by_id(conn, upper["id"])
        lower_row = tm.get_task_by_id(conn, lower["id"])
        assert json.loads(upper_row["git_commits"]) == []
        assert [item["hash"] for item in json.loads(lower_row["git_commits"])] == ["b" * 40]


def test_conditional_task_update_rejects_project_identity_change(db):
    from app import tm

    with tm._conn() as conn:
        tm.ensure_project(conn, "original", scope="/original")
        tm.ensure_project(conn, "foreign", scope="/foreign")
        task = tm.create_task(conn, "original", "task", par_number=6)
    identity = tm.resolve_scoped_task_identity("/original", "6")
    with tm._conn() as conn:
        conn.execute(
            "UPDATE tm_tasks SET project_id='foreign' WHERE id=?", (task["id"],),
        )

    result = tm.api_update_task_if_current(identity, status="in_progress")

    assert result["ok"] is False
    assert "identity changed" in result["error"]
    with tm._conn() as conn:
        assert tm.get_task_by_id(conn, task["id"])["status"] == "new"


def test_conditional_task_update_rejects_par_identity_change(db):
    from app import tm

    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope="/project")
        task = tm.create_task(conn, "project", "task", par_number=6)
    identity = tm.resolve_scoped_task_identity("/project", "6")
    with tm._conn() as conn:
        conn.execute("UPDATE tm_tasks SET par_number=7 WHERE id=?", (task["id"],))

    result = tm.api_update_task_if_current(identity, status="in_progress")

    assert result["ok"] is False
    assert "identity changed" in result["error"]
    with tm._conn() as conn:
        assert tm.get_task_by_id(conn, task["id"])["status"] == "new"


def test_scoped_task_identity_selects_duplicate_number_in_session_project(db):
    from app import tm

    scope_a = str(db / "repo-a")
    scope_b = str(db / "repo-b")
    with tm._conn() as conn:
        tm.ensure_project(conn, "project-a", scope=scope_a, prefix="PRA")
        tm.ensure_project(conn, "project-b", scope=scope_b, prefix="PRB")
        task_a = tm.create_task(conn, "project-a", "A", par_number=7)
        task_b = tm.create_task(conn, "project-b", "B", par_number=7)

    identity = tm.resolve_scoped_task_identity(scope_b, "#7")
    assert tm.resolve_scoped_task_identity(scope_b, "task-7") == identity
    result = tm.api_update_task_if_current(identity, status="in_progress")

    assert identity == {
        "id": task_b["id"],
        "project_id": "project-b",
        "par_number": 7,
        "sync_revision": 0,
    }
    assert result["ok"] is True
    with tm._conn() as conn:
        assert tm.get_task_by_id(conn, task_a["id"])["status"] == "new"
        assert tm.get_task_by_id(conn, task_b["id"])["status"] == "in_progress"


def test_scoped_task_identity_rejects_unmapped_scope_and_wrong_prefix(db):
    from app import tm

    scope = str(db / "repo")
    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope=scope, prefix="PRJ")
        tm.create_task(conn, "project", "task", par_number=3)

    with pytest.raises(ValueError, match="no task project"):
        tm.resolve_scoped_task_identity(str(db / "missing"), "3")
    with pytest.raises(ValueError, match="belongs to project"):
        tm.resolve_scoped_task_identity(scope, "ALT-3")


def test_conditional_task_update_rejects_revision_change(db):
    from app import tm

    scope = str(db / "repo")
    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope=scope)
        task = tm.create_task(conn, "project", "task", par_number=4)
    identity = tm.resolve_scoped_task_identity(scope, "4")
    with tm._conn() as conn:
        conn.execute(
            "UPDATE tm_tasks SET title='changed', sync_revision=sync_revision+1 WHERE id=?",
            (task["id"],),
        )

    result = tm.api_update_task_if_current(identity, status="in_progress")

    assert result["ok"] is False
    assert "revision" in result["error"]
    with tm._conn() as conn:
        assert tm.get_task_by_id(conn, task["id"])["status"] == "new"


def test_conditional_task_update_does_not_touch_reused_number(db):
    from app import tm

    scope = str(db / "repo")
    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope=scope)
        old_task = tm.create_task(conn, "project", "old", par_number=5)
    identity = tm.resolve_scoped_task_identity(scope, "5")
    with tm._conn() as conn:
        conn.execute("DELETE FROM tm_tasks WHERE id=?", (old_task["id"],))
        replacement = tm.create_task(conn, "project", "replacement", par_number=5)

    result = tm.api_update_task_if_current(identity, status="in_progress")

    assert result["ok"] is False
    assert "no longer exists" in result["error"]
    with tm._conn() as conn:
        assert tm.get_task_by_id(conn, replacement["id"])["status"] == "new"
