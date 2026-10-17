# Candidate cand-28

## ORIGIN commit 94b786f59e (2026-07-29): #99: #99: add conditional recurring cron commands
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index c45aec7c2..d5c1ece7f 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -24,16 +24,18 @@ from app.db import (
 
 logger = logging.getLogger(__name__)
 
 MAX_JOBS_PER_SCOPE = 50
 MAX_TIMEOUT = 86400
 MAX_TIMER_TIMEOUT = 8 * 86400
 DEFAULT_TIMEOUT = 3600
 OUTPUT_PROGRESS_INTERVAL = 30
+_CRON_COMMAND_TIMEOUT_SECONDS = 30
+_NO_EXPIRY_TYPES = frozenset({"file", "command", "ssh", "cron", "cron_command"})
 
 _SSH_OPTS = [
     "-o", "BatchMode=yes",
     "-o", "ConnectTimeout=10",
     "-o", "ServerAliveInterval=30",
     "-o", "ServerAliveCountMax=3",
     "-o", "StrictHostKeyChecking=accept-new",
 ]
@@ -83,22 +85,32 @@ def _validate_config(job_type: str, config: dict) -> str | None:
         if not config.get("command"):
             return "command is required"
         success_pattern = config.get("success_pattern", "")
         if success_pattern:
             try:
                 re.compile(success_pattern)
             except re.error as e:
                 return f"invalid success_pattern: {e}"
-    elif job_type == "cron":
+    elif job_type in ("cron", "cron_command"):
         expr = config.get("cron_expr", "")
         if not expr:
             return "cron_expr is required"
         if not croniter.is_valid(expr):
             return f"invalid cron expression: {expr!r}"
+        if job_type == "cron_command":
+            if not config.get("command"):
+                return "command is required"
+            pattern = config.get("pattern", "")
+            if not pattern:
+                return "pattern is required"
+            try:
+                re.compile(pattern)
+            except re.error as e:
+                return f"invalid regex pattern: {e}"
     else:
         return f"unknown job type: {job_type}"
     return None
 
 
 async def _kill_proc(proc: asyncio.subprocess.Process) -> None:
     if proc.returncode is not None:
         return
@@ -116,16 +128,25 @@ async def _kill_proc(proc: asyncio.subprocess.Process) -> None:
         except (ProcessLookupError, PermissionError):
             pass
         try:
             await asyncio.wait_for(proc.wait(), timeout=2)
         except Exception:
             pass
 
 
+async def _communicate_cron_command(
+    proc: asyncio.subprocess.Process,
+) -> tuple[bytes, bytes]:
+    return await asyncio.wait_for(
+        proc.communicate(),
+        timeout=_CRON_COMMAND_TIMEOUT_SECONDS,
+    )
+
+
 class BgJobManager:
     def __init__(self):
         self._tasks: dict[str, asyncio.Task] = {}
         self._procs: dict[str, asyncio.subprocess.Process] = {}
         self._session_manager = None
 
     def set_session_manager(self, mgr) -> None:
         self._session_manager = mgr
@@ -137,17 +158,17 @@ class BgJobManager:
         err = _validate_config(job_type, config)
         if err:
             return {"error": err}
         count = bg_count_active(target_scope)
         if not replace_key and count >= MAX_JOBS_PER_SCOPE:
             return {"error": f"too many active jobs ({count}/{MAX_JOBS_PER_SCOPE})"}
 
         now = datetime.now(timezone.utc)
-        no_expiry = (job_type == "cron" and timeout_seconds <= 0)
+        no_expiry = job_type in _NO_EXPIRY_TYPES and timeout_seconds <= 0
         if no_expiry:
             config = {**config, "no_expiry": True}
             expires_at = (now + timedelta(days=36500)).isoformat()
         else:
             max_timeout = MAX_TIMER_TIMEOUT if job_type == "timer" else MAX_TIMEOUT
             if job_type == "timer":
                 timeout_seconds = max(
                     timeout_seconds,
@@ -182,45 +203,53 @@ class BgJobManager:
         self._start_task(job_id, job_type, stored_config, message, target_session_id,
                          target_name, target_scope, timeout_seconds,
                          trigger_at)
         logger.info(f"bg_job created: {job_id} type={job_type} target={target_name}")
         return {"id": job_id, "type": job_type, "status": "active"}
 
     def _start_task(self, job_id, job_type, config, message, target_session_id,
                     target_name, target_scope, timeout, trigger_at=None):
+        watch_timeout = None if config.get("no_expiry") else timeout
         if job_type == "timer":
             delay = config["delay_seconds"]
             if trigger_at:
                 remaining = (datetime.fromisoformat(trigger_at) - datetime.now(timezone.utc)).total_seconds()
                 delay = max(0, remaining)
             if config.get("action") == "wake_subscription_limited":
                 coro = self._run_wake_timer(job_id, delay, config)
             else:
                 coro = self._run_timer(job_id, delay, message, target_name, target_scope)
         elif job_type == "file":
             coro = self._run_file_watch(job_id, config["path"], config["pattern"],
-                                        message, target_name, target_scope, timeout)
+                                        message, target_name, target_scope, watch_timeout)
         elif job_type == "command":
             interval = max(5, config.get("interval_seconds", 60))
             coro = self._run_command_watch(job_id, config["command"], config["pattern"],
-                                          interval, message, target_name, target_scope, timeout)
+                                          interval, message, target_name, target_scope,
+                                          watch_timeout)
         elif job_type == "ssh":
             coro = self._run_ssh_watch(job_id, config["host"], config["command"],
-                                       config["pattern"], message, target_name, target_scope, timeout)
+                                       config["pattern"], message, target_name, target_scope,
+                                       watch_timeout)
         elif job_type == "run":
             host = config.get("host")
             coro = self._run_exec(job_id, config["command"], message, target_name,
                                   target_scope, timeout, host=host,
                                   success_file=config.get("success_file"),
                                   success_pattern=config.get("success_pattern", ""))
         elif job_type == "cron":
