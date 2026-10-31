# V-1173 — unified exec process creation failures

## Result

The alert was ten failed Codex `Bash` tool launches, all returned as `Failed to create unified exec process: No such file or directory (os error 2)`. The events span 2026-10-31 07:20:03–20:05:37 UTC, across five sessions in three project scopes. They were read-only shell commands. Each affected session's nearby log sequence contains later successful read activity, commonly after a different working directory was supplied. The log rows do not carry an explicit retry ID, so this does not link a successful result to each failed call one-to-one. This makes an invalid or stale `cwd` the leading explanation; the event-time filesystem state was not captured, so it is not proven for every event.

The error is emitted by the Codex tool/runtime process launcher and recorded by Orchestra. `app/backend_codex.py` wraps the Codex CLI/app-server (`:1`, `:506`); all affected sessions in the log database have `backend_type='codex'`. `app/error_watch.py::collect_db_events` reads existing error rows from SQLite read-only (`:199–216`) and does not create command processes. No Orchestra application defect producing this message was found.

## Coverage and evidence

Read the live `/home/kesha/orchestra/data/orchestra.db` using SQLite URI `mode=ro`; the query covered UTC 2026-10-31 and required `(tool_is_error=1 OR type='error')` plus the unified-exec prefix. It returned 13 failed tool results: ten `No such file or directory (os error 2)` and three distinct `Argument list too long (os error 7)`. The ten ENOENT records match the detector alert's count and first/last timestamps. `journalctl -u orchestra` returned zero exact-prefix lines for 07:20–20:06 UTC; the evidence is in the session log table, not that journal stream.

Protected raw records, each with its preceding Bash call and up to four following same-session rows, are in `.orchestra/private/V-1173/exec-error-context-20261031.json` (SHA-256 `87f3786fb57dffcfc5aa5719c0059d36f786afc4d57119ca3514e7b06ac7213f`). The private file contains exact command arguments and tool output; it is not committed. No model was called, the service and sessions were not changed, and the error-watch state file was not read or written.

## Ten alerted events

| UTC | Session / scope | `cwd` supplied to Bash | Command and nearby result |
|---|---|---|---|
| 07:20:03 | `nis-test-env` / University | `/home/kesha/orchestra/worktrees/tmp-university-nis-test-env/feat-nis-rebuild` | Read-only `id`, Git status/ignore check, `sed pyproject.toml`, `ls uv.lock`, `stat`, `rg --files`; next inspection ran in a different worktree and returned output. |
| 11:02:49 | `tender-intake-native` / seedon | `/home/kesha/orchestra/worktrees/home-kesha/projects-seedon/tender-intake-native` | `sed model_shadow.py` plus `rg` for `RU_HOST`, `RU_KEY`, `USER_AGENT`; the next call at the same path also failed. |
| 11:02:51 | same | same | Same read-only inspection; subsequent call used `/home/kesha/orchestra/worktrees/home-kesha-projects-seedon/tender-intake-native` and returned source lines. |
| 12:05:21 | `tender-evening-native-3110` / seedon | `/home/kesha/orchestra/worktrees/home-kesha/projects/seedon/tender-evening-native-3110` | `rg` in a local tender report; the repeated command returned a match after cwd changed to the canonical `home-kesha-projects-seedon` path. |
| 12:06:00 | same | same | Read-only Python report parsing; same command returned rows after cwd correction. |
| 12:07:14 | same | same | Read-only Python inspection of a local SQLite cache; same command returned results after cwd correction. |
| 12:07:20 | same | same | `rg`/`sed` source inspection; first repeated launch at the same cwd also failed. |
| 12:07:21 | same | same | Same source inspection; nearby result contained the expected `rg`/source output and subsequent commands succeeded. |
| 18:47:49 | `ege9-local-source-kit` / katya-work | `/home/kesha/katya-work/???` | `command -v`, `rg --files`, `ls`; next call used its worker worktree path and returned file listings. The literal `???` is the clearest invalid-cwd case. |
| 20:05:37 | `seedon-orchestrator` / seedon | `/home/kesha/projects/seedon/worktrees/seedon/tender-intake-native` | `cat .orchestra/tasks/V-464/native-intake.md`; next call used `/home/kesha/projects/seedon` and read task files successfully. |

These records are ten launch failures, not ten distinct underlying causes. They cluster around stale or differently mapped worktree paths: the seedon requests show a changed path prefix on later calls, the 18:47 request contains a placeholder component, and the 20:05 nested path was replaced by the project root. All ten original `cwd` strings were absent at the time of this read-only check; this does not prove they were absent at event time. The same-session sequences show work resumed successfully, but the stored rows do not prove a one-to-one recovery for every failed call.

## Reproduction and limits

For five representative logged `cwd` values, running the harmless local equivalent `subprocess.run(['/bin/bash', '-lc', 'true'], cwd=<logged-cwd>)` raised `FileNotFoundError` with errno 2. A read-only `Path.exists()` check found all ten logged paths absent now. This reproduces the OS-level result when the requested cwd is missing, not the Codex unified-exec implementation. No deliberate runtime failure, model call, session operation, or service operation was performed.

The database records the requested cwd and the failure, but not the filesystem state at that instant or why each client supplied that path. ENOENT can also arise from a missing executable or loader. Nearby successful calls after cwd changes make stale/invalid cwd more likely than a missing `/bin/bash`, but they do not identify which component constructed the bad path or prove one cause for all ten events.

Three other failed Bash launches in the same day had `Argument list too long (os error 7)` (14:56, 18:45, 19:08 UTC). They are distinct from ENOENT: their logged commands carry oversized inline data, and the runtime rejected process creation with E2BIG. They did not contribute to this ten-event alert and should not be merged with its cause.

## Existing code, tasks, and disposition

V-647 is the existing recurring-error detector task. It stores error tool results from SQLite and normalizes paths and numbers before grouping (`app/error_watch.py::normalize_signature`); therefore its alert intentionally omits the cwd distinction needed for diagnosis. No V-1173-specific fix or prior repair was found. An older `codex_core::tools::router` ENOENT appears twice in V-909's `raw/clean-446.stderr` and corresponding JSONL on 17 Oct, during a separate review run; that task did not fix exec launch behavior. The exact string search covered the available `.orchestra/tasks/`, `.orchestra/kb/`, `TODO.md`, and `app/` sources; it found that V-909 evidence and no other specific fix.

Disposition: keep the signal actionable; it is not harmless output, even though retries recovered. First trace the producer of per-call cwd values for the affected Codex sessions and correct canonical worktree/session path mapping where it is wrong. If the value originates outside Orchestra, fix that caller/runtime integration at its source. Keep E2BIG separate. Do not globally classify this message as noise: a retry may fail again, and the current records do not prove that every occurrence is recovered. A future detector improvement could retain errno and a sanitized cwd class with each sample, rather than merging distinct launch contexts after path normalization; no classifier change was made here.

## Checks

- Read-only SQLite query: 13 unified-exec error rows on 31 Oct; 10 ENOENT plus 3 E2BIG.
- `journalctl -u orchestra` exact-prefix query for the alert interval: 0 matching rows.
- Logged-command and same-session sequence review: ten failures; later successful read activity appears in every affected session, but the DB does not preserve a call/result retry ID.
- Local spawn reproduction on five representative missing cwd values: five `FileNotFoundError(2)` results.
- No tests run; no app, service, classifier, session, or error-watch state changes.
