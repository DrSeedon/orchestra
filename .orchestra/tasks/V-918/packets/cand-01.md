# Candidate cand-01

## ORIGIN commit 5d3d2a1532 (2026-06-01): #41: #41: fix codex_review silent failures — notify worker on bg job timeout
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index f8dfbaf57..182db8f03 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -288,16 +288,41 @@ class BgJobManager:
         except Exception as e:
             bg_fail_job(job_id, str(e)[:500])
             logger.error(f"bg_job {job_id}: trigger failed: {e}")
 
     def _expire(self, job_id: str) -> None:
         bg_expire_job(job_id)
         self._procs.pop(job_id, None)
 
+    async def _expire_notify(self, job_id, message, target_name, target_scope,
+                             timeout, output=""):
+        """Timeout for a `run` job: NOTIFY the worker instead of expiring silently.
+        Without this, a hung process leaves the worker waiting forever."""
+        bg_expire_job(job_id)
+        self._procs.pop(job_id, None)
+        dur = f"{round(timeout / 60, 1)} min" if timeout >= 60 else f"{int(timeout)}s"
+        err = (f"{message}\n[TIMEOUT] killed after {dur} — no completion. "
+               f"The process produced no output or hung. Check the target tool "
+               f"(codex auth/proxy/sandbox) and retry.")
+        try:
+            session = await self._session_manager.ensure_loaded(target_name, target_scope)
+            if not session:
+                session = await self._session_manager.ensure_loaded_any(target_name)
+            if not session:
+                logger.warning(f"bg_job {job_id}: timeout, target {target_name} not found")
+                return
+            body = f"[Background job TIMED OUT] {err}"
+            if output:
+                body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
+            await session.send(body)
+            logger.warning(f"bg_job {job_id}: TIMED OUT after {dur} → notified {target_name}")
+        except Exception as e:
+            logger.error(f"bg_job {job_id}: timeout-notify failed: {e}")
+
     def _fail_if_active(self, job_id: str, error: str) -> None:
         from app.db import bg_fail_job_if_active
         bg_fail_job_if_active(job_id, error)
 
     # ── Runners ──
 
     async def _run_timer(self, job_id, delay, message, target_name, target_scope):
         try:
@@ -436,33 +461,42 @@ class BgJobManager:
                     preexec_fn=os.setsid,
                 )
             else:
                 proc = await asyncio.create_subprocess_shell(
                     command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                     preexec_fn=os.setsid,
                 )
             self._procs[job_id] = proc
+            where = host or "local"
+            logger.info(f"bg_job {job_id}: run started pid={proc.pid} on={where} "
+                        f"timeout={timeout}s cmd_len={len(command)}")
             last_progress = time.time()
             async with asyncio.timeout(timeout):
                 async for line in proc.stdout:
                     output_buf.append(line.decode(errors="replace"))
                     if len(output_buf) > 500:
                         output_buf = output_buf[-300:]
                     now = time.time()
                     if now - last_progress > OUTPUT_PROGRESS_INTERVAL:
                         bg_update_output(job_id, "".join(output_buf))
                         last_progress = now
                 await proc.wait()
             full_output = "".join(output_buf)
             exit_code = proc.returncode
-            trigger_msg = f"{message}\nExit code: {exit_code}"
+            note = "" if exit_code == 0 else " — process failed, see output"
+            trigger_msg = f"{message}\nExit code: {exit_code}{note}"
+            logger.info(f"bg_job {job_id}: run done pid={proc.pid} exit={exit_code} "
+                        f"lines={len(output_buf)}")
             await self._trigger(job_id, trigger_msg, target_name, target_scope, full_output)
         except asyncio.TimeoutError:
-            self._expire(job_id)
+            if proc:
+                await _kill_proc(proc)
+            await self._expire_notify(job_id, message, target_name, target_scope,
+                                      timeout, "".join(output_buf))
         except asyncio.CancelledError:
             pass
         except Exception as e:
             bg_fail_job(job_id, str(e)[:500])
         finally:
             self._procs.pop(job_id, None)
             if proc:
                 await _kill_proc(proc)
diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 47b72f3af..13282cc36 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -656,26 +656,31 @@ async def codex_review(
             f"cd {cwd} && UV_CACHE_DIR=/tmp/uv-cache {_CODEX_BIN} exec"
             f" -s workspace-write --skip-git-repo-check --full-auto --ephemeral"
             f" -o {output_abs}"
             f" - < {prompt_file}"
         )
     else:
         return f"Error: unknown mode '{mode}'. Use 'review' or 'exec'."
 
