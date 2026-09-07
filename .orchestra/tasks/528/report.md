# #528 — cleanup of a removed session's CLI home

## Implementation and consumers

`app/manager.py:SessionManager.remove` calls `_cleanup_cli_home` in a worker thread after backend disconnect, successful worktree removal, FD retirement, DB archive and runtime registry removal. This shared lifecycle path also covers detached sessions and scope removal; placing it in `kill_worker` would miss callers of `remove`. Existing failures before archive retain their old behavior.

The helper reuses `app.backend_codex._CODEX_HOME_ROOT` and `_SAFE_HOME_KEY`, the owner used by `CodexBackend._managed_codex_home_path` and preparation. It passes exactly `root / session_id` to `shutil.rmtree`; no shell, enumeration or periodic cleanup. Fresh DB status must be `archived`, and the ID must be absent from the runtime registry. Missing DB records, live DB records, live runtime records and invalid path keys are refused. The adjacent comment prohibits sweeping unknown IDs, including `.locks` and test homes.

A missing directory logs at debug; other exceptions log a warning with traceback. Archiving and registry removal already finished, so cleanup failure cannot retain the session. Existing shared `sessions` symlink targets are preserved by rmtree; a symlink at the home root itself is refused and logged.

A managed live backend is disconnected before cleanup; a disconnect failure leaves the home and session intact. An OS `EBUSY`/permission failure is logged and removal completes. Unix open files do not inherently prevent unlink: an unrelated unmanaged process holding a file can keep its allocated blocks until closing it. This patch does not discover/kill unrelated processes, use a global process scan, or promise immediate reclamation for such handles. No live-process deletion experiment was performed.

## Acceptance checks and pre-mortem

Committed tests in `tests/test_manager.py::TestRemoveCliHome` cover loaded and detached home deletion, preserving a sibling unknown home and `.locks`, preserving shared symlink history, rejection of a live runtime ID even with an archived DB row, rejection of a live DB row without a runtime record, absent DB record, disconnect failure, idempotent missing home, symlink root, and PermissionError/FileNotFoundError/EBUSY cleanup failures.

`tests/conftest.py` isolates the managed home root for tests: ordinary remove callers must never reach live CLI homes.

Authoritative AC: owner's #528 request, including exact per-session path, DB ownership, live-session exclusion, nonfatal cleanup and remove-hook mutation. The tests were written during this implementation, so they are not claimed as an independently frozen oracle.

Commands use `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest` under `systemd-run --user --scope -p MemoryMax=2G nice -n 15`. Imported module: `/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/cli-home-cleanup/app/manager.py`. Initial system `python` lacked dotenv/pytest-asyncio and was replaced with the project venv.

- `python -m pytest tests/test_manager.py tests/test_fan_barrier_gates.py tests/test_task_tracker_integration.py -q`: **222 passed, 2 failed in 14.98s** (`tests.log`).
- Both failures reproduced against the original `HEAD:app/manager.py`: `test_message_without_sender_is_never_buffered`, `test_t3_merge_operation_replay_does_not_repeat_git_or_lose_task_outcome`; **2 failed in 1.74s** (`baseline.log`). They do not exercise cleanup. No unrelated fix included.
- Mutation removes only the `remove` → cleanup call. `python -m pytest tests/test_manager.py -k test_remove_cleans_only_its_home -q`: **2 failed, 172 deselected in 1.73s**, EXIT_CODE=1 (`mutation.log`). Both loaded/detached cases fail at home existence. Repro script `check_mutation.py` restores code in `finally`.
- Restored `python -m pytest tests/test_manager.py -q`: **174 passed** (`restored.log`).
- `rg -l 'remove\(' tests` also matches workspace helpers, frontend DOM removal, subagent-clock JavaScript and list removal in outbox tests; these do not call `SessionManager.remove`. The three modules above contain actual consumers. Full suite and test lock were not used.

Fresh read-only observation 07.09: actual home root `/home/maxim/.orchestra/codex-home`, 29 direct subdirectories, root free 31.70 GiB (`df`: 86% used). This is consistent with the post-cleanup free space; the historical pre-cleanup counts cannot be reproduced after deletion. No live home was changed by this task.

## Review gate

Author metadata: `mcp__orchestra__list_agents` reports `cli-home-cleanup | gpt-6-astra`; Codex runtime. Files/consumers and AC/check output are above. Session lifecycle plus destructive deletion set the high-risk floor. Sol has no explicit extra-run authorization; per codex-debate auxiliary-review rule use one fresh independent Luna pass. This is not a deterministic low-risk skip. Reviewer receives committed implementation and artifact paths, with a required literal source quote or named command/output as independence evidence.

Review attempt 1 completed: Luna verdict **Correct**, no findings. Independent reviewer ran `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_manager.py -k TestRemoveCliHome`: **9 passed, 165 deselected**. Its literal source quote was checked at `app/manager.py:1334`. Output `.orchestra/tasks/528/review.md`, metadata `reviewer_model=gpt-5.6-luna`.

Calibration of reviewer prose: its sentence about Codex/Luna being unavailable contradicts the completed tool run and metadata; no second reviewer was requested or needed. Its mention of a failing “full suite” means the targeted 224-test run; no full suite was run. Neither sentence changes the source-backed clean verdict. One review round, no blockers, no implementation changes after review.

Python changes require an owner-initiated Orchestra restart after merge; none was performed.
