## Tests

Test status: not green.

Commands run:

```bash
uv run pytest
```

Failed before pytest. `uv` tried to initialize cache under `/home/maxim/.cache/uv`, which is read-only in this environment.

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest
```

Failed before pytest because `uv` tried to fetch packages from PyPI and network access is blocked.

```bash
.venv/bin/python -m pytest
```

Failed during collection because pytest also collected tests inside generated worktrees:

```text
ERROR collecting worktrees/cwd-final/tests
ERROR collecting worktrees/orch-worker-1/tests
ModuleNotFoundError: No module named 'tests.conftest'
```

This is a repo hygiene issue: `pyproject.toml` should restrict pytest discovery to `tests/` and exclude `worktrees/`.

```bash
timeout 60s .venv/bin/python -m pytest tests -q
```

Timed out with exit code `124` and no completed result.

Targeted results:

```bash
.venv/bin/python -m pytest tests/test_db.py tests/test_workspace.py -q
# 45 passed in 0.32s
```

```bash
timeout 20s .venv/bin/python -m pytest tests/test_api.py -q
# exit 124
```

```bash
timeout 20s .venv/bin/python -m pytest tests/test_session.py -q
# exit 124 after one passing test
```

```bash
timeout 20s .venv/bin/python -m pytest tests/test_manager.py -q
# exit 124 after one passing test
```

The current test suite does not give a reliable safety signal. The fast DB/worktree tests pass, but the lifecycle/API/session tests hang. There are also no integration tests proving real SDK/MCP delivery semantics, worker callbacks, spawn failure reporting, or permission safety.

## Architecture Assessment

Assessment: fragile, close to duct-tape.

There is a reasonable skeleton here: `AgentSession` owns one SDK client, `SessionManager` owns lifecycle and persistence, workers get git worktrees, FastAPI exposes a dashboard/API, and SQLite is enough for a local orchestrator. That part is salvageable.

The control plane is not sound. The system's most important behaviors are currently implemented by avoiding broken SDK paths rather than replacing them with explicit, observable, durable control mechanisms. Several operations return success before the operation has happened, failures are logged but not returned to the orchestrator, and one major operation (`send_to_worker`) no longer performs the action its name promises.

The architecture is especially weak around four boundaries:

- Permission boundary: `bypassPermissions` gives the model full tool authority.
- Message boundary: worker communication is a mix of SDK turns, log writes, and HTTP callbacks.
- Lifecycle boundary: spawn/kill are async side effects without job state or failure propagation.
- Hang boundary: SDK receive loops and MCP control calls have no hard timeout/recovery model.

This is not ready to ship as a reliable orchestrator. It can be used as an experimental local prototype if the operator understands that workers may not receive messages, jobs may fail silently, and model/tool access is effectively trusted.

## Workaround Analysis

1. `bypassPermissions` instead of `can_use_tool`: hack.

Reason: using `bypassPermissions` may be the only way around the current SDK `can_use_tool` stdin bug, but architecturally it removes the permission layer instead of replacing it. On workers this is somewhat contained by git worktrees, but `workspace.py` copies `.env` into worktrees and the model can still run shell commands. On orchestrators it is worse because the orchestrator shares the user's cwd. This is not acceptable as a long-term permission model.

Minimum acceptable replacement: enforce an application-side allow/deny policy before tool exposure, run agents under OS-level sandboxing where possible, do not copy secrets into worker worktrees by default, and make dangerous tools unavailable rather than relying on SDK permission callbacks.

2. `send_to_worker = log-only`: hack, and currently a semantic break.

Reason: `app/tools.py` logs a `user_message` directly with `session._log(...)` and returns success. It does not call `session.send()`, does not enqueue a turn, and does not inject a message into the worker context. The response says "Worker will see it in next turn", but the worker has no mechanism that automatically reads its own persisted logs. This is not "degraded messaging"; it is not messaging.

This is the most damaging workaround because it breaks the orchestrator contract. A system where the orchestrator cannot reliably send a task/update to a worker is not a working orchestrator.

3. `kill_worker = asyncio.create_task`: hack.

Reason: returning quickly from MCP handlers is correct, but untracked fire-and-forget is not. `kill_worker` returns "kill queued" while `_manager.stop()` may fail, hang, or archive incorrectly. There is no job id, no status, no done callback, no error record visible to the orchestrator, and no retry/timeout.

Reasonable shape: make kill a managed job with a durable/inspectable state: `queued`, `running`, `succeeded`, `failed`, `timed_out`. The MCP tool can still return immediately, but the operation must be observable.

4. `spawn_worker = queue`: reasonable trade-off, incomplete implementation.

Reason: moving spawn out of the MCP control path is the right direction. Direct spawn previously competed with SDK/MCP control response handling and could hang the orchestrator. `asyncio.Queue` plus a supervisor loop is a legitimate design.

The current implementation is still too weak: `enqueue_worker_spawn()` returns no job id, spawn failures are only logged, duplicate names fail later and invisibly, the queue is in-memory only, the `0.5s` delay is a magic timing dependency, and there is no `list_spawn_jobs`/status surface. This is an incomplete job system, not a complete control-plane fix.

5. Worker HTTP callback instead of MCP send_message: hack, but an understandable emergency escape hatch.

Reason: using a separate HTTP channel can be a valid design if MCP injection deadlocks. But the current version is hardcoded into `worker_prompt.md` as `http://127.0.0.1:8888`, depends on `curl` through Bash, has no auth/token, assumes the server is on that port, and trusts prompt-substituted `scope`/agent names. It is also not represented as a first-class transport abstraction in code.

