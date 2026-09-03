# Orchestra — Full Code Review (Fable 5)

**Date:** 2026-06-10
**Reviewer:** fable-reviewer (claude-fable-5)
**Scope:** ~13,850 lines — app/main.py, session.py, manager.py, db.py, tm.py, backend_claude.py, backend_codex.py, tg_bridge.py, workspace.py, pipeline.py, models.py, auth.py (security-relevant), app/static/js/app.js (structural pass)
**Context:** MVP, small team, ~10 users, single-operator dashboard. Severity calibrated to that — not to "bank in prod".

---

## Verdict (TL;DR)

The codebase is **substantially better than typical MVP code**. The hard parts — git merge orchestration, payment distribution, SQLite concurrency, SDK zombie recovery — show real engineering: flock + merge-tree prechecks, CAS claims, BEGIN IMMEDIATE transactions, coalesced persists, turn-generation invalidation. The "pit of success" philosophy is mostly followed.

The problems cluster in three areas:

1. **Async state machine races in session.py** — the lifecycle lock exists but several paths check state outside it (mid-turn inject, compact, heartbeat self-cancellation).
2. **Silent data-integrity landmines** — the `model` column is never updated on conflict (confirmed bug, contradicts CLAUDE.md), and the ×1000 money migration heuristic re-runs on every boot.
3. **Fail-silent violations of the project's own "fail loud" principle** — a dozen `except Exception: pass` in places where silence costs hours of debugging.

Confirmed bugs: **4 × P1, 8 × P2**. Details below, file:line everywhere.

---

## P1 — Confirmed bugs

### P1-1. `change_model` does NOT persist — `save_session` upsert omits `model`
`app/db.py:457-488` — the `ON CONFLICT(id) DO UPDATE SET` list updates 30 columns but **not `model`**. `AgentSession.change_model()` (`app/session.py:967-986`) updates the field in memory and calls `save_session`, which hits the conflict branch and silently skips it.

**Effect:** change a worker sonnet→opus, restart the server → worker resumes on sonnet. No error anywhere. CLAUDE.md explicitly claims *"change_model — immediate DB persist (survives restart)"* — that claim is false. I grepped the entire codebase: no other code path writes `sessions.model` for an existing row.