+    logger.info(f"codex_review: mode={mode} cwd={cwd} output={output_abs} cmd={cmd[:300]}")
     result = await _api("POST", "/api/bg/jobs", json={
         "type": "run",
         "config": {"command": cmd},
         "message": f"Codex {mode} done. Results in {output}",
         "target_name": WORKER_NAME,
         "target_scope": SCOPE,
-        "timeout_seconds": 600,
+        "timeout_seconds": 300,
         "created_by": WORKER_NAME,
     })
     if isinstance(result, dict) and result.get("error"):
         return f"Error creating bg job: {result['error']}"
     job_id = result.get("id", "?")
-    return f"Codex {mode} started (bg job {job_id}). You'll be notified when done. Results → {output}"
+    return (
+        f"Codex {mode} started (bg job {job_id}, 5-min timeout). "
+        f"You WILL be notified on success, timeout, or failure — do NOT poll, just wait. "
+        f"On success: read {output}. Do not start another codex_review until this one reports back."
+    )
 
 
 if __name__ == "__main__":
     logger.info(f"Orchestra MCP stdio (url={ORCHESTRA_URL}, scope={SCOPE})")
     mcp.run(transport="stdio")


## LATER FIX 62a9625e96 (37.0 days later): #codex-cwd: fix codex_review running in main repo instead of worker worktree
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

#codex-cwd: fix codex_review running in main repo instead of worker worktree

Squashed commits:
- #codex-cwd: fix codex_review running in main repo instead of worker worktree
- #codex-cwd: add report


diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index e6bb5de49..14b3a335b 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -724,24 +724,24 @@ async def codex_review(
 
     logger.info(f"codex_review: mode={mode} cwd={cwd} output={output_abs} cmd={cmd[:300]}")
     result = await _api("POST", "/api/bg/jobs", json={
         "type": "run",
         "config": {"command": cmd},
         "message": f"Codex {mode} done. Results in {output}",
         "target_name": WORKER_NAME,
         "target_scope": SCOPE,
-        "timeout_seconds": 300,
+        "timeout_seconds": 600,
         "created_by": WORKER_NAME,
     })
     if isinstance(result, dict) and result.get("error"):
         return f"Error creating bg job: {result['error']}"
     job_id = result.get("id", "?")
     return (
-        f"Codex {mode} started (bg job {job_id}, 5-min timeout). "
+        f"Codex {mode} started (bg job {job_id}, 10-min timeout). "
         f"You WILL be notified on success, timeout, or failure — do NOT poll, just wait. "
         f"On success: read {output}. Do not start another codex_review until this one reports back."
     )
 
 
 if __name__ == "__main__":
     logger.info(f"Orchestra MCP stdio (url={ORCHESTRA_URL}, scope={SCOPE})")
     mcp.run(transport="stdio")
diff --git a/app/session.py b/app/session.py
index b9556b81e..ed3de82f5 100644
--- a/app/session.py
+++ b/app/session.py
@@ -1032,16 +1032,17 @@ class AgentSession:
         }
 
     async def get_context(self) -> dict:
         return self._last_context
 
     def to_dict(self) -> dict:
         return {
             "id": self.id, "name": self.name, "scope": self.scope,
+            "cwd": self.cwd, "worktree_path": self.worktree_path,
             "status": self.status.value, "model": self.model,
             "cost_usd": round(self.cost_usd, 4),
             "cost_usd_cached": round(self.cost_usd_cached, 4),
             "branch": self.branch,
             "is_orchestrator": self.is_orchestrator,
             "role": self.role, "parent_id": self.parent_id, "parent_name": self.parent_name,
             "color": self.color,
             "created_at": self.created_at.isoformat(),


## LATER FIX 9f777f912d (64.4 days later): Squashed commits: - #82: исследование — имя как внешний ключ в трёх слоях, тихий путь не тот, что в репорте - #82: план — env чинится пересб
lines of origin it changed/deleted: 2
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


## LATER FIX 17a7d398b9 (128.5 days later): V-756: #V-756: fix repeated workflow prompts and wakes
lines of origin it changed/deleted: 11
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
 