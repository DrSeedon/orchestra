# V-1064: retained-workspace transport retry (parent/Seedon only)

The parent has already restored the live incident by Seedon's verified cleanup
and normal sync. This recipe documents the existing route for a future approved
transport failure; it is not an instruction to repeat recovery now.

This worker did not access the real hub or run this live recipe. The existing internal
`HubBackend._sync_back(ssh, state, root, scratch)` already downloads, validates,
imports, commits and saves the canonical workspace record. It does not call
`connect`, `_provision`, `_start`, `send`, a provider, or project/thread creation.
No new route or public API is necessary. This is an internal maintenance invocation,
not a new user-facing API contract.

Use the broker's existing service account, its normal authenticated environment and
its authoritative checkout/state directory with the fixed Python loaded. Do not copy
credentials into a command, task artifact, output or transcript. Before running,
parent must confirm that the worker and retained thread are idle, hold the worker's
exclusive maintenance ownership for the entire operation, and keep its worktree and
workspace state associated with the worker (so ordinary orphan release cannot race).
Do not use normal `send_message` / `events`: those paths refresh uploads and run the
model. Do not recreate a missing workspace or run provisioning. Do not run cleanup,
release, model switching or a merge as part of this retry.

First verify through existing authenticated read tools that the service sees the
saved project ID with `workspaceRoot == state.remote_dir`, and that the saved thread
ID belongs to that project. Existing `t3_project_list` and `t3_thread_list` return
`projects` and `threads`, `nextCursor` supports paging. Inspect IDs locally without
publishing account labels or directory prefixes. A missing/mismatched identity stops
recovery; it never authorizes replacement. The code below additionally checks the
exact retained run is terminal through `t3_thread_wait` (a read, not a new turn).
The expected run ID must be obtained from the parent's already recorded turn4
identity, not guessed or replaced with the latest unrelated run.

The following Python is the concrete direct invocation. Run it once using
`uv run --frozen python` in the broker's normal environment. Supply the `V1064_*`
values from canonical worker/session records and verified service reads. They are
identity assertions, not credentials. The workspace ID below comes from the bug
report; all other IDs/paths/model/branch/HEAD must be checked against current records.
Do not fill the worktree/branch from this fix worker's own identity.

```python
import asyncio
import os
import shlex
import subprocess
from pathlib import Path

from app import backend_hub, hub_workspace as hw
from app.multicode_client import MultiCodeClient


def expected(name):
    value = os.environ[f"V1064_{name}"]
    if not value:
        raise RuntimeError(f"missing expected identity: {name}")
    return value


async def recover():
    state = hw.WorkspaceState.load("hub-0cabf759f930454a")
    assert state is not None and state.uploaded
    assert hw.STATE_DIR.resolve() == Path(expected("STATE_DIR")).resolve()
    root = Path(expected("WORKTREE")).resolve(strict=True)
    assert Path(state.worktree).resolve(strict=True) == root
    assert state.project_id == expected("PROJECT_ID")
    assert state.thread_id == expected("THREAD_ID")
    assert state.ws_id in {s.ws_id for s in hw.states_for_worktree(str(root))}
    assert state.manifest  # the established upload baseline must still exist
    ssh = hw.HubSsh.from_env()
    assert ssh is not None
    assert state.remote_dir == await ssh.dir_for(state.ws_id)

    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    assert git("branch", "--show-current") == expected("BRANCH")
    assert git("rev-parse", "HEAD") == expected("HEAD")
    assert not git("status", "--porcelain", "--untracked-files=no")
    # Upload-origin originals may remain untracked: their exact SHA/provenance
    # is checked by the existing capture_inputs/apply_changes path, not git add -A.
    saved_record = state.path().read_bytes()
    async with MultiCodeClient.from_env() as mc:
        done = await mc.tool_call("t3_thread_wait", {
            "threadId": state.thread_id, "runId": expected("RUN_ID"), "timeoutMs": 1})
        assert not done.get("timedOut") and done.get("status") in {
            "completed", "failed", "cancelled", "interrupted", "rolled_back"}
    q = shlex.quote(state.remote_dir)
    # A pending outbox would execute actions and clear its file in _sync_back.
    # Stop for parent assessment rather than consuming/deleting that remote state.
    await ssh.run(f"test -d {q} && test ! -s {q}/{shlex.quote(hw.OUTBOX_NAME)}")
    assert state.path().read_bytes() == saved_record
    backend = backend_hub.HubBackend(expected("MODEL"), str(root))
    scratch = hw.local_scratch()
    try:
        note = await backend._sync_back(ssh, state, root, scratch)
        print(note)  # workspace ID and byte counts, no credential output
        assert "NOT COMMITTED" not in note
        assert "left uncommitted" not in note
        assert "conflicts (" not in note and "rejected:" not in note
        assert not git("status", "--porcelain", "--untracked-files=no")
        print("imported HEAD", git("rev-parse", "HEAD"))
    finally:
        hw.rmtree_quiet(scratch)  # only this invocation's local temporary directory


asyncio.run(recover())
```

An existing custom virtualenv marker can legitimately produce a `rejected:` diagnostic;
that assertion deliberately stops automatic acceptance for parent assessment. It
does not release or discard anything. Any sync rejection/conflict/commit refusal
requires inspecting the note and local status before a retry. `_sync_back` retains
its existing commit-refusal reporting; it is not a general crash/failed-commit
transaction repair API. The proven retry is a transport failure before import.

After success, inspect the resulting commit's exact paths and required report/media,
verify input originals' hashes and that they are absent from `git ls-files`, refresh
any owner's in-memory hub state from the saved record, and record the full new worker
HEAD in the parent's task. A repeat `_sync_back` against the same unchanged remote
snapshot yields zero changed/deleted files and no extra commit; the internal sync
counter still increments per successful sync, as before. No provider upload refresh
or new turn is needed. Retain the workspace until the parent separately accepts the
result. This recipe does not merge or deploy it.
