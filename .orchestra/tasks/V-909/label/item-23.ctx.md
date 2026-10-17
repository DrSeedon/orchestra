# Context for item-23

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index 4a560b358..4be9ea8ad 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -3711,42 +3711,92 @@ async def handle_group_message(msg: types.Message):
     orch_name, session = await _resolve_orch(msg)
     if not session:
         return
     reply_prefix = ""
     if msg.reply_to_message and msg.reply_to_message.text:
         quoted = msg.reply_to_message.text[:200]
         reply_prefix = f"> {quoted}\n\n"
     content = f"{reply_prefix}{_forward_meta(msg)}{msg.text}"
     await _send_to_agent(msg, session, content)
 
 
 async def topic_sync_loop():
     while True:
         await asyncio.sleep(30)
         try:
             await ensure_topics()
         except Exception as e:
             logger.error(f"Topic sync error: {e}")
 
 
+class UnmanagedInstanceError(RuntimeError):
+    """This Orchestra is not the one systemd runs, so it must not hold the bot token."""
+
+
+def _unmanaged_instance_reason() -> str | None:
+    """Why this process may NOT poll Telegram, or None if it is the canonical instance.
+
+    Telegram serves getUpdates to one consumer per token. `.env` is copied into every
+    worker worktree with the production TG_BRIDGE_TOKEN in it (22 of 42 copies on
+    18.08.2026), so any app an agent starts there steals the user's incoming messages
+    — #324: 383 TelegramConflictError in one hour from two orphaned instances.
+
+    The canonical instance is the process systemd socket-activates: sd_listen_fds sets
+    LISTEN_PID to the pid of the very process systemd EXEC'D. Measured on the live
+    service: MainPID 2577299, LISTEN_PID=2577299.
+
+    Presence of the systemd variables proves nothing — a worker's shell inherits
+    LISTEN_PID, LISTEN_FDS, NOTIFY_SOCKET, INVOCATION_ID and SYSTEMD_EXEC_PID from the
+    service (measured in an agent worktree, all five visible). Only the pid identity
+    distinguishes the process that owns them from the processes that inherited them.
+
+    What satisfies this is the DIRECT exec of the interpreter, NOT the `--fd 3` argument:
+    an ExecStart of the form `uv run uvicorn … --fd 3` serves HTTP perfectly (fd 3 is
+    inherited by the child) while failing this check, because `uv run` forks instead of
+    exec'ing. Measured (#324): `uv run` -> LISTEN_PID=2751595 pid=2751601; direct
+    interpreter -> 2751602 == 2751602. On this host the direct form comes from the
+    untracked drop-in 60-runtime-isolation.conf (#303); deploy/orchestra.service carries
+    it too, so the base unit is safe without that drop-in. Changing ExecStart back to a
+    wrapper takes the bridge down silently — the log says so, the user's Telegram just
+    goes quiet. app/fdstore.py:92 relies on the same identity for agent adoption.
+    """
+    listen_pid = os.environ.get("LISTEN_PID")
+    if not listen_pid:
+        return "LISTEN_PID is unset — this process was not socket-activated by systemd"
+    if listen_pid != str(os.getpid()):
+        return (
+            f"LISTEN_PID={listen_pid} does not match this process ({os.getpid()}) — the "
+            "value was inherited from the canonical instance, not assigned to this one"
+        )
+    return None
+
+
 async def start_bridge(manager):
     global bot, _manager
+    reason = _unmanaged_instance_reason()
+    if reason is not None:
+        raise UnmanagedInstanceError(
+            f"TG bridge refused to start: {reason}. Only orchestra.service "
+            "(`uvicorn app.main:app --fd 3`, socket-activated) may hold TG_BRIDGE_TOKEN; a "
+            "second poller silently swallows the user's Telegram messages (#324). Nothing "
+            f"else about this instance is affected. cwd={os.getcwd()}"
+        )
     from dotenv import load_dotenv
     load_dotenv()
     await _reset_tg_delivery_state()
 
     # Wire callbacks regardless of bridge state: handlers no-op while _manager is
     # None, and remove_topics_for_orchs has its own bridge-inactive guard — this
     # preserves the legacy always-callable semantics without session/manager
     # importing tg_bridge.
     from app import session as _session_mod
     _session_mod.on_scope_idle = _on_session_scope_idle
     _session_mod.on_scope_running = _on_session_scope_running
     manager.tg_topics_remover = remove_topics_for_orchs
 
     load_config()
     token = os.getenv("TG_BRIDGE_TOKEN", "")
     group = int(os.getenv("TG_BRIDGE_GROUP", config.get("group_id", 0)))
 
     if not token or not group:
         logger.info("TG Bridge disabled (no TG_BRIDGE_TOKEN/TG_BRIDGE_GROUP)")
         return
@@ -3878,36 +3928,20 @@ async def stop_bridge():
     _tasks.clear()
     _stream_tasks.clear()
     _topic_status_tasks.clear()
     _topic_status_desired.clear()
     _topic_status.clear()
     _topic_create_tasks.clear()
     _bridge_tasks.clear()
     _mirror_tasks.clear()
     _mirror_outboxes.clear()
     _mirror_dropped.clear()
     _buffers.clear()
     await _reset_tg_delivery_state()
     try:
         if bot:
             await bot.session.close()
     finally:
         # A handler racing past the unhook must see inactive state even if close fails.
         bot = None
         _manager = None
         _mirror_stopping.clear()
-
-
-if __name__ == "__main__":
-    import sys
-    async def _main():
-        from app.manager import SessionManager
-        m = SessionManager()
-        from app.db import init_db
-        init_db()
-        if len(sys.argv) > 1:
-            os.environ["TG_BRIDGE_TOKEN"] = sys.argv[1]
-        if len(sys.argv) > 2:
-            os.environ["TG_BRIDGE_GROUP"] = sys.argv[2]
-        await start_bridge(m)
-        await asyncio.Event().wait()
-    asyncio.run(_main())
diff --git a/deploy/install.sh b/deploy/install.sh
index a5fca84a2..ec9f3dab7 100755
--- a/deploy/install.sh
+++ b/deploy/install.sh
@@ -108,21 +108,28 @@ echo "Orchestra: http://$(hostname -I | awk '{print $1}')"
 echo ""
 STATUS=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8888/ || echo "failed")
 if [ "$STATUS" = "200" ] || [ "$STATUS" = "302" ]; then
     echo "Health check: OK (HTTP $STATUS)"
 else
     echo "Health check: FAILED (HTTP $STATUS)"
     echo "Check: journalctl -u orchestra -f"
 fi
 
 REMOTE_SCRIPT
 
 echo ""
 echo "=== Install complete ==="
 echo "SSH: ssh $SSH_TARGET"
 echo "Logs: ssh $SSH_TARGET journalctl -u orchestra -f"
 echo ""
 echo "Next steps:"
 echo "  1. Set up Claude Code auth: claude setup-token (on laptop)"
 echo "  2. Copy token to VPS: ssh $SSH_TARGET 'echo CLAUDE_CODE_OAUTH_TOKEN=sk-ant-... >> /opt/orchestra/.env'"
 echo "  3. (Optional) Add domain + SSL: certbot --nginx -d your-domain.com"
