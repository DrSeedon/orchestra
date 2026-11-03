import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.test_hub_archive_v1244 import history
from tests.test_merge_operations import merge_db


@pytest.mark.asyncio
async def test_stale_cleared_task_snapshot_does_not_close_published_generation(
    history, merge_db, monkeypatch
):
    from app import db, hub_workspace as hw, merge_operations as operations, workspace, worktree_cleanup

    h = history
    old = db.get_session("merge-session")
    old.update(worktree_path=str(h.wt), task_id="", branch="task-42/worker")
    db.save_session(old)
    stale_snapshot = db.get_session("merge-session")
    assert stale_snapshot["task_id"] == ""

    new_id = "hub-bbbbbbbbbbbbbbbb"
    new_thread = "thread-task-43"
    new_remote = h.ssh.base / new_id
    new_remote.mkdir(parents=True)
    (new_remote / "provider.jsonl").write_text("synthetic generation 43 history\n")
    new_state = hw.WorkspaceState(
        new_id, str(h.wt), str(new_remote), project_id="project-task-43", thread_id=new_thread,
        manifest={"result.py": "new-generation"}, input_manifest={"input.txt": "new-input"},
    )
    new_state.save()

    read_count = 0
    def snapshot_then_publish(_session_id):
        nonlocal read_count
        read_count += 1
        published = db.get_session("merge-session")
        published.update(task_id="43", branch="task-43/worker", base_branch="main")
        db.save_session(published)
        return dict(stale_snapshot)
    monkeypatch.setattr(operations, "get_session", snapshot_then_publish)

    remote_calls = []
    async def synthetic_tool_call(name, args):
        remote_calls.append({"tool": name, "threadId": args.get("threadId"), "action": args.get("action")})
        if name == "t3_thread_wait":
            return {"status": "interrupted", "timedOut": False}
        return {"ok": True}
    h.mc.tool_call = synthetic_tool_call

    monkeypatch.setattr(workspace, "_resolve_repo", lambda *_: h.wt)
    local_cleanup = Mock(return_value={"state": "skipped"})
    monkeypatch.setattr(worktree_cleanup, "clean_worktree", local_cleanup)

    await operations._clean_worktree_after_merge(
        {"session_id": "merge-session", "accepted_task_id": "42",
         "request": {"merge_schema_version": 2, "task_outcome": "complete", "next_task_id": ""}},
        {"git": {"target_branch": "main"}},
    )

    states = hw.states_for_worktree(str(h.wt))
    observed = {
        "snapshot_task_id": stale_snapshot["task_id"],
        "current_db_task_id": db.get_session("merge-session")["task_id"],
        "current_db_branch": db.get_session("merge-session")["branch"],
        "remote_calls": remote_calls,
        "archived": {state.ws_id: state.archived for state in states},
        "local_cleanup_calls": local_cleanup.call_count,
        "local_cleanup_args": repr(local_cleanup.call_args_list),
        "session_snapshot_reads": read_count,
    }
    print("INTERLEAVING_PROBE " + json.dumps(observed, sort_keys=True))

    assert new_id not in observed["archived"] or observed["archived"][new_id] is False
    assert not any(call["threadId"] == new_thread for call in remote_calls)
    assert local_cleanup.call_count == 0