This can become reasonable if made configurable and authenticated: pass callback URL/token through worker config, validate sender/session/scope server-side, and expose callback delivery state in the manager.

6. `include_partial_messages=False`: reasonable trade-off.

Reason: disabling partial streaming to avoid SDK buffer pressure is acceptable. Live preview in the dashboard is nice-to-have; a stable control plane matters more. The code still has stream handling paths, but with partials disabled the product loses preview, not correctness.

This is one of the few workarounds that is a clean trade-off rather than a broken semantic.

7. Prompt rule "max 2 MCP calls": hack.

Reason: prompt rules are not control-plane engineering. The model can ignore the instruction, tool-call planning can change across models, and a user can ask for a workflow that naturally needs more than two control operations. If three MCP calls hang the system, the system needs enforced throttling, queueing, or per-turn tool-call guards in code.

The prompt is acceptable as a temporary operator warning. It is not an architectural solution.

## Blocking Issues

1. Fix worker message delivery.

`send_to_worker` must either deliver a real turn or be renamed to something like `append_worker_log`. The current behavior lies to the orchestrator. If SDK `session.send()` blocks, build a managed worker inbox: persist messages, have the worker explicitly poll/read inbox through a safe tool or callback, and mark messages delivered/acknowledged.

2. Replace untracked fire-and-forget with managed jobs.

Spawn and kill need job ids, visible status, error persistence, timeout, and cancellation semantics. Returning "queued" is fine only if the orchestrator can later inspect whether the operation actually succeeded.

3. Add hard timeouts and recovery around SDK turns.

`AgentSession._run_turn()` awaits `query()` and `_listen_loop()` without a hard deadline. A hung SDK receive loop can leave sessions permanently running and tests permanently hanging. Add turn timeout, interrupt/disconnect recovery, terminal error state, and explicit archive behavior.

4. Stop using unrestricted `bypassPermissions` as the only safety model.

If `can_use_tool` is unusable, the replacement must be outside the SDK callback. At minimum: no secret copying to worktrees by default, restrict tool exposure per role, validate cwd/worktree boundaries, and make dangerous actions opt-in.

5. Make HTTP callbacks configurable and authenticated.

Hardcoded `127.0.0.1:8888` is not maintainable. Workers should receive a callback URL and one-time token from the manager, not from static prompt text. The API should reject callbacks that do not match worker identity/scope.

6. Fix test discovery and hanging lifecycle tests.

Configure pytest to only collect `tests/` and exclude `worktrees/`. Then fix the hanging `test_api.py`, `test_session.py`, and `test_manager.py` paths. A project whose unit tests hang around the same lifecycle paths that production depends on has no credible regression safety.

7. Make persistence/logging failures visible.

`AgentSession._persist()` and `_log()` submit DB writes through `run_in_executor()` and discard the future. That hides DB failures and allows state/log loss on shutdown or crash. Critical lifecycle transitions should be awaited or routed through a managed writer with failure reporting.

8. Scope all agent lookups.

`find_worker()` and `find_session_id_by_name()` search by name only. The rest of the data model treats `(name, scope)` as the identity. In a multi-repo orchestrator this can kill, log, or message the wrong worker.

## Suggestions

1. Create a real control-plane model.

Introduce explicit tables/objects for jobs, inbox messages, callback events, and terminal errors. The orchestrator should operate on these records instead of inferred side effects in logs.

2. Separate transports from agent lifecycle.

