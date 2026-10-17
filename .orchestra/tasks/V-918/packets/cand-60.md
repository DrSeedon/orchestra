# Candidate cand-60

## ORIGIN commit 444115851c (2026-08-28): #414: cover restart-safe background jobs
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index dcd069382..a28c7e804 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -334,16 +334,30 @@ class BgJobManager:
     def __init__(self):
         self._tasks: dict[str, asyncio.Task] = {}
         self._procs: dict[str, asyncio.subprocess.Process] = {}
         self._session_manager = None
 
     def set_session_manager(self, mgr) -> None:
         self._session_manager = mgr
 
+    async def _spawn_managed_process(self, job_id, command, *, shell, **kwargs):
+        """Register a process or kill it if the owner is cancelled during spawn."""
+        spawn_task = asyncio.create_task(
+            _spawn_bg_process(command, shell=shell, **kwargs)
+        )
+        try:
+            proc = await asyncio.shield(spawn_task)
+        except asyncio.CancelledError:
+            proc = await asyncio.shield(spawn_task)
+            await _kill_proc(proc)
+            raise
+        self._procs[job_id] = proc
+        return proc
+
     async def create(self, job_type: str, config: dict, message: str,
                      target_session_id: str, target_name: str, target_scope: str,
                      created_by: str, timeout_seconds: int = DEFAULT_TIMEOUT,
                      replace_key: str = "") -> dict:
         err = _validate_config(job_type, config)
         if err:
             return {"error": err}
         count = bg_count_active(target_scope)
@@ -492,33 +506,44 @@ class BgJobManager:
         active = bg_get_active_all()
         restored = 0
         for row in active:
             if row["id"] in self._tasks:
                 continue
             if row["status"] != "active":
                 continue
             config = json.loads(row["config"])
+            if row["type"] == "run":
+                await self._interrupt_run_notify(
+                    row["id"], row["message"], row["target_name"], row["target_scope"],
+                )
+                continue
             remaining = (datetime.fromisoformat(row["expires_at"]) - datetime.now(timezone.utc)).total_seconds()
             if remaining <= 0:
                 bg_expire_job(row["id"])
                 continue
             self._start_task(
                 row["id"], row["type"], config, row["message"],
                 row["target_session_id"], row["target_name"], row["target_scope"],
                 remaining, trigger_at=row.get("trigger_at"),
             )
             restored += 1
         logger.info(f"bg_jobs: restored {restored} jobs, expired {len(expired_ids)}")
 
     async def shutdown(self) -> None:
         for jid, task in list(self._tasks.items()):
             task.cancel()
         for jid, proc in list(self._procs.items()):
-            await _kill_proc(proc)
+            try:
+                await _kill_proc(proc)
+            except Exception as e:
+                logger.error(
+                    "bg_job %s: shutdown process kill failed (%s): %s",
+                    jid, type(e).__name__, e,
+                )
         self._tasks.clear()
         self._procs.clear()
 
     def has_active_jobs(self, session_id: str) -> bool:
         return len(bg_get_jobs(session_id=session_id, active_only=True)) > 0
 
     # ── Trigger ──
 
@@ -641,16 +666,36 @@ class BgJobManager:
             await self._session_manager.send(
                 session.id,
                 self._terminal_message(job_id, "failed", body),
             )
             logger.warning(f"bg_job {job_id}: FAILED → notified {target_name}: {error}")
         except Exception as e:
             logger.error(f"bg_job {job_id}: failure-notify failed: {e}")
 
+    async def _interrupt_run_notify(self, job_id, message, target_name, target_scope):
+        reason = "Прерван рестартом сервиса, повторный запуск не выполнялся."
+        bg_fail_job(job_id, reason)
+        try:
+            session, _failure = await self._load_job_target(job_id, target_name)
+            if not session:
+                return
+            body = f"[Background job INTERRUPTED] {message}\n{reason}"
+            self._restore_report_provenance(session)
+            await self._session_manager.send(
+                session.id,
+                self._terminal_message(job_id, "interrupted", body),
+            )
+            logger.warning(
+                "bg_job %s: interrupted by service restart → notified %s",
+                job_id, target_name,
+            )
+        except Exception as e:
+            logger.error(f"bg_job {job_id}: restart-interrupt notify failed: {e}")
+
     def _fail_if_active(self, job_id: str, error: str) -> None:
         bg_fail_job_if_active(job_id, error)
 
     # ── Runners ──
 
     async def _run_timer(self, job_id, delay, message, target_name, target_scope):
         try:
             await asyncio.sleep(delay)