-echo "  4. (Optional) TG bot: add TG_BRIDGE_TOKEN + TG_BRIDGE_GROUP to .env"
+# The TG bridge refuses to start unless systemd socket-activated the process itself
+# (app/tg_bridge.py, #324). orchestra.service.template binds --host/--port, so setting the token
+# on this installation would produce a bridge that never starts and says so only in the journal.
+# Say what it costs instead of inviting a dead configuration.
+echo "  4. (Optional) TG bot: NOT available with this unit template — it binds --host/--port,"
+echo "     and the bridge only runs under socket activation (deploy/orchestra.socket +"
+echo "     ExecStart=<venv>/bin/python -m uvicorn app.main:app --fd 3, interpreter exec'd"
+echo "     directly, no 'uv run'). Setting TG_BRIDGE_TOKEN alone will NOT start it."
diff --git a/deploy/orchestra.service b/deploy/orchestra.service
index 32b0c6f8f..85c831fc9 100644
--- a/deploy/orchestra.service
+++ b/deploy/orchestra.service
@@ -18,41 +18,55 @@
 [Unit]
 Description=Orchestra AI Agent Orchestrator
 After=network.target
 Requires=orchestra.socket
 After=orchestra.socket
 
 StartLimitIntervalSec=300
 StartLimitBurst=5
 
 [Service]
 Type=simple
 NotifyAccess=main
 User=kesha
 Group=kesha
 WorkingDirectory=/home/kesha/orchestra
 Environment=PATH=/home/kesha/.local/bin:/usr/local/bin:/usr/bin:/bin
 Environment=WORKSPACE_DIR=/home/kesha/workspace/project
 EnvironmentFile=/home/kesha/orchestra/.env
 
 # --fd 3 — serve the socket systemd already holds instead of binding our own.
-ExecStart=/home/kesha/.local/bin/uv run uvicorn app.main:app --fd 3
+#
+# The interpreter is exec'd DIRECTLY, and that is load-bearing, not a style choice. systemd sets
+# LISTEN_PID to the pid of the process it exec'd; `uv run` does not exec, it forks a child, so
+# the application ends up with a pid that LISTEN_PID does not name. Measured (#324):
+#   LISTEN_PID=$$ exec uv run --no-project python -c ... -> LISTEN_PID=2751595 pid=2751601 False
+#   LISTEN_PID=$$ exec .venv/bin/python            -c ... -> LISTEN_PID=2751602 pid=2751602 True
+# app/tg_bridge.py refuses to start the Telegram bridge unless LISTEN_PID == os.getpid(), so the
+# `uv run` form starts HTTP fine (fd 3 is inherited either way) and silently leaves the user with
+# no Telegram at all. app/fdstore.py:92 already depended on the same identity for agent adoption.
+#
+# WHICH interpreter is not decided here: on this host the untracked drop-in
+# /etc/systemd/system/orchestra.service.d/60-runtime-isolation.conf (#303) resets ExecStart= and
+# pins an isolated runtime under /opt/orchestra/runtimes. This line is the base that must stay
+# safe when that drop-in is absent.
+ExecStart=/home/kesha/orchestra/.venv/bin/python -m uvicorn app.main:app --fd 3
 
 Restart=always
 RestartSec=5
 
 # Children outlive us on purpose. Their reaping is ours to do (#230 T7: the fail-closed orphan
 # sweep on startup), not systemd's.
 KillMode=process
 
 # 2 descriptors per live session plus the listening socket. Measured fleet: 6 CLI children = 12
 # descriptors; 13 sessions would need 26. 256 leaves room for growth without silent refusal —
 # an over-full store rejects the handover, and app/fdstore.py raises FdStoreUnavailable rather
 # than losing an agent quietly.
 FileDescriptorStoreMax=256
 # Default is already "restart", stated explicitly because the whole design leans on it:
 # descriptors survive a RESTART and a crash, and are released on a full stop.
 FileDescriptorStorePreserve=restart
 
 # Unchanged from the current live unit — deliberate, not inherited by accident.
 OOMScoreAdjust=800
 MemoryHigh=8G
