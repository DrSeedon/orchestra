"""Regression oracle for the #248 T2 review finding: prose is not a task ref.

`UTF-8`, `GPT-5` and `SHA-256` match the historical `[A-Z]{2,5}-\\d+` ref pattern.
Feeding them to the merge gate refuses honest work, and feeding them to the squash
builder links the merge to whatever numeric tail they end in (`UTF-8` -> `#8`).
Both directions are covered here; the control arm keeps the gate itself honest.
"""

import json
import subprocess
from pathlib import Path

import pytest

from tests.test_task_tracker_integration import (
    _commit_file,
    _init_db,
    _make_git_scope,
    _prepare_merge,
    _save_worker,
)


@pytest.mark.asyncio
async def test_prose_token_neither_refuses_nor_relabels_an_honest_merge(
    monkeypatch, tmp_path,
):
    """A subject naming UTF-8 must merge, keep its own ref, and link only that task."""
    import app.routes.sessions as sessions_route
    import app.workspace as workspace
    from app import tm

    _init_db()
    repo = _make_git_scope(monkeypatch, tmp_path)
    scope = str(repo)
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope=scope)
        # #8 is a real neighbouring task: mislinking must be observable, not silent.
        tm.create_task(connection, "project", "Unrelated neighbour", par_number=8)
        task = tm.create_task(
            connection, "project", "Honest work", par_number=42, status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("prose-worker", task["id"]),
        )

    worktree = workspace.create_worktree(scope, "prose-worker", task_id="42")
    head = _commit_file(
        worktree.path, "reader.py", "#42: fix UTF-8 decoding in the log reader",
    )
    _save_worker(
        session_id="prose-worker", task_id="42", scope=scope,
        worktree_path=worktree.path, branch=worktree.branch,
    )
    found = _prepare_merge(monkeypatch, session_id="prose-worker", scope=scope)

    result = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=found.branch,
        expected_head=head,
        req={"scope": scope, "task_outcome": "continue", "merge_schema_version": 2},
    )

    assert result["ok"] is True, result
    subject = subprocess.run(
        ["git", "log", "-1", "--format=%s", "main"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert subject == "#42: fix UTF-8 decoding in the log reader", subject

    with tm._conn() as connection:
        owner = tm.resolve_task_ref(connection, "42", "project")
        neighbour = tm.resolve_task_ref(connection, "8", "project")
    assert json.loads(owner["git_commits"]), "the bound task must receive its commit"
    assert not json.loads(neighbour["git_commits"] or "[]"), (
        "a prose token must never link the merge to task #8"
    )


@pytest.mark.asyncio
async def test_unknown_leading_ref_is_still_refused_before_git(monkeypatch, tmp_path):
    """Control arm: narrowing prose must not disarm the gate for a real fake ref."""
    import app.routes.sessions as sessions_route
    import app.workspace as workspace
    from app import tm

    _init_db()
    repo = _make_git_scope(monkeypatch, tmp_path)
    scope = str(repo)
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope=scope)
        task = tm.create_task(
            connection, "project", "Bound", par_number=42, status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("fake-ref-worker", task["id"]),
        )
    worktree = workspace.create_worktree(scope, "fake-ref-worker", task_id="42")
    head = _commit_file(worktree.path, "work.txt", "#999: fabricated assignment")
    _save_worker(
        session_id="fake-ref-worker", task_id="42", scope=scope,
        worktree_path=worktree.path, branch=worktree.branch,
    )
    found = _prepare_merge(monkeypatch, session_id="fake-ref-worker", scope=scope)
    target_before = subprocess.run(
        ["git", "rev-parse", "main"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()

    result = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=found.branch,
        expected_head=head,
        req={"scope": scope, "task_outcome": "complete", "merge_schema_version": 2},
    )

    target_after = subprocess.run(
        ["git", "rev-parse", "main"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert result["commit_point"] == "not_reached"
    assert target_after == target_before


@pytest.mark.asyncio
async def test_reserved_operation_trailer_in_body_is_refused_before_git(
    monkeypatch, tmp_path,
):
    """T2 claims this guard in its AC; the frozen oracle survives disabling it."""
    import app.routes.sessions as sessions_route
    import app.workspace as workspace
    from app import tm

    _init_db()
    repo = _make_git_scope(monkeypatch, tmp_path)
    scope = str(repo)
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope=scope)
        task = tm.create_task(
            connection, "project", "Bound", par_number=42, status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("trailer-worker", task["id"]),
        )
    worktree = workspace.create_worktree(scope, "trailer-worker", task_id="42")
    (Path(worktree.path) / "work.txt").write_text("payload")
    subprocess.run(["git", "add", "."], cwd=worktree.path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "#42: honest subject", "-m", "Orchestra-Operation: spoof"],
        cwd=worktree.path, check=True, capture_output=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=worktree.path,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    _save_worker(
        session_id="trailer-worker", task_id="42", scope=scope,
        worktree_path=worktree.path, branch=worktree.branch,
    )
    found = _prepare_merge(monkeypatch, session_id="trailer-worker", scope=scope)
    target_before = subprocess.run(
        ["git", "rev-parse", "main"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()

    result = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=found.branch,
        expected_head=head,
        req={"scope": scope, "task_outcome": "complete", "merge_schema_version": 2},
    )

    target_after = subprocess.run(
        ["git", "rev-parse", "main"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert result["commit_point"] == "not_reached"
    assert "Orchestra-Operation" in str(result.get("error") or "")
    assert target_after == target_before


def test_lowercase_prose_prefix_is_not_a_task_ref():
    """`wip-2:` is a word, not a ref.

    Case-sensitivity is owned by `_HEADER_TASK_REFS_RE`, which decides what counts
    as a header at all. `_ONE_TASK_REF_RE` only splits what that header already
    captured, so it is a co-owner in name only: making IT ignore case cannot change
    a result, because every token reaching it passed the case-sensitive header.
    The mixed header below is what separates the two — it fails if the HEADER regex
    starts accepting lowercase prose.
    """
    from app.workspace import _extract_task_refs

    assert _extract_task_refs(["wip-2: adjust parser"]) == []
    assert _extract_task_refs(["wip-2, #42: mixed header"]) == []
    assert _extract_task_refs(["#42: fix UTF-8 decoding"]) == ["42"]
    assert _extract_task_refs(["#42, #44: linked candidate"]) == ["42", "44"]
    assert _extract_task_refs(["see #172 for context"]) == []


def test_one_task_number_is_named_once_in_the_squash_header():
    """`#248` and `PAR-248` are one task: the header must not say it twice."""
    from app.workspace import _build_squash_message

    assert _build_squash_message("x", ["#248: a", "PAR-248: b"]).splitlines()[0] == (
        "#248: a"
    )
    assert _build_squash_message("x", ["ORC-1: a", "#1: b"]).splitlines()[0] == "#1: a"
    assert _build_squash_message("x", ["#42: a", "#44: b"]).splitlines()[0] == (
        "#42, #44: a"
    )
