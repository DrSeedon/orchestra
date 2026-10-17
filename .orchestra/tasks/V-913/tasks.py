"""V-906 frozen task set. T = root cause with a false obvious version, K = root cause obvious, C = creative.
Reference causes come from fixing commits / past reports (see protocol.md); the model sees only symptoms + the code snapshot
from the parent of the fixing commit."""
import runpy
from pathlib import Path

PHRASE = ("Если выясняешь, откуда взялось наблюдаемое (ошибка, число, поведение, формат), то гипотеза принята, "
          "только когда предложенный тобой процесс воспроизводит наблюдаемое точно, а не правдоподобно. "
          "Если воспроизвести не удалось, так и напиши.")

WRAP = ("You are working in the current directory (a snapshot of a software project without git history, or an empty "
        "scratch directory). Work only inside this directory; do not read or list anything outside it. "
        "If your tool set can run commands: the project's Python with dependencies is "
        "/home/kesha/orchestra/.venv/bin/python (run it from this directory with PYTHONPATH=. so that `app` is imported "
        "from this snapshot, e.g. `PYTHONPATH=. /home/kesha/orchestra/.venv/bin/python -m pytest tests/<file> -q`). "
        "Tests in tests/ are existing tests of this snapshot. Never touch the network or the live service.\n\n")

FORMAT = ("\n\nYou may create scratch files under ./scratch/ but do not modify any existing file. Final answer: at most "
          "400 words, plain text, starting with 'CAUSE:'. State the root cause, the evidence (file/function names) and "
          "the fix you recommend.")