SDK turn delivery, log append, HTTP callback, and future MCP injection should be separate transport implementations behind one interface. Right now they are mixed across prompts, tools, and session internals.

3. Add integration tests with a fake SDK transport.

Mocking `ClaudeSDKClient` methods is not enough. Build a fake transport that can simulate `ResultMessage`, hangs, control request deadlock, partial messages, tool results, and disconnects. Test message delivery and failure visibility end-to-end through FastAPI/MCP tool handlers.

4. Replace magic sleeps with readiness signals.

`await asyncio.sleep(0.5)` in the spawn loop is a timing patch. Prefer "control response returned -> job picked by supervisor" boundaries, or at least schedule from a supervisor task with explicit yield/readiness state rather than a fixed delay.

5. Move blocking cleanup to threads too.

`create_worktree()` is already wrapped with `asyncio.to_thread()`, but `remove_worktree()` in `manager.remove()` still runs synchronously in the event loop. Use the same pattern for cleanup.

6. Improve archived/terminal lifecycle invariants.

Define one invariant: active sessions live in `sessions`; terminal sessions live in `archived`; DB is source of truth after process restart. Then enforce it in one manager-owned lifecycle path, not partially in `AgentSession` callbacks.

7. Make dashboard live preview optional by design.

With partial messages disabled, dashboard should show coarse turn state and final messages confidently. If live preview returns later, it should be behind a bounded buffer with backpressure handling.

## Verdict

Partial rewrite.

Do not rewrite the whole project. Keep FastAPI, SQLite, the broad `SessionManager`/`AgentSession` split, and git worktree isolation. Rewrite the control plane: worker messaging, spawn/kill job supervision, callback transport, timeout/recovery, permission boundary, and tests around those behaviors.

Do not ship this as a dependable orchestrator in its current form. Ship only as a local experimental prototype with explicit warnings. The first production-quality milestone should be: real worker message delivery, observable spawn/kill jobs, scoped identities, bounded SDK turns, authenticated callbacks, and a non-hanging test suite.

## Round 2 — Plan Review

Overall: direction is better. The plan accepts that SDK paths are broken and tries to make the workaround layer explicit and observable. That is the right framing.

Still, several proposed fixes are not strong enough yet. The repeated risk is replacing "SDK call deadlocks" with "model/prompt should cooperate". That is an improvement for debugging, but it is not a reliable control plane unless the server can observe state transitions and enforce semantics.

1. Blocking Issue 1, `send_to_worker` via Worker Inbox: PUSHBACK as written, ACK on direction.

Worker Inbox is the right replacement for `session.send()` if SDK turns deadlock. But the proposed prompt rule "before every response check inbox" does not wake an idle worker and does not guarantee a busy worker sees urgent messages during a long task. It only works when the worker is already in a turn and chooses to poll.

To make this sound, define the semantics honestly: this is asynchronous mailbox delivery, not immediate turn injection. Add an explicit worker-side polling/heartbeat workflow, or an inbox tool/API the worker must call at known checkpoints. The orchestrator should see message state: `queued`, `fetched`, `acked`, maybe `expired`. `delivered=True` should not mean "GET endpoint returned"; it should mean the worker explicitly acknowledged the message.

Also watch the DB-write contradiction: `send_to_worker` writing inbox rows synchronously inside the MCP handler can recreate the MCP hang class. If writes stay off-loop, the tool must not return "queued" until the write is accepted by an observed writer/job path.

2. Blocking Issue 2, Job Registry for spawn/kill: ACK with conditions.

This is sound. MCP handlers should return fast, and spawn/kill should become observable jobs. The required details are: return `job_id` from the MCP tool, scope every job, persist error text, expose `list_jobs`, add timeout/cancel semantics, and attach done callbacks to background tasks.

Do not use ambiguous job states. `running` can mean "job executing" or "worker session running". Prefer `queued`, `executing`, `succeeded`, `failed`, `timed_out`, `cancelled`.

Durability can be pragmatic for a local dev tool, but be explicit: if the process restarts, queued in-memory jobs are lost unless the supervisor reconciles `jobs` rows on startup.

3. Blocking Issue 3, SDK turn timeout: PUSHBACK as incomplete.

Wrapping only `_listen_loop()` is not enough. Hangs can happen in `connect()`, `query()`, `receive_messages()`, `interrupt()`, and `disconnect()`. The timeout boundary needs to cover the whole turn lifecycle, with smaller nested timeouts for cleanup.