-            cron_timeout = None if config.get("no_expiry") else timeout
             coro = self._run_cron(job_id, config["cron_expr"], message,
-                                  target_name, target_scope, cron_timeout)
+                                  target_name, target_scope, watch_timeout)
+        elif job_type == "cron_command":
+            coro = self._run_cron(
+                job_id, config["cron_expr"], message,
+                target_name, target_scope, watch_timeout,
+                command=config["command"], pattern=config["pattern"],
+            )
         else:
             return
         task = asyncio.create_task(coro)
         self._tasks[job_id] = task
         task.add_done_callback(
             lambda finished: (
                 self._tasks.pop(job_id, None)
                 if self._tasks.get(job_id) is finished
@@ -396,28 +425,39 @@ class BgJobManager:
             from app.limit_wake import run_wake_job
 
             await run_wake_job(job_id, config, self._session_manager)
         except asyncio.CancelledError:
             pass
         except Exception as error:
             bg_fail_job(job_id, str(error)[:500])
 
-    async def _run_cron(self, job_id, cron_expr, message, target_name, target_scope, timeout):
+    async def _run_cron(
+        self, job_id, cron_expr, message, target_name, target_scope, timeout,
+        command="", pattern="",
+    ):
         deadline = (time.time() + timeout) if timeout else None
         try:
             while True:
                 now = datetime.now(timezone.utc)
                 nxt = croniter(cron_expr, now).get_next(datetime)
                 sleep_s = max(0, (nxt - now).total_seconds())
                 if deadline is not None and time.time() + sleep_s > deadline:
                     await asyncio.sleep(max(0, deadline - time.time()))
                     break
                 await asyncio.sleep(sleep_s)
-                await self._fire_cron(job_id, message, target_name, target_scope)
+                if command:
+                    await self._fire_cron_command(
+                        job_id, command, pattern, message,
+                        target_name, target_scope,
+                    )
+                else:
+                    await self._fire_cron(
+                        job_id, message, target_name, target_scope,
+                    )
             self._expire(job_id)
         except asyncio.CancelledError:
             pass
         except Exception as e:
             bg_fail_job(job_id, str(e)[:500])
 
     async def _fire_cron(self, job_id, message, target_name, target_scope):
         if not bg_cron_should_fire(job_id):
@@ -428,16 +468,91 @@ class BgJobManager:
                 logger.warning(f"cron {job_id}: target {target_name} not found, skipping fire")
                 return
             await session.send(f"[Cron job fired] {message}")
             bg_cron_record_fire(job_id)
             logger.info(f"cron {job_id}: fired → {target_name}")
         except Exception as e:
             logger.error(f"cron {job_id}: fire failed (continuing schedule): {e}")
 
+    async def _fire_cron_command(
+        self, job_id, command, pattern, message, target_name, target_scope,
+    ):
+        if not bg_cron_should_fire(job_id):
+            return
+        proc = None
+        output = ""
+        try:
+            proc = await asyncio.create_subprocess_shell(
+                command,
+                stdout=asyncio.subprocess.PIPE,
+                stderr=asyncio.subprocess.PIPE,
+                preexec_fn=os.setsid,
+            )
+            self._procs[job_id] = proc
+            try:
+                stdout, stderr = await _communicate_cron_command(proc)
+            except asyncio.TimeoutError:
+                output = (
+                    f"[command timed out after "
+                    f"{_CRON_COMMAND_TIMEOUT_SECONDS} seconds]"
+                )
+                bg_update_output(job_id, output)
+                logger.warning(
+                    "cron_command %s: command timed out after %ss",
+                    job_id,
+                    _CRON_COMMAND_TIMEOUT_SECONDS,
+                )
+                return
+
+            raw_output = (
+                stdout.decode(errors="replace")
+                + stderr.decode(errors="replace")
+            )
+            output = raw_output
+            if proc.returncode:
+                output += f"\n[exit code {proc.returncode}]"
+            output = output.strip()
+            bg_update_output(job_id, output)
+            if not raw_output or re.search(pattern, raw_output) is None:
+                return
+            if not bg_cron_should_fire(job_id):
+                return
+            session = await self._session_manager.ensure_loaded(
+                target_name, target_scope,
+            )
+            if not session:
+                logger.warning(
+                    "cron_command %s: target %s not found, skipping match",
+                    job_id,
+                    target_name,
+                )
+                return
+            self._restore_report_provenance(session)
+            body = f"[Cron command matched] {message}"
+            if output:
+                body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
+            await session.send(body)
+            bg_cron_record_fire(job_id)
+            bg_update_output(job_id, output)
+            logger.info("cron_command %s: matched → %s", job_id, target_name)
+        except asyncio.CancelledError:
+            raise
+        except Exception as e:
+            logger.error(
+                "cron_command %s: fire failed (continuing schedule): %s",
+                job_id,
+                e,
+            )
+        finally:
+            if self._procs.get(job_id) is proc:
+                self._procs.pop(job_id, None)
+            if proc:
+                await _kill_proc(proc)
+
     async def _run_file_watch(self, job_id, path, pattern, message,
                               target_name, target_scope, timeout):
         proc = None
         try:
             proc = await asyncio.create_subprocess_exec(
                 "tail", "-F", "-n", "0", path,
                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                 preexec_fn=os.setsid,
@@ -458,19 +573,19 @@ class BgJobManager:
             self._fail_if_active(job_id, str(e)[:500])
         finally:
             self._procs.pop(job_id, None)
             if proc:
                 await _kill_proc(proc)
 
     async def _run_command_watch(self, job_id, command, pattern, interval,
                                  message, target_name, target_scope, timeout):
-        deadline = time.time() + timeout
+        deadline = (time.time() + timeout) if timeout is not None else None
         try:
-            while time.time() < deadline:
+            while deadline is None or time.time() < deadline:
                 proc = await asyncio.create_subprocess_shell(
                     command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                     preexec_fn=os.setsid,
                 )
                 self._procs[job_id] = proc
                 try:
                     stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                 except asyncio.TimeoutError:
@@ -478,17 +593,18 @@ class BgJobManager:
                     stdout, stderr = b"", b""
                 finally:
                     self._procs.pop(job_id, None)
                 output = stdout.decode(errors="replace") + stderr.decode(errors="replace")
                 if re.search(pattern, output):
                     await self._trigger(job_id, message, target_name, target_scope, output.strip())
                     return
                 await asyncio.sleep(interval)
-            self._expire(job_id)
+            if deadline is not None:
+                self._expire(job_id)
         except asyncio.CancelledError:
             pass
         except Exception as e:
             bg_fail_job(job_id, str(e)[:500])
 
     async def _run_ssh_watch(self, job_id, host, command, pattern, message,
                               target_name, target_scope, timeout):
         proc = None
diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 990e7d511..b94fb02ba 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -768,30 +768,39 @@ async def bg_create(type: str, message: str = "", target: str = "",
     - timer: fires after delay_seconds
     - file: watches file at path for pattern (regex)
     - command: runs command every interval_seconds, matches pattern in output
     - ssh: streams ssh command output, matches pattern
     - run: executes command, wakes agent when done with exit code + output
     - cron: periodically wakes the target agent on a cron schedule (cron_expr, 5-field, UTC).
             Recurring — stays active across firings. timeout_seconds=0 = no expiry (forever
             until cancelled). Missed fires during downtime are skipped (no backfill).
-    target: agent name (default: you). timeout_seconds: max lifetime (default 1h, max 24h)."""
+    - cron_command: runs command on cron_expr and wakes only when completed stdout/stderr
+            matches pattern. Recurring, UTC, no backfill.
+    target: agent name (default: you). timeout_seconds: max lifetime (default 1h,
+            max 24h); 0 = no expiry for file/command/ssh/cron/cron_command."""
     config = {}
     if type == "timer":
         config = {"delay_seconds": delay_seconds}
     elif type == "file":
         config = {"path": path, "pattern": pattern}
     elif type == "command":
         config = {"command": command, "pattern": pattern, "interval_seconds": interval_seconds}
     elif type == "ssh":
         config = {"command": command, "host": host, "pattern": pattern}
     elif type == "run":
         config = {"command": command, "host": host} if host else {"command": command}
     elif type == "cron":
         config = {"cron_expr": cron_expr}
+    elif type == "cron_command":
+        config = {
+            "cron_expr": cron_expr,
+            "command": command,
+            "pattern": pattern,
+        }
     target_name = target or WORKER_NAME
     result = await _api("POST", "/api/bg/jobs", json={
         "type": type, "config": config, "message": message,
         "target_name": target_name, "target_scope": SCOPE,
         "timeout_seconds": timeout_seconds, "created_by": WORKER_NAME,
     })
     if isinstance(result, dict) and result.get("error"):
         return f"Error: {result['error']}"
@@ -801,17 +810,20 @@ async def bg_create(type: str, message: str = "", target: str = "",
 @mcp.tool()
 async def bg_list() -> str:
     """List active background jobs in your project."""
     jobs = await _api("GET", "/api/bg/jobs", params={"scope": SCOPE})
     if not isinstance(jobs, list):
         return f"Error: {jobs}"
     if not jobs:
         return "No background jobs"
-    icons = {"timer": "⏰", "file": "📄", "command": "🖥️", "ssh": "🔗", "run": "🚀", "cron": "🔁"}
+    icons = {
+        "timer": "⏰", "file": "📄", "command": "🖥️", "ssh": "🔗",
+        "run": "🚀", "cron": "🔁", "cron_command": "🔎",
+    }
     lines = []
     for j in jobs:
         icon = icons.get(j["type"], "❓")
         status = j["status"]
         target = j.get("target_name", "?")
         msg = j.get("message", "")[:60]
         lines.append(f"{icon} **{j['id']}** | {status} | → {target} | {msg}")
     return "\n".join(lines)
diff --git a/tests/test_bg_jobs.py b/tests/test_bg_jobs.py
index 0af45b039..9a5b3de20 100644
--- a/tests/test_bg_jobs.py
+++ b/tests/test_bg_jobs.py
@@ -36,16 +36,38 @@ class TestValidateCron:
         from app.bg_jobs import _validate_config
         err = _validate_config("cron", {"cron_expr": "not a cron"})
         assert err and "invalid cron" in err
 
     def test_accepts_valid(self):
         from app.bg_jobs import _validate_config
         assert _validate_config("cron", {"cron_expr": "*/5 * * * *"}) is None
 
+    def test_cron_command_requires_command_and_pattern(self):
+        from app.bg_jobs import _validate_config
+
+        assert _validate_config(
+            "cron_command", {"cron_expr": "*/5 * * * *"}
+        ) == "command is required"
+        assert _validate_config(
+            "cron_command",
+            {"cron_expr": "*/5 * * * *", "command": "python monitor.py"},
+        ) == "pattern is required"
+
+    def test_cron_command_rejects_invalid_regex(self):
+        from app.bg_jobs import _validate_config
+
+        error = _validate_config("cron_command", {
+            "cron_expr": "*/5 * * * *",
+            "command": "python monitor.py",
+            "pattern": "[",
+        })
+
+        assert error and "invalid regex" in error
+
 
 def test_run_rejects_invalid_success_pattern():
     from app.bg_jobs import _validate_config
     error = _validate_config("run", {"command": "true", "success_pattern": "["})
     assert error and "success_pattern" in error
 
 
 class TestCronCreate:
@@ -63,16 +85,96 @@ class TestCronCreate:
         assert res["status"] == "active"
         job = next(j for j in bg_get_active_all() if j["id"] == res["id"])
         cfg = json.loads(job["config"])
         assert cfg.get("no_expiry") is True
         # far-future expiry → never overdue
         exp = datetime.fromisoformat(job["expires_at"])
         assert (exp - datetime.now(timezone.utc)).days > 1000
 
+    @pytest.mark.asyncio
+    @pytest.mark.parametrize("job_type", ["file", "command", "ssh", "cron_command"])
+    async def test_zero_timeout_means_forever_for_watchers(
+        self, db, monkeypatch, job_type,
+    ):
+        from app.bg_jobs import BgJobManager
+        from app.db import bg_get_active_all
+
+        configs = {
+            "file": {"path": "/tmp/watch.log", "pattern": "MATCH"},
+            "command": {
+                "command": "python monitor.py",
+                "pattern": "MATCH",
+                "interval_seconds": 60,
+            },
+            "ssh": {
+                "host": "example",
+                "command": "journalctl -f",
+                "pattern": "MATCH",
+            },
+            "cron_command": {
+                "cron_expr": "*/5 * * * *",
+                "command": "python monitor.py",
+                "pattern": "MATCH",
+            },
+        }
+        mgr = BgJobManager()
+        started = []
+        monkeypatch.setattr(
+            mgr, "_start_task", lambda *args, **kwargs: started.append(args),
+        )
+
+        result = await mgr.create(
+            job_type, configs[job_type], "found",
+            f"s-{job_type}", f"w-{job_type}", "/s", "orch",
+            timeout_seconds=0,
+        )
+
+        row = next(
+            job for job in bg_get_active_all()
+            if job["id"] == result["id"]
+        )
+        assert json.loads(row["config"])["no_expiry"] is True
+        assert started[0][7] == 0
+        assert (
+            datetime.fromisoformat(row["expires_at"])
+            - datetime.now(timezone.utc)
+        ).days > 1000
+
+    @pytest.mark.asyncio
+    async def test_no_expiry_reaches_cron_command_runner_as_none(self):
+        from app.bg_jobs import BgJobManager
+
+        mgr = BgJobManager()
+        run_cron = AsyncMock()
+        mgr._run_cron = run_cron
+
+        mgr._start_task(
+            "cron-command-forever",
+            "cron_command",
+            {
+                "cron_expr": "*/5 * * * *",
+                "command": "python monitor.py",
+                "pattern": "MATCH",
+                "no_expiry": True,
+            },
+            "found",
+            "s-1",
+            "w1",
+            "/s",
+            0,
+        )
+        await mgr._tasks["cron-command-forever"]
+
+        assert run_cron.await_args.args[5] is None
+        assert run_cron.await_args.kwargs == {
+            "command": "python monitor.py",
+            "pattern": "MATCH",
+        }
+
 
 class TestFireCron:
     @pytest.mark.asyncio
     async def test_fire_keeps_active_and_counts(self, db, mgr_mock):
         from app.bg_jobs import BgJobManager
         from app.db import bg_save_job, bg_get_active_all
         mgr = BgJobManager()
         m, sess = mgr_mock
@@ -156,16 +258,267 @@ class TestRunCron:
         monkeypatch.setattr(bj.asyncio, "sleep", fake_sleep)
         # _run_cron swallows CancelledError → returns without raising
         await mgr._run_cron("c4", "* * * * *", "ping", "w1", "/s", None)
         assert fired["n"] == 2
         # sleep was called with the computed next-fire delay (<= 60s for * * * * *)
         assert slept and all(0 <= s <= 60 for s in slept)
 
 
+class TestCronCommand:
+    @staticmethod
+    def _job(job_id, now):
+        return {
+            "id": job_id,
+            "type": "cron_command",
+            "config": json.dumps({
+                "cron_expr": "*/5 * * * *",
+                "command": "python monitor.py",
+                "pattern": "ALERT",
+            }),
+            "message": "monitor found work",
+            "target_session_id": "s-1",
+            "target_name": "w1",
+            "target_scope": "/s",
+            "created_by_name": "orch",
+            "status": "active",
+            "expires_at": (now + timedelta(hours=1)).isoformat(),
+            "trigger_at": None,
+            "created_at": now.isoformat(),
+            "last_output": "",
+        }
+
+    @staticmethod
+    def _proc(output=b"", error=b"", returncode=0):
+        return type("Process", (), {
+            "pid": 12345,
+            "returncode": returncode,
+            "output": output,
+            "error": error,
+        })()
+
+    @pytest.mark.asyncio
+    async def test_four_no_match_fires_do_not_wake_and_stay_active(
+        self, db, mgr_mock, monkeypatch,
+    ):
+        import app.bg_jobs as module
+        from app.bg_jobs import BgJobManager
+        from app.db import bg_get_active_all, bg_save_job
+
+        mgr = BgJobManager()
+        manager, session = mgr_mock
+        mgr.set_session_manager(manager)
+        bg_save_job(self._job("cron-command-empty", datetime.now(timezone.utc)))
+        processes = [
+            self._proc(output=f"empty-{index}".encode())
+            for index in range(4)
+        ]
+        create = AsyncMock(side_effect=processes)
+        monkeypatch.setattr(module.asyncio, "create_subprocess_shell", create)
+
+        async def communicate(proc):
+            return proc.output, proc.error
+
+        monkeypatch.setattr(module, "_communicate_cron_command", communicate)
+
+        for _ in range(4):
+            await mgr._fire_cron_command(
+                "cron-command-empty",
+                "python monitor.py",
+                "ALERT",
+                "monitor found work",
+                "w1",
+                "/s",
+            )
+
+        assert create.await_count == 4
+        manager.ensure_loaded.assert_not_awaited()
+        session.send.assert_not_awaited()
+        row = next(
+            job for job in bg_get_active_all()
+            if job["id"] == "cron-command-empty"
+        )
+        assert row["status"] == "active"
+        assert row["last_output"] == "empty-3"
+
+    @pytest.mark.asyncio
+    async def test_completed_nonzero_match_wakes_and_remains_active(
+        self, db, mgr_mock, monkeypatch,
+    ):
+        import app.bg_jobs as module
+        from app.bg_jobs import BgJobManager
+        from app.db import bg_get_active_all, bg_save_job
+
+        mgr = BgJobManager()
+        manager, session = mgr_mock
+        session.parent_name = "parent-orchestrator"
+        session.last_task_sender = ""
+        mgr.set_session_manager(manager)
+        bg_save_job(self._job("cron-command-match", datetime.now(timezone.utc)))
+        proc = self._proc(output=b"ALERT: item 42\n", returncode=7)
+        monkeypatch.setattr(
+            module.asyncio,
+            "create_subprocess_shell",
+            AsyncMock(return_value=proc),
+        )
+
+        async def communicate(process):
+            return process.output, process.error
+
+        monkeypatch.setattr(module, "_communicate_cron_command", communicate)
+
+        await mgr._fire_cron_command(
+            "cron-command-match",
+            "python monitor.py",
+            "ALERT",
+            "monitor found work",
+            "w1",
+            "/s",
+        )
+
+        sent = session.send.await_args.args[0]
+        assert "monitor found work" in sent
+        assert "ALERT: item 42" in sent
+        assert "exit code 7" in sent
+        assert session.last_task_sender == "parent-orchestrator"
+        row = next(
+            job for job in bg_get_active_all()
+            if job["id"] == "cron-command-match"
+        )
+        assert row["status"] == "active"
+        config = json.loads(row["config"])
+        assert config["fire_count"] == 1
+        assert "ALERT: item 42" in row["last_output"]
+
+    @pytest.mark.asyncio
+    async def test_empty_output_never_wakes_even_if_regex_matches_empty(
+        self, db, mgr_mock, monkeypatch,
+    ):
+        import app.bg_jobs as module
+        from app.bg_jobs import BgJobManager
+        from app.db import bg_save_job
+
+        mgr = BgJobManager()
+        manager, session = mgr_mock
+        mgr.set_session_manager(manager)
+        bg_save_job(self._job("cron-command-empty-output", datetime.now(timezone.utc)))
+        proc = self._proc()
+        monkeypatch.setattr(
+            module.asyncio,
+            "create_subprocess_shell",
+            AsyncMock(return_value=proc),
+        )
+
+        async def communicate(process):
+            return process.output, process.error
+
+        monkeypatch.setattr(module, "_communicate_cron_command", communicate)
+
+        await mgr._fire_cron_command(
+            "cron-command-empty-output",
+            "python monitor.py",
+            ".*",
+            "monitor found work",
+            "w1",
+            "/s",
+        )
+
+        manager.ensure_loaded.assert_not_awaited()
+        session.send.assert_not_awaited()
+
+    @pytest.mark.asyncio
+    async def test_timeout_never_wakes_even_after_partial_match(
+        self, db, mgr_mock, monkeypatch,
+    ):
+        import app.bg_jobs as module
+        from app.bg_jobs import BgJobManager
+        from app.db import bg_get_active_all, bg_save_job
+
+        mgr = BgJobManager()
+        manager, session = mgr_mock
+        mgr.set_session_manager(manager)
+        bg_save_job(self._job("cron-command-timeout", datetime.now(timezone.utc)))
+        proc = self._proc(output=b"ALERT: partial\n", returncode=None)
+        monkeypatch.setattr(
+            module.asyncio,
+            "create_subprocess_shell",
+            AsyncMock(return_value=proc),
+        )
+
+        async def timeout(_process):
+            raise asyncio.TimeoutError
+
+        killed = AsyncMock()
+        monkeypatch.setattr(module, "_communicate_cron_command", timeout)
+        monkeypatch.setattr(module, "_kill_proc", killed)
+
+        await mgr._fire_cron_command(
+            "cron-command-timeout",
+            "python monitor.py",
+            "ALERT",
+            "monitor found work",
+            "w1",
+            "/s",
+        )
+
+        manager.ensure_loaded.assert_not_awaited()
+        session.send.assert_not_awaited()
+        killed.assert_awaited_once_with(proc)
+        row = next(
+            job for job in bg_get_active_all()
+            if job["id"] == "cron-command-timeout"
+        )
+        assert row["status"] == "active"
+        assert "timed out after 30 seconds" in row["last_output"]
+
+    @pytest.mark.asyncio
+    async def test_cancellation_while_communicate_blocked_kills_process(
+        self, db, mgr_mock, monkeypatch,
+    ):
+        import app.bg_jobs as module
+        from app.bg_jobs import BgJobManager
+        from app.db import bg_save_job
+
+        mgr = BgJobManager()
+        manager, _session = mgr_mock
+        mgr.set_session_manager(manager)
+        bg_save_job(self._job("cron-command-cancel", datetime.now(timezone.utc)))
+        proc = self._proc(returncode=None)
+        monkeypatch.setattr(
+            module.asyncio,
+            "create_subprocess_shell",
+            AsyncMock(return_value=proc),
+        )
+        communicating = asyncio.Event()
+        never = asyncio.Event()
+
+        async def blocked(_process):
+            communicating.set()
+            await never.wait()
+
+        killed = AsyncMock()
+        monkeypatch.setattr(module, "_communicate_cron_command", blocked)
+        monkeypatch.setattr(module, "_kill_proc", killed)
+        task = asyncio.create_task(mgr._fire_cron_command(
+            "cron-command-cancel",
+            "python monitor.py",
+            "ALERT",
+            "monitor found work",
+            "w1",
+            "/s",
+        ))
+        await communicating.wait()
+
+        task.cancel()
+        await asyncio.gather(task, return_exceptions=True)
+
+        killed.assert_awaited_once_with(proc)
+        assert "cron-command-cancel" not in mgr._procs
+
+
 class TestRunExecOutcome:
     @staticmethod
     def _job(job_id, now):
         return {
             "id": job_id, "type": "run", "config": json.dumps({"command": "true"}),
             "message": "review done", "target_session_id": "s-1", "target_name": "w1",
             "target_scope": "/s", "created_by_name": "orch", "status": "active",
             "expires_at": (now + timedelta(hours=1)).isoformat(),
diff --git a/tests/test_mcp_stdio.py b/tests/test_mcp_stdio.py
index bc35e1a3b..02090b9f4 100644
--- a/tests/test_mcp_stdio.py
+++ b/tests/test_mcp_stdio.py
@@ -517,8 +517,46 @@ def test_full_access_mode_preserves_all_tools():
     assert m._tool_names_for_access_mode(names, "full") == names
 
 
 def test_unknown_access_mode_is_rejected():
     import app.mcp_stdio as m
 
     with pytest.raises(ValueError, match="ORCHESTRA_ACCESS_MODE"):
         m._tool_names_for_access_mode({"list_agents", "spawn_worker"}, "typo")
+
+
+@pytest.mark.asyncio
+async def test_bg_create_cron_command_sends_fail_closed_type(monkeypatch):
+    import app.mcp_stdio as m
+
+    monkeypatch.setattr(m, "SCOPE", "/scope")
+    monkeypatch.setattr(m, "WORKER_NAME", "intent-hunter")
+    captured = {}
+
+    async def fake_api(method, path, **kwargs):
+        captured.update(kwargs["json"])
+        return {"id": "bg-monitor", "type": "cron_command", "status": "active"}
+
+    with patch.object(m, "_api", side_effect=fake_api):
+        result = await m.bg_create(
+            type="cron_command",
+            message="new intent found",
+            cron_expr="*/15 * * * *",
+            command="python3 monitor.py",
+            pattern="^FOUND:",
+            timeout_seconds=0,
+        )
+
+    assert captured == {
+        "type": "cron_command",
+        "config": {
+            "cron_expr": "*/15 * * * *",
+            "command": "python3 monitor.py",
+            "pattern": "^FOUND:",
+        },
+        "message": "new intent found",
+        "target_name": "intent-hunter",
+        "target_scope": "/scope",
+        "timeout_seconds": 0,
+        "created_by": "intent-hunter",
+    }
+    assert "type=cron_command" in result
diff --git a/tests/test_tg_bridge.py b/tests/test_tg_bridge.py
index f6a0c8e2c..112782ac3 100644
--- a/tests/test_tg_bridge.py
+++ b/tests/test_tg_bridge.py
@@ -2300,8 +2300,81 @@ class TestSendFileRetry:
         assert result["ok"] is True
         assert tb.bot.send_document.await_count == 3
         files = [call.args[1] for call in tb.bot.send_document.await_args_list]
         assert len({id(file) for file in files}) == 3
         assert [
             call.kwargs["message_thread_id"]
             for call in tb.bot.send_document.await_args_list
         ] == [555, 555, 666]
+
+
+class TestCronCommandTopicBoundary99:
+    @pytest.mark.asyncio
+    async def test_no_match_is_silent_but_match_reaches_topic_status(
+        self, tb, monkeypatch,
+    ):
+        import app.bg_jobs as module
+
+        tb.bot = AsyncMock()
+        tb.bot.edit_forum_topic.return_value = object()
+        tb.config["topics"] = {"orch": 42}
+
+        session = type("Session", (), {
+            "parent_name": "orch",
+            "last_task_sender": "orch",
+        })()
+
+        async def send(_message):
+            await tb.notify_scope_running("orch")
+
+        session.send = AsyncMock(side_effect=send)
+        session_manager = type("Manager", (), {
+            "ensure_loaded": AsyncMock(return_value=session),
+        })()
+        manager = module.BgJobManager()
+        manager.set_session_manager(session_manager)
+        monkeypatch.setattr(module, "bg_cron_should_fire", lambda _job_id: True)
+        monkeypatch.setattr(module, "bg_update_output", lambda *_args: None)
+        monkeypatch.setattr(module, "bg_cron_record_fire", lambda _job_id: None)
+        outputs = [b"empty-1", b"empty-2", b"empty-3", b"empty-4", b"FOUND: 42"]
+
+        async def create_process(*_args, **_kwargs):
+            return type("Process", (), {
+                "pid": 12345,
+                "returncode": 0,
+                "output": outputs.pop(0),
+                "error": b"",
+            })()
+
+        async def communicate(process):
+            return process.output, process.error
+
+        monkeypatch.setattr(
+            module.asyncio, "create_subprocess_shell", create_process,
+        )
+        monkeypatch.setattr(module, "_communicate_cron_command", communicate)
+
+        for _ in range(4):
+            await manager._fire_cron_command(
+                "monitor",
+                "python monitor.py",
+                "^FOUND:",
+                "new intent found",
+                "intent-hunter",
+                "/scope",
+            )
+
+        session.send.assert_not_awaited()
+        tb.bot.edit_forum_topic.assert_not_awaited()
+
+        await manager._fire_cron_command(
+            "monitor",
+            "python monitor.py",
+            "^FOUND:",
+            "new intent found",
+            "intent-hunter",
+            "/scope",
+        )
+        await asyncio.gather(*tb._topic_status_tasks.values())
+
+        session.send.assert_awaited_once()
+        tb.bot.edit_forum_topic.assert_awaited_once()


## LATER FIX a36e1a236b (4.0 days later): #120: restore cron_command test seam after pidfd spawn refactor
lines of origin it changed/deleted: 3
(code only, capped 400 lines)

#120: restore cron_command test seam after pidfd spawn refactor

Moving _fire_cron_command to _spawn_bg_process left the tg_bridge test
mocking asyncio.create_subprocess_shell, a seam no longer called. The mock
stopped intercepting, so the test spawned a real `sh -c "python monitor.py"`
and the fake communicate() read .output off a real asyncio Process.

Point the test at _spawn_bg_process (the seam the other cron tests already
use) and stub _kill_proc, which fails loud on a process without a pidfd.
cron_command behaviour and production code are unchanged.

Also fix a create-vs-write race in the pidfd lifecycle test: it waited for
the pid file to exist, but open(...,"w") creates it empty before the write.

Full suite: 1375 passed, 27 skipped.


diff --git a/tests/test_bg_jobs.py b/tests/test_bg_jobs.py
index 56187a892..1c0c1d759 100644
--- a/tests/test_bg_jobs.py
+++ b/tests/test_bg_jobs.py
@@ -833,23 +833,28 @@ os._exit(0)
 """
         proc = await module._spawn_bg_process(
             [sys.executable, "-c", code],
             shell=False,
             stdout=asyncio.subprocess.DEVNULL,
             stderr=asyncio.subprocess.DEVNULL,
         )
         await asyncio.wait_for(proc.wait(), 2)
-        for _ in range(100):
-            if child_file.exists():
+        # open(..., "w") creates the file before the pid is written — waiting on
+        # existence alone reads an empty file on a loaded machine.
+        for _ in range(500):
+            recorded = (
+                child_file.read_text() if child_file.exists() else ""
+            ).strip()
+            if recorded:
                 break
             await asyncio.sleep(0.01)
         else:
             pytest.fail("TERM-ignoring child did not start")
-        child_pid = int(child_file.read_text())
+        child_pid = int(recorded)
         unrelated = await asyncio.create_subprocess_exec(
             "/bin/sleep", "30", start_new_session=True,
         )
         sent = []
         real_send = module.pidfd_send_group
 
         def record_send(pidfd, sig):
             sent.append(sig)
diff --git a/tests/test_tg_bridge.py b/tests/test_tg_bridge.py
index a9575e8f3..fec99d95e 100644
--- a/tests/test_tg_bridge.py
+++ b/tests/test_tg_bridge.py
@@ -3966,19 +3966,18 @@ class TestCronCommandTopicBoundary99:
                 "returncode": 0,
                 "output": outputs.pop(0),
                 "error": b"",
             })()
 
         async def communicate(process):
             return process.output, process.error
 
-        monkeypatch.setattr(
-            module.asyncio, "create_subprocess_shell", create_process,
-        )
+        monkeypatch.setattr(module, "_spawn_bg_process", create_process)
+        monkeypatch.setattr(module, "_kill_proc", AsyncMock())
         monkeypatch.setattr(module, "_communicate_cron_command", communicate)
 
         for _ in range(4):
             await manager._fire_cron_command(
                 "monitor",
                 "python monitor.py",
                 "^FOUND:",
                 "new intent found",


## LATER FIX 9f777f912d (6.6 days later): Squashed commits: - #82: исследование — имя как внешний ключ в трёх слоях, тихий путь не тот, что в репорте - #82: план — env чинится пересб
lines of origin it changed/deleted: 8
(code only, capped 400 lines)

Squashed commits:
- #82: исследование — имя как внешний ключ в трёх слоях, тихий путь не тот, что в репорте
- #82: план — env чинится пересборкой, сохранённые ссылки предпочитают id, 4 тикета
- #82: T1 — bg-джобы будят по неизменяемому id, а не по имени
- WIP #82: T2 наполовину — в session.py есть флаг _identity_stale и его гашение на границе хода; НЕ сделано: manager.refresh_identity (пересборка mcp_servers) и вызов из rename_session, весь T3, T4
- #82: T2 — переименование пересобирает MCP-идентичность, перезапуск на границе хода
- #82: T3 — держатель тест-лока по неизменяемому id, дети переименованного родителя
- #82: T4 — живой прогон переименования, отчёт и личная память

(cherry picked from commit 827cd2a6ff6c44030dc80503ae75f0eea0a74f80)

diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index d9f5a4740..c7cd9c228 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -17,17 +17,17 @@ from uuid import uuid4
 from croniter import croniter
 
 from app.db import (
     bg_save_job, bg_claim_trigger, bg_finish_trigger, bg_fail_job,
     bg_cancel_job, bg_expire_job, bg_update_output, bg_get_active_all,
     bg_expire_overdue, bg_count_active, bg_cancel_by_session,
     bg_reset_stale_triggering, bg_cleanup_old,
     bg_cron_should_fire, bg_cron_record_fire,
-    bg_get_jobs, bg_fail_job_if_active, bg_replace_job,
+    bg_get_jobs, bg_get_job, bg_fail_job_if_active, bg_replace_job,
     bg_reset_wake_triggering,
 )
 from app.pidfd_exec import pidfd_send_group
 from app.tasks import spawn_supervised
 
 logger = logging.getLogger(__name__)
 
 MAX_JOBS_PER_SCOPE = 50
@@ -504,26 +504,49 @@ class BgJobManager:
 
     # ── Trigger ──
 
     @staticmethod
     def _restore_report_provenance(session) -> None:
         if not session.last_task_sender and session.parent_name:
             session.last_task_sender = session.parent_name
 
+    async def _load_job_target(self, job_id: str, target_name: str):
+        """Найти цель джоба по НЕИЗМЕНЯЕМОМУ id из его же строки.
+
+        Имя, записанное при создании, к моменту срабатывания могло смениться
+        (`rename_worker`) или уже принадлежать ДРУГОМУ агенту — разбудить по нему значит
+        либо не разбудить никого молча, либо разбудить чужого. Имя оставлено для человека.
+        """
+        row = bg_get_job(job_id) or {}
+        target_session_id = str(row.get("target_session_id") or "")
+        if not target_session_id:
+            logger.error(
+                f"bg_job {job_id}: no target_session_id "
+                f"(name at creation: {target_name!r}) — refusing to wake by name"
+            )
+            return None, "job has no target_session_id"
+        session = await self._session_manager.ensure_loaded_by_id(target_session_id)
+        if not session:
+            logger.warning(
+                f"bg_job {job_id}: target session {target_session_id} "
+                f"(name at creation: {target_name!r}) not found"
+            )
+            return None, "target session not found"
+        return session, ""
+
     async def _trigger(self, job_id: str, message: str,
                        target_name: str, target_scope: str, output: str = "") -> None:
         claimed = bg_claim_trigger(job_id)
         if not claimed:
             return
         try:
-            session = await self._session_manager.ensure_loaded(target_name, target_scope)
+            session, failure = await self._load_job_target(job_id, target_name)
             if not session:
-                bg_fail_job(job_id, "target session not found")
-                logger.warning(f"bg_job {job_id}: target {target_name} not found")
+                bg_fail_job(job_id, failure)
                 return
             body = f"[Background job completed] {message}"
             if output:
                 body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
             self._restore_report_provenance(session)
             await self._session_manager.send(session.id, body)
             bg_finish_trigger(job_id, output)
             logger.info(f"bg_job {job_id}: triggered → {target_name}")
@@ -553,37 +576,35 @@ class BgJobManager:
         Without this, a hung process leaves the worker waiting forever."""
         bg_expire_job(job_id)
         self._procs.pop(job_id, None)
         dur = f"{round(timeout / 60, 1)} min" if timeout >= 60 else f"{int(timeout)}s"
         err = (f"{message}\n[TIMEOUT] killed after {dur} — no completion. "
                f"The process produced no output or hung. Check the target tool "
                f"(codex auth/proxy/sandbox) and retry.")
         try:
-            session = await self._session_manager.ensure_loaded(target_name, target_scope)
+            session, _failure = await self._load_job_target(job_id, target_name)
             if not session:
-                logger.warning(f"bg_job {job_id}: timeout, target {target_name} not found")
                 return
             body = f"[Background job TIMED OUT] {err}"
             if output:
                 body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
             self._restore_report_provenance(session)
             await self._session_manager.send(session.id, body)
             logger.warning(f"bg_job {job_id}: TIMED OUT after {dur} → notified {target_name}")
         except Exception as e:
             logger.error(f"bg_job {job_id}: timeout-notify failed: {e}")
 
     async def _fail_notify(self, job_id, message, target_name, target_scope,
                            error, output=""):
         """Persist a failed run and wake the waiting agent with an explicit failure."""
         bg_fail_job(job_id, error)
         try:
-            session = await self._session_manager.ensure_loaded(target_name, target_scope)
+            session, _failure = await self._load_job_target(job_id, target_name)
             if not session:
-                logger.warning(f"bg_job {job_id}: failed, target {target_name} not found")
                 return
             body = f"[Background job FAILED] {message}\n{error}"
             if output:
                 body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
             self._restore_report_provenance(session)
             await self._session_manager.send(session.id, body)
             logger.warning(f"bg_job {job_id}: FAILED → notified {target_name}: {error}")
         except Exception as e:
@@ -640,19 +661,19 @@ class BgJobManager:
             pass
         except Exception as e:
             bg_fail_job(job_id, str(e)[:500])
 
     async def _fire_cron(self, job_id, message, target_name, target_scope):
         if not bg_cron_should_fire(job_id):
             return
         try:
-            session = await self._session_manager.ensure_loaded(target_name, target_scope)
+            session, _failure = await self._load_job_target(job_id, target_name)
             if not session:
-                logger.warning(f"cron {job_id}: target {target_name} not found, skipping fire")
+                # Расписание живёт дальше: цель могла быть выгружена временно.
                 return
             await self._session_manager.send(
                 session.id, f"[Cron job fired] {message}",
             )
             bg_cron_record_fire(job_id)
             logger.info(f"cron {job_id}: fired → {target_name}")
         except Exception as e:
             logger.error(f"cron {job_id}: fire failed (continuing schedule): {e}")
@@ -695,25 +716,18 @@ class BgJobManager:
             if proc.returncode:
                 output += f"\n[exit code {proc.returncode}]"
             output = output.strip()
             bg_update_output(job_id, output)
             if not raw_output or re.search(pattern, raw_output) is None:
                 return
             if not bg_cron_should_fire(job_id):
                 return
-            session = await self._session_manager.ensure_loaded(
-                target_name, target_scope,
-            )
+            session, _failure = await self._load_job_target(job_id, target_name)
             if not session:
-                logger.warning(
-                    "cron_command %s: target %s not found, skipping match",
-                    job_id,
-                    target_name,
-                )
                 return
             self._restore_report_provenance(session)
             body = f"[Cron command matched] {message}"
             if output:
                 body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
             await self._session_manager.send(session.id, body)
             bg_cron_record_fire(job_id)
             bg_update_output(job_id, output)
diff --git a/app/db.py b/app/db.py
index ffce0e963..762e69f3d 100644
--- a/app/db.py
+++ b/app/db.py
@@ -118,16 +118,17 @@ def init_db() -> None:
                 ended_at TEXT,
                 UNIQUE(session_id, task_id)
             );
             CREATE INDEX IF NOT EXISTS idx_subagents_session ON subagents(session_id);
 
             CREATE TABLE IF NOT EXISTS test_lock (
                 scope TEXT PRIMARY KEY,
                 holder TEXT NOT NULL,
+                holder_session_id TEXT NOT NULL DEFAULT '',
                 reason TEXT DEFAULT '',
                 acquired_at TEXT NOT NULL
             );
         """)
         c.executescript("""
             CREATE TABLE IF NOT EXISTS tm_projects (
                 id TEXT PRIMARY KEY,
                 name TEXT NOT NULL,
@@ -404,16 +405,19 @@ def _guard_session_id(c) -> None:
         BEGIN SELECT RAISE(ABORT, 'sessions.id must be non-empty'); END;
     """)
 
 
 def _migrate(c) -> None:
     # Additive ALTER TABLE migrations — safe to re-run (IF NOT EXISTS / column check).
     # Never drop columns: old Orchestra versions reading the same DB must still work.
     _guard_session_id(c)
+    lock_cols = {row[1] for row in c.execute("PRAGMA table_info(test_lock)").fetchall()}
+    if lock_cols and "holder_session_id" not in lock_cols:
+        c.execute("ALTER TABLE test_lock ADD COLUMN holder_session_id TEXT NOT NULL DEFAULT ''")
     cols = {row[1] for row in c.execute("PRAGMA table_info(sessions)").fetchall()}
     if "color" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN color TEXT DEFAULT ''")
     if "context_pct" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN context_pct INTEGER DEFAULT 0")
     if "context_tokens" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN context_tokens INTEGER DEFAULT 0")
     if "progress_pct" not in cols:
@@ -1330,16 +1334,22 @@ def bg_claim_trigger(job_id: str) -> bool:
     with _conn() as c:
         cur = c.execute(
             "UPDATE bg_jobs SET status='triggering', triggered_at=? WHERE id=? AND status='active'",
             (datetime.now(timezone.utc).isoformat(), job_id),
         )
         return cur.rowcount > 0
 
 
+def bg_get_job(job_id: str) -> dict | None:
+    with _conn() as c:
+        row = c.execute("SELECT * FROM bg_jobs WHERE id = ?", (job_id,)).fetchone()
+        return dict(row) if row else None
+
+
 def bg_finish_trigger(job_id: str, last_output: str = "") -> None:
     with _conn() as c:
         c.execute(
             "UPDATE bg_jobs SET status='triggered', last_output=? WHERE id=?",
             (last_output[-3000:], job_id),
         )
 
 
@@ -1802,44 +1812,68 @@ def usage_get_history(hours: int = 24, step_minutes: int = 5, until: str = "") -
         t += step
     if not grid or grid[-1].get("id") != raw[-1].get("id"):
         grid.append(raw[-1])
     return grid
 
 
 # ── Test Lock ──
 
-def acquire_test_lock(scope: str, holder: str, reason: str = "") -> tuple[bool, str | None]:
+def _same_lock_holder(row, holder: str, holder_session_id: str) -> bool:
+    """Тот же держатель?
+
+    По НЕИЗМЕНЯЕМОМУ id, когда он известен обеим сторонам: имя агента меняется
+    `rename_worker` и может быть занято другим агентом — тогда сравнение по строке либо
+    не даёт снять свой лок, либо даёт снять ЧУЖОЙ. Строка от старого сервера id не имеет,
+    и для неё остаётся сравнение по имени — иначе живой лок стал бы неснимаемым в окне
+    между мержем и рестартом.
+    """
+    stored_id = row["holder_session_id"] if "holder_session_id" in row.keys() else ""
+    if stored_id and holder_session_id:
+        return stored_id == holder_session_id
+    return row["holder"] == holder
+
+
+def acquire_test_lock(scope: str, holder: str, reason: str = "",
+                      holder_session_id: str = "") -> tuple[bool, str | None]:
     """Захватить глобальный тест-лок для scope.
 
     Возвращает (ok, current_holder):
     - (True, None)   — лок свободен, захвачен
-    - (True, holder) — лок уже за этим же holder (идемпотентно), reason обновлён
+    - (True, holder) — лок уже за этим же держателем (идемпотентно), reason обновлён
     - (False, name)  — занят другим, name = текущий держатель
     """
     now = datetime.now(timezone.utc).isoformat()
     with _conn() as c:
-        row = c.execute("SELECT holder FROM test_lock WHERE scope = ?", (scope,)).fetchone()
+        row = c.execute("SELECT * FROM test_lock WHERE scope = ?", (scope,)).fetchone()
         if row is not None:
-            if row["holder"] == holder:
-                c.execute("UPDATE test_lock SET reason = ?, acquired_at = ? WHERE scope = ?",
-                          (reason, now, scope))
+            if _same_lock_holder(row, holder, holder_session_id):
+                # Имя держателя могло смениться с момента захвата — показываем текущее.
+                c.execute(
+                    "UPDATE test_lock SET holder = ?, holder_session_id = ?, reason = ?, "
+                    "acquired_at = ? WHERE scope = ?",
+                    (holder, holder_session_id or row["holder_session_id"], reason, now, scope),
+                )
                 return True, holder
             return False, row["holder"]
         c.execute(
-            "INSERT INTO test_lock (scope, holder, reason, acquired_at) VALUES (?, ?, ?, ?)",
-            (scope, holder, reason, now),
+            "INSERT INTO test_lock (scope, holder, holder_session_id, reason, acquired_at) "
+            "VALUES (?, ?, ?, ?, ?)",
+            (scope, holder, holder_session_id, reason, now),
         )
         return True, None
 
 
-def release_test_lock(scope: str, holder: str) -> bool:
-    """Освободить лок. True — освобождён (был за этим holder); False — не держатель / лок свободен."""
+def release_test_lock(scope: str, holder: str, holder_session_id: str = "") -> bool:
+    """Освободить лок. True — освобождён (был за этим держателем); False — не держатель."""
     with _conn() as c:
-        cur = c.execute("DELETE FROM test_lock WHERE scope = ? AND holder = ?", (scope, holder))
+        row = c.execute("SELECT * FROM test_lock WHERE scope = ?", (scope,)).fetchone()
+        if row is None or not _same_lock_holder(row, holder, holder_session_id):
+            return False
+        cur = c.execute("DELETE FROM test_lock WHERE scope = ?", (scope,))
         return cur.rowcount > 0
 
 
 def get_test_lock(scope: str) -> dict | None:
     """Текущий держатель лока для scope или None."""
     with _conn() as c:
         row = c.execute("SELECT * FROM test_lock WHERE scope = ?", (scope,)).fetchone()
         return dict(row) if row else None
diff --git a/app/manager.py b/app/manager.py
index ccf0f7822..96a5a6963 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -383,25 +383,29 @@ def _parse_custom_mcp(raw) -> dict:
             return {}
     if not isinstance(raw, dict):
         logger.warning(f"mcp_servers_custom is not an object ({type(raw).__name__}); ignoring")
         return {}
     return {k: v for k, v in raw.items() if k != "orchestra"}
 
 
 def _make_mcp_config(name: str, scope: str, role: str = "worker",
-                     parent_name: str = "", extra: dict | None = None) -> dict:
+                     parent_name: str = "", extra: dict | None = None,
+                     session_id: str = "") -> dict:
     env = {
         **MCP_BASE_ENV,
         "ORCHESTRA_URL": "http://127.0.0.1:8888",
         "ORCHESTRA_SCOPE": scope,
         "ORCHESTRA_ROLE": role,
         "ORCHESTRA_ACCESS_MODE": "full",
         "WORKER_NAME": name,
         "PARENT_NAME": parent_name,
+        # Имя агент может сменить, id — нет. Всё, что СОХРАНЯЕТСЯ и сравнивается позже
+        # (держатель тест-лока), обязано опираться на него, а не на имя (#82).
+        "ORCHESTRA_SESSION_ID": session_id,
     }
     cfg = {"orchestra": {"command": MCP_STDIO_CMD[0], "args": MCP_STDIO_CMD[1:], "env": env, "alwaysLoad": True}}
     if extra:
         for k, v in extra.items():
             if k == "orchestra":
                 logger.warning("custom MCP server 'orchestra' would override Orchestra MCP — ignored")
                 continue
             cfg[k] = v
@@ -638,23 +642,25 @@ class SessionManager:
         if is_orch and not parent_name:
             tg_topic = True
 
         custom_mcp = _parse_custom_mcp(mcp_servers)
         bt = backend_for_model(model)
         _rr_effort = get_role(pipeline, role)
         raw_effort = getattr(_rr_effort, "effort", None) if _rr_effort else None
         effort = raw_effort if isinstance(raw_effort, str) and raw_effort else None
+        session_id = str(uuid.uuid4())
         session = AgentSession(
-            id=str(uuid.uuid4()), name=name, scope=scope, cwd=cwd, model=model,
+            id=session_id, name=name, scope=scope, cwd=cwd, model=model,
             system_prompt=prompt, role=role,
             parent_id=parent_id, parent_name=parent_name,
             pipeline=pipeline, profile=profile,
             color="" if is_orch else self._pick_color(),
-            mcp_servers=_make_mcp_config(name, scope, role, parent_name=parent_name, extra=custom_mcp),
+            mcp_servers=_make_mcp_config(name, scope, role, parent_name=parent_name,
+                                         extra=custom_mcp, session_id=session_id),
             mcp_servers_custom=custom_mcp,
             backend_type=bt, effort=effort, task_id=task_id, description=description,
             base_branch=base_branch,
             owned_dirs=owned_dirs,
             tg_topic=tg_topic,
         )
         session.is_orchestrator = is_orch
         session._template_hash = prompt_template_hash(role)
@@ -956,16 +962,40 @@ class SessionManager:
             await asyncio.to_thread(
                 remove_worktree,
                 session.scope,
                 session.worktree_path,
             )
         archive_session(session_id)
         self.sessions.pop(session_id, None)
 
+    def refresh_identity(self, session) -> str:
+        """Пересобрать MCP-конфиг сессии под её ТЕКУЩИЕ имя и родителя.
+
+        `WORKER_NAME`/`PARENT_NAME` попадают в env MCP-подпроцесса один раз — при его
+        старте, — поэтому переименование обязано поднять подпроцесс заново. Конфиг
+        обновляем СРАЗУ: любой следующий коннект строит бэкенд из `session.mcp_servers`,
+        значит упавший ход, гибернация и рестарт чинятся сами. Живой бэкенд гасится не


## LATER FIX 402715d761 (61.2 days later): V-653: #V-653: fix timer, cron timeout, and migration
lines of origin it changed/deleted: 16
(code only, capped 400 lines)

V-653: #V-653: fix timer, cron timeout, and migration

Squashed commits:
- #V-653: fix timer, cron timeout, and migration
- #V-653: cancel only pending precompact timers
- #V-653: cover precompact timer removal after hibernate
- #V-653: record hibernated timer mutation check

Orchestra-Operation: 7e291512-62ac-4b6c-ab4d-144443d975fd


diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index b290ca9bf..bd35d70e2 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -886,26 +886,47 @@ class BgJobManager:
                 shell=True,
                 stdout=asyncio.subprocess.PIPE,
                 stderr=asyncio.subprocess.PIPE,
             )
             self._procs[job_id] = proc
             try:
                 stdout, stderr = await _communicate_cron_command(proc)
             except asyncio.TimeoutError:
+                previous = bg_get_job(job_id) or {}
+                already_notified = str(previous.get("last_output") or "").startswith(
+                    "[command timed out after "
+                )
                 output = (
                     f"[command timed out after "
                     f"{_CRON_COMMAND_TIMEOUT_SECONDS} seconds]"
                 )
                 bg_update_output(job_id, output)
                 logger.warning(
                     "cron_command %s: command timed out after %ss",
                     job_id,
                     _CRON_COMMAND_TIMEOUT_SECONDS,
                 )
+                if not already_notified and bg_cron_should_fire(job_id):
+                    session, _failure = await self._load_job_target(job_id, target_name)
+                    if session:
+                        self._restore_report_provenance(session)
+                        body = (
+                            f"[Cron command timed out] bg job {job_id}; command: {command}; "
+                            f"limit: {_CRON_COMMAND_TIMEOUT_SECONDS} seconds. "
+                            "The command was stopped. Check its runtime/output and adjust "
+                            "the command or schedule before the next run."
+                        )
+                        provenance = MessageProvenance(
+                            origin="background_task", senders=(job_id,),
+                            subtype="cron_command_timeout", ref=job_id,
+                        )
+                        await self._session_manager.send(
+                            session.id, body, provenance=provenance,
+                        )
                 return
 
             raw_output = (
                 stdout.decode(errors="replace")
                 + stderr.decode(errors="replace")
             )
             output = raw_output
             if proc.returncode:
diff --git a/app/manager.py b/app/manager.py
index 9dc8b5e39..a82ea3889 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -1183,16 +1183,18 @@ class SessionManager:
         # #219 T1b, AC-2: убитый ребёнок обязан породить ПОЛОЖИТЕЛЬНЫЙ терминальный
         # токен. Гейт на `fire_auto_report` его породить не может — тот выходит
         # раньше `on_idle` для `_manually_interrupted` (`session_turns.py:266`).
         # Без этого веер висит до дедлайна при уже известном исходе.
         _killed_name = session.name if session else (get_session(session_id) or {}).get("name")
         if _killed_name:
             from app import fan_barrier
             fan_barrier.on_child_killed(_killed_name)
+        if session is not None:
+            session._cancel_precompact_timer("removed")
         # Процесс CLI есть только у загруженной живой сессии; гасим его до удаления
         # worktree, в котором он работает. Гидрированная из БД сессия его не имеет.
         if session is not None and session.loaded:
             await session._disconnect_backend()
         if session is None:
             row = get_session(session_id)
             if row is None:
                 return
diff --git a/app/startup_migration.py b/app/startup_migration.py
index a10098b96..b8547de67 100644
--- a/app/startup_migration.py
+++ b/app/startup_migration.py
@@ -54,17 +54,17 @@ def _database_needs_migration(connection: sqlite3.Connection) -> bool:
             "SELECT name FROM sqlite_master WHERE type='table'"
         ).fetchall()
     }
     if "tm_tasks" not in tables:
         return False  # свежая установка: схема создаётся сразу нужной версии
     columns = {
         str(row[1]) for row in connection.execute("PRAGMA table_info(tm_tasks)").fetchall()
     }
-    return "tags" not in columns
+    return "tags" not in columns or "attention_events" not in tables
 
 
 def _backup(database: Path) -> Path:
     stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
     target = database.with_name(f"{database.stem}-pre-v576-{stamp}.db")
     source = sqlite3.connect(str(database))
     try:
         destination = sqlite3.connect(str(target))
@@ -130,22 +130,37 @@ def _migrate_database(database: Path) -> dict:
     try:
         version = int(connection.execute("PRAGMA user_version").fetchone()[0])
         if not _database_needs_migration(connection):
             if version == DB_VERSION_AFTER:
                 return {"state": "already", "schema_version": version}
             connection.execute(f"PRAGMA user_version={DB_VERSION_AFTER}")
             connection.commit()
             return {"state": "version_only", "schema_version": DB_VERSION_AFTER}
-        if version != DB_VERSION_BEFORE:
+        if version not in (DB_VERSION_BEFORE, DB_VERSION_AFTER):
             raise MigrationError(
-                f"unsupported schema version {version}; expected {DB_VERSION_BEFORE} before V-576"
+                f"unsupported schema version {version}; expected {DB_VERSION_BEFORE} or "
+                f"{DB_VERSION_AFTER} for V-576 repair"
             )
         connection.execute("BEGIN IMMEDIATE")
-        connection.execute("ALTER TABLE tm_tasks ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")
+        columns = {
+            str(row[1]) for row in connection.execute("PRAGMA table_info(tm_tasks)").fetchall()
+        }
+        if "tags" not in columns:
+            connection.execute("ALTER TABLE tm_tasks ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")
+        connection.execute("""
+            CREATE TABLE IF NOT EXISTS attention_events (
+                id TEXT PRIMARY KEY,
+                kind TEXT NOT NULL
+                    CHECK(kind IN ('legacy','incident','reversal','plan_change','waiting')),
+                reason TEXT NOT NULL,
+                source_session_id TEXT NOT NULL REFERENCES sessions(id),
+                created_at TEXT NOT NULL
+            )
+        """)
         connection.execute(f"PRAGMA user_version={DB_VERSION_AFTER}")
         connection.commit()
         return {"state": "migrated", "schema_version": DB_VERSION_AFTER}
     except MigrationError:
         connection.rollback()
         raise
     except Exception as error:
         connection.rollback()
diff --git a/tests/test_bg_jobs.py b/tests/test_bg_jobs.py
index fb564459e..6b223be7e 100644
--- a/tests/test_bg_jobs.py
+++ b/tests/test_bg_jobs.py
@@ -457,49 +457,62 @@ class TestCronCommand:
             "w1",
             "/s",
         )
 
         manager.ensure_loaded.assert_not_awaited()
         session.send.assert_not_awaited()
 
     @pytest.mark.asyncio
-    async def test_timeout_never_wakes_even_after_partial_match(
+    async def test_timeout_wakes_once_until_a_successful_run(
         self, db, mgr_mock, monkeypatch,
     ):
         import app.bg_jobs as module
         from app.bg_jobs import BgJobManager
         from app.db import bg_get_active_all, bg_save_job
 
         mgr = BgJobManager()
         manager, session = mgr_mock
         mgr.set_session_manager(manager)
         bg_save_job(self._job("cron-command-timeout", datetime.now(timezone.utc)))
-        proc = self._proc(output=b"ALERT: partial\n", returncode=None)
-        monkeypatch.setattr(module, "_spawn_bg_process", AsyncMock(return_value=proc))
+        procs = [
+            self._proc(output=b"ALERT: partial\n", returncode=None),
+            self._proc(output=b"ALERT: partial\n", returncode=None),
+            self._proc(output=b"healthy\n"),
+            self._proc(output=b"ALERT: partial\n", returncode=None),
+        ]
+        monkeypatch.setattr(module, "_spawn_bg_process", AsyncMock(side_effect=procs))
 
-        async def timeout(_process):
-            raise asyncio.TimeoutError
+        async def communicate(process):
+            if process.returncode is None:
+                raise asyncio.TimeoutError
+            return process.output, process.error
 
         killed = AsyncMock()
-        monkeypatch.setattr(module, "_communicate_cron_command", timeout)
+        monkeypatch.setattr(module, "_communicate_cron_command", communicate)
         monkeypatch.setattr(module, "_kill_proc", killed)
 
-        await mgr._fire_cron_command(
-            "cron-command-timeout",
-            "python monitor.py",
-            "ALERT",
-            "monitor found work",
-            "w1",
-            "/s",
-        )
+        for _ in range(4):
+            await mgr._fire_cron_command(
+                "cron-command-timeout",
+                "python monitor.py",
+                "ALERT",
+                "monitor found work",
+                "w1",
+                "/s",
+            )
 
-        manager.ensure_loaded.assert_not_awaited()
-        session.send.assert_not_awaited()
-        killed.assert_awaited_once_with(proc)
+        assert manager.ensure_loaded_by_id.await_count == 2
+        assert session.send.await_count == 2
+        notified = session.send.await_args_list[0].args[0]
+        assert "cron-command-timeout" in notified
+        assert "python monitor.py" in notified
+        assert "600 seconds" in notified
+        assert "Check its runtime/output" in notified
+        assert killed.await_count == 4
         row = next(
             job for job in bg_get_active_all()
             if job["id"] == "cron-command-timeout"
         )
         assert row["status"] == "active"
         assert "timed out after 600 seconds" in row["last_output"]
 
     @pytest.mark.asyncio
diff --git a/tests/test_manager.py b/tests/test_manager.py
index 577de77e6..047e6dbc8 100644
--- a/tests/test_manager.py
+++ b/tests/test_manager.py
@@ -1672,22 +1672,43 @@ class TestSendAndControl:
         session.needs_switch = False
         session.send = AsyncMock()
 
         await mgr.send(session.id, "steer", provenance=USER_PROVENANCE)
 
         session.send.assert_awaited_once_with("steer", provenance=USER_PROVENANCE)
 
     @pytest.mark.asyncio
-    async def test_stop_and_remove(self, mgr):
+    async def test_remove_cancels_pending_precompact_timer(self, mgr, monkeypatch):
         from tests.conftest import make_backend_mock
         with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
             session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]")
+            session.loaded = False
+            sleeping = asyncio.Event()
+            release_sleep = asyncio.Event()
+
+            async def wait_until_cancelled(_delay):
+                sleeping.set()
+                await release_sleep.wait()
+
+            monkeypatch.setattr("app.session.asyncio.sleep", wait_until_cancelled)
+            session.compact = AsyncMock()
+            session._fire_precompact_timer = AsyncMock(side_effect=session.compact)
+            session._precompact_timer = {"delay_seconds": 1500}
+            timer_task = session._spawn_bg(session._run_precompact_timer())
+            session._precompact_timer_task = timer_task
+            await sleeping.wait()
             await mgr.remove(session.id)
+            release_sleep.set()
+            await timer_task
         assert mgr.get(session.id) is None
+        assert timer_task.done()
+        session._fire_precompact_timer.assert_not_awaited()
+        session.compact.assert_not_awaited()
+        assert session._precompact_timer is None
 
     @pytest.mark.asyncio
     async def test_remove_deletes_from_dict_and_db(self, mgr):
         from app.db import get_session
         from tests.conftest import make_backend_mock
         with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
             session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]")
             await mgr.remove(session.id)
diff --git a/tests/test_startup_migration_v576.py b/tests/test_startup_migration_v576.py
index 598c3d7ce..f02291670 100644
--- a/tests/test_startup_migration_v576.py
+++ b/tests/test_startup_migration_v576.py
@@ -122,16 +122,35 @@ def test_second_start_changes_nothing(legacy_install):
     second = migrate_v576(database, root)
 
     assert first["state"] == "migrated"
     assert second == {"state": "already"}
     assert _head(root) == head_after_first
     assert sorted(p.name for p in database.parent.glob("*pre-v576*")) == backups_after_first
 
 
+def test_v3_database_missing_attention_events_is_repaired(legacy_install):
+    database, root, _records = legacy_install
+    migrate_v576(database, root)
+    with sqlite3.connect(database) as connection:
+        connection.execute("DROP TABLE attention_events")
+        connection.commit()
+
+    result = migrate_v576(database, root)
+
+    assert result["state"] == "migrated"
+    with sqlite3.connect(database) as connection:
+        table = connection.execute(
+            "SELECT sql FROM sqlite_master WHERE type='table' AND name='attention_events'"
+        ).fetchone()
+        assert table and "CREATE TABLE attention_events" in table[0]
+        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == 3
+    assert migrate_v576(database, root) == {"state": "already"}
+
+
 def test_a_dirty_task_store_refuses_instead_of_mixing_changes_in(legacy_install):
     database, root, records = legacy_install
     stray = root / "projects" / "alpha-vps" / "tasks" / "stray.json"
     stray.write_text("{}\n")
 
     with pytest.raises(MigrationError, match="uncommitted"):
         migrate_v576(database, root)
 