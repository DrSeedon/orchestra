"""#386 RED oracles: target-aware admission for vertical tickets.

Every repository/merge rehearsal in this file is confined to pytest ``tmp_path``.
The production tree, live DB, providers, and running #380 branches are never mutated.
"""

from __future__ import annotations

import inspect
import json
import shlex
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


ACTOR = {
    "session_id": "parent-session-386",
    "name": "Orchestra-orchestrator",
    "role": "orchestrator",
    "scope": "/scope",
}
MANIFEST = [
    "pyproject.toml",
    "tests",
]


def _required_parameters(func, names: set[str], label: str) -> None:
    missing = names - set(inspect.signature(func).parameters)
    assert not missing, f"#386 missing behavior: {label} lacks {sorted(missing)}"


def _required_callable(owner, name: str):
    value = getattr(owner, name, None)
    assert callable(value), f"#386 missing behavior: {owner.__name__}.{name}"
    return value


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        timeout=30, check=False,
    )
    assert proc.returncode == 0, (
        f"git {' '.join(args)} failed in {cwd}:\n{proc.stdout}\n{proc.stderr}"
    )
    return proc.stdout.strip()


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def git_graph(tmp_path: Path) -> dict:
    """Real graph: main M -> integration I -> C/B/U worker branches."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "task386@example.invalid")
    _git(repo, "config", "user.name", "Task 386")

    _write(repo, "app/__init__.py", "")
    _write(repo, "app/widget.py", "VALUE = 0\nREGRESSION_OK = True\n")
    _write(repo, "tests/__init__.py", "")
    _write(
        repo,
        "tests/oracle_helper.py",
        "def expected_t1():\n    return 1\n",
    )
    _write(
        repo,
        "tests/conftest.py",
        "import pytest\n"
        "from tests.oracle_helper import expected_t1\n\n"
        "@pytest.fixture\n"
        "def t1_expected():\n"
        "    return expected_t1()\n",
    )
    _write(
        repo,
        "tests/test_widget.py",
        "from app.widget import REGRESSION_OK\n\n"
        "def test_non_ticket_regression():\n"
        "    assert REGRESSION_OK\n",
    )
    _write(
        repo,
        "pyproject.toml",
        "[tool.pytest.ini_options]\naddopts = '-q'\n",
    )
    _write(repo, "tests/test_collection_bad_386.py", "def broken(:\n    pass\n")
    _write(
        repo,
        "tests/test_timeout_386.py",
        "import time\n\ndef test_timeout_386():\n    time.sleep(2)\n",
    )
    main_sha = _commit(repo, "M")

    _git(repo, "checkout", "-b", "integration")
    _write(
        repo,
        "tests/test_ticket_386.py",
        "from app.widget import VALUE\n\n"
        "def test_t386_graph_t1_vertical(t1_expected):\n"
        "    assert VALUE >= t1_expected\n\n"
        "def test_t386_graph_t2_future_red():\n"
        "    assert VALUE == 2\n",
    )
    integration_sha = _commit(repo, "I: frozen T1+T2 RED")

    candidate = tmp_path / "candidate"
    _git(repo, "worktree", "add", "-b", "candidate", str(candidate), "integration")
    _write(candidate, "app/widget.py", "VALUE = 1\nREGRESSION_OK = True\n")
    candidate_sha = _commit(candidate, "C: implement T1")

    broken = tmp_path / "broken"
    _git(repo, "worktree", "add", "-b", "candidate-broken", str(broken), "integration")
    _write(broken, "app/widget.py", "VALUE = 1\nREGRESSION_OK = False\n")
    broken_sha = _commit(broken, "B: implement T1 and regress widget")

    mutated = tmp_path / "mutated"
    _git(repo, "worktree", "add", "-b", "candidate-mutated", str(mutated), "candidate")
    _write(
        mutated,
        "tests/oracle_helper.py",
        "def expected_t1():\n    return 99\n",
    )
    mutated_sha = _commit(mutated, "U: mutate frozen oracle helper")

    final = tmp_path / "final"
    _git(repo, "worktree", "add", "-b", "candidate-final", str(final), "integration")
    _write(final, "app/widget.py", "VALUE = 2\nREGRESSION_OK = True\n")
    final_sha = _commit(final, "F: implement T1+T2 for final-only merge")

    python = shlex.quote(sys.executable)
    ticket_command = (
        f"{python} -m pytest -q tests/test_ticket_386.py "
        "-k test_t386_graph_t1_vertical"
    )
    return {
        "repo": repo,
        "candidate": candidate,
        "broken": broken,
        "mutated": mutated,
        "final": final,
        "main_sha": main_sha,
        "integration_sha": integration_sha,
        "candidate_sha": candidate_sha,
        "broken_sha": broken_sha,
        "mutated_sha": mutated_sha,
        "final_sha": final_sha,
        "ticket_command": ticket_command,
    }


@pytest.fixture
def task_db(tmp_path: Path, monkeypatch) -> Path:
    import app.db as dbmod

    db_path = tmp_path / "task386.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    dbmod.init_db()
    return db_path


def test_t386_t1_task_oracle_revision_is_atomic_and_audited(task_db):
    from app import tm

    required = {"acceptance_manifest", "acceptance_required", "acceptance_actor"}
    _required_parameters(tm.create_task, required, "tm.create_task")
    _required_parameters(tm.update_task, required, "tm.update_task")

    with tm._conn() as conn:
        project = tm.ensure_project(conn, "proj", scope="/scope")
        created = tm.create_task(
            conn,
            project["id"],
            "target-aware ticket",
            par_number=386,
            acceptance_command="python -m pytest -q tests/test_ticket_386.py",
            acceptance_manifest=MANIFEST,
            acceptance_required=True,
            acceptance_actor=ACTOR,
        )
        row = tm.get_task_by_id(conn, created["id"])

    oracle = json.loads(row["acceptance_oracle_json"])
    assert oracle["version"] == 1
    assert oracle["required"] is True
    assert oracle["revision"] == 1
    assert oracle["manifest_paths"] == sorted(MANIFEST)
    assert oracle["updated_by"] == ACTOR
    assert oracle["updated_at"]

    with tm._conn() as conn:
        tm.update_task(conn, created["id"], status="in_progress")
        status_only = tm.get_task_by_id(conn, created["id"])
    assert json.loads(status_only["acceptance_oracle_json"])["revision"] == 1

    actor2 = {**ACTOR, "session_id": "second-parent-386"}
    with tm._conn() as conn:
        tm.update_task(
            conn,
            created["id"],
            acceptance_command="python -m pytest -q tests/test_ticket_386.py",
            acceptance_manifest=[*MANIFEST, "app/__init__.py"],
            acceptance_required=True,
            acceptance_actor=actor2,
        )
        updated = tm.get_task_by_id(conn, created["id"])
    revised = json.loads(updated["acceptance_oracle_json"])
    assert revised["revision"] == 2
    assert revised["updated_by"] == actor2


def _create_task_schema_with_legacy_unique(
    connection: sqlite3.Connection,
    *,
    include_oracle: bool,
) -> None:
    oracle_column = (
        "acceptance_oracle_json TEXT NOT NULL DEFAULT '{}',"
        if include_oracle else ""
    )
    connection.executescript(f"""
        CREATE TABLE tm_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            par_number INTEGER NOT NULL,
            project_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            price_rub INTEGER NOT NULL DEFAULT 0,
            paid_rub INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'backlog',
            assignee TEXT NOT NULL DEFAULT '',
            yougile_task_id TEXT UNIQUE,
            sync_revision INTEGER NOT NULL DEFAULT 0,
            worker_session_id TEXT,
            git_commits TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            paid_at TEXT,
            acceptance_command TEXT NOT NULL DEFAULT '',
            {oracle_column}
            priority INTEGER NOT NULL DEFAULT 2,
            UNIQUE(par_number)
        );
    """)


def test_t386_t1_old_schema_and_recreation_preserve_acceptance_bundle(tmp_path, monkeypatch):
    import app.db as dbmod
    import app.merge_operations as operations

    db_path = tmp_path / "legacy386.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript("""
            CREATE TABLE tm_projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                prefix TEXT NOT NULL DEFAULT 'TASK',
                scope TEXT UNIQUE,
                yougile_project_id TEXT,
                yougile_board_id TEXT,
                yougile_enabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(prefix)
            );
            INSERT INTO tm_projects
                (id,name,prefix,scope,created_at)
                VALUES ('proj','Project','PRJ','/scope','2026-08-24T00:00:00+00:00');
        """)
        _create_task_schema_with_legacy_unique(connection, include_oracle=False)
        connection.execute(
            """INSERT INTO tm_tasks
               (par_number,project_id,title,status,created_at,updated_at,
                acceptance_command,priority)
               VALUES (386,'proj','legacy','new',?,?,?,2)""",
            (
                "2026-08-24T00:00:00+00:00",
                "2026-08-24T00:00:00+00:00",
                "python -m pytest -q tests/test_ticket_386.py",
            ),
        )
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    try:
        dbmod.init_db()
    except Exception as exc:  # current drift repair has no #386 column contract
        pytest.fail(f"#386 missing behavior: legacy acceptance migration failed: {exc}")

    with dbmod._conn() as connection:
        row = connection.execute(
            "SELECT * FROM tm_tasks WHERE par_number=386",
        ).fetchone()
        assert row["acceptance_command"].startswith("python -m pytest")
        assert json.loads(row["acceptance_oracle_json"]) == {}
        stored = {
            "version": 1,
            "required": True,
            "revision": 4,
            "manifest_paths": MANIFEST,
            "updated_at": "2026-08-24T00:00:00+00:00",
            "updated_by": ACTOR,
        }
        connection.execute(
            "UPDATE tm_tasks SET acceptance_oracle_json=? WHERE par_number=386",
            (json.dumps(stored, sort_keys=True),),
        )

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("ALTER TABLE tm_tasks RENAME TO tm_tasks_before_386")
        _create_task_schema_with_legacy_unique(connection, include_oracle=True)
        columns = [
            row[1] for row in connection.execute(
                "PRAGMA table_info(tm_tasks_before_386)",
            ).fetchall()
        ]
        names = ",".join(f'"{name}"' for name in columns)
        connection.execute(
            f"INSERT INTO tm_tasks ({names}) SELECT {names} FROM tm_tasks_before_386",
        )
        connection.execute("DROP TABLE tm_tasks_before_386")
        connection.commit()
    try:
        dbmod.init_db()
    except Exception as exc:
        pytest.fail(f"#386 missing behavior: recreated acceptance migration failed: {exc}")
    with dbmod._conn() as connection:
        preserved = connection.execute(
            "SELECT acceptance_oracle_json FROM tm_tasks WHERE par_number=386",
        ).fetchone()[0]
    assert json.loads(preserved) == stored

    operation_id = str(uuid.uuid4())
    operations.accept_operation_snapshot(
        operation_id=operation_id,
        request=operations.normalize_request(
            name="legacy-worker", scope="/scope", target="main",
        ),
        accepted={
            "session_id": "legacy-session",
            "name": "legacy-worker",
            "scope": "/scope",
            "base_branch": "main",
            "worker_branch": "legacy-branch",
            "worker_head": "b" * 40,
            "task_id": "386",
            "needs_switch": False,
            "worktree_path": "/legacy-worktree",
            "admission": {
                "target": {"branch": "main", "sha": "a" * 40},
                "oracle": {"required": False, "source": "none"},
            },
        },
    )
    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1] for row in connection.execute(
                "PRAGMA table_info(merge_operations)",
            ).fetchall()
        }
        assert "accepted_admission_json" in columns, (
            "#386 missing behavior: merge operation admission column was not created"
        )
        connection.execute(
            "ALTER TABLE merge_operations DROP COLUMN accepted_admission_json",
        )
        connection.commit()
    dbmod.init_db()
    with dbmod._conn() as connection:
        replay_row = connection.execute(
            "SELECT * FROM merge_operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
    assert replay_row is not None
    assert json.loads(replay_row["accepted_admission_json"]) == {}


@pytest.mark.asyncio
async def test_t386_t1_worker_cannot_create_update_clear_or_narrow_oracle_bundle(monkeypatch):
    import app.mcp_stdio as mcp

    required = {"acceptance_manifest", "acceptance_required"}
    _required_parameters(mcp.task_create, required, "mcp.task_create")
    _required_parameters(mcp.task_update, required, "mcp.task_update")
    _required_parameters(
        mcp.task_update, {"clear_acceptance_oracle"}, "mcp.task_update",
    )
    api = AsyncMock(return_value={"id": 386, "par": "386", "project": "proj"})
    monkeypatch.setattr(mcp, "_api", api)
    monkeypatch.setattr(mcp, "ROLE", "worker")

    await mcp.task_create(
        "worker-created task",
        acceptance_command="true",
        acceptance_manifest=["tests/worker-picked.py"],
        acceptance_required=True,
    )
    create_body = api.await_args.kwargs["json"]
    assert create_body["acceptance_command"] == ""
    assert "acceptance_manifest" not in create_body
    assert "acceptance_required" not in create_body
    api.reset_mock()

    result = await mcp.task_update(
        "386",
        acceptance_command="true",
        acceptance_manifest=["tests/worker-picked.py"],
        acceptance_required=True,
        clear_acceptance_oracle=True,
    )

    assert result == "Nothing to update"
    api.assert_not_awaited()


@pytest.mark.asyncio
async def test_t386_t1_verified_parent_identity_owns_oracle_audit(monkeypatch):
    from starlette.requests import Request

    import app.db as dbmod
    import app.routes.tm as routes

    required_fields = {"acceptance_manifest", "acceptance_required"}
    missing = required_fields - set(routes.TmTaskUpdate.model_fields)
    assert not missing, (
        f"#386 missing behavior: TmTaskUpdate lacks {sorted(missing)}"
    )
    create_missing = required_fields - set(routes.TmTaskCreate.model_fields)
    assert not create_missing, (
        f"#386 missing behavior: TmTaskCreate lacks {sorted(create_missing)}"
    )
    assert "acceptance_actor" not in routes.TmTaskUpdate.model_fields
    assert "acceptance_actor" not in routes.TmTaskCreate.model_fields

    captured = {}
    captured_create = {}

    def fake_update(*_args, **kwargs):
        captured.update(kwargs)
        return {"updated": ["acceptance_oracle"]}

    def fake_create(*_args, **kwargs):
        captured_create.update(kwargs)
        return {"id": 386, "par": "386", "project": "proj"}

    monkeypatch.setattr(routes._tm, "api_update_task", fake_update)
    monkeypatch.setattr(routes._tm, "api_create_task", fake_create)
    monkeypatch.setattr(routes, "_resolve_task_project_id", lambda *_args: "proj")
    monkeypatch.setattr(
        "app.mcp_proof.caller_may_use_orchestrator_privilege", lambda _request: True,
    )
    monkeypatch.setattr(
        dbmod,
        "get_session",
        lambda _session_id: {
            "id": ACTOR["session_id"],
            "name": ACTOR["name"],
            "role": ACTOR["role"],
            "scope": ACTOR["scope"],
        },
    )
    request = Request({
        "type": "http",
        "headers": [(b"x-orchestra-session-id", ACTOR["session_id"].encode())],
    })

    forged_create = routes.TmTaskCreate.model_validate({
        "title": "forged actor",
        "scope": "/scope",
        "acceptance_command": "python -m pytest -q tests/test_ticket_386.py",
        "acceptance_manifest": MANIFEST,
        "acceptance_required": True,
        "acceptance_actor": {"role": "worker-forged-orchestrator"},
    })
    created = await routes.tm_create_task(forged_create, request)
    assert created["id"] == 386
    assert captured_create["acceptance_actor"] == ACTOR

    forged_update = routes.TmTaskUpdate.model_validate({
        "acceptance_command": "python -m pytest -q tests/test_ticket_386.py",
        "acceptance_manifest": MANIFEST,
        "acceptance_required": True,
        "acceptance_actor": {"role": "worker-forged-orchestrator"},
    })
    result = await routes.tm_update_task(
        "386",
        forged_update,
        request,
        scope="/scope",
    )

    assert result["updated"] == ["acceptance_oracle"]
    assert captured["acceptance_actor"] == ACTOR


@pytest.mark.asyncio
async def test_t386_t1_unauthorized_and_cross_project_oracle_updates_are_refused(monkeypatch):
    import json as jsonlib

    from starlette.requests import Request

    import app.db as dbmod
    import app.routes.tm as routes

    required_fields = {"acceptance_manifest", "acceptance_required"}
    missing = required_fields - set(routes.TmTaskUpdate.model_fields)
    assert not missing, f"#386 missing behavior: TmTaskUpdate lacks {sorted(missing)}"
    create_missing = required_fields - set(routes.TmTaskCreate.model_fields)
    assert not create_missing, (
        f"#386 missing behavior: TmTaskCreate lacks {sorted(create_missing)}"
    )
    update_api = MagicMock()
    create_api = MagicMock()
    monkeypatch.setattr(routes._tm, "api_update_task", update_api)
    monkeypatch.setattr(routes._tm, "api_create_task", create_api)
    request = Request({
        "type": "http",
        "headers": [(b"x-orchestra-session-id", ACTOR["session_id"].encode())],
    })
    update = routes.TmTaskUpdate(
        acceptance_command="python -m pytest -q tests/test_ticket_386.py",
        acceptance_manifest=MANIFEST,
        acceptance_required=True,
    )
    create = routes.TmTaskCreate(
        title="unauthorized oracle create",
        scope="/scope",
        acceptance_command="python -m pytest -q tests/test_ticket_386.py",
        acceptance_manifest=MANIFEST,
        acceptance_required=True,
    )

    monkeypatch.setattr(
        "app.mcp_proof.caller_may_use_orchestrator_privilege", lambda _request: False,
    )
    unauthorized = await routes.tm_update_task(
        "386", update, request, scope="/scope",
    )
    assert unauthorized.status_code == 403
    assert "orchestrator-only" in jsonlib.loads(unauthorized.body)["error"]
    unauthorized_create = await routes.tm_create_task(create, request)
    assert unauthorized_create.status_code == 403
    assert "orchestrator-only" in jsonlib.loads(unauthorized_create.body)["error"]
    create_api.assert_not_called()

    monkeypatch.setattr(
        "app.mcp_proof.caller_may_use_orchestrator_privilege", lambda _request: True,
    )
    monkeypatch.setattr(
        dbmod,
        "get_session",
        lambda _session_id: {
            "id": ACTOR["session_id"],
            "name": ACTOR["name"],
            "role": ACTOR["role"],
            "scope": "/scope",
        },
    )
    monkeypatch.setattr(
        routes,
        "_resolve_task_project_id",
        lambda _project, scope: "caller-project" if scope == "/scope" else "other-project",
    )
    mismatch = await routes.tm_update_task(
        "386", update, request, scope="/other",
    )
    assert mismatch.status_code == 400
    assert "limited to caller's project" in jsonlib.loads(mismatch.body)["error"]
    cross_project_create = await routes.tm_create_task(
        routes.TmTaskCreate(
            title="cross-project oracle create",
            scope="/other",
            acceptance_command="python -m pytest -q tests/test_ticket_386.py",
            acceptance_manifest=MANIFEST,
            acceptance_required=True,
        ),
        request,
    )
    assert cross_project_create.status_code == 400
    assert "limited to caller's project" in jsonlib.loads(cross_project_create.body)["error"]
    update_api.assert_not_called()
    create_api.assert_not_called()


def _pin_oracle(acceptance, graph: dict, *, command: str, manifest: list[str], revision=7):
    pin = _required_callable(acceptance, "pin_task_oracle")
    return pin(
        task_id="386",
        revision=revision,
        command=command,
        manifest_paths=manifest,
        updated_by=ACTOR,
        target_ref="integration",
        target_sha=graph["integration_sha"],
        worktree_path=str(graph["candidate"]),
    )


def test_t386_t1_pinned_oracle_passes_and_mutation_blocks_before_execution(
    git_graph, monkeypatch,
):
    import app.acceptance as acceptance

    evaluate = _required_callable(acceptance, "evaluate_pinned_oracle")
    pinned = _pin_oracle(
        acceptance,
        git_graph,
        command=git_graph["ticket_command"],
        manifest=MANIFEST,
    )
    assert pinned["source"] == "task"
    assert pinned["task_id"] == "386"
    assert pinned["revision"] == 7
    assert pinned["ref"] == git_graph["integration_sha"]
    assert len(pinned["hash"]) == 64
    pinned_paths = {entry["path"] for entry in pinned["manifest"]}
    assert {
        "pyproject.toml",
        "tests/__init__.py",
        "tests/conftest.py",
        "tests/oracle_helper.py",
        "tests/test_ticket_386.py",
    } <= pinned_paths

    with pytest.raises(ValueError, match="manifest.*tests"):
        _pin_oracle(
            acceptance,
            git_graph,
            command=git_graph["ticket_command"],
            manifest=["pyproject.toml", "tests/test_ticket_386.py"],
            revision=8,
        )

    passed = evaluate(pinned, str(git_graph["candidate"]), timeout=30)
    assert passed["status"] == acceptance.PASSED
    assert passed["reason"] == ""

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("mutated oracle reached subprocess execution")

    monkeypatch.setattr(acceptance, "run_command", must_not_run)
    mutated = evaluate(pinned, str(git_graph["mutated"]), timeout=30)
    assert mutated["status"] != acceptance.PASSED
    assert mutated["reason"] == "oracle_input_mutated"
    assert "tests/oracle_helper.py" in mutated["mutated_inputs"]


@pytest.mark.parametrize(
    "mutation,expected_path",
    [
        ("ticket_bytes", "tests/test_ticket_386.py"),
        ("conftest_bytes", "tests/conftest.py"),
        ("config_bytes", "pyproject.toml"),
        ("file_mode", "tests/test_ticket_386.py"),
        ("added_conftest", "conftest.py"),
        ("added_pytest_config", "pytest.ini"),
    ],
)
def test_t386_t1_every_oracle_input_mutation_blocks_before_execution(
    git_graph, monkeypatch, mutation, expected_path,
):
    import app.acceptance as acceptance

    evaluate = _required_callable(acceptance, "evaluate_pinned_oracle")
    pinned = _pin_oracle(
        acceptance,
        git_graph,
        command=git_graph["ticket_command"],
        manifest=MANIFEST,
        revision=9,
    )
    candidate = git_graph["candidate"]
    if mutation == "ticket_bytes":
        path = candidate / "tests/test_ticket_386.py"
        path.write_text(path.read_text(encoding="utf-8") + "\n# worker mutation\n")
    elif mutation == "conftest_bytes":
        path = candidate / "tests/conftest.py"
        path.write_text(path.read_text(encoding="utf-8") + "\n# worker mutation\n")
    elif mutation == "config_bytes":
        path = candidate / "pyproject.toml"
        path.write_text(path.read_text(encoding="utf-8") + "\n# worker mutation\n")
    elif mutation == "file_mode":
        path = candidate / "tests/test_ticket_386.py"
        path.chmod(path.stat().st_mode | 0o111)
    elif mutation == "added_conftest":
        _write(candidate, "conftest.py", "pytest_plugins = []\n")
    elif mutation == "added_pytest_config":
        _write(candidate, "pytest.ini", "[pytest]\naddopts = -x\n")
    else:  # pragma: no cover - parametrization is the closed set above
        raise AssertionError(mutation)

    def must_not_run(*_args, **_kwargs):
        raise AssertionError(f"{mutation} reached subprocess execution")

    monkeypatch.setattr(acceptance, "run_command", must_not_run)
    result = evaluate(pinned, str(candidate), timeout=30)
    assert result["status"] != acceptance.PASSED
    assert result["reason"] == "oracle_input_mutated"
    assert expected_path in result["mutated_inputs"]


def test_t386_t1_missing_skipped_deselected_collection_and_timeout_never_authorize(
    git_graph, monkeypatch,
):
    import app.acceptance as acceptance

    evaluate = _required_callable(acceptance, "evaluate_pinned_oracle")
    missing = evaluate({}, str(git_graph["candidate"]), timeout=0.05)
    assert missing["status"] != acceptance.PASSED
    assert missing["reason"] == "oracle_missing"

    skipped_pin = _pin_oracle(
        acceptance,
        git_graph,
        command=git_graph["ticket_command"],
        manifest=MANIFEST,
        revision=19,
    )
    monkeypatch.setattr(
        acceptance,
        "run_command",
        lambda *_args, **_kwargs: {
            "status": acceptance.SKIPPED,
            "reason": "no_command",
            "exit_code": None,
            "output": "",
        },
    )
    skipped = evaluate(skipped_pin, str(git_graph["candidate"]), timeout=0.05)
    assert skipped["status"] != acceptance.PASSED
    assert skipped["reason"] == "oracle_skipped"
    monkeypatch.undo()

    python = shlex.quote(sys.executable)
    cases = [
        (
            "deselected",
            f"{python} -m pytest -q tests/test_ticket_386.py -k no_such_ticket_386",
            MANIFEST,
            30,
        ),
        (
            "collection",
            f"{python} -m pytest -q tests/test_collection_bad_386.py",
            MANIFEST,
            30,
        ),
        (
            "timeout",
            f"{python} -m pytest -q tests/test_timeout_386.py",
            MANIFEST,
            0.05,
        ),
    ]
    for index, (label, command, manifest, timeout) in enumerate(cases, start=20):
        pinned = _pin_oracle(
            acceptance,
            git_graph,
            command=command,
            manifest=manifest,
            revision=index,
        )
        result = evaluate(pinned, str(git_graph["candidate"]), timeout=timeout)
        assert result["status"] != acceptance.PASSED, (label, result)
        assert result["reason"] not in {"", "no_command"}, (label, result)


def test_t386_t1_nested_target_passes_while_main_and_mapped_regression_reject(git_graph):
    import app.merge_test_gate as gate

    _required_parameters(
        gate.evaluate_test_gate,
        {"target_ref", "target_sha"},
        "merge_test_gate.evaluate_test_gate",
    )
    nested = gate.evaluate_test_gate(
        str(git_graph["candidate"]),
        target_ref="integration",
        target_sha=git_graph["integration_sha"],
    )
    assert nested["status"] == gate.PASSED
    assert nested["target_ref"] == "integration"
    assert nested["target_sha"] == git_graph["integration_sha"]
    assert nested["mapped_files"] == ["tests/test_widget.py"]
    assert "tests/test_ticket_386.py" not in nested["mapped_files"]

    main = gate.evaluate_test_gate(
        str(git_graph["candidate"]),
        target_ref="main",
        target_sha=git_graph["main_sha"],
    )
    assert main["status"] == gate.FAILED
    assert "tests/test_ticket_386.py" in main["mapped_files"]

    final = gate.evaluate_test_gate(
        str(git_graph["final"]),
        target_ref="main",
        target_sha=git_graph["main_sha"],
    )
    assert final["status"] == gate.PASSED
    assert "tests/test_ticket_386.py" in final["mapped_files"]

    broken = gate.evaluate_test_gate(
        str(git_graph["broken"]),
        target_ref="integration",
        target_sha=git_graph["integration_sha"],
    )
    assert broken["status"] == gate.FAILED
    assert broken["mapped_files"] == ["tests/test_widget.py"]


def test_t386_t1_candidate_subset_metadata_cannot_hide_mapped_regression(git_graph):
    import app.merge_test_gate as gate

    _required_parameters(
        gate.evaluate_test_gate,
        {"target_ref", "target_sha"},
        "merge_test_gate.evaluate_test_gate",
    )
    _write(
        git_graph["broken"],
        ".orchestra-merge-tests.json",
        json.dumps({"tests": ["tests/test_ticket_386.py::test_t386_graph_t1_vertical"]}),
    )

    result = gate.evaluate_test_gate(
        str(git_graph["broken"]),
        target_ref="integration",
        target_sha=git_graph["integration_sha"],
    )

    assert result["status"] == gate.FAILED
    assert result["mapped_files"] == ["tests/test_widget.py"]


@pytest.mark.asyncio
@pytest.mark.parametrize("requested_target", ["integration", ""])
async def test_t386_t1_public_operation_pins_target_and_task_oracle_before_runner(
    git_graph, tmp_path, monkeypatch, requested_target,
):
    import app.db as dbmod
    import app.merge_operations as operations
    import app.tm as tm

    _required_parameters(
        tm.create_task,
        {"acceptance_manifest", "acceptance_required", "acceptance_actor"},
        "tm.create_task",
    )
    db_path = tmp_path / "pin-operation386.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    dbmod.init_db()
    operations._runner_tasks.clear()
    dbmod.save_session(_session_row(git_graph))
    with tm._conn() as conn:
        project = tm.ensure_project(conn, "proj", scope="/scope")
        task = tm.create_task(
            conn,
            project["id"],
            "pinned ticket",
            par_number=386,
            acceptance_command=git_graph["ticket_command"],
            acceptance_manifest=MANIFEST,
            acceptance_required=True,
            acceptance_actor=ACTOR,
        )
    monkeypatch.setattr(operations, "ensure_operation_runner", lambda _operation_id: None)

    operation_id = str(uuid.uuid4())
    result, status = await operations.accept_merge_operation(
        operation_id=operation_id,
        name="worker-386",
        scope="/scope",
        target=requested_target,
    )

    assert status == 202
    record = operations.get_operation_record(result["operation_id"])
    admission = record.get("accepted_admission")
    assert admission, "#386 missing behavior: admission was not pinned before runner"
    assert admission["target"] == {
        "branch": "integration",
        "sha": git_graph["integration_sha"],
    }
    assert admission["oracle"]["source"] == "task"
    assert admission["oracle"]["task_id"] == "386"
    assert admission["oracle"]["revision"] == 1
    assert admission["oracle"]["ref"] == git_graph["integration_sha"]
    assert len(admission["oracle"]["hash"]) == 64

    with tm._conn() as connection:
        tm.update_task(
            connection,
            task["id"],
            acceptance_command=git_graph["ticket_command"],
            acceptance_manifest=[*MANIFEST, "app/__init__.py"],
            acceptance_required=True,
            acceptance_actor={**ACTOR, "session_id": "new-revision-386"},
        )
    _write(git_graph["repo"], "target-after-operation.txt", "new target\n")
    _commit(git_graph["repo"], "advance target after operation snapshot")
    replay, replay_status = await operations.accept_merge_operation(
        operation_id=operation_id,
        name="worker-386",
        scope="/scope",
        target=requested_target,
    )
    assert replay_status == 202
    assert replay == result
    replay_record = operations.get_operation_record(operation_id)
    assert replay_record["accepted_admission"] == admission


@pytest.mark.asyncio
async def test_t386_t1_malformed_task_oracle_metadata_refuses_before_runner(
    git_graph, tmp_path, monkeypatch,
):
    import app.db as dbmod
    import app.merge_operations as operations
    import app.tm as tm

    _required_parameters(
        tm.create_task,
        {"acceptance_manifest", "acceptance_required", "acceptance_actor"},
        "tm.create_task",
    )
    db_path = tmp_path / "malformed-operation386.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    dbmod.init_db()
    operations._runner_tasks.clear()
    dbmod.save_session(_session_row(git_graph))
    with tm._conn() as connection:
        project = tm.ensure_project(connection, "proj", scope="/scope")
        task = tm.create_task(
            connection,
            project["id"],
            "malformed oracle",
            par_number=386,
            acceptance_command=git_graph["ticket_command"],
            acceptance_manifest=MANIFEST,
            acceptance_required=True,
            acceptance_actor=ACTOR,
        )
        connection.execute(
            "UPDATE tm_tasks SET acceptance_oracle_json='{not-json' WHERE id=?",
            (task["id"],),
        )
    runner = MagicMock()
    monkeypatch.setattr(operations, "ensure_operation_runner", runner)

    result, status = await operations.accept_merge_operation(
        operation_id=str(uuid.uuid4()),
        name="worker-386",
        scope="/scope",
        target="integration",
    )

    assert status == 409
    assert result["operation_state"] == "FAILED"
    assert result["error"]["code"] == "ORACLE_METADATA_INVALID"
    runner.assert_not_called()


def test_t386_t1_target_move_rejects_under_lock_without_mutation(git_graph):
    import app.workspace as workspace

    _required_parameters(
        workspace.merge_worktree_to_main,
        {"expected_target_head"},
        "workspace.merge_worktree_to_main",
    )
    _write(git_graph["repo"], "target-moved.txt", "advanced after admission\n")
    actual_target = _commit(git_graph["repo"], "advance integration after admission")
    before_worker = _git(git_graph["candidate"], "rev-parse", "HEAD")

    result = workspace.merge_worktree_to_main(
        str(git_graph["candidate"]),
        str(git_graph["repo"]),
        target_branch="integration",
        expected_worker_branch="candidate",
        expected_worker_head=git_graph["candidate_sha"],
        expected_target_head=git_graph["integration_sha"],
    )

    assert result["ok"] is False
    assert result["code"] == "TARGET_HEAD_CHANGED"
    assert result["target_recheck"] == {
        "expected": git_graph["integration_sha"],
        "actual": actual_target,
        "matched": False,
    }
    assert _git(git_graph["repo"], "rev-parse", "integration") == actual_target
    assert _git(git_graph["candidate"], "rev-parse", "HEAD") == before_worker
    assert _git(git_graph["repo"], "status", "--porcelain") == ""
    assert _git(git_graph["candidate"], "status", "--porcelain") == ""


def test_t386_t1_target_move_after_precheck_still_rejects_before_merge(
    git_graph, monkeypatch,
):
    import app.workspace as workspace

    _required_parameters(
        workspace.merge_worktree_to_main,
        {"expected_target_head"},
        "workspace.merge_worktree_to_main",
    )
    original_git_cmd = workspace._git_cmd
    advanced = {"sha": ""}
    merge_started = []

    def moving_git_cmd(args, *pos, **kwargs):
        if args[:3] == ["git", "merge", "--squash"] or args[:2] == ["git", "cherry-pick"]:
            merge_started.append(list(args))
        result = original_git_cmd(args, *pos, **kwargs)
        if args[:3] == ["git", "merge-tree", "--write-tree"] and not advanced["sha"]:
            _write(git_graph["repo"], "late-target-move.txt", "after precheck\n")
            advanced["sha"] = _commit(
                git_graph["repo"], "advance target after merge precheck",
            )
        return result

    monkeypatch.setattr(workspace, "_git_cmd", moving_git_cmd)
    result = workspace.merge_worktree_to_main(
        str(git_graph["candidate"]),
        str(git_graph["repo"]),
        target_branch="integration",
        expected_worker_branch="candidate",
        expected_worker_head=git_graph["candidate_sha"],
        expected_target_head=git_graph["integration_sha"],
    )

    assert advanced["sha"], "control did not move target after precheck"
    assert result["ok"] is False
    assert result["code"] == "TARGET_HEAD_CHANGED"
    assert result["target_recheck"] == {
        "expected": git_graph["integration_sha"],
        "actual": advanced["sha"],
        "matched": False,
    }
    assert merge_started == []
    assert "VALUE = 0" in _git(
        git_graph["repo"], "show", "integration:app/widget.py",
    )


def test_t386_t1_matching_target_commits_and_records_recheck(git_graph):
    import app.workspace as workspace

    _required_parameters(
        workspace.merge_worktree_to_main,
        {"expected_target_head"},
        "workspace.merge_worktree_to_main",
    )
    result = workspace.merge_worktree_to_main(
        str(git_graph["candidate"]),
        str(git_graph["repo"]),
        target_branch="integration",
        expected_worker_branch="candidate",
        expected_worker_head=git_graph["candidate_sha"],
        expected_target_head=git_graph["integration_sha"],
    )

    assert result["ok"] is True
    assert result["target_recheck"] == {
        "expected": git_graph["integration_sha"],
        "actual": git_graph["integration_sha"],
        "matched": True,
    }
    merged = _git(git_graph["repo"], "show", "integration:app/widget.py")
    assert "VALUE = 1" in merged


def _session_row(graph: dict) -> dict:
    return {
        "id": "merge-session-386",
        "name": "worker-386",
        "scope": "/scope",
        "cwd": "/scope",
        "model": "model",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": str(graph["candidate"]),
        "branch": "candidate",
        "base_branch": "integration",
        "is_orchestrator": False,
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "task_id": "386",
        "needs_switch": 0,
    }


def _admission_snapshot(graph: dict, *, required: bool = True) -> dict:
    oracle = {
        "source": "task" if required else "none",
        "task_id": "386" if required else "",
        "revision": 7 if required else 0,
        "ref": graph["integration_sha"],
        "hash": "a" * 64 if required else "",
        "command": graph["ticket_command"] if required else "",
        "required": required,
        "manifest": [
            {
                "path": "tests/test_ticket_386.py",
                "mode": "100644",
                "blob": "b" * 40,
            },
        ] if required else [],
    }
    return {
        "target": {"branch": "integration", "sha": graph["integration_sha"]},
        "oracle": oracle,
    }


def _accepted_snapshot(graph: dict, admission: dict) -> dict:
    return {
        "session_id": "merge-session-386",
        "name": "worker-386",
        "scope": "/scope",
        "base_branch": "integration",
        "worker_branch": "candidate",
        "worker_head": graph["candidate_sha"],
        "task_id": "386",
        "needs_switch": False,
        "worktree_path": str(graph["candidate"]),
        "admission": admission,
    }


def _gate_result(status: str) -> dict:
    return {
        "status": status,
        "reason": "" if status == "passed" else f"mapped_{status}",
        "exit_code": 0 if status == "passed" else 1,
        "output": status,
        "tests": ["tests/test_widget.py"],
        "mapped_files": ["tests/test_widget.py"],
        "target_ref": "integration",
        "target_sha": "pinned-by-test",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "oracle_status,oracle_reason,mapped_status",
    [
        ("failed", "oracle_failed", "passed"),
        ("inconclusive", "oracle_timeout", "passed"),
        ("skipped", "oracle_skipped", "passed"),
        ("failed", "oracle_missing", "passed"),
        ("failed", "oracle_input_mutated", "passed"),
        ("passed", "", "failed"),
        ("passed", "", "inconclusive"),
        ("passed", "", "skipped"),
    ],
)
async def test_t386_t1_every_non_authorizing_operation_result_blocks_executor_and_is_audited(
    git_graph, tmp_path, monkeypatch, oracle_status, oracle_reason, mapped_status,
):
    import app.acceptance as acceptance
    import app.db as dbmod
    import app.merge_operations as operations
    import app.merge_test_gate as gate

    db_path = tmp_path / "blocked-operation386.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    dbmod.init_db()
    operations._runner_tasks.clear()
    dbmod.save_session(_session_row(git_graph))
    admission = _admission_snapshot(git_graph)
    operation_id = str(uuid.uuid4())
    operations.accept_operation_snapshot(
        operation_id=operation_id,
        request=operations.normalize_request(
            name="worker-386", scope="/scope", target="integration",
        ),
        accepted=_accepted_snapshot(git_graph, admission),
    )
    record = operations.get_operation_record(operation_id)
    assert record.get("accepted_admission") == admission, (
        "#386 missing behavior: fail-closed operation lacks pinned admission"
    )
    oracle_result = {
        "status": oracle_status,
        "reason": oracle_reason,
        "exit_code": 0 if oracle_status == "passed" else 1,
        "output": oracle_reason or "passed",
        "command": admission["oracle"]["command"],
    }
    monkeypatch.setattr(acceptance, "evaluate_for_merge", lambda **_kwargs: oracle_result)
    if hasattr(acceptance, "evaluate_pinned_oracle"):
        monkeypatch.setattr(
            acceptance, "evaluate_pinned_oracle", lambda *_args, **_kwargs: oracle_result,
        )
    mapped_result = _gate_result(mapped_status)
    mapped_result["target_sha"] = git_graph["integration_sha"]
    monkeypatch.setattr(gate, "evaluate_test_gate", lambda *_args, **_kwargs: mapped_result)
    executor = AsyncMock()
    monkeypatch.setattr("app.routes.sessions.execute_merge_session", executor)

    await operations._run_operation(operation_id)
    result = operations.get_operation_result(operation_id)

    assert result["operation_state"] == "FAILED"
    executor.assert_not_awaited()
    assert result["admission"]["target"] == admission["target"]
    assert result["admission"]["oracle"]["status"] == (
        oracle_status if oracle_status != "passed" else "passed"
    )
    assert "mapped_files" in result["admission"]
    if oracle_status == "passed":
        assert result["admission"]["mapped_files"] == ["tests/test_widget.py"]
    assert result["commit_point"] == "NOT_REACHED"


@pytest.mark.asyncio
async def test_t386_t1_runner_uses_stored_target_sha_after_branch_moves(
    git_graph, tmp_path, monkeypatch,
):
    import app.acceptance as acceptance
    import app.db as dbmod
    import app.merge_operations as operations
    import app.merge_test_gate as gate

    db_path = tmp_path / "stored-target386.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    dbmod.init_db()
    operations._runner_tasks.clear()
    dbmod.save_session(_session_row(git_graph))
    admission = _admission_snapshot(git_graph)
    operation_id = str(uuid.uuid4())
    operations.accept_operation_snapshot(
        operation_id=operation_id,
        request=operations.normalize_request(
            name="worker-386", scope="/scope", target="integration",
        ),
        accepted=_accepted_snapshot(git_graph, admission),
    )
    record = operations.get_operation_record(operation_id)
    assert record.get("accepted_admission") == admission, (
        "#386 missing behavior: stored target SHA was not persisted"
    )
    _write(git_graph["repo"], "moved-before-runner.txt", "moved\n")
    moved_sha = _commit(git_graph["repo"], "move target before runner")
    seen = {"oracle_ref": "", "gate_sha": "", "execute_sha": ""}

    passed_oracle = {
        "status": acceptance.PASSED,
        "reason": "",
        "exit_code": 0,
        "output": "1 passed",
        "command": admission["oracle"]["command"],
    }

    def pinned_oracle(snapshot, *_args, **_kwargs):
        seen["oracle_ref"] = snapshot["ref"]
        return passed_oracle

    monkeypatch.setattr(acceptance, "evaluate_for_merge", lambda **_kwargs: passed_oracle)
    if hasattr(acceptance, "evaluate_pinned_oracle"):
        monkeypatch.setattr(acceptance, "evaluate_pinned_oracle", pinned_oracle)

    def mapped_gate(*_args, **kwargs):
        seen["gate_sha"] = kwargs["target_sha"]
        result = _gate_result(gate.PASSED)
        result["target_sha"] = kwargs["target_sha"]
        return result

    monkeypatch.setattr(gate, "evaluate_test_gate", mapped_gate)

    async def moved_execute(**kwargs):
        seen["execute_sha"] = kwargs["expected_target_head"]
        return {
            "ok": False,
            "state": "not_merged",
            "commit_point": "not_reached",
            "code": "TARGET_HEAD_CHANGED",
            "error": "target moved",
            "target_branch": "integration",
            "target_before": moved_sha,
            "target_after": moved_sha,
            "worker_branch": "candidate",
            "worker_head": git_graph["candidate_sha"],
            "target_recheck": {
                "expected": git_graph["integration_sha"],
                "actual": moved_sha,
                "matched": False,
            },
            "conflicts": [],
            "commits_merged": 0,
        }

    monkeypatch.setattr("app.routes.sessions.execute_merge_session", moved_execute)
    await operations._run_operation(operation_id)
    result = operations.get_operation_result(operation_id)

    assert seen == {
        "oracle_ref": git_graph["integration_sha"],
        "gate_sha": git_graph["integration_sha"],
        "execute_sha": git_graph["integration_sha"],
    }
    assert result["operation_state"] == "FAILED"
    assert result["admission"]["target_recheck"] == {
        "expected": git_graph["integration_sha"],
        "actual": moved_sha,
        "matched": False,
    }
    assert result["admission"]["oracle"]["status"] == "passed"
    assert result["admission"]["mapped_files"] == ["tests/test_widget.py"]


@pytest.mark.asyncio
async def test_t386_t1_final_only_main_merge_does_not_require_ticket_oracle(
    git_graph, tmp_path, monkeypatch,
):
    import app.acceptance as acceptance
    import app.db as dbmod
    import app.merge_operations as operations
    import app.merge_test_gate as gate

    db_path = tmp_path / "final-only386.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    dbmod.init_db()
    operations._runner_tasks.clear()
    row = _session_row(git_graph)
    row.update({
        "worktree_path": str(git_graph["final"]),
        "branch": "candidate-final",
        "base_branch": "main",
        "task_id": "",
    })
    dbmod.save_session(row)
    admission = {
        "target": {"branch": "main", "sha": git_graph["main_sha"]},
        "oracle": {
            "source": "none",
            "task_id": "",
            "revision": 0,
            "ref": git_graph["main_sha"],
            "hash": "",
            "command": "",
            "required": False,
            "manifest": [],
        },
    }
    accepted = {
        "session_id": "merge-session-386",
        "name": "worker-386",
        "scope": "/scope",
        "base_branch": "main",
        "worker_branch": "candidate-final",
        "worker_head": git_graph["final_sha"],
        "task_id": "",
        "needs_switch": False,
        "worktree_path": str(git_graph["final"]),
        "admission": admission,
    }
    operation_id = str(uuid.uuid4())
    operations.accept_operation_snapshot(
        operation_id=operation_id,
        request=operations.normalize_request(
            name="worker-386", scope="/scope", target="main",
        ),
        accepted=accepted,
    )
    record = operations.get_operation_record(operation_id)
    assert record.get("accepted_admission") == admission, (
        "#386 missing behavior: final-only operation lacks target snapshot"
    )

    def oracle_must_not_run(*_args, **_kwargs):
        raise AssertionError("optional final-only merge executed a ticket oracle")

    monkeypatch.setattr(acceptance, "evaluate_for_merge", oracle_must_not_run)
    if hasattr(acceptance, "evaluate_pinned_oracle"):
        monkeypatch.setattr(acceptance, "evaluate_pinned_oracle", oracle_must_not_run)
    mapped = _gate_result(gate.PASSED)
    mapped.update({
        "tests": ["tests/test_ticket_386.py", "tests/test_widget.py"],
        "mapped_files": ["tests/test_ticket_386.py", "tests/test_widget.py"],
        "target_ref": "main",
        "target_sha": git_graph["main_sha"],
    })
    monkeypatch.setattr(gate, "evaluate_test_gate", lambda *_args, **_kwargs: mapped)
    executor_calls = []

    async def final_execute(**kwargs):
        executor_calls.append(kwargs)
        return {
            "ok": True,
            "state": "merged",
            "commit_point": "target_committed",
            "target_branch": "main",
            "target_before": git_graph["main_sha"],
            "target_after": "f" * 40,
            "worker_branch": "candidate-final",
            "worker_head": git_graph["final_sha"],
            "target_recheck": {
                "expected": git_graph["main_sha"],
                "actual": git_graph["main_sha"],
                "matched": True,
            },
            "conflicts": [],
            "commits_merged": 1,
            "lifecycle_status": {"ok": True},
            "rag_backfill_status": "accepted",
        }

    monkeypatch.setattr("app.routes.sessions.execute_merge_session", final_execute)
    await operations._run_operation(operation_id)
    result = operations.get_operation_result(operation_id)

    assert len(executor_calls) == 1
    assert result["operation_state"] == "SUCCEEDED"
    assert result["admission"]["oracle"]["status"] == "not_required"
    assert result["admission"]["target"]["branch"] == "main"
    assert result["admission"]["mapped_files"] == [
        "tests/test_ticket_386.py", "tests/test_widget.py",
    ]


@pytest.mark.asyncio
async def test_t386_t1_terminal_result_records_complete_admission_evidence(
    git_graph, tmp_path, monkeypatch,
):
    import app.acceptance as acceptance
    import app.db as dbmod
    import app.merge_operations as operations

    db_path = tmp_path / "operations386.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    dbmod.init_db()
    operations._runner_tasks.clear()
    dbmod.save_session(_session_row(git_graph))

    admission = _admission_snapshot(git_graph)
    accepted = _accepted_snapshot(git_graph, admission)
    request = operations.normalize_request(
        name="worker-386", scope="/scope", target="integration",
    )
    operation_id = str(uuid.uuid4())
    operations.accept_operation_snapshot(
        operation_id=operation_id, request=request, accepted=accepted,
    )
    record = operations.get_operation_record(operation_id)
    assert record.get("accepted_admission") == admission, (
        "#386 missing behavior: operation did not persist pinned admission snapshot"
    )

    passed_oracle = {
        "status": acceptance.PASSED,
        "reason": "",
        "exit_code": 0,
        "output": "1 passed",
        "command": git_graph["ticket_command"],
    }
    monkeypatch.setattr(acceptance, "evaluate_for_merge", lambda **_kwargs: passed_oracle)
    if hasattr(acceptance, "evaluate_pinned_oracle"):
        monkeypatch.setattr(
            acceptance, "evaluate_pinned_oracle", lambda *_args, **_kwargs: passed_oracle,
        )
    import app.merge_test_gate as gate

    monkeypatch.setattr(
        gate,
        "evaluate_test_gate",
        lambda *_args, **_kwargs: {
            "status": gate.PASSED,
            "reason": "",
            "exit_code": 0,
            "output": "1 passed",
            "tests": ["tests/test_widget.py"],
            "mapped_files": ["tests/test_widget.py"],
            "target_ref": "integration",
            "target_sha": git_graph["integration_sha"],
        },
    )

    async def fake_execute(**_kwargs):
        return {
            "ok": True,
            "state": "merged",
            "commit_point": "target_committed",
            "target_branch": "integration",
            "target_before": git_graph["integration_sha"],
            "target_after": "f" * 40,
            "worker_branch": "candidate",
            "worker_head": git_graph["candidate_sha"],
            "target_recheck": {
                "expected": git_graph["integration_sha"],
                "actual": git_graph["integration_sha"],
                "matched": True,
            },
            "conflicts": [],
            "commits_merged": 1,
            "lifecycle_status": {"ok": True},
            "rag_backfill_status": "accepted",
        }

    monkeypatch.setattr("app.routes.sessions.execute_merge_session", fake_execute)
    await operations._run_operation(operation_id)
    result = operations.get_operation_result(operation_id)

    assert result["operation_state"] == "SUCCEEDED"
    assert result["admission"] == {
        "target": admission["target"],
        "oracle": {
            "source": "task",
            "task_id": "386",
            "revision": 7,
            "ref": git_graph["integration_sha"],
            "hash": "a" * 64,
            "status": "passed",
        },
        "mapped_files": ["tests/test_widget.py"],
        "target_recheck": {
            "expected": git_graph["integration_sha"],
            "actual": git_graph["integration_sha"],
            "matched": True,
        },
    }