@@ -717,18 +762,18 @@ class BgJobManager:
     async def _fire_cron_command(
         self, job_id, command, pattern, message, target_name, target_scope,
     ):
         if not bg_cron_should_fire(job_id):
             return
         proc = None
         output = ""
         try:
-            proc = await _spawn_bg_process(
-                command,
+            proc = await self._spawn_managed_process(
+                job_id, command,
                 shell=True,
                 stdout=asyncio.subprocess.PIPE,
                 stderr=asyncio.subprocess.PIPE,
             )
             self._procs[job_id] = proc
             try:
                 stdout, stderr = await _communicate_cron_command(proc)
             except asyncio.TimeoutError:
@@ -781,18 +826,18 @@ class BgJobManager:
                 self._procs.pop(job_id, None)
             if proc:
                 await _kill_proc(proc)
 
     async def _run_file_watch(self, job_id, path, pattern, message,
                               target_name, target_scope, timeout):
         proc = None
         try:
-            proc = await _spawn_bg_process(
-                ["tail", "-F", "-n", "0", path],
+            proc = await self._spawn_managed_process(
+                job_id, ["tail", "-F", "-n", "0", path],
                 shell=False,
                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
             )
             self._procs[job_id] = proc
             async with asyncio.timeout(timeout):
                 async for line in proc.stdout:
                     text = line.decode(errors="replace")
                     if re.search(pattern, text):
@@ -810,18 +855,18 @@ class BgJobManager:
             if proc:
                 await _kill_proc(proc)
 
     async def _run_command_watch(self, job_id, command, pattern, interval,
                                  message, target_name, target_scope, timeout):
         deadline = (time.time() + timeout) if timeout is not None else None
         try:
             while deadline is None or time.time() < deadline:
-                proc = await _spawn_bg_process(
-                    command, shell=True,
+                proc = await self._spawn_managed_process(
+                    job_id, command, shell=True,
                     stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                 )
                 self._procs[job_id] = proc
                 try:
                     stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                 except asyncio.TimeoutError:
                     await _kill_proc(proc)
                     stdout, stderr = b"", b""
@@ -838,18 +883,18 @@ class BgJobManager:
             pass
         except Exception as e:
             bg_fail_job(job_id, str(e)[:500])
 
     async def _run_ssh_watch(self, job_id, host, command, pattern, message,
                               target_name, target_scope, timeout):
         proc = None
         try:
-            proc = await _spawn_bg_process(
-                ["ssh", *_SSH_OPTS, host, command],
+            proc = await self._spawn_managed_process(
+                job_id, ["ssh", *_SSH_OPTS, host, command],
                 shell=False,
                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
             )
             self._procs[job_id] = proc
             async with asyncio.timeout(timeout):
                 async for line in proc.stdout:
                     text = line.decode(errors="replace")
                     if re.search(pattern, text):
@@ -873,25 +918,25 @@ class BgJobManager:
         proc = None
         reader_task = None
         output_buf = []
         try:
             # 16MB readline limit: Codex JSONL contains base64 images / long JSON lines
             # that exceed asyncio's default 64KB StreamReader limit → ValueError
             _STREAM_LIMIT = 16 * 1024 * 1024
             if host:
-                proc = await _spawn_bg_process(
-                    ["ssh", *_SSH_OPTS, host, command],
+                proc = await self._spawn_managed_process(
+                    job_id, ["ssh", *_SSH_OPTS, host, command],
                     shell=False,
                     stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                     limit=_STREAM_LIMIT,
                 )
             else:
-                proc = await _spawn_bg_process(
-                    command, shell=True,
+                proc = await self._spawn_managed_process(
+                    job_id, command, shell=True,
                     stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                     limit=_STREAM_LIMIT,
                 )
             self._procs[job_id] = proc
             where = host or "local"
             logger.info(f"bg_job {job_id}: run started pid={proc.pid} on={where} "
                         f"timeout={timeout}s cmd_len={len(command)}")
             last_progress = time.time()
diff --git a/tests/test_bg_jobs.py b/tests/test_bg_jobs.py
index c69d28e1f..560073e4c 100644
--- a/tests/test_bg_jobs.py
+++ b/tests/test_bg_jobs.py
@@ -784,16 +784,142 @@ class TestRunExecOutcome:
             "w1", "/s", 10,
             success_file=str(artifact),
         )
 
         row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-sandbox-talk")
         assert row["status"] == "triggered"
 
 
+class TestRestartProcessSafety:
+    @staticmethod
+    def _job(job_id, job_type, config):
+        now = datetime.now(timezone.utc)
+        return {
+            "id": job_id, "type": job_type, "config": json.dumps(config),
+            "message": "background task", "target_session_id": "s-1",
+            "target_name": "w1", "target_scope": "/s", "created_by_name": "orch",
+            "status": "active", "expires_at": (now + timedelta(hours=1)).isoformat(),
+            "trigger_at": None, "created_at": now.isoformat(), "last_output": "",
+        }
+
+    @pytest.mark.asyncio
+    async def test_restore_marks_active_run_interrupted_without_restarting(
+        self, db, mgr_mock, monkeypatch,
+    ):
+        import app.bg_jobs as module
+        from app.bg_jobs import BgJobManager
+        from app.db import bg_get_jobs, bg_save_job
+
+        mgr = BgJobManager()
+        manager, session = mgr_mock
+        mgr.set_session_manager(manager)
+        bg_save_job(self._job("run-restart", "run", {"command": "side-effect"}))
+        started = MagicMock()
+        monkeypatch.setattr(mgr, "_start_task", started)
+
+        await mgr.restore_from_db()
+
+        started.assert_not_called()
+        row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-restart")
+        assert row["status"] == "failed"
+        reason = "Прерван рестартом сервиса, повторный запуск не выполнялся"
+        assert reason in row["error"]
+        session.send.assert_awaited_once()
+        assert reason in session.send.await_args.args[0].text
+        assert module.bg_get_active_all() == []
+
+    @pytest.mark.asyncio
+    @pytest.mark.parametrize(
+        ("job_type", "config"),
+        [
+            ("timer", {"delay_seconds": 10}),
+            ("file", {"path": "/tmp/events.log", "pattern": "MATCH"}),
+            ("command", {"command": "printf MATCH", "pattern": "MATCH"}),
+            ("ssh", {"host": "example", "command": "journalctl", "pattern": "MATCH"}),
+            ("cron", {"cron_expr": "*/5 * * * *"}),
+            ("cron_command", {
+                "cron_expr": "*/5 * * * *", "command": "printf MATCH", "pattern": "MATCH",
+            }),
+        ],
+    )
+    async def test_restore_keeps_non_run_types_restartable(
+        self, db, monkeypatch, job_type, config,
+    ):
+        from app.bg_jobs import BgJobManager
+        from app.db import bg_save_job
+
+        mgr = BgJobManager()
+        bg_save_job(self._job(f"restore-{job_type}", job_type, config))
+        started = MagicMock()
+        monkeypatch.setattr(mgr, "_start_task", started)
+
+        await mgr.restore_from_db()
+
+        started.assert_called_once()
+        assert started.call_args.args[1] == job_type
+
+    @pytest.mark.asyncio
+    async def test_cancel_during_spawn_kills_unregistered_process(
+        self, db, monkeypatch,
+    ):
+        import app.bg_jobs as module
+        from app.bg_jobs import BgJobManager
+        from app.db import bg_save_job
+
+        mgr = BgJobManager()
+        bg_save_job(self._job("run-spawn-cancel", "run", {"command": "side-effect"}))
+        spawned = asyncio.Event()
+        release = asyncio.Event()
+        proc = type("Process", (), {"pid": 123, "returncode": None})()
+
+        async def spawn(*_args, **_kwargs):
+            spawned.set()
+            await release.wait()
+            return proc
+
+        killed = AsyncMock()
+        monkeypatch.setattr(module, "_spawn_bg_process", spawn)
+        monkeypatch.setattr(module, "_kill_proc", killed)
+        task = asyncio.create_task(
+            mgr._run_exec("run-spawn-cancel", "side-effect", "background task", "w1", "/s", 10)
+        )
+        await spawned.wait()
+        task.cancel()
+        release.set()
+        await asyncio.gather(task, return_exceptions=True)
+
+        killed.assert_awaited_once_with(proc)
+        assert "run-spawn-cancel" not in mgr._procs
+
+    @pytest.mark.asyncio
+    async def test_shutdown_kill_failure_does_not_skip_other_processes(
+        self, monkeypatch, caplog,
+    ):
+        import app.bg_jobs as module
+        from app.bg_jobs import BgJobManager
+
+        mgr = BgJobManager()
+        first = object()
+        second = object()
+        mgr._procs = {"first": first, "second": second}
+        killed = AsyncMock(side_effect=[RuntimeError("pidfd missing"), None])
+        monkeypatch.setattr(module, "_kill_proc", killed)
+        caplog.set_level("ERROR", logger="app.bg_jobs")
+
+        await mgr.shutdown()
+
+        assert killed.await_args_list == [
+            ((first,),), ((second,),),
+        ]
+        assert "first" in caplog.text
+        assert "RuntimeError" in caplog.text
+        assert mgr._procs == {}
+
+
 class TestPidfdProcessLifecycle:
     @pytest.mark.asyncio
     async def test_shell_and_argv_modes_preserve_arguments(self):
         from app.bg_jobs import _kill_proc, _spawn_bg_process
 
         argv_proc = await _spawn_bg_process(
             ["/usr/bin/printf", "%s", "argv value"],
             shell=False,


## LATER FIX 17a7d398b9 (40.5 days later): V-756: #V-756: fix repeated workflow prompts and wakes
lines of origin it changed/deleted: 14
(code only, capped 400 lines)

V-756: #V-756: fix repeated workflow prompts and wakes

Squashed commits:
- #V-756: fix repeated workflow prompts and wakes
- #V-756: import workflow runner in regression test
- #V-756: record merge gate verification

Orchestra-Operation: a3291105-3158-41af-aecd-f325f21e867f


diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index c88f5ca4d..147005f5b 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -478,38 +478,52 @@ class BgJobManager:
             lambda finished: (
                 self._tasks.pop(job_id, None)
                 if self._tasks.get(job_id) is finished
                 else None
             )
         )
 
     async def cancel(self, job_id: str) -> dict:
+        row = bg_get_job(job_id) or {}
         ok = bg_cancel_job(job_id)
         if not ok:
             return {"error": "job not found or not active"}
         task = self._tasks.pop(job_id, None)
         if task and not task.done():
             task.cancel()
         proc = self._procs.pop(job_id, None)
         if proc:
             await _kill_proc(proc)
+        if row.get("type") == "run":
+            await self._interrupt_run_notify(
+                job_id, row.get("message") or "Background run", row.get("target_name") or "?",
+                row.get("target_scope") or "",
+                reason="Отменён вызывающим агентом; повторный запуск не выполнялся.",
+                output=row.get("last_output") or "",
+            )
         return {"ok": True}
 
     async def cancel_by_session(self, session_id: str) -> None:
         active = bg_get_jobs(session_id=session_id, active_only=True)
         job_ids = [j["id"] for j in active]
         cancelled_count = bg_cancel_by_session(session_id)
         for jid in job_ids:
             task = self._tasks.pop(jid, None)
             if task and not task.done():
                 task.cancel()
             proc = self._procs.pop(jid, None)
             if proc:
                 await _kill_proc(proc)
+            row = next((job for job in active if job["id"] == jid), {})
+            if row.get("type") == "run":
+                await self._report_undelivered_job(
+                    jid, row.get("target_name") or "?", row.get("target_scope") or "",
+                    "target session stopped while its run job was active",
+                )
         if cancelled_count:
             logger.info(f"bg_jobs: cancelled {cancelled_count} jobs for session {session_id}")
 
     async def restore_from_db(self) -> None:
         legacy_idle = bg_cancel_removed_idle()
         if legacy_idle:
             logger.info("bg_jobs: cancelled %s legacy idle watches (type removed)", legacy_idle)
         cleaned = bg_cleanup_old(24)
@@ -521,16 +535,27 @@ class BgJobManager:
                 "bg_jobs: reset %s interrupted wake jobs",
                 len(wake_reset_ids),
             )
         expired_ids = bg_expire_overdue()
         for jid in expired_ids:
             task = self._tasks.pop(jid, None)
             if task and not task.done():
                 task.cancel()
+            row = bg_get_job(jid)
+            if row and row.get("type") == "run":
+                timeout = max(
+                    1,
+                    (datetime.fromisoformat(row["expires_at"])
+                     - datetime.fromisoformat(row["created_at"])).total_seconds(),
+                )
+                await self._expire_notify(
+                    jid, row["message"], row["target_name"], row["target_scope"],
+                    timeout, row.get("last_output") or "",
+                )
         reset_ids = bg_reset_stale_triggering()
         if reset_ids:
             logger.info(f"bg_jobs: reset {len(reset_ids)} stale triggering jobs")
         interrupted_delivery = set(reset_ids)
         active = bg_get_active_all()
         restored = 0
         for row in active:
             if row["id"] in self._tasks:
@@ -620,129 +645,128 @@ class BgJobManager:
         if not session:
             logger.warning(
                 f"bg_job {job_id}: target session {target_session_id} "
                 f"(name at creation: {target_name!r}) not found"
             )
             return None, "target session not found"
         return session, ""
 
-    async def _trigger(self, job_id: str, message: str,
-                       target_name: str, target_scope: str, output: str = "") -> None:
-        claimed = bg_claim_trigger(job_id)
-        if not claimed:
-            return
+    async def _notify_job_target(
+        self, job_id: str, outcome: str, body: str,
+        target_name: str, target_scope: str,
+    ) -> str | None:
         try:
             session, failure = await self._load_job_target(job_id, target_name)
             if not session:
-                bg_fail_job(job_id, failure)
-                return
-            body = f"[Background job completed] {message}"
-            if output:
-                body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
+                raise RuntimeError(failure or "target session not found")
             self._restore_report_provenance(session)
-            injected = self._terminal_message(job_id, "completed", body)
+            injected = self._terminal_message(job_id, outcome, body)
             await self._session_manager.send(
-                session.id,
-                injected,
-                provenance=injected.provenance,
+                session.id, injected, provenance=injected.provenance,
             )
-            bg_finish_trigger(job_id, output)
-            logger.info(f"bg_job {job_id}: triggered → {target_name}")
-        except Exception as e:
-            bg_fail_job(job_id, str(e)[:500])
-            logger.error(f"bg_job {job_id}: trigger failed: {e}")
-            # Факт в состоянии джоба виден только глазами в дашборде — это не уведомление.
-            # Адресат — оркестратор scope: он ставил джоб, ему и решать (#30).
-            from app.notify import report_undelivered
+            return None
+        except Exception as error:
+            reason = f"{type(error).__name__}: {error}"
+            logger.error("bg_job %s: %s notification failed: %s", job_id, outcome, reason)
+            await self._report_undelivered_job(
+                job_id, target_name, target_scope, reason,
+            )
+            return reason
+
+    async def _report_undelivered_job(
+        self, job_id: str, target_name: str, target_scope: str, reason: str,
+    ) -> None:
+        from app.notify import report_undelivered
 
+        try:
             await report_undelivered(
                 self._session_manager,
                 scope=target_scope,
                 worker=target_name,
-                what=f"результат фоновой задачи {job_id}",
-                reason=f"{type(e).__name__}: {e}",
+                what=f"result of background job {job_id}",
+                reason=reason,
                 dedupe_key=f"bgjob:{job_id}",
             )
+        except Exception as fallback_error:
+            logger.error(
+                "bg_job %s: undelivered report failed (%s): %s",
+                job_id, type(fallback_error).__name__, fallback_error,
+            )
+
+    async def _trigger(self, job_id: str, message: str,
+                       target_name: str, target_scope: str, output: str = "") -> None:
+        claimed = bg_claim_trigger(job_id)
+        if not claimed:
+            return
+        body = f"[Background job completed] {message}"
+        if output:
+            body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
+        failure = await self._notify_job_target(
+            job_id, "completed", body, target_name, target_scope,
+        )
+        if failure is None:
+            bg_finish_trigger(job_id, output)
+            logger.info(f"bg_job {job_id}: triggered → {target_name}")
+        else:
+            bg_fail_job(job_id, failure)
 
     def _expire(self, job_id: str) -> None:
         bg_expire_job(job_id)
         self._procs.pop(job_id, None)
 
     async def _expire_notify(self, job_id, message, target_name, target_scope,
                              timeout, output=""):
         """Timeout for a `run` job: NOTIFY the worker instead of expiring silently.
         Without this, a hung process leaves the worker waiting forever."""
         bg_expire_job(job_id)
         self._procs.pop(job_id, None)
         dur = f"{round(timeout / 60, 1)} min" if timeout >= 60 else f"{int(timeout)}s"
         err = (f"{message}\n[TIMEOUT] killed after {dur} — no completion. "
                f"The process produced no output or hung. Check the target tool "
                f"(codex auth/proxy/sandbox) and retry.")
-        try:
-            session, _failure = await self._load_job_target(job_id, target_name)
-            if not session:
-                return
-            body = f"[Background job TIMED OUT] {err}"
-            if output:
-                body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
-            self._restore_report_provenance(session)
-            injected = self._terminal_message(job_id, "timed_out", body)
-            await self._session_manager.send(
-                session.id,
-                injected,
-                provenance=injected.provenance,
-            )
+        body = f"[Background job TIMED OUT] {err}"
+        if output:
+            body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
+        failure = await self._notify_job_target(
+            job_id, "timed_out", body, target_name, target_scope,
+        )
+        if failure is None:
             logger.warning(f"bg_job {job_id}: TIMED OUT after {dur} → notified {target_name}")
-        except Exception as e:
-            logger.error(f"bg_job {job_id}: timeout-notify failed: {e}")
 
     async def _fail_notify(self, job_id, message, target_name, target_scope,
                            error, output=""):
         """Persist a failed run and wake the waiting agent with an explicit failure."""
         bg_fail_job(job_id, error)
-        try:
-            session, _failure = await self._load_job_target(job_id, target_name)
-            if not session:
-                return
-            body = f"[Background job FAILED] {message}\n{error}"
-            if output:
-                body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
-            self._restore_report_provenance(session)
-            injected = self._terminal_message(job_id, "failed", body)
-            await self._session_manager.send(
-                session.id,
-                injected,
-                provenance=injected.provenance,
-            )
+        body = f"[Background job FAILED] {message}\n{error}"
+        if output:
+            body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
+        failure = await self._notify_job_target(
+            job_id, "failed", body, target_name, target_scope,
+        )
+        if failure is None:
             logger.warning(f"bg_job {job_id}: FAILED → notified {target_name}: {error}")
-        except Exception as e:
-            logger.error(f"bg_job {job_id}: failure-notify failed: {e}")
 
-    async def _interrupt_run_notify(self, job_id, message, target_name, target_scope):
-        reason = "Прерван рестартом сервиса, повторный запуск не выполнялся."
+    async def _interrupt_run_notify(
+        self, job_id, message, target_name, target_scope,
+        reason="Прерван рестартом сервиса, повторный запуск не выполнялся.",
+        output="",
+    ):
         bg_fail_job(job_id, reason)
-        try:
-            session, _failure = await self._load_job_target(job_id, target_name)
-            if not session:
-                return
-            body = f"[Background job INTERRUPTED] {message}\n{reason}"
-            self._restore_report_provenance(session)
-            injected = self._terminal_message(job_id, "interrupted", body)
-            await self._session_manager.send(
-                session.id,
-                injected,
-                provenance=injected.provenance,
-            )
+        body = f"[Background job INTERRUPTED] {message}\n{reason}"
+        if output:
+            body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
+        failure = await self._notify_job_target(
+            job_id, "interrupted", body, target_name, target_scope,
+        )
+        if failure is None:
             logger.warning(
-                "bg_job %s: interrupted by service restart → notified %s",
+                "bg_job %s: interrupted → notified %s",
                 job_id, target_name,
             )
-        except Exception as e:
-            logger.error(f"bg_job {job_id}: restart-interrupt notify failed: {e}")
 
     def _fail_if_active(self, job_id: str, error: str) -> None:
         bg_fail_job_if_active(job_id, error)
 
     # ── Runners ──
 
     async def _run_merge_watch(self, job_id, operation_id, message,
                                target_name, target_scope, timeout):
@@ -1133,24 +1157,38 @@ class BgJobManager:
                     job_id, message, target_name, target_scope,
                     validation_error, full_output,
                 )
                 return
 
             trigger_msg = f"{message}\nExit code: 0"
             await self._trigger(job_id, trigger_msg, target_name, target_scope, full_output)
         except asyncio.TimeoutError:
+            kill_error = ""
             if proc:
-                await _kill_proc(proc)
-            await self._expire_notify(job_id, message, target_name, target_scope,
-                                      timeout, "".join(output_buf))
+                try:
+                    await _kill_proc(proc)
+                except Exception as error:
+                    kill_error = f"; process kill failed: {type(error).__name__}: {error}"
+            output = "".join(output_buf)
+            if kill_error:
+                output += f"\n{kill_error}"
+            await self._expire_notify(
+                job_id, message, target_name, target_scope, timeout,
+                output,
+            )
+            if kill_error:
+                logger.error("bg_job %s: %s", job_id, kill_error.lstrip("; "))
         except asyncio.CancelledError:
             pass
         except Exception as e:
-            bg_fail_job(job_id, str(e)[:500])
+            await self._fail_notify(
+                job_id, message, target_name, target_scope,
+                f"{type(e).__name__}: {e}", "".join(output_buf),
+            )
         finally:
             if reader_task and not reader_task.done():
                 reader_task.cancel()
                 await asyncio.gather(reader_task, return_exceptions=True)
             self._procs.pop(job_id, None)
             if proc:
                 await _kill_proc(proc)
                 transport = getattr(proc, "_transport", None)
diff --git a/scripts/wf_run.py b/scripts/wf_run.py
index a490e303e..49a76f9b8 100644
--- a/scripts/wf_run.py
+++ b/scripts/wf_run.py
@@ -106,16 +106,20 @@ class WorkflowValue:
             workspace_path=str(row.get("workspace_path") or ""),
             free_sources=frozenset(str(item) for item in row.get("free_sources") or []),
             verified_sources=frozenset(
                 str(item) for item in row.get("verified_sources") or []
             ),
         )
 
 
+class WorkspacePreparationError(RuntimeError):
+    pass
+
+
 class Budget:
     def __init__(self, maximum_usd: float, maximum_calls: int):
         if maximum_usd < 0:
             raise ValueError("budget_usd must be non-negative")
         if maximum_calls < 1:
             raise ValueError("max_calls must be positive")
         self.maximum_usd = float(maximum_usd)
         self.maximum_calls = int(maximum_calls)
@@ -492,29 +496,37 @@ class WorkflowEngine:
                 self.budget.spent_usd += float(row.get("cost_usd") or 0)
             elif event == "schema_invalid":
                 call_key = str(row.get("call_key") or "")
                 last_state[call_key] = "schema_invalid"
                 self._retry_state[call_key] = (
                     int(row.get("next_attempt") or 0),
                     str(row.get("error") or "schema validation failed"),
                 )
+            elif event == "prepare_failed":
+                call_key = str(row.get("call_key") or "")
+                last_state[call_key] = "prepare_failed"
+                self.budget.dispatched_calls = max(0, self.budget.dispatched_calls - 1)
+                self._step_records[call_key] = {
+                    **row, "reason": "prepare_failed", "value": None,
+                }
             elif event == "completed":
                 call_key = str(row.get("call_key") or "")
                 last_state[call_key] = "completed"
                 value = row.get("value")
                 self._completed[call_key] = (
                     WorkflowValue.from_record(value) if isinstance(value, dict) else None
                 )
                 self._completed_reason[call_key] = str(row.get("reason") or "completed")
                 self._step_records[call_key] = row
         self._unknown_calls = {
             call_key
             for call_key in dispatched_calls
-            if call_key not in self._completed and last_state.get(call_key) != "schema_invalid"
+            if call_key not in self._completed
+            and last_state.get(call_key) not in {"schema_invalid", "prepare_failed"}
         }
         if self._unknown_calls:
             self.budget.spent_usd = max(self.budget.spent_usd, self.budget.maximum_usd)
 