diff --git a/docs/tasks/324/report.md b/docs/tasks/324/report.md
new file mode 100644
index 000000000..a435b3309
--- /dev/null
+++ b/docs/tasks/324/report.md
@@ -0,0 +1,278 @@
+# #324 — the TG bridge may only start in the instance systemd runs
+
+Live incident, 18.08.2026: an app started by an agent inside its worktree polled Telegram with
+the production token and swallowed the user's incoming messages.
+
+## Why code and not a prompt rule
+
+The project's own criterion for where a rule may live: a prompt is admissible only when BOTH
+directions of failure degrade into today's behaviour. Here the "agent forgot the rule" direction
+produces the incident itself — a second getUpdates consumer, and the user's Telegram stops
+working. That is a forbidden action, not a degradation, so the rule has to be enforced by code.
+
+Measured 18.08.2026 before this change: `.env` is copied into every worktree at spawn, 22 of 42
+copies carry the production `TG_BRIDGE_TOKEN` (sha256 `ee7326271483`, identical to the main
+checkout), two orphans (`ppid=1`, cwd `worktrees/home-kesha-orchestra/feat-runtime-switch`) held
+`127.0.0.1:8081` and produced 383 `TelegramConflictError` in one hour. Killing them took the
+count to 0.
+
+## The discriminator, chosen by measurement rather than by plausibility
+
+The obvious candidates fail. An agent's shell **inherits** the systemd markers from the service
+that spawned it. Measured in this worktree, from a worker's own Bash:
+
+```
+$ env | grep -E '^(INVOCATION_ID|LISTEN_FDS|LISTEN_PID|NOTIFY_SOCKET|SYSTEMD_EXEC_PID)='
+LISTEN_FDS=59
+SYSTEMD_EXEC_PID=2577299
+INVOCATION_ID=04fd72909f134e93ab9726ccebc88331
+NOTIFY_SOCKET=/run/systemd/notify
+LISTEN_PID=2577299
+```
+
+So *presence* of any of these proves nothing — a test instance has all five. Testing for
+`INVOCATION_ID`, `NOTIFY_SOCKET` or `LISTEN_FDS` would have been a check that returns the same
+answer whether or not the process is canonical.
+
+What is not inheritable is the **pid identity**. `sd_listen_fds` sets `LISTEN_PID` to the pid of
+the very process systemd exec'd, and the unit runs `uvicorn app.main:app --fd 3` under
+`Requires=orchestra.socket`, so it is always set there. Measured on the live service:
+
+```
+MainPID=2577299   cwd=/home/kesha/orchestra
+/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m uvicorn app.main:app --fd 3
+LISTEN_PID=2577299
+```
+
+`LISTEN_PID == str(os.getpid())` holds in that process and in no descendant of it. Uvicorn
+without `--workers`/`--reload` runs the app in the process systemd exec'd, so the identity is
+available to application code — confirmed by `ps -p 2577299` showing the python process itself,
+not a supervisor.
+
+Rejected: comparing the running code's directory against the canonical checkout (via
+`git rev-parse --git-common-dir`). It adds a subprocess at startup and covers nothing extra —
+the unit pins `WorkingDirectory=/home/kesha/orchestra`, so a systemd-launched instance can never
+run from a worktree, and a worktree-launched instance is already refused by the pid check. It
+would also miss an app started from the main checkout, which the pid check catches.
+
+## The change
+
+`app/tg_bridge.py`, two additions and one call:
+
+- `UnmanagedInstanceError(RuntimeError)`;
+- `_unmanaged_instance_reason() -> str | None`, fail-closed in both directions — an unset
+  `LISTEN_PID` refuses just as an inherited one does, so the guard is not green in an empty room;
+- the call as the **first statement** of `start_bridge`, before `load_dotenv()` and before the
+  token is read.
+
+`start_bridge` is the only seam: `grep -rn "TG_BRIDGE_TOKEN" app/` returns exactly one read
+(`app/tg_bridge.py:3747`), both `Bot(token=…)` constructions are inside it, and both call sites
+(`app/main.py:46` and the `__main__` block at the bottom of `tg_bridge.py`) go through it.
+
+Fail loud: the guard raises rather than returning. `_start_bridge_background` already logs
+`TG bridge FAILED to start: <class>: <message>` with a traceback, and the message names the
+failing check, both pids and the cwd:
+
+```
+TG bridge refused to start: LISTEN_PID=2577299 does not match this process (2707527) — the
+value was inherited from the canonical instance, not assigned to this one. Only
+orchestra.service (`uvicorn app.main:app --fd 3`, socket-activated) may hold TG_BRIDGE_TOKEN;
+a second poller silently swallows the user's Telegram messages (#324). Nothing else about this
+instance is affected. cwd=/home/kesha/orchestra/worktrees/home-kesha-orchestra/some-worker
+```
+
+Refusal is confined to the bridge: HTTP keeps serving, because `_start_bridge_background` runs
+as a background task and catches the exception.
+
+## systemd
+
+**RETRACTED — the first version of this report said "No unit change required" and that was
+wrong.** Corrected after independent review (H1, `docs/tasks/324/opus-review.md`), reproduced
+here before accepting it.
+
+The live service passes the guard because of an **untracked drop-in**,
+`/etc/systemd/system/orchestra.service.d/60-runtime-isolation.conf` (#303, dated 16.08), which
+does `ExecStart=` (reset) and then pins a direct interpreter path. The base `ExecStart` — in
+`/etc/systemd/system/orchestra.service` *and* in the tracked `deploy/orchestra.service:38` — was
+`uv run uvicorn app.main:app --fd 3`, and **`uv run` does not exec, it forks**. Measured by me,
+independently of the reviewer:
+
+```
+$ sh -c 'LISTEN_PID=$$ exec /home/kesha/.local/bin/uv run --no-project python /tmp/324-pidcheck.py'
+LISTEN_PID=2751595 app_pid=2751601 MATCH=False      <- the guard would have refused
+$ sh -c 'LISTEN_PID=$$ exec /home/kesha/orchestra/.venv/bin/python /tmp/324-pidcheck.py'
+LISTEN_PID=2751602 app_pid=2751602 MATCH=True       <- the live drop-in's form
+```
+
+So on the tracked configuration this change would have taken the production bridge down, and
+`--fd 3` was never what satisfied the check — the **direct exec of the interpreter** is. HTTP
+would have kept working (fd 3 is inherited by the forked child either way), which is exactly what
+makes the failure quiet: one line in the journal, and the user discovers it as silence in
+Telegram.
+
+**How I missed it:** `ps` showed the live process as
+`/opt/orchestra/runtimes/…/bin/python -m uvicorn app.main:app --fd 3` while the unit I had just
+read said `uv run uvicorn …`. I had both facts and never asked why they differed. The
+measurement was right; the attribution of *why* it passed was not.
+
+### Changed here (repo files only — nothing applied to /etc)
+
+- `deploy/orchestra.service:38` → `ExecStart=/home/kesha/orchestra/.venv/bin/python -m uvicorn
+  app.main:app --fd 3`, with the constraint and the measurement in a comment above it. The
+  dated `/opt/orchestra/runtimes/...` path is deliberately *not* copied here: it rots on every
+  runtime rebuild, and which runtime to use is #303's drop-in decision. This line only has to be
+  safe when that drop-in is absent. `systemd-analyze verify` → rc=0.
+- `app/tg_bridge.py` guard docstring — now names the direct exec as the mechanism instead of
+  citing the `uv run … --fd 3` line, which does *not* satisfy the guard.
+
+**Still an operator action.** Nothing in /etc was touched by me.
+
+## Tests — `tests/test_tg_bridge_instance_guard.py`
+
+Four cases: worktree-like instance refuses (inherited `LISTEN_PID`, worktree cwd), bare process
+refuses (no systemd vars), socket-activated process is let through, and the recorded live
+service environment passes the guard.
+
+Two things stop them from passing vacuously. The `bridge_body_tripwire` fixture replaces
+`_reset_tg_delivery_state` — the first real step of `start_bridge` — with a raiser, so a guard
+that stopped firing surfaces as `_ReachedBridgeBody` instead of a quiet `return`. And the
+permitting arm asserts that the body IS reached, so a guard wired to reject everything (which
+would take the production bridge down) cannot pass either.
+
+`start_bridge` is bound by name at module scope because conftest's autouse `_no_tg_bridge`
+fixture replaces the module attribute with an `AsyncMock`; the module-scope binding keeps
+pointing at the real coroutine.
+
+### Mutation runs (protocol: `cp` → mutate → run → `mv` back → `touch` → marker count both sides → green repeat)
+
+| # | Mutation | Marker before / after revert | Result |
+|---|---|---|---|
+| A | `reason = _unmanaged_instance_reason()` → `reason = None` (guard not wired) | 1 / 1 | **2 failed**, both raising `_ReachedBridgeBody` — the bridge body was really entered |
+| B | `if listen_pid != str(os.getpid()):` → `if False:` (inherited pid accepted) | 1 / 1 | **1 failed** (`test_worktree_instance_refuses_to_start`), `_ReachedBridgeBody` |
+| C | `if not listen_pid:` → `if False:` (missing `LISTEN_PID` accepted) | 1 / 1 | **1 failed** (`test_bare_process_refuses_to_start`) — falls through to the wrong branch and the message assertion catches it |
+
+Each mutation targeted a string with `grep -c == 1` in the file (asserted inside the patch
+script, so a non-applying mutation aborts instead of reading as "survived"). Green repeat after
+every revert: `4 passed`. Final: `4 passed`.
+
+### Regression runs
+
+- `tests/test_tg_bridge.py tests/test_startup_bridge.py tests/test_tg_bridge_instance_guard.py` → **199 passed**
+- `tests/test_api.py tests/test_restart_inbox.py tests/test_routes_surface.py tests/test_undelivered.py tests/test_voice_input.py tests/test_bug_report_notify.py` → **157 passed** (every test file that drives the lifespan through `TestClient(app)`)
+
+## Pre-mortem
+
+| Scenario | Check |
+|---|---|
+| Production bridge dies after this merge | `test_live_service_environment_passes_the_guard` replays the measured live env (`LISTEN_PID=2577299`, pid 2577299) and asserts the guard returns `None`; the permitting arm asserts `start_bridge` reaches its body. **This row was insufficient as first written** — the tests pin the live *process* environment, and nothing in them would have caught the tracked unit's `uv run` form producing that environment differently (H1). Config the tests cannot see is the residual hole; the comments in `deploy/orchestra.service` and the guard docstring are what carries it |
+| `POST /api/restart` leaves a stale `LISTEN_PID` and the bridge never comes back | Restart goes through `systemctl restart`, so systemd re-exec's and re-assigns `LISTEN_PID`. `grep -rn "execv\|execl" app/ --include=*.py` finds self-exec only in `app/pidfd_exec.py`, a child-spawn helper — the app never re-execs itself |
+| Existing suite starts failing because something calls the real `start_bridge` | 356 tests across the bridge, startup and lifespan files, all green; the only unmocked caller is the new test file |
+| Refusal takes HTTP down with it | The raise happens inside a background task caught by `_start_bridge_background`; `test_startup_bridge.py` (already covering a raising `start_bridge`) is green |
+| A test instance reaches Telegram by some other door | `TG_BRIDGE_TOKEN` has exactly one reader and both `Bot(token=…)` calls are inside `start_bridge`, downstream of the guard; with `bot` left `None` every outgoing path no-ops |
+
+## Review route
+
+**`review route unavailable`.** The gate selects a mandatory Sol pass — the risk floor fires
+twice (shared message-delivery path; a lifecycle/admission gate whose bypass disables the
+control), and size does not lower that floor. The oracle is explicitly weak: I wrote the test
+after the implementation, so it is not an independent deterministic oracle.
+
+The call was refused before reaching the reviewer:
+`weekly_quota_blocked: Codex weekly quota is 98% (threshold 95%). Available provider: Claude,
+Codex Spark.` Luna shares the Codex runtime and is blocked identically; Spark is forbidden for
+review by policy. **Rounds spent: 0** (no reviewer output — a route refusal, not an attempt).
+
+Author is Claude/Opus, so a Sol pass would also have been the cross-family review. An Opus
+reviewer needs a fresh session from a spawn-capable parent, which a terminal worker cannot
+start — the handoff goes to the orchestrator. Until then: **cross-family verdict unavailable.**
+
+### Adversarial self-review (substitute for the review, not equivalent to it)
+
+Every claim below was checked by command, not by reading the diff.
+
+- **Is `start_bridge` the only seam?** `grep -rn "TG_BRIDGE_TOKEN" app/` → one functional read
+  (`app/tg_bridge.py:3786`), the rest are the comment, a log string and the `__main__` argv
+  assignment. `grep -rn "Bot(token=" app/` → `3817` and `3820`, both inside `start_bridge`
+  downstream of the guard. With `bot` left `None`, every outgoing path no-ops.
+- **Does raising early strand the wired callbacks?** It skips the assignment of
+  `session.on_scope_idle`, `session.on_scope_running` and `manager.tg_topics_remover`. All three
+  consumers already guard against the unassigned state: `app/session.py:2728`
+  (`if on_scope_idle is None: return`), `:2736` (same for `on_scope_running`),
+  `app/manager.py:1419` (`if delete_tg_topics and orch_names and self.tg_topics_remover`), and
+  the module-level defaults at `app/session.py:3529-3530` are `None`. Leaving them unwired in a
+  refused instance is also the correct behaviour — those callbacks push to Telegram.
+- **Can `POST /api/restart` strand a stale `LISTEN_PID`?** No. `_do_restart_service` ends with
+  `os.kill(os.getpid(), signal.SIGINT)` (`app/routes/system.py:2113`); the process exits and
+  systemd's `Restart=always` starts a new one, so `LISTEN_PID` is re-assigned by systemd.
+  `grep -rn "execv\|execl" app/ --include=*.py` finds self-exec only in `app/pidfd_exec.py`, a
+  child-spawn helper — the app never re-execs itself.
+
+**Open question I could not close alone, and the reason the handoff matters:** the guard makes
+the production bridge depend on socket activation. If the unit is ever changed away from
+`--fd 3` / `Requires=orchestra.socket`, the bridge stops — loudly in the log, but the user finds
+out by his Telegram going quiet. That trade was taken deliberately (it is the only measured
+non-inheritable signal), but it is exactly the kind of call a second opinion exists for.
+
+### Outcome of the handoff
+
+The orchestrator ran an independent Opus reviewer (`review324`,
+`docs/tasks/324/opus-review.md`, `db36cfb1`). Verdict **APPROVED WITH SUGGESTIONS**. Still not
+cross-family — author and reviewer are both Claude/Opus, Codex was at 98%; the family confound
+is named, not removed.
+
+And the open question above was the right one to hand over: it is exactly where the review found
+something. Not the runtime behaviour — that direction came back confirmed — but the configuration
+the guard silently depends on (H1 above). Confirmed by the reviewer, not by me:
+
+- **Direction 1 (can a non-canonical instance still reach Telegram?)** — confirmed by count, and
+  extended past what I checked: no raw HTTP client to the Bot API anywhere, 8 `bot is None` guards
+  on the send paths, and the worktree instance writes to its own SQLite (`ORCHESTRA_DB_PATH`
+  unset, default path is relative to the code) so it cannot corrupt production delivery state.
+- **Direction 2 (false refusal of the live process)** — no path found; `LISTEN_PID` survives to
+  `start_bridge` (nothing in the runtime's site-packages or `app/` mutates it), and
+  `app/fdstore.py:92-94` already ships the identical predicate and works in production.
+- **Oracle not vacuous** — the reviewer added the mutation I had not: `return None` →
+  `return "MUTANT: always refuse"`, i.e. a guard nailed shut, the defect that kills the
+  production bridge. 2 failed, caught by the permitting arm.
+
+Findings taken: H1 and S2 (both applied above). S3 (a positive "token set but `TG bridge: ready`
+never arrived" signal surfaced where the user actually looks, since the journal is not his
+channel) is deliberately **not** in this commit — the orchestrator is filing it separately; it is
+about the failure being observable, not about the gate. N1 (the same predicate now lives in
+`app/fdstore.py:92-94` and here) left as a nit: if the signal ever changes, both must change.
+
+## Behaviour change worth naming
+
+`python -m app.tg_bridge <token> <group>` — the standalone runner at the bottom of the module —
+could not succeed under any invocation once the guard existed: it always went through
+`start_bridge`, and a hand-started process never has `LISTEN_PID == os.getpid()`. I had first
+left it in place as "documentation of the refusal"; on review (S2) that is a door guaranteed to
+return a traceback, and the project rule is to delete what your own change orphaned. **Removed**
+(`app/tg_bridge.py`, 14 lines). Checked first that nothing invokes it: `import sys` and all four
+`sys.` uses were local to the block, and no script, unit or doc calls `python -m app.tg_bridge`.
+
+## Deployment installs (`deploy/install.sh`)
+
+Second edge of H1: `install.sh:86` installs `orchestra.service.template`, whose ExecStart is
+`--host 127.0.0.1 --port 8888` with no socket activation at all, while `install.sh:128` invited
+the operator to set `TG_BRIDGE_TOKEN`. On such an installation the bridge can never start.
+
+**Decision: stop advertising it, rather than give the template socket activation** — the tracked
+`deploy/orchestra.socket` is `ListenStream=0.0.0.0:8888`, and shipping it onto a client VPS whose
+nginx proxies `127.0.0.1:8888` would expose the dashboard port on every interface, a security
+regression I cannot test from here. The step now states plainly that this template cannot run the
+bridge and what it would take (socket unit + direct-exec `--fd 3`), so nobody sets a token and
+waits for a bridge that will not come. `bash -n` clean.
+
+**For the owner of the client VPS, after rollout:** check whether a TG bridge is configured
+there (`grep TG_BRIDGE_TOKEN /opt/orchestra/.env`) and whether its unit exec's the interpreter
+directly. If a token is set on an `install.sh`-style unit, this change turns a working bridge
+into a refusing one — for that host it is blocking, not a suggestion. The reviewer had no access
+to that host and neither do I; it is unverified either way.
+
+## Found, not fixed
+
+The token is still sitting in 22 worktree `.env` copies (`.env` is out of scope here by
+instruction). This change removes the way that token gets used by accident, not the copies. If
+the copies themselves should stop carrying it, that is a separate task against the spawn-time
+`.env` copy.
diff --git a/docs/workers/fix-tg-bridge-guard.md b/docs/workers/fix-tg-bridge-guard.md
new file mode 100644
index 000000000..46fa3e0fa
--- /dev/null
+++ b/docs/workers/fix-tg-bridge-guard.md
@@ -0,0 +1,30 @@
+# fix-tg-bridge-guard — personal notes
+
+## systemd env vars do NOT identify the service process on this VPS
+A worker's own Bash inherits `INVOCATION_ID`, `LISTEN_FDS`, `LISTEN_PID`, `NOTIFY_SOCKET` and
+`SYSTEMD_EXEC_PID` from `orchestra.service` — measured 18.08.2026, all five present in a
+worktree shell. Testing for their *presence* is a check that answers the same way whether or not
+the process is the canonical one.
+
+The one non-inheritable fact is pid identity: `os.environ["LISTEN_PID"] == str(os.getpid())` is
+true only in the process systemd exec'd (`MainPID=2577299`, `uvicorn app.main:app --fd 3`).
+Use that to answer "am I the real instance?"; never `INVOCATION_ID`.
+
+Read the env of the live process with plain `tr '\0' '\n' < /proc/<MainPID>/environ` — same
+user, `sudo` is refused here (`no new privileges`).
+
+## `ps` disagrees with the unit file → find the drop-in BEFORE concluding anything
+Caught by review on #324. I read `ExecStart=… uv run uvicorn …` in the unit, then measured the
+live process as `/opt/.../bin/python -m uvicorn …`, and did not ask why the two differed. The
+answer was an untracked drop-in (`/etc/systemd/system/<unit>.d/60-runtime-isolation.conf`) that
+resets `ExecStart=`. Because of it I wrote "no unit change required" when the tracked unit would
+in fact have broken production.
+
+Rule for next time: `systemctl cat <unit>` (shows base + every drop-in), never `cat` the unit
+file alone; and when the observed process does not match the config I just read, that mismatch
+IS the finding — resolve it before building anything on top.
+
+Related, worth knowing on its own: **`uv run` does not exec, it forks.** So any systemd contract
+keyed to the exec'd pid (`LISTEN_PID`, `sd_notify`, `MainPID`) breaks under an `ExecStart` that
+wraps the interpreter. Measured: `uv run` → LISTEN_PID 2751595 vs pid 2751601; direct interpreter
+→ equal.
diff --git a/tests/test_tg_bridge_instance_guard.py b/tests/test_tg_bridge_instance_guard.py
new file mode 100644
index 000000000..cd25e9893
--- /dev/null
+++ b/tests/test_tg_bridge_instance_guard.py
@@ -0,0 +1,115 @@
+"""#324 — only the systemd socket-activated instance may start the TG bridge.
+
+An app started by an agent in its worktree inherits the production TG_BRIDGE_TOKEN from
+the copied `.env` and fights the real process for getUpdates, so the user's incoming
+Telegram messages disappear.
+
+`start_bridge` is imported by name at module scope on purpose: conftest's autouse
+`_no_tg_bridge` fixture replaces the module ATTRIBUTE `tg_bridge.start_bridge` with an
+AsyncMock, and this binding keeps pointing at the real coroutine. Calling the mock would
+make every assertion below vacuous.
+"""
+
+import os
+
+import pytest
+
+import app.tg_bridge as tb
+from app.tg_bridge import UnmanagedInstanceError, start_bridge
+
+
+class _ReachedBridgeBody(Exception):
+    """Raised in place of the first real step of start_bridge."""
+
+
+@pytest.fixture
+def bridge_body_tripwire(monkeypatch):
+    """Make the first real step of start_bridge explode.
+
+    Without it a guard that silently stopped firing would let the refusal tests pass
+    against a bridge that actually started: the coroutine would run on to the
+    "no token" branch and return None, and `pytest.raises` is the only thing standing
+    between that and a green run.
+    """
+    async def _boom():
+        raise _ReachedBridgeBody()
+
+    monkeypatch.setattr(tb, "_reset_tg_delivery_state", _boom)
+
+
+@pytest.fixture
+def manager_stub():
+    class _Manager:
+        tg_topics_remover = None
+
+    return _Manager()
+
+
+def _as_worktree_instance(monkeypatch, tmp_path):
+    """Environment of an app an agent starts in its worktree: systemd variables are
+    inherited from the live service, cwd is a worktree copy of the repository."""
+    worktree = tmp_path / "worktrees" / "home-kesha-orchestra" / "some-worker"
+    worktree.mkdir(parents=True)
+    monkeypatch.chdir(worktree)
+    monkeypatch.setenv("LISTEN_PID", str(os.getpid() + 1))
+    monkeypatch.setenv("LISTEN_FDS", "59")
+    monkeypatch.setenv("NOTIFY_SOCKET", "/run/systemd/notify")
+    monkeypatch.setenv("INVOCATION_ID", "04fd72909f134e93ab9726ccebc88331")
+    monkeypatch.setenv("SYSTEMD_EXEC_PID", str(os.getpid() + 1))
+
+
+@pytest.mark.asyncio
+async def test_worktree_instance_refuses_to_start(
+    monkeypatch, tmp_path, manager_stub, bridge_body_tripwire
+):
+    _as_worktree_instance(monkeypatch, tmp_path)
+
+    with pytest.raises(UnmanagedInstanceError) as excinfo:
+        await start_bridge(manager_stub)
+
+    assert tb.bot is None
+    # Fail loud: the refusal has to say which check failed and where it happened, or the
+    # agent who started the instance cannot tell a guard from a crash.
+    message = str(excinfo.value)
+    assert "LISTEN_PID" in message
+    assert str(os.getpid()) in message
+    assert os.getcwd() in message
+
+
+@pytest.mark.asyncio
+async def test_bare_process_refuses_to_start(
+    monkeypatch, manager_stub, bridge_body_tripwire
+):
+    """No systemd variables at all — the guard must fail closed, not open."""
+    for key in ("LISTEN_PID", "LISTEN_FDS", "NOTIFY_SOCKET", "SYSTEMD_EXEC_PID"):
+        monkeypatch.delenv(key, raising=False)
+
+    with pytest.raises(UnmanagedInstanceError) as excinfo:
+        await start_bridge(manager_stub)
+
+    assert tb.bot is None
+    assert "LISTEN_PID is unset" in str(excinfo.value)
+
+
+@pytest.mark.asyncio
+async def test_socket_activated_instance_is_let_through(
+    monkeypatch, manager_stub, bridge_body_tripwire
+):
+    """Permitting arm. A guard that only ever refuses is indistinguishable from a guard
+    wired to reject everything, which would take the production bridge down with it."""
+    monkeypatch.setenv("LISTEN_PID", str(os.getpid()))
+
+    with pytest.raises(_ReachedBridgeBody):
+        await start_bridge(manager_stub)
+
+
+def test_live_service_environment_passes_the_guard(monkeypatch):
+    """The recorded environment of the running orchestra.service, replayed verbatim:
+    MainPID 2577299 with LISTEN_PID=2577299 (measured 18.08.2026). The bridge must not
+    need any operator action to keep working."""
+    monkeypatch.setattr(os, "getpid", lambda: 2577299)
+    monkeypatch.setenv("LISTEN_PID", "2577299")
+    monkeypatch.setenv("LISTEN_FDS", "59")
+    monkeypatch.setenv("NOTIFY_SOCKET", "/run/systemd/notify")
+
+    assert tb._unmanaged_instance_reason() is None


## Later history of the touched files on main (after this commit)

48 later commits touch these paths; the first 40 (oldest first):
0707d9257 2026-08-19 #343: одно правило допуска по квоте, прежние квотные системы вырезаны
2fa666288 2026-08-24 #337: #337: add durable primary TG file receipts
499176cc2 2026-08-24 chore: remove second dead-code batch
0ce9151a0 2026-08-25 #361: research live knowledge activation
a2c45a484 2026-08-25 #396: restore weekly limits card and reuse renderer
4c1dfe9c7 2026-08-25 #396: close limits renderer and unify window count
0349fc14c 2026-08-26 Repair Orchestra startup and dashboard resilience
aaa98a8fd 2026-08-26 #402: freeze red batch delivery oracles
99fa70980 2026-08-27 #405: add upload size and progress oracles
9d552660b 2026-08-28 #412: cover silent turn anchor suppression
475d56eb6 2026-08-28 большие файлы из TG не теряются по таймауту сессии
99d661a57 2026-08-28 пустой якорь конца хода не уходит юзеру
82d2d403e 2026-08-31 #418: refreeze dashboard portfolio panel RED
9093641f3 2026-09-01 v2.41.0: аудит кодовой базы — 27 дефектов закрыто (3 P0 в tm.py), 2 фикса откачены как регрессии
4e5940ef6 2026-09-02 #433: research message provenance
4eac349d7 2026-09-03 #508: freeze Telegram ingress regression tests
0afee6db5 2026-09-03 #509: freeze Telegram service-event regression oracle
498c0d149 2026-09-03 Orchestra: migrate project state to .orchestra
71240bd4f 2026-09-03 #446: suppress raw telemetry from user channels
43c82f0bd 2026-09-03 Merge remote-tracking branch 'origin/main'
afdf03ea0 2026-09-03 #450: hide user timestamps in human-facing channels
f3c2eaaaf 2026-09-03 merge: забрать 15 коммитов VPS; оглавление базы знаний сведено с обеих сторон
480ca55c2 2026-09-04 refactor: extract privacy and error helpers, trim duplicated validation
da8876dfa 2026-09-06 лимиты файлов: 50 -> 2000 МБ по потолку локального Bot API, квота загрузок 1 -> 10 ГБ
264daeb75 2026-09-07 Separate runtime control from model prose and preserve review results
e6da7e30a 2026-09-10 #537: stop runtime trees with Orchestra and remove live adoption
3e068562f 2026-09-11 V-544: #V-544: тяжёлое фото уходит документом, отказ провайдера терминален, лимиты названы
2dd2e8382 2026-09-16 #V-582: в ленте Telegram видно, какой скилл вызван
323b5e6ff 2026-09-18 #V-597: недельное окно Codex показывается рядом с пятичасовым
8941811c9 2026-09-22 V-610: rewrite third-party code in app/ with own implementation
de5d62a52 2026-09-22 V-576: #V-576: каталог проектов файлом и теги задач вместо второй сущности проекта
759b3be64 2026-09-24 V-628: collapse incoming Telegram topic messages
80ef49b10 2026-09-24 V-630: #V-630: bound SSE graceful shutdown
c3367cad9 2026-09-25 V-644: #V-644: send_message агента — отдельное раскрываемое сообщение в TG, счётчик ⚙️ по пачке
c4d36776d 2026-09-29 V-658: WIP #V-658: switch default Sonnet to 5.5 pending full tests
87f4ffd1e 2026-09-29 V-672: #V-672: group compaction activity in chat
3c697a7ab 2026-10-02 TG: иконка простоя топика через 1 мин вместо 5, логировать успешные смены иконки
b09a8450e 2026-10-02 V-681: #V-681: MP4 в Telegram уходит видео с превью и откатом в документ
c6cc8a5dd 2026-10-04 V-692: keep live limits message updated
5365e1ab4 2026-10-05 V-701: #V-701: fix Telegram media routing

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 0707d9257 #343: одно правило допуска по квоте, прежние квотные системы вырезаны

diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index 4be9ea8ad..117a1cbfa 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -3341,17 +3341,13 @@ async def stream_logs(orch_name: str, thread_id: int):
     finally:
         _poll_conn.close()
 
 
 async def _get_limits_usage() -> dict:
-    # `quota_headroom` роут `/api/usage` считает у себя, а мы зовём `_get_usage_data`
-    # напрямую — без этой строки на пути картинки не было бы главного числа, «сколько
-    # полных пятичасовых окон осталось» (#274). Считаем ровно тем же вызовом, что и роут.
-    from app.routes.system import _get_usage_data, _quota_headroom
+    from app.routes.system import _get_usage_data
 
-    data = await _get_usage_data()
-    return {**data, "quota_headroom": _quota_headroom(data.get("anthropic"))}
+    return await _get_usage_data()
 
 
 async def _is_limits_owner(msg: types.Message) -> bool:
     group_id = config.get("group_id")
     user_id = getattr(getattr(msg, "from_user", None), "id", None)
### 2fa666288 #337: #337: add durable primary TG file receipts

diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index 117a1cbfa..9a22cbf98 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -2380,10 +2380,50 @@ async def _tg_send_file_safe(
         best_effort=not important,
         optional_kind=("image" if is_photo else "file") if not important else None,
     )
 
 
+async def _submit_file_snapshot_once(
+    chat_id: int,
+    snapshot_path: str,
+    caption: str,
+    thread_id: int | None,
+    *,
+    is_photo: bool,
+):
+    """Cross the Bot API boundary once for a durable file-delivery receipt."""
+    if bot is None:
+        raise RuntimeError("TG bridge not active")
+    from aiogram.types import FSInputFile
+
+    tg_file = FSInputFile(snapshot_path, filename=Path(snapshot_path).name)
+    async with asyncio.timeout(_TG_RELIABLE_CALL_TIMEOUT):
+        if is_photo:
+            return await bot.send_photo(
+                chat_id,
+                tg_file,
+                caption=caption,
+                message_thread_id=thread_id,
+            )
+        return await bot.send_document(
+            chat_id,
+            tg_file,
+            caption=caption,
+            message_thread_id=thread_id,
+        )
+
+
+async def _reserve_file_snapshot_slot(chat_id: int) -> bool:
+    """Reserve the shared per-chat rate slot before a durable provider boundary."""
+    if bot is None:
+        return False
+    if not isinstance(bot, Bot):
+        return True
+    state = await _tg_delivery_state_for(chat_id)
+    return bool(await _tg_reserve_rate_slot(chat_id, state, wait_for_slot=True))
+
+
 _TG_TOOL_ICONS = {
     'Bash': '🖥', 'Read': '📖', 'Write': '✏️', 'Edit': '✏️',
     'Glob': '🔎', 'Grep': '🔎', 'WebSearch': '🌐', 'WebFetch': '🌐',
     'Agent': '🤖', 'ToolSearch': '🔍', 'AskUserQuestion': '❓',
     # Одна правка файла — один значок, каким бы рантаймом она ни была сделана:
### 499176cc2 chore: remove second dead-code batch

diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index 9a22cbf98..8c63b788e 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -3413,76 +3413,10 @@ def _to_utc_datetime(raw) -> datetime | None:
     if parsed.tzinfo is None:
         return parsed.replace(tzinfo=timezone.utc)
     return parsed
 
 
-def _format_limits_message(usage: dict, *, now: datetime | None = None) -> str:
-    now = now or datetime.now(timezone.utc)
-    if now.tzinfo is None:
-        now = now.replace(tzinfo=timezone.utc)
-    local_tz = timezone(timedelta(hours=7))
-
-    def window_line(label: str, window: dict | None) -> str:
-        if not isinstance(window, dict) or not isinstance(
-            window.get("utilization"), (int, float)
-        ):
-            return f"• {label} — нет данных"
-
-        remaining = max(0.0, min(100.0, 100 - float(window["utilization"])))
-        remaining_text = f"{remaining:.1f}".rstrip("0").rstrip(".")
-        reset_value = window.get("resets_at")
-        if not reset_value:
-            return f"• {label} — осталось {remaining_text}%; сброс не указан"
-        try:
-            reset = datetime.fromisoformat(
-                str(reset_value).replace("Z", "+00:00")
-            )
-            if reset.tzinfo is None:
-                reset = reset.replace(tzinfo=timezone.utc)
-        except (TypeError, ValueError):
-            return f"• {label} — осталось {remaining_text}%; сброс некорректен"
-
-        absolute = reset.astimezone(local_tz).strftime("%d.%m.%Y %H:%M UTC+7")
-        seconds = (reset - now).total_seconds()
-        if seconds <= 0:
-            relative = "сброс уже наступил"
-        else:
-            minutes_total = max(1, int((seconds + 59) // 60))
-            days, minutes_total = divmod(minutes_total, 24 * 60)
-            hours, minutes = divmod(minutes_total, 60)
-            parts = []
-            if days:
-                parts.append(f"{days} д")
-            if hours:
-                parts.append(f"{hours} ч")
-            if minutes or not parts:
-                parts.append(f"{minutes} мин")
-            relative = f"через {' '.join(parts)}"
-        return (
-            f"• {label} — осталось {remaining_text}%; "
-            f"сброс {absolute}, {relative}"
-        )
-
-    anthropic = usage.get("anthropic") or {}
-    codex = usage.get("codex") or {}
-    lines = [
-        "*Лимиты*",
-        window_line("Claude 5h", anthropic.get("five_hour")),
-        window_line("Claude 7d", anthropic.get("seven_day")),
-        window_line("Codex", codex.get("primary")),
-        window_line("Spark", (codex.get("spark") or {}).get("primary")),
-        window_line("Grok", (usage.get("grok") or {}).get("primary")),
-    ]
-    extra_usage = anthropic.get("extra_usage") or {}
-    if extra_usage.get("spend_limit_reached") is True:
-        lines.append(
-            "• Claude extra usage — лимит расходов достигнут "
-            "(базовые окна считаются отдельно)"
-        )
-    return "\n".join(lines)
-
-
 def _format_limits_message_for_chat(usage: dict, *, now: datetime | None = None) -> str:
     now = now or datetime.now(timezone.utc)
     if now.tzinfo is None:
         now = now.replace(tzinfo=timezone.utc)
     local_tz = timezone(timedelta(hours=7))
### 0ce9151a0 #361: research live knowledge activation

diff --git a/deploy/orchestra.service b/deploy/orchestra.service
index 85c831fc9..93520bbb4 100644
--- a/deploy/orchestra.service
+++ b/deploy/orchestra.service
@@ -31,10 +31,12 @@ User=kesha
 Group=kesha
 WorkingDirectory=/home/kesha/orchestra
 Environment=PATH=/home/kesha/.local/bin:/usr/local/bin:/usr/bin:/bin
 Environment=WORKSPACE_DIR=/home/kesha/workspace/project
 EnvironmentFile=/home/kesha/orchestra/.env
+StateDirectory=orchestra
+StateDirectoryMode=0700
 
 # --fd 3 — serve the socket systemd already holds instead of binding our own.
 #
 # The interpreter is exec'd DIRECTLY, and that is load-bearing, not a style choice. systemd sets
 # LISTEN_PID to the pid of the process it exec'd; `uv run` does not exec, it forks a child, so
### a2c45a484 #396: restore weekly limits card and reuse renderer

diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index 8c63b788e..7696e19ec 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -3381,13 +3381,14 @@ async def stream_logs(orch_name: str, thread_id: int):
     finally:
         _poll_conn.close()
 
 
 async def _get_limits_usage() -> dict:
-    from app.routes.system import _get_usage_data
+    from app.routes.system import _get_usage_data, _quota_headroom
 
-    return await _get_usage_data()
+    data = await _get_usage_data()
+    return {**data, "quota_headroom": _quota_headroom(data.get("anthropic"))}
 
 
 async def _is_limits_owner(msg: types.Message) -> bool:
     group_id = config.get("group_id")
     user_id = getattr(getattr(msg, "from_user", None), "id", None)
@@ -3483,10 +3484,16 @@ def _format_limits_message_for_chat(usage: dict, *, now: datetime | None = None)
         _window_line("Claude 7d", anthropic.get("seven_day"), "seven_day"),
         _window_line("Codex", codex.get("primary")),
         _window_line("Spark", (codex.get("spark") or {}).get("primary")),
         _window_line("Grok", (usage.get("grok") or {}).get("primary")),
     ]
+    headroom = usage.get("quota_headroom")
+    windows_left = headroom.get("windows_left") if isinstance(headroom, dict) else None
+    if isinstance(windows_left, (int, float)) and windows_left > 0:
+        lines.append(f"• Остаток пятичасовых окон в неделе — {windows_left:.2f}")
+    else:
+        lines.append("• Остаток пятичасовых окон в неделе — курс не измерен: нет истории расхода")
     extra_usage = anthropic.get("extra_usage") or {}
     if extra_usage.get("spend_limit_reached") is True:
         lines.append(
             "• Claude extra usage — лимит расходов достигнут "
             "(базовые окна считаются отдельно)"
### 4c1dfe9c7 #396: close limits renderer and unify window count

diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index 7696e19ec..3978c218e 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -4,10 +4,11 @@ Integrated into FastAPI lifespan — no separate process needed.
 """
 
 import asyncio
 import json
 import logging
+import math
 import os
 import re
 import time
 from collections import Counter, OrderedDict, deque
 from datetime import datetime, timezone, timedelta
@@ -3486,11 +3487,14 @@ def _format_limits_message_for_chat(usage: dict, *, now: datetime | None = None)
         _window_line("Spark", (codex.get("spark") or {}).get("primary")),
         _window_line("Grok", (usage.get("grok") or {}).get("primary")),
     ]
     headroom = usage.get("quota_headroom")
     windows_left = headroom.get("windows_left") if isinstance(headroom, dict) else None
-    if isinstance(windows_left, (int, float)) and windows_left > 0:
+    if (isinstance(windows_left, (int, float))
+            and not isinstance(windows_left, bool)
+            and math.isfinite(windows_left)
+            and windows_left > 0):
         lines.append(f"• Остаток пятичасовых окон в неделе — {windows_left:.2f}")
     else:
         lines.append("• Остаток пятичасовых окон в неделе — курс не измерен: нет истории расхода")
     extra_usage = anthropic.get("extra_usage") or {}
     if extra_usage.get("spend_limit_reached") is True:
### 0349fc14c Repair Orchestra startup and dashboard resilience

diff --git a/deploy/orchestra.service b/deploy/orchestra.service
index 93520bbb4..53e7fbebe 100644
--- a/deploy/orchestra.service
+++ b/deploy/orchestra.service
@@ -23,11 +23,11 @@ After=orchestra.socket
 
 StartLimitIntervalSec=300
 StartLimitBurst=5
 
 [Service]
-Type=simple
+Type=notify
 NotifyAccess=main
 User=kesha
 Group=kesha
 WorkingDirectory=/home/kesha/orchestra
 Environment=PATH=/home/kesha/.local/bin:/usr/local/bin:/usr/bin:/bin
### aaa98a8fd #402: freeze red batch delivery oracles

diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index 3978c218e..2322e8ab7 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -2411,10 +2411,41 @@ async def _submit_file_snapshot_once(
             caption=caption,
             message_thread_id=thread_id,
         )
 
 
+async def _submit_file_group_once(
+    chat_id: int,
+    items: list[dict],
+    thread_id: int | None,
+):
+    """Cross one Bot API album boundary for already snapshotted durable files."""
+    if bot is None:
+        raise RuntimeError("TG bridge not active")
+    if not 2 <= len(items) <= 10:
+        raise ValueError("Telegram media group must contain 2-10 files")
+    from aiogram.types import FSInputFile, InputMediaDocument, InputMediaPhoto
+
+    media = []
+    for item in items:
+        tg_file = FSInputFile(
+            item["snapshot_path"], filename=item["original_name"],
+        )
+        media_type = InputMediaPhoto if item["kind"] == "photo" else InputMediaDocument
+        media.append(media_type(
+            media=tg_file,
+            caption=item.get("caption") or None,
+            parse_mode=None,
+        ))
+    async with asyncio.timeout(_TG_RELIABLE_CALL_TIMEOUT):
+        return await bot.send_media_group(
+            chat_id=chat_id,
+            media=media,
+            message_thread_id=thread_id,
+        )
+
+
 async def _reserve_file_snapshot_slot(chat_id: int) -> bool:
     """Reserve the shared per-chat rate slot before a durable provider boundary."""
     if bot is None:
         return False
     if not isinstance(bot, Bot):