"""V-911 frozen task set: 12 NEW research questions (none from V-896), prompts for arm A, blind checklists.
WRAP, C_SUFFIX, R_FORMAT, GRADER_PROMPT are imported verbatim from V-896 (arm C = A + C_SUFFIX, byte-identical)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "V-896"))
import importlib.util
_spec = importlib.util.spec_from_file_location("tasks896", Path(__file__).resolve().parents[1] / "V-896" / "tasks.py")
_t = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_t)
WRAP, C_SUFFIX, R_FORMAT, GRADER_PROMPT = _t.WRAP, _t.C_SUFFIX, _t.R_FORMAT, _t.GRADER_PROMPT

# Snapshot = parent of the commit that added the real report/fix (see build_fixtures.sh); report and fix absent.
RESEARCH = {
 "S01": dict(past="#30", snapshot="f2ce77eb^", prompt=(
   "In this project SessionManager.send() can now raise when an auto-switch refuses to adopt a branch that already "
   "exists under someone else's history; in that case the message is NOT delivered. List every code path that "
   "delivers a message into a worker session (HTTP route, MCP tool, Telegram bridge, background jobs, limit-wake, "
   "others you find) and determine for each what the sender learns when send() raises. The owner's worry is a "
   "message lost silently, indistinguishable from an agent ignoring it. Say which paths are affected, how bad each "
   "is, and where a fix belongs." + R_FORMAT),
   checklist=[
    "The Telegram path for a USER message loses it silently: _flush_batch runs inside a fire-and-forget debounce task (asyncio.create_task), the exception ends in that task, nothing is sent back to the chat; the only trace is asyncio's 'Task exception was never retrieved' at garbage collection.",
    "The HTTP send route and the MCP send_message tool do surface the full reason to the sender (HTTP 400 with the message, ApiToolError with response body), so those paths are fine and should not be changed.",
    "The background-job path and the limit-wake path catch the exception but only mark the job failed / log it; neither the sender nor the addressee is told, and a worker waiting for a limit reset is never woken.",
    "There is no delivery retry on any of the paths.",
    "send() can also fail for reasons other than the auto-switch (busy runtime, missing worker), so the fix must catch the class 'message not delivered', not the specific branch text.",
    "A single central 'undelivered' handler is tempting but risks notifying everyone about everything; better to oblige each caller to tell somebody (in Telegram: one reply per batch, not per message, to avoid spam).",
   ]),
 "S02": dict(past="#61", snapshot="10d1a858^", prompt=(
   "merge_worker merges a worker's branch into main as a squash. When the worker later returns to the same task via "
   "switch_worker_branch, it is reported that this 'always fails with a merge conflict and force=True does not "
   "help'. From the code, establish when it really fails and when not, what force=True actually does on this path, "
   "and what reliable signal the platform could use to know that the branch's work is already in the base so that "
   "recreating the branch from the base is safe. Evaluate the obvious candidate signal (git-based content check such "
   "as branch_content_status) against what a squash does to history." + R_FORMAT),
   checklist=[
    "It does not always fail: if main did not touch the same lines after the squash, the content check reports 'noop' and the switch works; it fails only when main later changed the same lines the worker's branch touched (add/add or content conflict).",
    "A squash destroys ancestry (--is-ancestor is false), and a tree-merge based content check (merge-tree / branch_content_status) reports content_merged=False with reason conflict exactly in the failing case, so a git-derived criterion cannot prove the work is already in base.",
    "The proof exists in our own durable record: the merge_operations table (accepted_worker_branch, accepted_worker_head, state SUCCEEDED, commit_point reached).",
    "Safe rule: a SUCCEEDED/commit-point-reached operation exists for the branch AND its accepted head equals the branch's current head, then recreate the branch from base (checkout -B); if the head differs, commits were added after the merge and recreating would destroy them.",
    "force is checked in one place only (leaving the current branch with unconfirmed content); it is never reached for the 'target branch exists' case, so force=True changes nothing here; it could be given the meaning 'recreate from base even without proof'.",
    "Risks: recreating the branch destroys its commits so the proof must be exact; old branches without a merge_operations record have no proof; the policy belongs in the route (has DB access) and the mechanism in workspace.",
   ]),
 "S03": dict(past="#62", snapshot="ef9c8057^", prompt=(
   "On this installation the git worktrees of many worker agents (several projects) vanished at once: the working "
   "directories, the .git/worktrees registrations and even the now-empty per-project directories are gone, while "
   "the branches survive; only clean (not dirty) copies disappeared; the server journal has no line about it. Find "
   "all code paths that can remove worktrees, work out which one fired and under what conditions, why nothing was "
   "logged, and which protections are missing. Do not run the full test suite." + R_FORMAT),
   checklist=[
    "The deleter is cleanup_stale_worktrees, started from start_background_tasks in the app lifespan on EVERY app start, including every TestClient(app) in tests, so a pytest run inside the main checkout deletes the live worktrees.",
    "Tests replace DB_PATH (an empty temp DB) but several test files do not replace WORKTREE_ROOT, so alive_paths is empty while the root is the real one, and everything clean is removed.",
    "The decision is made by absence from alive_paths, an empty list silently means 'nothing alive' (the worse the query, the more is deleted); the only protection is a dirty tree, so clean copies with unmerged commits are unprotected; the radius is all projects at once (sessions are not filtered by scope) and empty scope directories are rmdir'ed.",
    "The server's own periodic cleanup is not the culprit in this incident (the process had started earlier and the next 24-hour pass was not due), the destructive call came from a test process.",
    "Nothing is logged because the app's log handler is attached only to the logger named 'orchestra' while modules log via logging.getLogger(__name__) (app.workspace), whose INFO is dropped; and the deletion runs inside the pytest process whose output pytest captures.",
    "Needed protections: refuse the pass when alive_paths is empty but the directory is not (anomaly, not permission) or a live session owns the path; an autouse conftest fixture that points WORKTREE_ROOT at a tmp dir for all tests and/or no cleanup under TestClient; log removals at WARNING; a session whose worktree_path does not exist should be shown as broken, not idle.",
   ]),
 "S04": dict(past="#71", snapshot="262b38b5^", prompt=(
   "GET /api/orchestrators returns about 21 KB over the wire (about 56 KB raw, 5 entries). Users on flaky "
   "connections lose responses larger than roughly 15 KB. The first page load also seems to call this endpoint "
   "twice. From the code, establish what makes the response heavy, whether that part can be dropped without "
   "breaking any consumer (list each consumer and which fields it reads), where exactly the cut belongs, and why "
   "the endpoint is hit twice at start. Give a recommendation." + R_FORMAT),
   checklist=[
    "One field, system_prompt, is by far the biggest part (about 93% of the gzip size, about 50 KB of 56 KB raw); removing it alone brings the response to about 1.5 KB, well inside the 15 KB envelope, without restructuring the response.",
    "No consumer of this response reads system_prompt: loadOrchestrators (parent_name, scope, id, name), refreshSessions (name, status, cost_usd, any_running), the field renderer in app.js skips it, the MCP list_orchestrators reads other fields; the prompt has its own endpoint (/api/sessions/{name}/prompt).",
    "The cut belongs in the route of /api/orchestrators, not in the shared to_dict(), because to_dict() also serves /api/sessions/{name}; and both sources must be trimmed: live sessions (to_dict) and rows read from the DB (get_all_sessions).",
    "The second call comes from the initial value of the throttle: _orchFreshAt starts at 0 and the condition is Date.now() - _orchFreshAt >= 15000, so the first refreshSessions (about 0.5 s after loadOrchestrators) considers the data stale and refetches.",
    "The fix for the double call is one line in the frontend: set _orchFreshAt = Date.now() in loadOrchestrators after a successful response.",
    "Residual risk: callers outside the repository cannot be verified (the endpoint is internal and token-protected); the rest of the response (about 50 other fields) adds under 3% and is not worth restructuring.",
   ]),
 "S05": dict(past="#97", snapshot="9764b850^", prompt=(
   "Codex-backed workers sometimes look idle right after the first message sent with POST /api/sessions/{name}/send: "
   "the call returns 200, within milliseconds the session is shown as idle, and the work and its logs appear only "
   "after a SECOND message, as if delivery were one turn behind. Claude workers do not show it. Find the mechanism "
   "in the code (backend_codex.py, session.py, turn handling) and say which obvious explanations (stale dashboard, "
   "lifecycle lock held, hibernate, pending-message queue) do not fit and why." + R_FORMAT),
   checklist=[
    "Native Codex compaction and ordinary turns share CodexBackend._notifications but only ordinary turns have a consumer: _read_stdout puts every notification into the queue unconditionally, and compact_context finishes when the compaction-completion notification arrives, without consuming the compact's own item/started, item/completed and turn/completed notifications.",
    "On the next idle send, turn/start returns the new turn id (stored in _active_turn_id) and the per-turn listener starts; it first drains the leftover compact notifications, and the delayed compact turn/started overwrites _active_turn_id with the compact turn's id.",
    "Neither _convert_notification nor events() compares a notification's turn id with the id returned by the current turn/start, so the stale compact turn/completed is treated as the terminal turn_end of the current turn.",
    "TurnManager then persists IDLE (and publishes turn-finished) although the new Codex turn is still working; the per-turn listener has exited, and the real turn's text/tools/completion stay buffered unread.",
    "The next send sees the false IDLE, starts another turn and listener, which first drains the previous turn's buffered events: hence 'one turn behind'.",
    "It is not the pending-message queue (_pending_messages / _flush_pending, no 'message queued' trace), not _lifecycle_lock (the first send returns 200 and the false completion follows within milliseconds), not hibernate (Codex registers hibernate=False), and not a dashboard-only staleness (the API reads AgentSession state directly).",
   ]),
 "S06": dict(past="#416", snapshot="8239760c^", prompt=(
   "merge_worker was refused three times for the same worker whose branch had a new commit. The third refusal said "
   "'merge produced no new commits' (code NO_COMMITS_MERGED, next action CHECK_WORKER_THEN_NEW_OPERATION). A "
   "teammate's unchecked guess: main is checked out in another worktree, so git checkout of the target fails. Work "
   "out from the code which git step really refuses, what raw error the workspace layer produces, what the result "
   "normalizer shows the user and why, and whether the target ref changed. Propose the safe boundary for a fix "
   "(what must not be broken by it)." + R_FORMAT),
   checklist=[
    "The teammate's busy-target-branch guess is wrong: the merge function finds the checkout that owns the target branch (via git worktree list --porcelain, _branch_worktree_path) and merges there; a direct git checkout of main from the worker worktree would fail with rc 128 but production code never does that, and existing tests merge into a checked-out parent successfully.",
    "The real refusal is a dirty target worktree: any tracked or untracked WIP (for example one untracked docs file) makes the clean-worktree check on the target (_clean_worktree_error) refuse BEFORE git merge --squash, with raw error 'target working tree is dirty', state failed, commit_point not_reached, and the target ref unchanged.",
    "The false text is created by normalize_merge_result, not by git or workspace: its no-op predicate (non-empty target_before, equal before/after snapshots, commits_merged == 0) never checks that the raw result claimed success, so any pre-merge refusal that happens after the target snapshot is read becomes NO_COMMITS_MERGED.",
    "The same collapse destroys the cause for conflict, target head change and unknown results; the classifier _classify_failure already knows TARGET_DIRTY / CLEAN_TARGET_THEN_NEW_OPERATION and would give the right message if the raw error were preserved.",
    "The first attempt showed the true cause because the diff-budget refusal happens before target_before is read (it is empty), so the faulty predicate does not fire; after the waiver execution reaches the snapshot and the predicate fires.",
    "Safe boundary: the zero-commit guard must not simply be deleted, because it protects against a contradictory legacy/resume result (ok=false but commit_point=target_committed with equal snapshots) being classified as success; coercion to NO_COMMITS_MERGED should apply only to results that claim success (ok=true, state merged or commit_point target_committed), while well-typed failed/not_reached results keep their raw error; the dirty-target safety check itself stays.",
   ]),
 "S07": dict(past="#56", snapshot="0d3975b0^", prompt=(
   "Agents file bug reports with the report_bug tool (POST /api/report_bug). Seven reports from four agents sat "
   "unread for two days, and the owner removed the UI badge on purpose. Evaluate the proposal 'a filed report "
   "should notify the orchestrator of the scope where it was filed': what happens to a report after it is "
   "written today, is there enough data to find the addressee, which existing helpers can be reused, what design "
   "options exist for the notification, and what risks and edge cases must the plan cover." + R_FORMAT),
   checklist=[
    "Today nothing happens after the write: the route builds a markdown entry and _publish_bug_record atomically publishes a file in a private state directory; there is no notification, queue, or read/acknowledged marker, and the only consumer is GET /api/report_bug that concatenates the entries; the agent just gets 'Bug reported ... Read: /api/report_bug'.",
    "The data to address it is present: scope is sent in the request and recorded in the entry, and a helper that finds the orchestrator of a scope already exists (notify.orchestrator_for_scope) and returns None instead of inventing a recipient.",
    "The natural design is to send a message to that scope's orchestrator right after publication (reusing manager.send and the existing undelivered-handling patterns such as report_undelivered / _record_undelivered_auto_report); the channel may refuse, so a refusal must be recorded loudly rather than lost.",
    "Writing the report must stay successful regardless of the notification's fate: the notification must not make the HTTP handler slow or able to fail the write (not synchronous-and-fatal).",
    "Edge cases: some reports are filed by the orchestrator itself (notifying the author of its own report is noise); a scope may have no orchestrator (then only a loud log, do not invent a recipient); the recipient may be an orchestrator of another project, so the notification text must be self-explanatory without this repository's context.",
    "Because the notification is sent exactly at publication and there are no retries, 'one report = one notification' holds by construction (a retried POST creates a second report and a second notification, which is honest); the store is append-only so a 'notified' flag has no place without a new file.",
   ]),
 "S08": dict(past="V-575", snapshot="0c3c0fcb^", prompt=(
   "execute_merge_session answers a merge request for a worker with HTTP 409 saying the worker's branch does not "
   "match what the merge operation pinned, although nothing was changed by anyone. Starting a new merge operation "
   "(new operation_id) gives the identical refusal, and so does following the suggested action "
   "REFRESH_WORKER_THEN_NEW_OPERATION (inspecting with worker_wip). Find from the code what is compared with what, "
   "where each value comes from, why the retry loop cannot escape, and design a fix that keeps the safety "
   "property." + R_FORMAT),
   checklist=[
    "The check compares the operation's expected_branch with row_branch, the sessions.branch column: both sides are platform records; git is not consulted at that point.",
    "expected_branch is pinned at acceptance (accept_merge_operation -> _session_snapshot -> inspect_worktree_identity), i.e. it comes from git; so a refusal means exactly that the sessions.branch column lags behind git.",
    "A new operation with a new operation_id does not help: acceptance pins the git branch again and the comparison runs against the same stale column.",
    "The suggested action REFRESH_WORKER_THEN_NEW_OPERATION leads to worker_wip -> branch_wip_status, which only reads git and never writes sessions.branch, so after the 'repair' both sides are what they were and the refusal repeats byte for byte.",
    "The same defect class was already solved elsewhere: switch_worktree_branch treats an idempotent repair as success and writes the record after git.",
    "Fix: move the check down and ask git (inspect_worktree_identity); if the query fails, refuse (fail-closed); if git is on the pinned branch AND the pinned HEAD, repair sessions.branch from git (via the lifecycle persist) and continue; any other state (a third branch or a diverged HEAD) is refused with a message naming all three sides (column, pinned, git) and a way out; git itself is never moved or renamed, the platform only fixes its own record.",
   ]),
 "S09": dict(past="V-620", snapshot="0f973de2^", prompt=(
   "A worker finished task 5 with merge_worker(task_outcome='continue') (merged; the task stays open for more "
   "work). Later the orchestrator tries to move the worker to task 6, either with switch_worker_branch or with "
   "merge_worker(task_outcome='complete', next_task_id=6). Both fail; switch_worker_branch reports that an open "
   "task run conflicts with the current assignment provenance, and force=True does not help. Find the chain of "
   "causes in the code and propose the options for fixing it, with trade-offs." + R_FORMAT),
   checklist=[
    "merge_worker(continue) finalizes the merge but keeps the same task_id bound and recreates the branch task-<ref>/<name> from the target (force), so worker HEAD equals target HEAD, while the task run (review_receipts row with subject_kind task_run, status requested) stays open by design.",
    "merge_worker(complete, next_task_id=...) reaches merge_worktree_to_main where target_before == worker_head returns NO_COMMITS_MERGED ('point to the same commit'), so the finalization, the only place where the run is closed normally, never runs.",
    "switch_worker_branch switches the git branch and then calls api_update_task_if_current(next, in_progress) -> _open_task_run_for_task -> db.task_run_receipt_open, which sees the still-open run of the same session for the old task and raises ValueError 'open task run conflicts with current assignment provenance'; the route rolls the branch back.",
    "force=True concerns only the git side of the switch and never reaches the task-run conflict.",
    "So it is a closed loop: neither path can close the old run, the worker stays bound to the old task forever.",
    "Fix direction chosen: release the old binding inside switch_worker_branch when the worker has no unlanded work (clean tree, no commits base..HEAD), in the same transaction as the new assignment (old task back to new or closed done with a note); unreadable state counts as 'has work' (fail-closed); the merge refusal 'branch equals main' stays, rather than empty commits or new receipt types.",
   ]),
 "S10": dict(past="V-648", snapshot="b2f143da^", prompt=(
   "The server journal shows about 830 warnings in a week of the form 'listen task exited without exception "
   "(silent death), status=...' from session listener tasks, many with status IDLE. The owner fears hundreds of "
   "lost turns. From the code, determine what this warning really means: every path that produces it, whether it "
   "indicates a lost turn, what the printed status does and does not tell, what the real risk is, and what should "
   "be logged instead. Do not try to read the journal or the production database." + R_FORMAT),
   checklist=[
    "The warning is raised by the task done-callback (_on_task_done) for ANY completion of the listener task without an exception and without cancellation, and the status in the message is read after the coroutine has already finished.",
    "A normal end of the per-turn event stream after turn_end (handle_turn_end sets IDLE/WAITING) also ends the task normally, so IDLE in the message does not mean a lost turn; much of the volume is expected end-of-stream noise.",
    "Deliberate cancellation is also reported: the loops catch CancelledError and return normally, so Task.exception() is None and the callback prints 'silent death' (for example when the listener is cancelled before compaction).",
    "The opposite ambiguity: a finally block normalizes RUNNING to IDLE when no active turn id remains, so a premature end of the stream before turn_end looks identical (status IDLE) and the callback does not call _finish_failed_running_turn; the warning cannot distinguish a normal end from an interrupted turn.",
    "An exception caught inside _turn_event_loop is logged separately as a turn error and then the finally block runs, so the callback may add the 'silent death' warning on top of a handled error; the persistent loop has its own normal returns (no backend, stream ended while IDLE during stop/restart, cancelled) and a reconnect limit of five.",
    "Conclusion/fix: it is mostly a classification and log-level defect rather than 829 lost turns; separate handled turn_end, intentional cancel and stream exhaustion with an unfinished turn; log only the unexpected exit before RUNNING is reset to IDLE, with session, backend, last event type and whether a terminal turn_end was seen.",
   ]),
 "S11": dict(past="V-680", snapshot="951d0d47^", prompt=(
   "An orchestrator learns that a worker's turn has ended only if the worker itself sends a report, or if the "
   "orchestrator had set up an 'idle' watcher job. Audit the code for every way a worker's turn can end (normal, "
   "failed, listener death, restart) and for every place where the parent is not told or the notification can be "
   "lost. List concrete holes with function names, and state the design principle for a durable fix." + R_FORMAT),
   checklist=[
    "The automatic end-of-turn report goes through TurnManager.fire_auto_report only from handle_turn_end/_idle_tail as an in-memory task; a new turn cancels it (bump_turn_gen), it is delivered once with no retry, and on refusal only a log line is written (the worker simply waits).",
    "The silent-death paths (_on_task_done / _finish_failed_running_turn, _finish_failed_continuation, the finally block in _turn_event_loop) set the session IDLE but never call the auto-report, so the parent is not told.",
    "On server restart auto_resume_all wakes the worker with a restart notice, but the parent is never told that the killed turn ended.",
    "The auto-report bypasses the durable message_deliveries mechanism (plain manager.send, no retry), and the callback silently returns when the parent session is not loaded in memory.",
    "Observed delivery failure reasons are structural (draining refusal during restart, quota gate at the receiver, backend not ready for writing), so a one-shot send will lose some reports.",
    "Durable-fix principle: record one signal per turn in a table with a unique key (session, boot, turn generation), deliver with backoff retries and a sweeper that survives restart, resolve the parent at delivery time, group simultaneous signals into one message and dedupe on the parent's side.",
   ]),
 "S12": dict(past="#93", snapshot="57474dec^", prompt=(
   "Spawning a worker, sending it a message, switch_worker_branch and merge_worker(next_task_id=...) each change "
   "several things in separate steps: git state, the sessions row, the needs_switch flag and the task status. "
   "Review these code paths for atomicity: find the distinct concrete races and failure modes where those states "
   "can diverge or an orphan is left behind (including cancellation and failures in the middle), and say what the "
   "right ordering and locking principle is. For each, say whether it is real or whether an apparent race is "
   "already prevented." + R_FORMAT),
   checklist=[
    "The suspected same-name double spawn race in a single process is NOT real: create_session does the duplicate check and the save without an await in between and sessions has UNIQUE(name, scope); across processes SQLite UNIQUE arbitrates.",
    "The early sessions row is published as an ordinary IDLE worker before create_worktree; a concurrent send can hydrate it (ensure_loaded) and start the backend in the primary checkout, after which the finishing spawn replaces the registry object (two objects, two lifecycle locks).",
    "Cancelling during asyncio.to_thread(create_worktree) leaves an orphan: the thread keeps running, the handler sees an empty worktree_path, deletes the DB row and returns cancelled, and the thread later completes git worktree add.",
    "DB identity is (scope, name) but filesystem identity is <repo_slug>/<name> and branch identity task-<id>/<name>, so two scopes spawning the same name in one repo pass the DB UNIQUE and collide in git (index.lock contention, orphan refs); create_worktree is not inside the repo flock.",
    "Spawn changes the task to in_progress and deletes the archived row before the fallible steps, so a later failure leaves the task in_progress (never reverted) and the archive erased; the task transition must happen only after worktree, session start, final session publication and registry insertion.",
    "needs_switch is read outside the shared locks: the HTTP send checks and clears it before the manager session lock and _lifecycle_lock, so send can pass the guard, then the merge sets it, and the turn starts with needs_switch=true; the gate should live in SessionManager.send (and other wake paths must go through it) with order session lock -> lifecycle -> repo; also switch_worktree_branch with ok=false can be destructive (reset --hard before the repo lock / target check, conflict leaves MERGE_HEAD) while the route treats result.branch as success.",
   ]),
}
