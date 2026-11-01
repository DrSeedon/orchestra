# V-1032: Orchestra audit by its orchestrators

Requested by the owner on 22.10.2026 at 18:53 KRS: every orchestrator describes what would make its work better, how it should work and why. The orchestrators' answers will be added here as they arrive, with raw details that name clients kept in `.orchestra/private/V-1032/`.

## Orchestra-orchestrator (own view, 22.10)

Every point below is taken from today's work, 22.10.

1. **Hub workers cannot run the project's tests.** The hub copy has no `uv` and no `.venv`, and Playwright is not installed there, so every hub task (V-1021, V-1022, V-1023, V-1024, V-1025, V-1026, V-1027, V-1029) came back with "could not run tests". I ran each one locally, and three of them were red: a guessed import in V-1021, a race in V-1022, event-loop breakage in V-1027. Each needed another full round trip.
   Wish: a `run_tests` outbox tool that the broker executes locally on the synced branch, with the result arriving in the next hub turn. Or ship a working `uv` and a lockfile-synced environment into the hub copy.
2. **The merge gate skips browser tests.** V-1017, a hub worker's change to `app.js`, was merged green and turned CI red because the timeline harness lacked `orchLocale`. CI caught it an hour later.
   Wish: when `app/static/**` changes, the gate runs the browser tests mapped to the changed JS. They take about 2 minutes.
3. **Tracked screenshots get rewritten by test runs.** Running `tests/test_frontend.py` rewrites PNG files under `.orchestra/tasks/V-860`, `V-874`, `V-967` and `V-994`. The worktree becomes dirty and `merge_worker` refuses; this happened twice today.
   Wish: tests write screenshots to a temp directory and never into tracked evidence.
4. **Stale hub workspace state after a task switch.** Fixed in V-1008 part 6. It cost about 6 failed launches and 3 manual state moves before the restart.
5. **Hub absolute paths leak into evidence.** Hub workers write their remote home path into reports and logs, and the publish guard then blocks the merge; I redacted by hand twice (V-1024, V-1025).
   Wish: the broker rewrites the remote workspace prefix to a relative path in synced text files.
6. **merge_worker output floods context.** One response was 69,556 characters with the full pytest output and node lists, and similar ones are 10–20 KB. I need four facts: state, the new main SHA, and gate pass or fail with the names of failing tests.
   Wish: a compact result by default and the full detail behind an option.
7. **No direct "wait for CI on SHA X".** My bg job's pattern matched the previous run's completion and woke me falsely once.
   Wish: a platform helper, or a bg type `ci` that waits for the given head SHA.
8. **Reports held silently by the quota gate.** Reports to native-Claude sub-orchestrators sat in `pending` for hours. This is V-1028 in progress.
9. **Cached tool schemas after a restart.** katya-work kept a pre-restart schema of `change_worker_model` without `model_reason` and filed a false bug.
   Wish: after a restart that changes MCP tool signatures, the platform tells each orchestrator to refresh the tool schemas it uses.
10. **The diff budget counts evidence files.** V-1024 was 2205 insertions, about 800 of them a copied patch in the task folder, and needed a waiver.
    Wish: count only code and tests, or make the budget per kind of file.
11. **My own prompt is large.** It is about 100 KB, with 33 KB of personal memory, and it nearly hit the 128 KB argument limit (V-1021). The memory holds many dated owner decisions verbatim.
    Wish: a periodic pass that moves settled decisions from memory into topic files, with one line left in memory.
12. **Restart cadence.** Python fixes queue behind the owner's word, which is correct, but each restart cuts running hub turns. Today two of them failed with `ReadError` and were restored.
    Wish: a "restart when no agent is running" option, used only after the owner's word.

## Answers from the orchestrators

