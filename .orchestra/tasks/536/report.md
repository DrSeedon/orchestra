# #536 — delivery visibility for detached Codex writer conflicts

Native Linux flock ownership is checked read-only before accepting a detached Codex delivery. An occupied thread returns HTTP 409 with `CODEX_WRITER_CONFLICT` and projects `broken` / `writer_conflict`. Contention discovered after admission uses the existing `FAILED_BEFORE_SUBMIT` receipt. Connected running sessions retain native steering. No native lock is deleted and no discovered process is signalled.

An owner that exits releases its kernel lock without removing its file. The regression verifies the unchanged inode can be acquired again; after lock release the session admission gate allows retry on the same thread. A native resume protocol conflict remains visible until successful reconnect. A surviving detached writer is exposed, not automatically terminated: its lock does not establish that its work is expendable.

## Verification

- `uv run --frozen python -m pytest tests/test_codex_writer_conflict_536.py tests/test_message_delivery_receipts_380.py tests/test_backend_codex.py tests/test_codex_handoff_window.py tests/test_fd_adopt.py -q`: **189 passed in 50.65s**, exit 0. Raw output: `tests-resumed.txt`. Teardown printed pending `_persist_loop` and `_idle_hibernate` tasks; the result is not warning-free.
- After strengthening the release/admission assertion: `uv run --frozen python -m pytest tests/test_codex_writer_conflict_536.py -q`: **7 passed in 8.44s**, no pending-task output. Raw output: `tests-recovery.txt`.
- Imported module: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-stuck-writer/app/session.py`.
- Checks ran sequentially with `nice -n 15` and `prlimit --as=2147483648`. A `MemoryMax=2G` systemd user scope could not start (`Failed to connect to bus: No medium found`); address-space limiting was the available fallback, not a cgroup aggregate limit.
- `git diff --check` and KB diff contract passed. Task artifacts passed `app.secret_mask.mask_secrets` form scanning.

## Review and limits

Recovered the completed Luna report at `.orchestra/tasks/536/review.md`, which names pinned HEAD `50825db2b22d283f626ee9e0c3df50c6761e3bb7` and reports no blockers. No additional review was launched after recovery. The report contains one valid suggestion: `to_dict()` observed writer health twice. Changed the status projection to reuse the same observed error as `runtime_connection`, removing the duplicate scan and possible inconsistent snapshot. The reviewer did not measure polling cost, and `/proc/locks` is only read when detached with an existing lock file; its broader performance claim is unmeasured. This small follow-up passed the seven writer-conflict regression tests (`tests-review.txt`) and was not externally re-reviewed. Direct kernel-flock tests, real subprocess steering, HTTP rejection, queued receipt failures, native protocol error conversion, and successful retry cover the changed boundary. The full application suite was not run. The test subprocess emulates a writer; no live provider turn or production service was started for validation.

Python changes require an owner-authorized Orchestra restart after merge. No service restart, delivery-barrier redesign, or model-switch workaround was performed.

Personal-memory check: the existing worker note records the reusable inode/device/PID distinction; no additional durable lesson emerged during recovery of this interrupted work.