# kind T: false obvious version exists (decoy). kind K: cause is obvious.
# Checklist: P = the root cause (the answer counts as correct only if P is clearly stated as THE cause),
# S = supporting facts, D = the false obvious version (flag if the answer names it as the cause).
ROOT = {
 "T1": dict(kind="T", fix="8239760c (#416)", prompt=(
   "An orchestrator called merge_worker for a worker branch `task-416/worker`. The branch has one new commit (a new "
   "tracked file worker.txt): `git log main..task-416/worker` shows it. The worker's worktree is a linked worktree of "
   "a repository whose main checkout holds `main`. The call returned:\n"
   "{\"code\": \"NO_COMMITS_MERGED\", \"message\": \"merge produced no new commits\", \"next_action\": {\"code\": "
   "\"CHECK_WORKER_THEN_NEW_OPERATION\", \"message\": \"No commits reached the target branch; verify the worker "
   "branch before retrying.\"}}\n"
   "The target branch `main` did not move. Repeating the call gives the same answer. Find the real reason the merge "
   "did not happen. Orchestra's merge code is in app/." + FORMAT),
   P="The real failure is that the target (main) checkout has a dirty working tree (an untracked or modified file): the workspace layer refuses to merge ('target working tree is dirty') before any git mutation.",
   S=["normalize_merge_result (app/merge_operations.py) replaces the specific raw error with the generic NO_COMMITS_MERGED / 'merge produced no new commits' because zero commits were merged, discarding the actual reason.",
      "The branch/commit itself is fine: with the target cleaned the same worker commit merges (commits_merged=1)."],
   D="The worker commit is empty/a no-op, or `main` is already checked out in another worktree so git checkout fails (busy-guard), or the diff budget/gate rejected it."),
 "T2": dict(kind="T", fix="bec4f378", prompt=(
   "merge_worker is refused for the branch `task-56/voice-astra` with the error \"cannot derive target-relative merge "
   "paths\". The branch has 2402 changed files, about 1900 of them PNG images, about 60 of them renames. Merges of "
   "small branches work. The same call fails identically on every retry. The test-gate (oracle) code has not been "
   "changed recently. Find the root cause. Orchestra's merge-gate code is in app/." + "\n\nA teammate's first guess, not yet checked: the branch's merge base cannot be found, so the base-relative path list comes back empty."
   + FORMAT),
   P="`changed_paths` in app/merge_test_gate.py runs `git diff --name-only base...HEAD` through `_git` with a 15 s timeout; rename detection on many binary files takes far longer, TimeoutExpired is swallowed, `_git` returns None, and changed_paths returns None, which produces the 'cannot derive target-relative merge paths' error.",
   S=["The fix is `--no-renames` (also more accurate: both old and new paths are affected) and/or a larger timeout.",
      "The error text blames path derivation, but nothing is wrong with the oracle's logic or the merge base: it is a swallowed timeout."],
   D="The merge base / `base` cannot be found, the branch history is broken, git is missing, or the oracle (test gate) logic is wrong."),
 "T3": dict(kind="T", fix="e86fc63f", prompt=(
   "Since 12 September the MCP tool `codex_review` fails for every project. The tool's MCP stdio server dies on start "
   "with `database schema needs offline migration before starting Orchestra` (raised from app/db.py). The live "
   "Orchestra server itself is healthy: it was started with the environment variable ORCHESTRA_DB_PATH pointing at "
   "its own database file, and that database was migrated on 11 September. The default file data/orchestra.db exists "
   "in the checkout. Nothing in the review code changed. Find the root cause." + "\n\nA teammate's first guess, not yet checked: the live database is behind on schema and needs the offline migration the message asks for."
   + FORMAT),
   P="The MCP stdio subprocess does not inherit ORCHESTRA_DB_PATH (and the task repository/prefix variables): app/runtime_env.py MCP_BASE_ENV passes only proxy and INTERNAL_TOKEN variables. The child therefore opens the default data/orchestra.db (non-empty, user_version=0), and the schema guard in app/db.py refuses to start.",
   S=["The fix is to propagate ORCHESTRA_DB_PATH, ORCHESTRA_TASK_REPOSITORY, ORCHESTRA_TASK_PREFIX (whatever selects state for the parent) into the child environment.",
      "The error message is misleading: the live database does not need migration; the child is looking at the wrong database."],
   D="The live database needs an offline migration / the schema version of the live DB is wrong, or the review tool code is broken."),
 "T4": dict(kind="T", fix="fbc9e40d", prompt=(
   "The owner edits the file `.env` in the checkout and sets `QUOTA_GATED_LANES=` (empty) to switch the quota gate "
   "off for some lanes. app/quota_gate.py has a hot reload of this file (it re-reads `.env` when its mtime changes), "
   "so a restart should not be needed. In the production service the gate keeps holding with the old value until the "
   "service is restarted; the debug log shows that `.env` WAS re-read after the edit (new mtime, new values parsed). "
   "In a plain local shell the same edit takes effect at once. Production runs as a systemd unit with "
   "`EnvironmentFile` pointing at that same `.env`. Find the root cause." + "\n\nA teammate's first guess, not yet checked: the mtime check does not fire reliably, so the reload never really happens."
   + FORMAT),
   P="In app/quota_gate.py `_live_quota_env` gives priority to the values captured from the process environment at startup (`_startup_quota_env`) over the re-read `.env`. Under systemd `EnvironmentFile` EVERY key of `.env` is also in the process environment at start, so the startup copy of the file's old value always overrides the edited file; the hot reload is dead in production.",
   S=["A local shell works because there the quota variables are not in the process environment at startup, so the file is the only source.",
      "The fix distinguishes startup values that are mere copies of the `.env` content (file-owned, must follow the file) from genuine external settings (shell, unit), which must still win."],
   D="The mtime check, caching or reload trigger does not fire / the file is not re-read / a parsing bug in dotenv handling."),
 "T5": dict(kind="T", fix="10698051 (V-882)", prompt=(
   "In the journal of a multi-agent platform there are 14 error rows `listen task exited unexpectedly while RUNNING` "
   "in a month. Each is followed by an automatic report to the orchestrator `Turn failed before an explicit report "
   "(no output)` and the worker goes IDLE, although in the next log row the worker is alive and a new turn starts. "
   "Two excerpts (id|time|type|text):\n"
   "374011|12:28:43.329|error|turn FAILED: rate_limit\n374012|12:28:43.368|status|mailbox: 2 — продолжаю ход вместо пробуждения\n"
   "374013|12:28:43.377|user_message|[from:orchestrator] ...\n374014|12:28:43.386|error|listen task exited unexpectedly while RUNNING\n"
   "374015|12:28:43.470|status|codex turn=01a0aa30 started\n"
   "---\n"
   "557152|11:53:20.800|status|turn ended (end_turn ...)\n557154|11:53:20.820|status|mailbox: 1 — продолжаю ход вместо пробуждения\n"
   "557156|11:53:20.846|error|listen task exited unexpectedly while RUNNING\n557157|11:53:20.830|user_message|[from:fix-api] ...\n"
   "Several of the 14 happened after the provider's quota was exhausted. Find the root cause of the false "
   "`listen task exited` verdict (app/session.py, app/session_turns.py)." + "\n\nA teammate's first guess, not yet checked: the Codex listener really crashes when the provider quota runs out."
   + FORMAT),
   P="Race between the finishing listener of turn N and the next turn: when turn N ends with a non-empty mailbox, handle_turn_end immediately starts turn N+1 via send() (status=RUNNING belongs to N+1), while the turn-N listener task has not fully exited and `_listen_task` still points at it. When it finishes, `_on_task_done`/the listener's finally sees status RUNNING and declares silent death, forcing IDLE and sending the failure auto-report, although turn N+1 is alive.",
   S=["The provider quota exhaustion is only a frequent reason for turn N to end followed by queued messages; its own error was logged correctly and then overwritten by the false verdict.",
      "The fix: remember the turn generation at listener start and ignore the end of a listener when a newer turn has started since."],
   D="The listener really crashed/died (an exception, process death, provider/quota failure) or the Codex process was lost."),
 "T6": dict(kind="T", fix="17a7d398 (V-756)", prompt=(
   "A `dynamic_workflow` / `scripts/wf_run.py` batch of 10 byte-identical agent calls (same prompt, same writable "
   "workspace option) at concurrency 3 aborts the whole stage with `ValueError: worktree already exists`, while "
   "batches whose prompts differ work. It happens on a fresh run directory: before the run `git worktree list` shows "
   "no leftover worktrees, and the run is not a resume. Find the root cause (scripts/wf_run.py and app/)." + "\n\nA teammate's first guess, not yet checked: stale worktree directories left over from earlier runs collide with the new ones."
   + FORMAT),
   P="The writable worktree name in scripts/wf_run.py `_run_attempt` is built from `call_key[:12]` only; call keys of identical payloads differ only by an occurrence suffix (`:0`, `:1`, ...) that is cut off, so all identical calls get the same worktree name/path; the first creates it, the others (serialized by the repo lock) hit 'worktree already exists'.",
   S=["The exception from one preparation escapes via asyncio.gather and aborts the whole stage while siblings are still preparing.",
      "The fix: include the full call key (with occurrence suffix) in the worktree name."],
   D="Stale worktrees from earlier runs, a race in git worktree creation under concurrency, or a concurrency/semaphore bug."),
 "T7": dict(kind="T", fix="d1bd9580", prompt=(
   "The owner cannot switch the model of an orchestrator session. Every attempt returns `dialog switch blocked; "
   "source retained: text_tail_source_release_failed` (error_code text_tail_source_release_failed in app/session.py). "
   "The orchestrator's Claude CLI process died earlier (its pid no longer exists). Retrying always fails; the session "
   "itself is otherwise idle. Find the root cause." + FORMAT),
   P="Releasing the source backend raises: `ClaudeBackend.disconnect` calls the SDK client's disconnect, which for an already dead process fails with AttributeError (inside the SDK transport, `.returncode` on a None process), and the unconditional `raise` turns an already-released resource into a failure that blocks the model switch.",
   S=["Disconnect only has to free the resource, and it is already free when the process is gone, so this error should count as success; any other error should still propagate.",
      "text_tail_source_release_failed in app/session.py is the symptom reporting a failed source release, not a failure of the text-tail handoff logic itself."],
   D="A lock, a busy/running state or a bug in the text-tail/dialog handoff logic itself blocks the switch."),
 "T8": dict(kind="T", fix="495eb220", prompt=(
   "The non-Claude agent harness has a `bash` tool (app/harness/tools.py) with a timeout. A call with timeout=30 on "
   "some commands returns at about 30 s with 'harness timeout ... killed' and partial output, as designed, but on "
   "other commands the tool call does not return at all for many minutes after the timeout, and the agent looks "
   "frozen. Find the root cause of the hang." + "\n\nA teammate's first guess, not yet checked: the timeout is not enforced because of how wait_for and shield are combined."
   + FORMAT),
   P="After the timeout the code kills the process but then `await reader` (the task running `proc.communicate()`), which waits for EOF on the stdout pipe; if the command started background/child processes that inherited the pipe (e.g. `cmd &`, nohup), the pipe stays open after the killed shell, so communicate never returns until those children exit.",
   S=["Plain commands return on time because killing the shell closes the pipe; only commands leaving inherited pipe holders hang.",
      "The fix: read output into a buffer outside the reader task and stop waiting for EOF after the kill/timeout."],
   D="The timeout is not applied / wait_for or shield is wrongly used, or the kill does not work on the shell itself."),
 "K1": dict(kind="K", fix="4b185fdc", prompt=(
   "When pytest run by the merge test gate times out, `merge_worker` crashes with:\n"
   "  File \"app/merge_test_gate.py\", line 125, in run_pytest\n    out = (exc.stdout or \"\") + (exc.stderr or \"\")\n"
   "TypeError: can only concatenate str (not \"bytes\") to str\n"
   "(or the reverse: bytes + str). It happens only on timeouts, never when pytest finishes. Find the root cause." + FORMAT),
   P="On `subprocess.TimeoutExpired`, `exc.stdout`/`exc.stderr` hold raw bytes (or None) even when the call used text=True, so concatenating them with each other or with a str fails; the bytes must be decoded separately before joining.",
   S=["The non-timeout path works because CompletedProcess output is already str."],
   D="n/a"),
 "K2": dict(kind="K", fix="16ebb5e1", prompt=(
   "A `git merge --squash` run by Orchestra for a project with Cyrillic file names raised "
   "`UnicodeDecodeError: 'utf-8' codec can't decode byte 0x80 in position 4021: invalid start byte` AFTER the squash "
   "had already been staged, so the merge ended in state UNKNOWN. Git itself had no error. The failing helper is in "
   "app/workspace.py (the subprocess wrapper). Find the root cause." + FORMAT),
   P="The wrapper runs git with text=True and strict utf-8 decoding; git's diffstat truncates long path names by BYTES, cutting a multi-byte (Cyrillic) character in half, which yields invalid UTF-8, and strict decoding raises after the side effect already happened.",
   S=["Fix: decode git output with errors='replace'."],
   D="n/a"),
 "K3": dict(kind="K", fix="a43f2686", prompt=(
   "`bg_create(type='timer', delay_seconds=864000)` (10 days) returns a job id, but the timer never fires and never "
   "wakes its target; the job later shows status `expired`. Timers with delays up to 3 days work. Find the root "
   "cause (app/bg_jobs.py)." + FORMAT),
   P="The timer's expiry (timeout_seconds) is capped at MAX_TIMER_TIMEOUT = 8 days after being raised to delay+3600, so for delays above about 8 days the job expires before trigger_at and is marked expired instead of firing.",
   S=["Fix: no 8-day cap for timers; the expiry must always be later than the trigger time."],
   D="n/a"),
 "K4": dict(kind="K", fix="cb96eb6f", prompt=(
   "On an Orchestra instance where the dashboard credentials DASHBOARD_USER and DASHBOARD_PASSWORD are empty "
   "(dashboard authorization is off), every message typed in the dashboard chat is rejected with HTTP 403 "
   "`SOURCE_PROVENANCE_REQUIRED: a sender or authenticated operator is required`. The frontend sends only "
   "`{message, scope}`. Find the root cause (app/routes/sessions.py, app/auth.py)." + FORMAT),
   P="send_message requires either a sender or a proven operator (valid session cookie). With dashboard auth disabled `validate_session` always returns False, so no operator can ever be proven, and the frontend sends no sender; the provenance gate therefore rejects every dashboard message.",
   S=["Fix: when the operator is not provable, record the origin as unknown instead of refusing to deliver."],
   D="n/a"),
}