All 9 replied on 22.10 between 18:55 and 19:20 KRS: seedon, katya-work, kesha-tg-bot, Game Master, University, VPN, comfy, cog, openrouter-lab. The full replies are in the session logs as messages to Orchestra-orchestrator and can be found with search_logs "V-1032 audit". This summary leaves out client names and personal details because the repository is public.

### Themes, with how many orchestrators raised each (out of 9)

| # | Theme | n | Proposed action |
|--:|---|--:|---|
| 1 | Prompt contradicts itself: the role block, Step 0.5, the critical rules and dynamic workflows say "Luna is the default", while model-routing says Luna is not a worker route | 8 | Prompt fix now: one source of the default |
| 2 | The full role prompt (30–60 KB) is re-injected on every refresh, 3–5 times per session | 8 | Send the refresh as a diff of changed modules |
| 3 | bg jobs: no user-slice/choom option, no pattern-miss alarm, no pause/snooze, no message update, no absolute-time timer, no cwd, bg_list shows history | 6 | Platform features |
| 4 | Quota gate opaque: WAITING_QUOTA without an ETA, no list or cancel of held messages, no wake when a deadline is earlier than the ETA; spawn creates the worker before admission | 5 | Visible queue, ETA, cancel by id, admission before creation |
| 5 | Voice STT: wrong language on short clips, wrong key words, no confidence | 4 | Pin the language per user, pass a confidence flag |
| 6 | A turn cut by a restart or session limit is reported in "user refused / you asked me to stop" words; workers stop; no auto-resume; no WIP commit before the cut | 4 | Explicit "interrupted by restart/limit" marker; auto-resume; auto WIP commit |
| 7 | Squash commit headline is the first WIP commit, so finished work shows as "WIP … to do" in main | 2 | Use the last commit subject or the acceptance note |
| 8 | Diff budget counts generated files and task evidence | 3 | Count code and tests only, or budget per path class |
| 9 | merge refused because of an unrelated dirty file in the target checkout | 3 | Block only on path overlap; name the file's owner |
| 10 | search_logs: truncated 10k-row scan, echoes the caller's own tool rows | 3 | Full-text index; exclude own tool rows by default |
| 11 | Cannot close a finished task that has no new commit | 3 | `task_close(par, note)` |
| 12 | Delivery failures are silent (NOT_SUBMITTED shown as QUEUED); cancel returns a bare 404 | 2 | Wake the sender with the verbatim error |
| 13 | Hub environment: no fonts or PDF/image libraries, no uv or test runner, no Drive upload, no Russian network egress, no YouTube or STT | 3 | Hub image with deps; broker-side `run_tests` and `upload` outbox tools; egress is an owner decision |
| 14 | The hub kill rule breaks warm lines (boards edited 6 times an evening, the price journal); the owner talks to some workers directly | 3 | Exception: keep a hub worker while its line got a task in the last 24 h or the user talked to it |
| 15 | Sender label missing on dashboard messages; the dashboard shows the agent's draft images to the client | 2 | A source label on every inbound message; mark agent work images as drafts |
| 16 | Answers drift to English after compaction | 1 | Pin the user's language through compaction and refresh |
| 17 | Harness: read/write sandbox stricter than bash; bash is /bin/sh; rg -E is broken | 1 | One access rule; real bash; fix the wrappers |
| 18 | Shared-host registry and network guard (the 14.10 outage); provider token vault | 1 | Owner decision |
| 19 | Routing needs explicit room for tasks that must stay local (deploy on this host, personal data, a project whose purpose is a given model) | 3 | Prompt fix: name these cases in model-routing |

### Data-loss risks found, to check separately

- The 24.09 Drive backup: University suspected that every native Google Doc was exported empty. Checked on 22.10: 4 of 40 .docx files contain no text (three "Новый документ" and one named document), and 36 have content. This is not systemic; the one document that matters must be re-exported from Drive.
- kill_worker removes ignored files from the worktree (seedon V-56 `raw/`).
- A platform migration commit sits unpushed in kesha-tg-bot's local main without notice.