Also, `asyncio.wait_for()` cancels the underlying coroutine. With SDK transports, cancellation may leave the client half-open. The recovery path should be deliberate: mark timeout, try `interrupt()` with its own timeout, then `disconnect()` with its own timeout, then drop/recreate the client. Persist/log the terminal state through the managed writer.

`300s` is fine as a default if configurable. Hardcoding it is acceptable for the first pass, but the important part is that all SDK await points have bounded behavior.

4. Blocking Issue 4, `bypassPermissions` app-level safety: PUSHBACK.

Removing `.env` copying is a real fix. Calling the tool dev-only is honest. But prompt rules like "never run rm -rf, git push --force, pip install" are not a permission policy. A model instruction is not a boundary.

If `can_use_tool` is unusable, the replacement has to be outside the SDK permission callback: run workers under constrained cwd/worktrees, avoid secrets, use OS/container sandboxing where possible, limit exposed tools by role, validate paths server-side, and document that orchestrator sessions are trusted local agents. If Bash remains unrestricted under `bypassPermissions`, say that plainly.

This does not block a local experimental tool, but it blocks any claim that the architecture has a real permission layer.

5. Blocking Issue 5, configurable/authenticated HTTP callback: ACK with gaps.

`ORCHESTRA_URL` plus `X-Worker-Token` is the right shape. Prompt templating is a reasonable config channel because the worker is a separate Claude CLI/SDK session.

Gaps to cover: generate a per-worker token, store only enough to validate it server-side, bind token to `session_id` and `scope`, reject callbacks for stopped/archived workers, and expose callback failures in logs/jobs. Also make sure the prompt uses safe JSON escaping; shell `curl -d` with arbitrary model text can break easily unless messages are encoded robustly.

6. Blocking Issue 6, hanging tests: PUSHBACK.

Adding `testpaths = ["tests"]` is necessary, but it only fixes worktree collection. It does not address the lifecycle hangs I reproduced under `.venv/bin/python -m pytest tests/test_api.py`, `tests/test_session.py`, and `tests/test_manager.py`.

If those pass in your local environment, good, but the plan needs a concrete compatibility fix: pin/record pytest and pytest-asyncio versions, make the SDK mock implement async iteration correctly, and add a CI/offline command that passes from a clean checkout. Also add `norecursedirs = worktrees .venv data` to make the discovery boundary explicit.

7. Blocking Issue 7, `_log`/`_persist` fire-and-forget: PUSHBACK.

The reason for not doing sync DB writes in the event loop is valid. The proposed DB health check is not enough. It detects repeated failure after the fact; it does not make critical writes reliable or observable.

For noncritical stream/log text, fire-and-forget is acceptable if failures are counted. For critical state transitions and new control-plane data, it is not acceptable. Inbox rows, job status, `ERROR`, `STOPPED`, timeout, and archive transitions need an observed persistence path.

The better pattern is a managed async writer: enqueue write operations quickly, attach futures for critical writes, await only the enqueue/acceptance or the specific critical future where needed, and surface writer errors in session/job state. That avoids blocking the event loop while still giving correctness for control-plane records.

The plan also conflicts with itself: if DB is only a backup/write-through cache, then the new `jobs` and `inbox` tables cannot be the source of truth unless their writes are observed.

8. Blocking Issue 8, scope-aware lookups: ACK with implementation caveat.

This is the right fix and should be first. But "MCP tools pass scope from orchestrator session" is not automatic in the current tool signatures. The current tool functions receive only `args`, not a reliable caller context. Either add `scope` to the MCP tool schema explicitly or add a manager-owned way to resolve the calling orchestrator/session safely.

Also scope `get_worker_logs`, `kill_worker`, archived lookup, and job lookup. The `(name, scope)` identity model should be applied consistently everywhere.

Additional missed risk: startup reconciliation.

Once `jobs`, `inbox`, worker tokens, and terminal states exist, startup must reconcile them. On process boot, queued/executing jobs from a dead process should become `failed` or `abandoned`; active workers whose SDK process is gone should become `error`; inbox messages for archived workers need a clear policy.

Additional missed risk: prompt-only worker polling can starve.

If the worker is doing a long coding task without checking inbox until final report, orchestrator messages are delayed arbitrarily. That may be acceptable, but then the UI/tool response should say "message queued for next worker inbox poll", not "sent".

Updated verdict: still partial rewrite, but the plan is a credible path if the PUSHBACK items are tightened. The highest-risk fixes are Worker Inbox semantics, permission boundary, and observed persistence. Job Registry, callback auth/config, and scoped lookup are solid directions.