**Fix:** add `model=excluded.model` (and consider `backend_type` is there but `model` isn't — they must move together anyway). Add a regression test: change model → reload from DB → assert.

### P1-2. ×1000 money migration heuristic re-runs forever — data corruption landmine
`app/db.py:387-395`:
```python
max_price = c.execute("SELECT MAX(price_rub) FROM tm_tasks").fetchone()[0] or 0
if 0 < max_price < 1000:
    c.execute("UPDATE tm_tasks SET price_rub = price_rub * 1000, ...")
```
This runs on **every** `init_db()`, with no migration-version flag. It assumes "all prices < 1000 means old thousands-unit data". For the original deployment (₽, prices ~20000) it never fires. For any open-source user whose real prices are < 1000 units (e.g. $500 tasks), the first restart **multiplies all money in the DB by 1000** — tasks, payments, allocations, balances. Then `_sanity_check` warnings start firing and nobody knows why.

**Fix:** one-shot flag (like `cost_reset_v1`) or just delete the migration — it's served its purpose for the original DB.

### P1-3. TG media buffer: late `_resolve_media` writes into the wrong batch
`app/tg_bridge.py:296-301` (timeout flush) + `366-383` (`_resolve_media`).
Flow: media message reserves slot `idx` in `buf.entries`; if download exceeds `MEDIA_WAIT_MAX=30s`, the debounce loop force-flushes (`pending_media = 0`, `entries.clear()`). When the slow download finally completes, `_resolve_media(sid, idx, content)` checks only `idx < len(buf.entries)` — **against the new, post-flush buffer**. If new messages have arrived, the media content overwrites an unrelated message's content (its `(msg, content)` tuple is replaced), and `pending_media` is decremented on the wrong generation.

**Effect:** user's text message silently replaced by a `[voice: ...]` tag; original text lost. Requires slow download + new traffic — rare but real, and undebuggable when it happens.

**Fix:** add a generation counter to `_BufState`, bump it on every flush, have `_register_media` return `(sid, idx, gen)` and `_resolve_media` drop the result if `gen` mismatches (log the orphaned media path so it's not lost silently).

### P1-4. Mid-turn inject fast path races with turn end → hibernate kills an active turn
`app/session.py:270-287` — `send()` checks `self.status == RUNNING` **outside** `_lifecycle_lock` and injects via `backend.send(message)`. If the turn ends between the check and the inject, the message starts a *new* turn while status stays IDLE (turn bookkeeping — `_bump_turn_gen`, `_turn_logs`, `_turn_start`, persist — all skipped). Consequences:

- `_schedule_hibernate()` was already armed by the turn end; after 300s of "idle" the hibernate task sees `status == IDLE`, passes its checks (`app/session.py:699-708`) and **disconnects the backend mid-turn**.
- The injected turn's auto-report/`_did_report` logic operates on the previous turn's generation.

The lock-protected re-check at `289-301` handles the slow path, but the fast path at 270 is exactly the TOCTOU it tries to avoid for latency. Mitigation that keeps the latency win: after a successful fast-path inject, cancel `_hibernate_task` and refresh `_last_msg_time`; or verify status under the lock and only do the raw inject when a listener event arrived recently.

---

## P2 — High-priority issues

### P2-1. `compact()` can inject the compact prompt into a running turn
`app/session.py:819-841` — the `status == RUNNING` check happens **before** acquiring `_lifecycle_lock`. A concurrent `send()` holding the lock can flip IDLE→RUNNING right after the check; `compact()` then takes the lock after the send releases it and feeds `COMPACT_PROMPT` into a session mid-task. Result: the "handoff summary" interleaves with live work, and the fresh-session preamble is built from garbage. Move the status check (and `_compacting = True`) under the lock.

### P2-2. Heartbeat zombie-recovery cancels and awaits **itself**
`app/session.py:745-749` → `_disconnect_backend` `:992-998`. The codex zombie path calls `await self._disconnect_backend()` from inside `_heartbeat_loop`; `_disconnect_backend` does `self._heartbeat_task.cancel()` then `await self._heartbeat_task` — that's the **current task**. The pending CancelledError fires at the await, gets swallowed by `except (asyncio.CancelledError, Exception)`, and the loop continues in a half-cancelled state (Python ≥3.11 cancellation counts now lie). The hibernate task guards against exactly this (`is not asyncio.current_task()` at `:989`) — the heartbeat needs the same guard.

### P2-3. `auto_resume_all` orphans workers that never finished their first turn
`app/manager.py:1029-1032` — resumable filter: `session_id IS NOT NULL`. A worker spawned moments before a server restart (task sent, first turn in flight, no ResultMessage yet → `session_id` NULL) is reset to idle in the DB but **never loaded**: no restart notice, no resume, orchestrator waits forever for a report. Given spawn → immediate `send(task)` (`manager.py:349`), the window is the entire first turn — minutes, not milliseconds. At minimum, load these rows and notify the parent that the task needs re-sending.

### P2-4. OAuth refresh can invalidate Claude CLI credentials; refreshed token never persisted
`app/main.py:1095-1109, 1146-1157` — on 401 the dashboard refreshes the OAuth token via `platform.claude.com` but: (a) the response's new **refresh_token** (rotation) is discarded — only `access_token` is read; (b) the new access token is stored in `_usage_cache["token"]` which is **never read anywhere** (write-only dead state); (c) nothing is written back to `~/.claude/.credentials.json`, which the Claude CLI owns. If Anthropic rotates refresh tokens, Orchestra's refresh races/invalidates the CLI's credentials — the worst possible failure mode for a system whose whole job is spawning Claude CLIs. Consider: read-only usage (skip refresh, show stale), or persist the full rotated credential set atomically.

### P2-5. Blocking subprocess calls inside async handlers stall the entire event loop
Every agent's event processing shares one loop. These handlers run synchronous subprocess/git work on it:
- `app/main.py:1429` — `/api/restart`: `subprocess.run(..., timeout=10)`
- `app/main.py:801-804` — rename: `git branch -m`
- `app/main.py:976` — `/wip`: `branch_wip_status` (2 git calls)
- `app/main.py:998` — check-conflict: `simulate_conflict` (4+ git calls)
- `app/main.py:957-960` — `_tm.api_update_task` (SQLite with BEGIN IMMEDIATE — can block up to busy_timeout 5s)
- `app/tg_bridge.py:1450` — health loop: `subprocess.run(systemctl restart)`

Each is "only" tens-to-thousands of ms, but during merges/locks a 5s stall freezes SSE streams, TG, and all agents. The codebase already knows the pattern (`asyncio.to_thread` used for merge/worktree) — apply it uniformly.

### P2-6. `merge` endpoint: state updates silently skipped for unloaded workers
`app/main.py:899-919` — after a successful merge, `found.branch/task_id/needs_switch` and the auto-switch all sit under `if not isinstance(found, dict)`. For a worker **not loaded in memory** (a dict from the DB — perfectly normal after restart) the merge succeeds but: `needs_switch` guard is never set (DB has no such column — it's memory-only state, `session.py:136`), branch/task_id in the DB stay stale, and `next_task_id` auto-switch is silently not performed. The caller gets `{"ok": true}` with no hint. Either load the session first (`ensure_loaded`) or fail loudly when it's a dict.

### P2-7. `switch_worktree_branch`: `git reset --hard` moves the OLD branch ref, outside the lock
`app/workspace.py:617-622` — the reset happens (a) before the flock is taken, and (b) **while still on the old branch**, so it rewrites the old task branch's ref to `from_ref`. Post-merge that's benign (content lives in main), but with `force=True` and unmerged commits, the commits become unreachable dangling objects with no warning of *which* sha to recover. Cheap insurance: log the pre-reset HEAD sha, and do the dirty/unmerged checks inside the lock.

### P2-8. HTML file preview iframe: `sandbox="allow-scripts allow-same-origin"` is not a sandbox
`app/static/js/app.js:437` — that attribute combination lets the framed document remove its own sandbox (same-origin + scripts = full access). Agent-written HTML (which may embed content fetched from the untrusted web) executes in the dashboard origin and can call every `/api/*` endpoint — spawn workers, read files under allowed roots, restart the server. For a localhost single-user tool this is a contained risk, but on the VPS deployment it's a real privilege-escalation path from "agent wrote a file" to "controls Orchestra". Drop `allow-same-origin`, or serve previews from a sandboxed null-origin response.

---

## Per-module assessment

### app/db.py — 7/10
**Good:** WAL + busy_timeout + foreign_keys on every connection; `bg_claim_trigger` CAS (`:825-833`) is the correct primitive for racing scheduler ticks; `bg_cron_record_fire` uses BEGIN IMMEDIATE; `change_scope` is a genuinely careful multi-table transaction with collision checks; additive-only migrations with a clear "never drop columns" comment.

**Bugs:** P1-1 (model column), P1-2 (×1000 heuristic).

**Smells:**
- `with _conn() as c:` everywhere — sqlite3's context manager commits but does **not close**; connections die by GC. Works, but it's luck-based resource management; one `contextlib.closing` wrapper would make it deterministic.
- `bg_expire_overdue` (`:928-942`) — the stale-`triggering` branch computes `triggered_at < now.replace(second=0)` (a 0–60 s arbitrary cutoff), returns those ids mixed into the "expired" list but doesn't update them. It half-duplicates `bg_reset_stale_triggering` and inflates the caller's log counts. Confusing, half-dead — delete the branch.
- `_reconstruct_costs` (`:218-241`) regex-parses human-readable log strings to rebuild billing. Acceptable as a one-shot migration; would be a bug anywhere else.
- `_migrate` has four `except Exception: pass` blocks (`:322-345, 367-378`) around table-rename repair. A migration that fails silently violates fail-loud where it hurts most.

### app/session.py — 7/10
**Good:** This is the hardest file in the project and mostly holds up. Persist coalescing (`_persist_loop`, `:1017-1041`) is correct (no lost-update window — verified the interleaving). Turn-generation counter invalidating stale auto-reports is a clean pattern. Pending-message queue with batching, compact-ack via generation-matched event, hibernate with `current_task` guard, dedicated DB thread pool — all thoughtful.

**Bugs:** P1-4 (inject race), P2-1 (compact race), P2-2 (heartbeat self-cancel).

**Smells:**
- `_log` (`:1047-1049`) — fire-and-forget `run_in_executor` on a 4-thread pool: log rows can be **inserted out of order** (UI orders by autoincrement id), and exceptions surface as "exception never retrieved" noise. A single-writer queue would fix ordering and error handling at once.
- `TURN_TIMEOUT` (`:394-400`) only triggers when an event arrives; it then injects "[system] Turn timed out. Continue" into a turn that may be fine (one long tool call) — a spurious mid-turn poke. The zombie heartbeat already covers the truly-dead case.
- `interrupt()` (`:785-791`) sets IDLE without the lifecycle lock while the listener may still be mid-event — small status flicker window.
- `status` checks via string `.value` comparisons in some callers vs enum in others — pick one.

### app/manager.py — 7.5/10
**Good:** create_session ordering (validate → resolve → worktree → start, with full rollback on `BaseException` incl. worktree removal); `_auto_commit_if_dirty` returns explicit FAILED strings instead of pretending; owned_dirs overlap check covers both memory and DB; `change_orchestrator_scope` documents and shrinks its TOCTOU windows honestly (drain-persist-before-transaction is a nice touch); orchestrators-before-workers resume order with reasoning.

**Bugs:** P2-3 (resume filter).

**Smells:**
- `_other_orchestrators_block` / `_workers_block` (`:63-127`) — `except Exception: return ""`. A DB failure during spawn silently produces a prompt without the workers list, and the orchestrator starts hallucinating worker names. Log loudly at minimum.
- `_pick_color` (`:1006-1013`) reads only in-memory sessions — colors collide with DB-stored ones after restart (cosmetic).
- `get_session_lock` / `_session_locks` grows unboundedly (one lock per session id, never pruned). Same for tg_bridge `_buffers`. Harmless at 10 users; note it.
- `remove()` (`:626-637`) — `bg_manager.cancel_by_session` called without the `if bg_manager` guard used everywhere else; None during early startup → AttributeError.
- Duplicated resume loops for orchs/workers (`:1042-1076`) — same 15 lines twice; one function with a list argument.

### app/tm.py — 8.5/10 (best module)
**Good:** The TDD heritage shows. Conn-injection design ("caller manages transactions") is exactly right; all public APIs wrap in BEGIN IMMEDIATE; `_distribute_payment` greedy-smallest-first is simple and correct; over-allocation raises (`_sanity_check:607-611`) while balance drift only warns — correct severity split; price-below-paid guard; manual `paid` status forbidden; ambiguous task ref raises with project list.

**Issues:**
- `_fire_sync` / `_fire_journal_sync` (`:714, 748`) use `asyncio.get_event_loop()` from sync code — deprecated since 3.12, and when called from a worker thread (e.g. any future `to_thread(api_update_task)`) it raises RuntimeError → **sync silently skipped** (logged as debug, not even warning). Pass the loop in or use `asyncio.run_coroutine_threadsafe` against a captured loop.
- Hardcoded default client `"aleksandr-kislinskiy"` (`:911, 931`) in an open-sourced repo — personal data as an API default. Move to env/config.
- `receive_payment` zero-price auto-close (`:398-404`) closes **all** done zero-price tasks for the client's project as a side effect of any payment — surprising action at a distance; deserves at least a docstring.
- `_sanity_check` balance mismatch only warns — fine, but there's no tool to *repair* drift once detected; warnings will just accumulate.

### app/backend_claude.py — 8/10
**Good:** Blocked-tools rationale documented inline (why disallowed_tools vs can_use_tool — `:34-40`); run_in_background denial with explanation the agent can act on; 50MB buffer for #425; telemetry/non-essential calls disabled; per-session cumulative-cost delta handled upstream in session.py; compact_boundary surfaced as status.

**Issues:**
- `connect()/reconnect()` catch `BaseException` and re-raise after cleanup — fine — but `_cleanup_failed_client` also swallows `BaseException` including CancelledError; shutdown can hang on a stuck disconnect.
- `_extract_tool_result` (`:68-83`) — JSON-sniffing every tool result and unwrapping `{"result": ...}` loses structure for any tool that legitimately returns a dict with a `result` key. Cosmetic, but lossy.
- Cache pricing constants inline (`:324`) duplicate knowledge that lives in models.py TOKEN_PRICES — same-fact-two-places.

### app/backend_codex.py — 7/10
**Good:** Honest one-shot subprocess model; synthetic `turn_end` on process death (`:197-210`) so session.py always sees a terminal event — this is the right contract; stderr tail captured for diagnostics; proxy stripped with reasoning.

**Issues:**
- **Resume drops flags** (`:62-65`): the resume invocation passes neither `-m self.model` nor `model_reasoning_effort` nor developer_instructions. If the thread doesn't pin the model server-side, a gpt-5.4-mini worker resumes as the CLI default. Verify and pin explicitly.
- Cost math (`:162-163`) charges full input price for cached tokens and sets `cost_usd_cached = cost` — cached pricing exists for Codex too; numbers shown in the dashboard are inflated.
- Message passed as **argv** (`:65, 74`): visible in `ps` to all local users (contains task text, possibly secrets), and breaks at ARG_MAX for huge prompts. stdin would be safer on both axes.
- `interrupt()` is also `disconnect()` — terminate then kill, fine, but a mid-write SIGTERM can leave worktree files half-written with no note in logs.

### app/tg_bridge.py — 6.5/10
**Good:** Debounce-batch design with explicit phase enum; media slot reservation idea is sound; flood control with important-message retry; UTF-16 entity offset handling (the classic TG trap — handled); local Bot API fast path; topic icon dedup to dodge rate limits; voice transcription caching by file_unique_id.

**Bugs:** P1-3 (buffer generation race).

**Smells:**
- `stream_logs` is a 190-line while-loop handling 7 message types with per-type formatting — the single hardest-to-modify function in the repo. The `_last_tool_msg/_last_tool_text/_last_tool_name` trio is stateful coupling between loop iterations begging for a small class.
- Tasks created in `ensure_topics` (`:868`) aren't appended to `_tasks` → not cancelled by `stop_bridge`; and if a `stream_logs` task dies (it can't — bare except inside — but if cancelled externally), nothing restarts it.
- `_mirror_send` (`:834-846`) bypasses `_tg_send_safe` — mirrors have **no flood control**; a chatty agent gets the bot rate-limited via the mirror path while the main path politely throttles.
- Hardcoded `timezone(timedelta(hours=7))` here (`:329`) *and* in main.py:625 — same magic in two files; "one way" violation. Make it `TZ_OFFSET` env.
- `logger.setLevel(DEBUG)` + handler at import time (`:22-24`) — bypasses the app's logging config; every incoming TG message logs at debug forever.
- `handle_restart` admin check is good; note `/restart` works in the main group only — mirrors can't restart (probably intended, worth a comment).

### app/workspace.py — 8.5/10
**Good:** The strongest "hard part" in the repo. flock around merge AND remove AND switch; `git merge-tree --write-tree` precheck before touching HEAD; stash/restore ordering with `did_stash`/`restore_ok` discipline and the explicit "skip pop if restore failed" branch (`:503-513`); cherry-pick fallback for unrelated histories; `_within`/`_resolve_src` symlink-escape containment; branch-checked-out-elsewhere guards; wip status that errors rather than reporting false-clean.

**Issues:** P2-7 (reset outside lock / old-branch ref move).
- `merge_worktree_to_main` is 160 lines of 6-level-deep `if/else` because errors are values (`result = {...}`) inside one giant `try`. Early-return helpers would cut the nesting in half without changing semantics.
- `remove_worktree` never deletes the branch — `task-N/name` branches accumulate forever in the main repo (dozens by now, presumably). Add optional branch deletion after successful merge.
- `cleanup_stale_worktrees` skips dirty worktrees (good) but doesn't report them anywhere persistent — a stale dirty worktree lives forever silently.

### app/pipeline.py — 9/10
**Good:** Closest to flawless. `extra="forbid"` on every model; `_is_safe_rel` traversal validation on *every* user-controlled path (layers, modules, copies, symlinks, docs); can_spawn graph validated at load; fail-closed default with documented fail-open escape hatch; `list_pipelines` marks broken manifests instead of dying; defaults→role merge semantics documented per-field.

**Issues:**
- `lru_cache(maxsize=None)` on `load_pipeline` (`:265`) — manifest edits require a server restart, which contradicts the prompt hot-reload story elsewhere (template_hash machinery). Either document "yaml = restart" or add a mtime-keyed cache.
- `validate_spawn` "fail-open: unknown parent → пропуск" means a typo'd parent role in fail-open mode silently grants full spawn rights. It's documented, but the asymmetry (typo = permissive) is the dangerous direction.

### app/models.py — 9/10
Single source of truth, does its one job. `resolve_model` returning the raw input on miss (`:80`) pushes validation to callers — main.py validates, but `create_session` via spawn queue trusts the job dict; a bad model string from MCP lands in `backend_for_model` → defaults to "claude" backend with an invalid model → SDK error at first send instead of spawn-time 400. Tighten: raise in `resolve_model` or validate in `enqueue_worker_spawn`.

### app/main.py — 6.5/10
**Good:** Pydantic request validation with real validators; global exception handler with traceback logging; GitHub webhook HMAC via compare_digest; `_is_safe_path` is a thoughtful deny-list (env/ssh/git/db/keys + home dotdirs) on top of an allow-list; upload path traversal guarded via `relative_to`; SSE backoff polling; git-status TTL cache.

**Bugs/issues:** P2-4 (OAuth), P2-5 (blocking calls), P2-6 (merge dict-path), P2-8 (iframe — counterpart in app.js).

**Smells:**
- `logger` used at `:76` and `:634` but **defined at `:1445`** as `logging.getLogger("orchestra.webhook")`. Works only because the module fully imports before serving; every main.py error logs under the webhook logger's name. Move to the top with a sane name.
- `/api/sessions/{name}/send` (`:602-635`): 30 lines doing fuzzy name matching with substring similarity inside the endpoint — helpful for agents, but it means a typo'd name can deliver to `ensure_loaded_any(name)` in a **different scope** (`:607`) — cross-project message misdelivery by design. At least require an explicit flag for cross-scope fallback.
- Hardcoded `timezone(timedelta(hours=7))` (`:625`) — see tg_bridge duplicate.
- `_ALLOWED_ROOTS` lazy-init mutates a module global list (`:265-283`) — includes `/tmp` and `$HOME` by default; combined with cookie-auth'd `/api/files/content`, the dashboard can read most of the user's files. Deny-list covers the obvious secrets; on a multi-tenant VPS this is still generous. Document the threat model.
- `update_progress` (`:1006`): `int(req.get("percent", 0))` — non-numeric input → 500 via global handler instead of 400.
- Dead state: `_usage_cache["token"]` written at `:1154`, never read.

### app/auth.py — 6/10
compare_digest everywhere — good. But the design: **token = HMAC(password, username), deterministic, no expiry, no revocation**. Same token forever, on every device; logout deletes the cookie but the token stays valid; the only rotation is changing the password. There's also no rate limit on `/login`. For one operator behind a VPS it's survivable; it's also ~20 lines away from signed-timestamp tokens (`itsdangerous`-style) with real expiry. Worth those 20 lines before more users get dashboards.

### app/static/js/app.js — 6.5/10 (structural pass, not line-by-line)
**Good:** DOMPurify applied consistently at every `marked.parse` sink I checked (18+ call sites) including CSV cell rendering — the XSS discipline is real, which matters since agents render untrusted web content into logs. MAX_CHAT_NODES cap; local-echo dedup via `localMessages`; draft preservation per agent.

**Issues:**
- P2-8: the iframe sandbox combo (`:437`).
- 4,518 lines, 46 top-level mutable globals, ~99 functions in one file. The leaf extraction (utils/tool-renderers/usage) was the right move; the remaining monolith mixes SSE protocol, rendering, modals, tasks UI, and git panels with shared global state (`selectedAgent`, `currentScope`, `chatLogs`) mutated from everywhere. Next extraction candidate: the SSE/stream state machine (it owns `eventSource`, `streamBubble`, `pendingBubble`).

---

## Cross-cutting themes

1. **Fail-silent vs fail-loud.** CLAUDE.md declares "Fail loud", but I count ~25 `except Exception: pass / return ""` sites, several in places where silence converts a 1-minute fix into an hour-long hunt: prompt blocks (manager:84,127), migration repair (db:322-378), task-status update on spawn (manager:549-551), api_update_task in merge/switch (main:916-918, 958-960). Recommend a sweep: every bare swallow gets at least `logger.warning` with context.

2. **State lives in memory that pretends to be durable.** `needs_switch`, `last_task_sender`, `_pending_messages` are memory-only; a restart silently drops the merge guard and queued messages. Either persist them or document loudly that restart loses them (the restart-notice message partially covers it).

3. **Same fact, two places.** UTC+7 in two files; cache pricing in backend_claude + models.py; `_normalize_task_id` (workspace) vs `_parse_task_ref` (tm) — two parsers for the same ref grammar that already diverge (one accepts bare `#N`, prefixes case-insensitively, etc.).

4. **The async/sync boundary is the bug factory.** Every P1/P2 race here is a status check outside the lock or a sync call on the loop. A small convention — "status transitions only under `_lifecycle_lock`; subprocess only via `to_thread`" — enforced in review would have prevented all of them.

## What's genuinely good (keep doing this)

- workspace.py merge discipline (flock, precheck, stash ordering) — better than most human-written merge tooling.
- tm.py data layer — conn injection + IMMEDIATE transactions + sanity invariants; the TDD origin is visible.
- pipeline.py validation posture — strict schema, path containment, fail-closed.
- bg job CAS claim + status state machine in db.py.
- Inline WHY comments are consistently real WHYs (cache-read pricing, UTF-16 offsets, squash-vs-rebase) — rare and valuable.
- 19 test files / 500+ tests passing in CI for an MVP of this size.

## Top-5 actions (ordered by value/effort)

1. Add `model=excluded.model` to `save_session` upsert + regression test (5 min, fixes a CLAUDE.md-documented lie). — `db.py:457`
2. Delete or version-flag the ×1000 money migration. — `db.py:387`
3. Move `compact()`'s status check and the `send()` fast-path inject under `_lifecycle_lock` (or cancel hibernate after fast-path inject); add the `current_task` guard to heartbeat's disconnect path. — `session.py`
4. Generation counter for TG media buffers. — `tg_bridge.py:258-383`
5. `asyncio.to_thread` the five blocking handlers in main.py; fix the OAuth refresh to stop touching CLI credentials it can't safely own.

---
*Found-but-not-fixed items above should land in TODO.md / BUGS.md — recommend the orchestrator triage P1-1..P1-4 first.*