_cre = runpy.run_path(str(Path(__file__).resolve().parent.parent / "V-896" / "tasks.py"))["CREATIVE"]
CREATIVE = {new: _cre[old] for new, old in (("C1", "K1"), ("C2", "K2"), ("C3", "K4"), ("C4", "K5"))}

JUDGE_CRITERIA = runpy.run_path(str(Path(__file__).resolve().parent.parent / "V-896" / "tasks.py"))["JUDGE_CRITERIA"]

GRADER_PROMPT = (
 "You grade an answer to a root-cause question against a reference. You do not know how the answer was produced. "
 "Reference root cause P, supporting facts S, and a false version D (may be 'n/a') are given. Score:\n"
 "- primary: 1 if the answer clearly states P as THE cause (same mechanism, different wording is fine; a mere list of "
 "candidate causes without choosing P scores 0); 0.5 if only part of the mechanism is stated or P is mentioned but not "
 "chosen as the cause; 0 otherwise.\n"
 "- supporting: one number 0/0.5/1 per S item, in order.\n"
 "- decoy_main: true if the answer names D (the false version) as its main conclusion, else false.\n"
 "- reproduction: 'ran' if the answer says it reproduced the observation by actually running something and gives the "
 "result; 'not_reproduced' if the answer explicitly says it could not reproduce / could not run / did not verify by "
 "running; 'none' if it says nothing about reproduction.\n"
 "Do not reward length or extra material. Reply with a JSON object only: "
 "{\"primary\": <number>, \"supporting\": [<numbers>], \"decoy_main\": <bool>, \"reproduction\": \"ran|not_reproduced|none\"}.")
