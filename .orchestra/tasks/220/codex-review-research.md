## Summary

F1 survives review: no path rebuilds `session._current_prompt` from pipeline prompt files for an already-running agent. However, F4–F8 contain material classification and measurement problems. In particular, the 10.0% headline is not supported because `pipelines/**` includes live-reloaded `pipeline.yaml`, not only stale prompt text.

## Findings

1. **suggestion — F4 incorrectly classifies all `pipelines/**` changes as cold.**  
   [research.md](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-hot-reload/docs/tasks/220/research.md:150) assigns the entire directory to T3 and attributes 47 commits exclusively to F1. But `pipeline.yaml` is cached by `(mtime_ns, size)` and re-read after edits in [pipeline.py](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-hot-reload/app/pipeline.py:391). Live code calls this path outside spawn—for example `_apply_manifest_effort()` runs on each new turn immediately after prompt injection logic. Manifest fields such as effort therefore can become effective without restart or reconnect. Prompt Markdown, manifest changes, and templates need separate classification. Until the 47 commits are reclassified file-by-file—and, for YAML, field-by-field—the 10.0% headline and “ten percentage points from one prompt fix” do not follow.

2. **suggestion — F4’s unit supports deployment-batch frequency, not “typical edits” or engineering payoff.**  
   A squash commit may contain one prompt-line change or a large cross-layer feature, yet each contributes one observation. Mixed commits are evidently assigned to their coldest path, while the headline then describes the “share of edits.” That measures “share of squash deployments containing at least one cold file,” not share of changed files, hunks, changes, incidents, or engineering effort. The commit-level result can still be useful, but the conclusion and ROI ranking should be narrowly named and sensitivity-tested against at least changed-file or task-level units. The checked-in task also contains no classification script, so the reported 472/47/110/74 sets cannot be audited from the research artifact.

3. **suggestion — F5’s window reconstruction duplicates or misattributes turns when messages arrive mid-turn or during compaction.**  
   Every mid-turn injection and queued message is logged as `user_message` in [session.py](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-hot-reload/app/session.py:885), while only one `turn_usage` row is written at terminal turn end. Pairing every user row with the next usage row therefore creates multiple overlapping “turns” ending at the same event. Conversely, queued messages may be paired with the current turn’s usage even though they execute in a later turn. The 7,200-second cutoff also removes precisely the longest completed turns, biasing duration and drain estimates downward; killed/hung turns have no terminal row and disappear entirely.

4. **suggestion — the 2.17 versus 2.38 agreement is not independent corroboration and has a denominator mismatch.**  
   Both estimates derive from the same session activity recorded in the same database. More importantly, 2.17 is mean concurrency across selected working-hour minutes, whereas 2.38 is conditional on restarts that caught at least one running agent, potentially at operator-chosen moments. These are not estimates of the same population parameter. Restart notices are also delayed new `user_message` sends after startup ([manager.py](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-hot-reload/app/manager.py:1816)); they identify sessions whose persisted status was `running`, not independently observed killed executions. Their numerical proximity should not be presented as validation.

5. **suggestion — F7 estimates residual lifetime of successfully completed historical turns, not the completion time of a real drain.**  
   “Maximum remaining time among active windows” is the right statistic only if admission closes every route that can create work and existing turns are guaranteed to terminate. An active agent can send or queue messages to another session; completed turns can auto-report to a parent; compaction can queue and later flush work. A gate limited to idle-worker admission would therefore allow an in-flight causal chain to keep generating work. Since the reconstructed windows exclude killed, hung, and over-7,200-second turns, the reported 87.6-minute maximum cannot establish a bound. A real drain needs a global generation/barrier semantics plus a deadline; otherwise it can fail to quiesce indefinitely. The document mentions a timeout, but its “CONFIRMED” latency distribution does not model that failure mode.

6. **suggestion — F8’s 23.3%/15.7% split is an assumed architecture boundary, not a measured benefit.**  
   The filename whitelist places all `manager.py`, `live_broker.py`, routing, persistence, scheduling, and callback work in “core,” although a per-session supervisor must own or coordinate parts of session registry, lifecycle state, event delivery, and turn admission. Changes to their IPC contract can require coordinated supervisor upgrades. Conversely, a supervisor-code change need not “kill a turn”: supervisors can be versioned and replaced after their individual session becomes idle. Thus both sides of the arithmetic can move, and counting any commit touching `session*.py` as an unavoidable killed turn bakes the current restart behavior into the proposed architecture. F8 should be marked a scenario estimate, not CONFIRMED.

7. **suggestion — the restart-only list makes several false “under any solution” claims and omits the genuinely process-bound boundary.**  
   [research.md](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-hot-reload/docs/tasks/220/research.md:292) overstates:

   - Starlette middleware can be rebuilt or replaced on a live app under admission/drain; it is risky, not impossible.
   - Pure-Python dependency changes can sometimes be loaded in a new module namespace or sidecar; only native/interpreter-level replacements are categorically process-bound.
   - Existing object instances can be explicitly migrated or replaced; adding a dataclass field is not inherently restart-only.
   - Long-running tasks can be cancelled and recreated.
   - Schema migrations can be executed online; `init_db()` being called only at startup is current wiring, not a fundamental requirement.
   - `.env` can be re-read into application configuration; systemd will not do it automatically, but a restart is not the only possible implementation.
   - Supervisor code can use rolling, per-session replacement, so item 7 contradicts the architecture being evaluated.

   Actually unavoidable or missing cases include changes to the Python interpreter/native extensions already loaded, uvicorn’s listening/process configuration, systemd unit properties, inherited file descriptors, and environment needed before process initialization. The list should distinguish “current implementation only runs this at startup” from “cannot safely change in-process.”

8. **question — No falsifying finding on F1 itself.**  
   The four direct `ROLE_SYSTEM_PROMPT()` call sites are correctly identified. The resume/compact path hashes current files but only calls `refresh_worker_memory()` on the old assembled string ([session.py](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-hot-reload/app/session.py:927)). Backend reconnect refreshes `AGENTS.md`, skills, and Codex project-doc diagnostics, but does not rebuild `_current_prompt`. `update_worker_prompt` can replace `_current_prompt` explicitly, yet it does not reread pipeline files and does not invalidate `_prompt_injected`. Therefore prompt Markdown remains stale until respawn/server reload or an explicit new refresh mechanism. What collapses is only the extrapolation from that fact to every `pipelines/**` commit.

## Verdict

The central F1 diagnosis is sound, but the load-bearing quantitative conclusions are not yet defensible. F4’s 10.0% figure must be recomputed with `pipeline.yaml` separated from prompt files; F5/F7 need turn-boundary-aware and censored-window handling; F8 and the restart-only list should be downgraded from confirmed/absolute claims to architecture assumptions. No blocking runtime defect is established because this is prose, but these are material suggestion-level issues that can change the recommendation’s stated ROI.
