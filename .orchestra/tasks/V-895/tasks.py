"""V-895 frozen task set: prompts (arm A), oracle rules, reference snapshots."""
import re

WRAP = ("You are working in the current directory, a snapshot of a software project (no git history). "
        "Work only inside this directory; do not read or list anything outside it.\n\n")

OPEN_FORMAT = ("\n\nDo not change any files. Final answer: start with 'ROOT CAUSE:' and give, in at most "
               "1200 characters, the file(s), function(s)/endpoint(s) and the mechanism.")
CLOSED_FORMAT = "\n\nEdit the files in this directory in place. Final answer: two or three sentences saying what you changed."

# Arm C: one added requirement, naming an external check.
C_SUFFIX = ("\n\nAdditionally: before finishing, name the external, independent criterion by which this result "
            "can be checked (a test, a command, or an observable fact outside your own reasoning), and apply "
            "it if you can.")

TASKS = {
 "O1": dict(kind="open", past="V-753", snapshot="86bb4e23^", prompt=(
   "In the dashboard, the agent right-click context menu has a toggle for the agent's Telegram topic. "
   "Clicking it has no lasting effect: after a refresh the setting is unchanged, and the browser console "
   "logs 'TG topic toggle failed'. Find the root cause." + OPEN_FORMAT)),
 "O2": dict(kind="open", past="V-814", snapshot="84de265c^", prompt=(
   "A dynamic workflow was run with three tasks, each with a JSON schema, budget_usd=3 and max_calls=3. "
   "The manifest shows spent_usd=0.016, dispatched_calls=3 and partial_reason=budget. The journal for every "
   "task has attempt_finished, then schema_invalid with \"invalid JSON: Expecting value at line 1 column 1\", "
   "then retry_deferred with reason=budget. No task produced valid output, although only 0.5% of the budget "
   "was spent. Find the root cause(s) in scripts/wf_run.py." + OPEN_FORMAT)),
 "O3": dict(kind="open", past="V-841", snapshot="d5e33acf^", prompt=(
   "The MCP tool get_worker_logs(name, limit=20) is slow and moves megabytes over the API for workers with "
   "long histories, even though the caller asked for only 20 entries. Find the root cause." + OPEN_FORMAT)),
 "O4": dict(kind="open", past="V-817", snapshot="095aef66^", prompt=(
   "A worker produced a DOCX and the chat showed a download link to it. A few days later, after the worker "
   "was archived, clicking the link shows 'not found', although the file exists in the project's main "
   "checkout. Find the root cause." + OPEN_FORMAT)),
 "C1": dict(kind="closed", past="a43f2686", snapshot="a43f2686^", prompt=(
   "In app/bg_jobs.py, BgJobManager.create limits a job's lifetime through timeout_seconds. For job_type "
   "'timer' a cap MAX_TIMER_TIMEOUT (8 days) is applied even when delay_seconds is longer, so a timer with "
   "a 10-day delay gets expires_at earlier than trigger_at and never fires.\n"
   "Required behavior: a timer's lifetime must always be at least delay_seconds + 3600 seconds, for any delay; "
   "the timer cap constant is removed; when the delay needs no extension the timer's timeout_seconds is "
   "clamped to [1, MAX_TIMEOUT]; all other job types stay clamped to [1, MAX_TIMEOUT]." + CLOSED_FORMAT)),
 "C2": dict(kind="closed", past="16ebb5e1", snapshot="16ebb5e1^", prompt=(
   "In app/workspace.py, _git_cmd wraps subprocess.run for git. git truncates long diffstat paths by bytes, "
   "so output can contain a cut multi-byte character; strict UTF-8 decoding then raises after "
   "`git merge --squash` has already staged changes, and the merge is left in an unknown state.\n"
   "Required behavior: when the caller passes text=True and does not pass `errors`, _git_cmd decodes output "
   "as UTF-8 with errors='replace'. An explicit `errors` argument is respected, and non-text calls are "
   "unchanged." + CLOSED_FORMAT)),
 "C3": dict(kind="closed", past="7111f3c2", snapshot="7111f3c2^", prompt=(
   "In app/session.py, the idle pre-compact floor PRECOMPACT_MIN_CONTEXT_PCT is 5. Measurements show that "
   "Claude compacts started below 30% context cut only 35-38% and rewrite the cache, while above 30% they "
   "cut 78-86%.\n"
   "Required behavior: _precompact_policy returns min_context_pct and arm_threshold of 30 for Claude "
   "sessions (PRECOMPACT_MIN_CONTEXT_PCT = 30); Codex sessions keep 5 through a new separate class constant "
   "CODEX_PRECOMPACT_MIN_CONTEXT_PCT; each backend's policy uses its own constant." + CLOSED_FORMAT)),
 "C4": dict(kind="closed", past="9fdd0499", snapshot="9fdd0499^", prompt=(
   "cron_command jobs currently kill the scheduled command after 30 seconds (_CRON_COMMAND_TIMEOUT_SECONDS "
   "in app/bg_jobs.py), which is too short for real checks.\n"
   "Required behavior: the limit is 600 seconds, and the docstring of the bg_create MCP tool in "
   "app/mcp_stdio.py tells callers that each cron_command run is killed after 600 s without a wake." + CLOSED_FORMAT)),
}

def _all(text, *groups):
    return all(re.search(g, text, re.I | re.S) for g in groups)

OPEN_RULES = {
 "O1": [r"tg-topic|toggle_tg_topic", r"save_session|session_id|\b500\b|update_session_fields"],
 "O2": [r"current_prompt|(first|initial)[^.]{0,100}(prompt|attempt|request)[^.]{0,160}schema|schema[^.]{0,160}(only|not|never)[^.]{0,80}(first|initial|retry|after)",
        r"exhausted|max_calls|call[_ -]?limit|dispatched_calls"],
 "O3": [r"get_worker_logs|mcp_stdio", r"slice|\[-limit|logs\[-|(ignor|not pass|n't pass|never pass|without|no)[^.]{0,80}limit"],
 "O4": [r"get_file_raw|/api/files/raw|files/raw", r"is_file|not found|404", r"worktree",
        r"remov|delet|archiv|gone|no longer|cleaned|missing"],
}

def score_open(task, text):
    if len(text) > 1800:
        return False
    return _all(text, *OPEN_RULES[task])
