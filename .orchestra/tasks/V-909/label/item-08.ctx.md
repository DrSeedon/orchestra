# Context for item-08

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index c7cd9c228..72002babe 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -21,40 +21,57 @@ from app.db import (
     bg_cancel_job, bg_expire_job, bg_update_output, bg_get_active_all,
     bg_expire_overdue, bg_count_active, bg_cancel_by_session,
     bg_reset_stale_triggering, bg_cleanup_old,
     bg_cron_should_fire, bg_cron_record_fire,
     bg_get_jobs, bg_get_job, bg_fail_job_if_active, bg_replace_job,
     bg_reset_wake_triggering,
 )
 from app.pidfd_exec import pidfd_send_group
 from app.tasks import spawn_supervised
 
 logger = logging.getLogger(__name__)
 
 MAX_JOBS_PER_SCOPE = 50
 MAX_TIMEOUT = 86400
 MAX_TIMER_TIMEOUT = 8 * 86400
 DEFAULT_TIMEOUT = 3600
 OUTPUT_PROGRESS_INTERVAL = 30
 _CRON_COMMAND_TIMEOUT_SECONDS = 30
 _NO_EXPIRY_TYPES = frozenset({"file", "command", "ssh", "cron", "cron_command"})
 _PIDFD_EXEC = str(Path(__file__).with_name("pidfd_exec.py"))
+# #180: rc=0 + nonempty file is not a review. Same markers as mcp_stdio's
+# first-line detector, plus the #174 opening that has no ## Verdict at all.
+_BLIND_REVIEW = re.compile(
+    r"Unable to perform an evidence-backed review|"
+    r"bwrap:|failed rtm_newaddr|setting up uid map: permission denied",
+    re.IGNORECASE,
+)
+_REVIEW_VERDICT = re.compile(r"(?im)^##\s+Verdict\b")
+
+
+def _blind_review_error(artifact: str, output: str = "") -> str:
+    """Empty string if the artifact looks like a real review; else why it does not."""
+    if _BLIND_REVIEW.search(artifact) or _BLIND_REVIEW.search(output):
+        return "review artifact is blind: execution never happened"
+    if _REVIEW_VERDICT.search(artifact) is None:
+        return "review artifact has no '## Verdict' section"
+    return ""
 _PIDFD_HANDSHAKE_TIMEOUT = 5
 _PIDFD_TERM_GRACE = 3
 _PIDFD_KILL_GRACE = 2
 _PIDFD_POLL_INTERVAL = 0.05
 
 _SSH_OPTS = [
     "-o", "BatchMode=yes",
     "-o", "ConnectTimeout=10",
     "-o", "ServerAliveInterval=30",
     "-o", "ServerAliveCountMax=3",
     "-o", "StrictHostKeyChecking=accept-new",
 ]
 
 
 def _validate_config(job_type: str, config: dict) -> str | None:
     if job_type == "timer":
         delay = config.get("delay_seconds")
         if not isinstance(delay, (int, float)) or delay <= 0:
             return "delay_seconds must be a positive number"
     elif job_type == "file":
@@ -898,48 +915,50 @@ class BgJobManager:
                         "bg_job %s: orphan_tree=1 session=%s processes=%s "
                         "oldest_process_age_seconds=%.1f observation_only=true",
                         job_id, proc.pid, orphan_count, oldest_age,
                     )
             full_output = "".join(output_buf)
             exit_code = proc.returncode
             logger.info(f"bg_job {job_id}: run done pid={proc.pid} exit={exit_code} "
                         f"lines={len(output_buf)}")
             if exit_code != 0:
                 await self._fail_notify(
                     job_id, message, target_name, target_scope,
                     f"Process exited with exit code {exit_code}", full_output,
                 )
                 return
 
             validation_error = ""
             if success_file:
                 try:
                     if not os.path.isfile(success_file) or os.path.getsize(success_file) == 0:
                         validation_error = f"Required output artifact is missing or empty: {success_file}"
-                    elif success_pattern:
+                    else:
                         with open(success_file, encoding="utf-8", errors="replace") as fh:
                             artifact = fh.read()
-                        if re.search(success_pattern, artifact) is None:
+                        if success_pattern and re.search(success_pattern, artifact) is None:
                             validation_error = (
                                 f"Required output artifact does not match success pattern: "
                                 f"{success_file}"
                             )
+                        else:
+                            validation_error = _blind_review_error(artifact, full_output)
                 except OSError as e:
                     validation_error = f"Cannot validate output artifact {success_file}: {e}"
             if validation_error:
                 await self._fail_notify(
                     job_id, message, target_name, target_scope,
                     validation_error, full_output,
                 )
                 return
 
             trigger_msg = f"{message}\nExit code: 0"
             await self._trigger(job_id, trigger_msg, target_name, target_scope, full_output)
         except asyncio.TimeoutError:
             if proc:
                 await _kill_proc(proc)
             await self._expire_notify(job_id, message, target_name, target_scope,
                                       timeout, "".join(output_buf))
         except asyncio.CancelledError:
             pass
         except Exception as e:
             bg_fail_job(job_id, str(e)[:500])
diff --git a/docs/workers/grok-36.md b/docs/workers/grok-36.md
index c23b3dab4..76a6a9766 100644
--- a/docs/workers/grok-36.md
+++ b/docs/workers/grok-36.md
@@ -1,5 +1,6 @@
 # grok-36
 
 - `#36`: `validate_spawn` fail-open существовал только чтобы пропустить неизвестную роль. После фикса режимы на этом шве совпадают; `can_spawn: ['*']` = любая *известная* роль.
 - Контракт дыры жил в `tests/test_pipeline.py` и `tests/test_default_pipeline.py` (`test_fail_open_unknown_*_passes`). Меняешь семантику — эти имена больше не истина, читай текущий `validate_spawn`.
 - `#271`: пустой вывод сканера ≠ «процессов нет». `check` на пустом файле делал 0 итераций и выходил 0 — тот же ответ, что у слепого матчера. Fail-closed в обе стороны: живой CLI при пустом снимке, и канарейка, которой `live()` не видит. Не проверять через `ps|grep` — видит сам себя.
+- `#180`: `_run_exec` доверял rc=0 + непустому файлу. Вердикта нет / «Unable to perform an evidence-backed review» / `bwrap:` — это слепое ревью, не успех. Не копировать широкий `sandbox.*fail` из mcp_stdio на весь артефакт: честный finding про sandbox ловится ложно. Правка в app/ живёт до рестарта orchestra.
diff --git a/tests/test_bg_jobs.py b/tests/test_bg_jobs.py
index 73fd562de..2e88ae31c 100644
--- a/tests/test_bg_jobs.py
+++ b/tests/test_bg_jobs.py
@@ -662,40 +662,149 @@ class TestRunExecOutcome:
 
     @pytest.mark.asyncio
     async def test_exit_zero_requires_declared_artifact(self, db, mgr_mock, tmp_path):
         from app.bg_jobs import BgJobManager
         from app.db import bg_get_jobs, bg_save_job
         mgr = BgJobManager()
         manager, session = mgr_mock
         mgr.set_session_manager(manager)
         bg_save_job(self._job("run-no-artifact", datetime.now(timezone.utc)))
 
         await mgr._run_exec(
             "run-no-artifact", "true", "review done", "w1", "/s", 10,
             success_file=str(tmp_path / "missing.md"),
         )
 
         row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-no-artifact")
         assert row["status"] == "failed"
         assert "artifact" in row["error"].lower()
         assert "FAILED" in session.send.await_args.args[0]
 
+    @pytest.mark.asyncio
+    async def test_exit_zero_blind_artifact_without_verdict_is_failed(
+        self, db, mgr_mock, tmp_path,
+    ):
+        """#180 oracle: rc=0 + existing file is not a completed review.
+
+        Fixture is the #174 opening: no ## Verdict, starts with the admission
+        that the review never happened. Today's _run_exec treats this as success.
+        """
+        artifact = tmp_path / "codex-review-plan.md"
+        artifact.write_text(
+            "Unable to perform an evidence-backed review: "
+            "the filesystem sandbox failed before every read-only command.\n",
+            encoding="utf-8",
+        )
+        from app.bg_jobs import BgJobManager
+        from app.db import bg_get_jobs, bg_save_job
+        mgr = BgJobManager()
+        manager, session = mgr_mock
+        mgr.set_session_manager(manager)
+        bg_save_job(self._job("run-blind", datetime.now(timezone.utc)))
+
+        await mgr._run_exec(
+            "run-blind", "true",
+            "Codex review → docs/tasks/174/codex-review-plan.md",
+            "w1", "/s", 10,
+            success_file=str(artifact),
+        )
+
+        row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-blind")
+        assert row["status"] == "failed", row
+        sent = session.send.await_args.args[0]
+        assert "FAILED" in sent
+        assert "completed" not in sent.lower()
+        err = (row.get("error") or "").lower()
+        assert "verdict" in err or "blind" in err or "unable" in err
+
+    @pytest.mark.asyncio
+    async def test_exit_zero_real_verdict_still_completes(self, db, mgr_mock, tmp_path):
+        artifact = tmp_path / "CODEX_REVIEW.md"
+        artifact.write_text("## Summary\nlooks good\n\n## Verdict\nAPPROVED\n")
+        from app.bg_jobs import BgJobManager
+        from app.db import bg_get_jobs, bg_save_job
+        mgr = BgJobManager()
+        manager, session = mgr_mock
+        mgr.set_session_manager(manager)
+        bg_save_job(self._job("run-ok", datetime.now(timezone.utc)))
+
+        await mgr._run_exec(
+            "run-ok", "true", "Codex review → CODEX_REVIEW.md",
+            "w1", "/s", 10,
+            success_file=str(artifact),
+        )
+
+        row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-ok")
+        assert row["status"] == "triggered"
+        assert "FAILED" not in session.send.await_args.args[0]
+
+    @pytest.mark.asyncio
+    async def test_exit_zero_verdict_with_bwrap_is_still_blind(
+        self, db, mgr_mock, tmp_path,
+    ):
+        artifact = tmp_path / "codex-review-impl.md"
+        artifact.write_text(
+            "bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted\n\n"
+            "## Verdict\nAPPROVED\n"
+        )
+        from app.bg_jobs import BgJobManager
+        from app.db import bg_get_jobs, bg_save_job
+        mgr = BgJobManager()
+        manager, session = mgr_mock
+        mgr.set_session_manager(manager)
+        bg_save_job(self._job("run-bwrap", datetime.now(timezone.utc)))
+
+        await mgr._run_exec(
+            "run-bwrap", "true", "Codex review → docs/tasks/179/codex-review-impl.md",
+            "w1", "/s", 10,
+            success_file=str(artifact),
+        )
+
+        row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-bwrap")
+        assert row["status"] == "failed"
+        assert "blind" in (row.get("error") or "").lower()
+
+    @pytest.mark.asyncio
+    async def test_exit_zero_verdict_mentioning_sandbox_is_not_blind(
+        self, db, mgr_mock, tmp_path,
+    ):
+        artifact = tmp_path / "CODEX_REVIEW.md"
+        artifact.write_text(
+            "## Findings\nThe sandbox fails closed on unknown roles.\n\n"
+            "## Verdict\nAPPROVED\n"
+        )
+        from app.bg_jobs import BgJobManager
+        from app.db import bg_get_jobs, bg_save_job
+        mgr = BgJobManager()
+        manager, session = mgr_mock
+        mgr.set_session_manager(manager)
+        bg_save_job(self._job("run-sandbox-talk", datetime.now(timezone.utc)))
+
+        await mgr._run_exec(
+            "run-sandbox-talk", "true", "Codex review → CODEX_REVIEW.md",
+            "w1", "/s", 10,
+            success_file=str(artifact),
+        )
+
+        row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-sandbox-talk")
+        assert row["status"] == "triggered"
+
 
 class TestPidfdProcessLifecycle:
     @pytest.mark.asyncio
     async def test_shell_and_argv_modes_preserve_arguments(self):
         from app.bg_jobs import _kill_proc, _spawn_bg_process
 
         argv_proc = await _spawn_bg_process(
             ["/usr/bin/printf", "%s", "argv value"],
             shell=False,
             stdout=asyncio.subprocess.PIPE,
         )
         argv_output, _ = await argv_proc.communicate()
         await _kill_proc(argv_proc)
 
         shell_proc = await _spawn_bg_process(
             "printf '%s' 'shell value'",
             shell=True,
             stdout=asyncio.subprocess.PIPE,
         )
         shell_output, _ = await shell_proc.communicate()


## Later history of the touched files on main (after this commit)

27 later commits touch these paths; the first 40 (oldest first):
e439707ce 2026-08-14 #250: #250: refuse unreviewable diffs at merge
71374ea56 2026-08-23 #385: #385: research deferred turn control and provenance
444115851 2026-08-28 #414: cover restart-safe background jobs
9093641f3 2026-09-01 v2.41.0: аудит кодовой базы — 27 дефектов закрыто (3 P0 в tm.py), 2 фикса откачены как регрессии
4e5940ef6 2026-09-02 #433: research message provenance
498c0d149 2026-09-03 Orchestra: migrate project state to .orchestra
f8e00522e 2026-09-03 #430: research .orchestra path migration
eb75808cc 2026-09-04 refactor: consolidate lifecycle and validation paths
b0f328975 2026-09-05 Reduce merge waiting and preserve Bash failure evidence
264daeb75 2026-09-07 Separate runtime control from model prose and preserve review results
25a7e6ed7 2026-09-07 Introduce advisory review and one pinned acceptance for new task assignments
bb115dcac 2026-09-07 Merge branch 'main' into codex/simplify-review
b1c7583ed 2026-09-08 #530: preserve historical text-control research and main-compatible regressions
f5713f4df 2026-09-08 Retire legacy review gates and fix adopted Codex writer release
5f7e72c50 2026-09-08 Add reusable idle watches and label dashboard message channel
e6da7e30a 2026-09-10 #537: stop runtime trees with Orchestra and remove live adoption
180a5a4f1 2026-09-10 V-543: #V-543: close pidfd ownership gaps in watchers and cancelled spawns
4bd1a5365 2026-09-21 V-603: clarify worker refusals and background receipts
9fdd0499b 2026-09-28 cron_command: лимит команды 30 → 600 с и описан в bg_create
402715d76 2026-09-28 V-653: #V-653: fix timer, cron timeout, and migration
a43f26866 2026-09-29 bg_create timer: без потолка 8 суток — срок жизни всегда позже срабатывания (баг seedon 29.09)
102fd30f2 2026-10-02 V-682: удалить тип bg-задания idle; старые idle-строки гасятся при старте
f163b3fa5 2026-10-05 V-704: #V-704: fix layout migration and run cwd defects
17a7d398b 2026-10-07 V-756: #V-756: fix repeated workflow prompts and wakes
62e76da50 2026-10-08 V-782: shared workflow admission scheduler and agent cgroup isolation
674af2dac 2026-10-09 V-798: #V-798: disable workflow balancer without cgroup delegation
89d7c8090 2026-10-15 V-886: #V-886: wake or idle a waiting target when its last watcher ends silently

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### e439707ce #250: #250: refuse unreviewable diffs at merge

diff --git a/docs/workers/grok-36.md b/docs/workers/grok-36.md
index 76a6a9766..aace5fa7b 100644
--- a/docs/workers/grok-36.md
+++ b/docs/workers/grok-36.md
@@ -2,5 +2,6 @@
 
 - `#36`: `validate_spawn` fail-open существовал только чтобы пропустить неизвестную роль. После фикса режимы на этом шве совпадают; `can_spawn: ['*']` = любая *известная* роль.
 - Контракт дыры жил в `tests/test_pipeline.py` и `tests/test_default_pipeline.py` (`test_fail_open_unknown_*_passes`). Меняешь семантику — эти имена больше не истина, читай текущий `validate_spawn`.
 - `#271`: пустой вывод сканера ≠ «процессов нет». `check` на пустом файле делал 0 итераций и выходил 0 — тот же ответ, что у слепого матчера. Fail-closed в обе стороны: живой CLI при пустом снимке, и канарейка, которой `live()` не видит. Не проверять через `ps|grep` — видит сам себя.
 - `#180`: `_run_exec` доверял rc=0 + непустому файлу. Вердикта нет / «Unable to perform an evidence-backed review» / `bwrap:` — это слепое ревью, не успех. Не копировать широкий `sandbox.*fail` из mcp_stdio на весь артефакт: честный finding про sandbox ловится ложно. Правка в app/ живёт до рестарта orchestra.
+- `#250`: потолок диффа — вставки, не удаления. Гейт на `merge_worktree_to_main`, не в промпте. Порог 2000 (бэктест 1871, 2.6%); 800 резал 8.3% и живые фичи. Обход: `waive_diff_budget=True` только оркестратор/cookie; дыра — INTERNAL_TOKEN + поддельный X-Orchestra-Session-Id оркестратора.
### 71374ea56 #385: #385: research deferred turn control and provenance

diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index 72002babe..dcd069382 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -24,10 +24,11 @@ from app.db import (
     bg_cron_should_fire, bg_cron_record_fire,
     bg_get_jobs, bg_get_job, bg_fail_job_if_active, bg_replace_job,
     bg_reset_wake_triggering,
 )
 from app.pidfd_exec import pidfd_send_group
+from app.events import InjectedMessage
 from app.tasks import spawn_supervised
 
 logger = logging.getLogger(__name__)
 
 MAX_JOBS_PER_SCOPE = 50
@@ -524,10 +525,19 @@ class BgJobManager:
     @staticmethod
     def _restore_report_provenance(session) -> None:
         if not session.last_task_sender and session.parent_name:
             session.last_task_sender = session.parent_name
 
+    @staticmethod
+    def _terminal_message(job_id: str, outcome: str, text: str) -> InjectedMessage:
+        return InjectedMessage(
+            text=text,
+            origin="orchestra.bg_jobs",
+            job_id=job_id,
+            event_id=f"bgjob:v1:{job_id}:{outcome}",
+        )
+
     async def _load_job_target(self, job_id: str, target_name: str):
         """Найти цель джоба по НЕИЗМЕНЯЕМОМУ id из его же строки.
 
         Имя, записанное при создании, к моменту срабатывания могло смениться
         (`rename_worker`) или уже принадлежать ДРУГОМУ агенту — разбудить по нему значит
@@ -562,11 +572,14 @@ class BgJobManager:
                 return
             body = f"[Background job completed] {message}"
             if output:
                 body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
             self._restore_report_provenance(session)
-            await self._session_manager.send(session.id, body)
+            await self._session_manager.send(
+                session.id,
+                self._terminal_message(job_id, "completed", body),
+            )
             bg_finish_trigger(job_id, output)
             logger.info(f"bg_job {job_id}: triggered → {target_name}")
         except Exception as e:
             bg_fail_job(job_id, str(e)[:500])
             logger.error(f"bg_job {job_id}: trigger failed: {e}")
@@ -603,11 +616,14 @@ class BgJobManager:
                 return
             body = f"[Background job TIMED OUT] {err}"
             if output:
                 body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
             self._restore_report_provenance(session)
-            await self._session_manager.send(session.id, body)
+            await self._session_manager.send(
+                session.id,
+                self._terminal_message(job_id, "timed_out", body),
+            )
             logger.warning(f"bg_job {job_id}: TIMED OUT after {dur} → notified {target_name}")
         except Exception as e:
             logger.error(f"bg_job {job_id}: timeout-notify failed: {e}")
 
     async def _fail_notify(self, job_id, message, target_name, target_scope,
@@ -620,11 +636,14 @@ class BgJobManager:
                 return
             body = f"[Background job FAILED] {message}\n{error}"
             if output:
                 body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
             self._restore_report_provenance(session)
-            await self._session_manager.send(session.id, body)
+            await self._session_manager.send(
+                session.id,
+                self._terminal_message(job_id, "failed", body),
+            )
             logger.warning(f"bg_job {job_id}: FAILED → notified {target_name}: {error}")
         except Exception as e:
             logger.error(f"bg_job {job_id}: failure-notify failed: {e}")
 
     def _fail_if_active(self, job_id: str, error: str) -> None:
diff --git a/tests/test_bg_jobs.py b/tests/test_bg_jobs.py
index 2e88ae31c..c69d28e1f 100644
--- a/tests/test_bg_jobs.py
+++ b/tests/test_bg_jobs.py
@@ -1090,5 +1090,276 @@ class TestWakeByImmutableId:
         })
         manager = SessionManager()
 
         assert await manager.ensure_loaded_by_id("arch-1") is None
         assert await manager.ensure_loaded_by_id("does-not-exist") is None
+
+
+@pytest.mark.asyncio
+@pytest.mark.parametrize(
+    "outcome,expected_status",
+    [
+        ("completed", "triggered"),
+        ("failed", "failed"),
+        ("timed_out", "expired"),
+    ],
+)
+async def test_t2_385_real_bg_result_uses_immutable_provenance_through_history(
+    db, outcome, expected_status,
+):
+    """RED #385 R3: real bg results carry app-owned provenance, never a heading."""
+    from dataclasses import FrozenInstanceError
+
+    from app.bg_jobs import BgJobManager
+    from app.db import (
+        bg_get_job,
+        bg_save_job,
+        get_history_logs,
+        get_logs_sync,
+        save_session,
+    )
+    from app.session import AgentSession, AgentStatus
+
+    now = datetime.now(timezone.utc)
+    job_id = f"bg-provenance-385-{outcome}"
+    session = AgentSession(
+        id=f"session-provenance-385-{outcome}",
+        name=f"worker-provenance-385-{outcome}",
+        scope="/scope-385",
+        cwd="/scope-385",
+        model="gpt-5.6-sol",
+        system_prompt="test",
+        created_at=now,
+    )
+    session.is_orchestrator = True
+    session.backend_type = "codex"
+    session.status = AgentStatus.IDLE
+    session._prompt_injected = True
+    save_session(session._to_db_dict())
+
+    class FakeBackend:
+        def __init__(self):
+            self.sent = []
+            self.never = asyncio.Event()
+
+        async def send(self, message):
+            self.sent.append(message)
+
+        async def events(self):
+            await self.never.wait()
### 444115851 #414: cover restart-safe background jobs

diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index dcd069382..a28c7e804 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -337,10 +337,24 @@ class BgJobManager:
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
@@ -495,10 +509,15 @@ class BgJobManager:
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
@@ -511,11 +530,17 @@ class BgJobManager:
 
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
@@ -644,10 +669,30 @@ class BgJobManager:
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
 
@@ -720,12 +765,12 @@ class BgJobManager:
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
@@ -784,12 +829,12 @@ class BgJobManager:
 
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
@@ -813,12 +858,12 @@ class BgJobManager:
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
@@ -841,12 +886,12 @@ class BgJobManager:
 
     async def _run_ssh_watch(self, job_id, host, command, pattern, message,
                               target_name, target_scope, timeout):
         proc = None
         try:
-            proc = await _spawn_bg_process(
-                ["ssh", *_SSH_OPTS, host, command],
### 9093641f3 v2.41.0: аудит кодовой базы — 27 дефектов закрыто (3 P0 в tm.py), 2 фикса откачены как регрессии

diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index a28c7e804..591753ad0 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -501,19 +501,29 @@ class BgJobManager:
             if task and not task.done():
                 task.cancel()
         reset_ids = bg_reset_stale_triggering()
         if reset_ids:
             logger.info(f"bg_jobs: reset {len(reset_ids)} stale triggering jobs")
+        interrupted_delivery = set(reset_ids)
         active = bg_get_active_all()
         restored = 0
         for row in active:
             if row["id"] in self._tasks:
                 continue
             if row["status"] != "active":
                 continue
             config = json.loads(row["config"])
             if row["type"] == "run":
+                if row["id"] in interrupted_delivery:
+                    # 'triggering' у run значит, что команда УЖЕ вышла и рестарт убил
+                    # ДОСТАВКУ её результата: «повторный запуск не выполнялся» здесь ложь,
+                    # а результат лежит в строке. Досылаем его штатным путём триггера.
+                    await self._trigger(
+                        row["id"], row["message"], row["target_name"],
+                        row["target_scope"], row["last_output"],
+                    )
+                    continue
                 await self._interrupt_run_notify(
                     row["id"], row["message"], row["target_name"], row["target_scope"],
                 )
                 continue
             remaining = (datetime.fromisoformat(row["expires_at"]) - datetime.now(timezone.utc)).total_seconds()
### 4e5940ef6 #433: research message provenance

diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index 591753ad0..faad6e2b8 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -24,11 +24,11 @@ from app.db import (
     bg_cron_should_fire, bg_cron_record_fire,
     bg_get_jobs, bg_get_job, bg_fail_job_if_active, bg_replace_job,
     bg_reset_wake_triggering,
 )
 from app.pidfd_exec import pidfd_send_group
-from app.events import InjectedMessage
+from app.events import InjectedMessage, MessageProvenance
 from app.tasks import spawn_supervised
 
 logger = logging.getLogger(__name__)
 
 MAX_JOBS_PER_SCOPE = 50
@@ -564,12 +564,16 @@ class BgJobManager:
 
     @staticmethod
     def _terminal_message(job_id: str, outcome: str, text: str) -> InjectedMessage:
         return InjectedMessage(
             text=text,
-            origin="orchestra.bg_jobs",
-            job_id=job_id,
+            provenance=MessageProvenance(
+                origin="background_task",
+                senders=(job_id,),
+                subtype=outcome,
+                ref=job_id,
+            ),
             event_id=f"bgjob:v1:{job_id}:{outcome}",
         )
 
     async def _load_job_target(self, job_id: str, target_name: str):
         """Найти цель джоба по НЕИЗМЕНЯЕМОМУ id из его же строки.
@@ -607,13 +611,15 @@ class BgJobManager:
                 return
             body = f"[Background job completed] {message}"
             if output:
                 body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
             self._restore_report_provenance(session)
+            injected = self._terminal_message(job_id, "completed", body)
             await self._session_manager.send(
                 session.id,
-                self._terminal_message(job_id, "completed", body),
+                injected,
+                provenance=injected.provenance,
             )
             bg_finish_trigger(job_id, output)
             logger.info(f"bg_job {job_id}: triggered → {target_name}")
         except Exception as e:
             bg_fail_job(job_id, str(e)[:500])
@@ -651,13 +657,15 @@ class BgJobManager:
                 return
             body = f"[Background job TIMED OUT] {err}"
             if output:
                 body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
             self._restore_report_provenance(session)
+            injected = self._terminal_message(job_id, "timed_out", body)
             await self._session_manager.send(
                 session.id,
-                self._terminal_message(job_id, "timed_out", body),
+                injected,
+                provenance=injected.provenance,
             )
             logger.warning(f"bg_job {job_id}: TIMED OUT after {dur} → notified {target_name}")
         except Exception as e:
             logger.error(f"bg_job {job_id}: timeout-notify failed: {e}")
 
@@ -671,13 +679,15 @@ class BgJobManager:
                 return
             body = f"[Background job FAILED] {message}\n{error}"
             if output:
                 body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
             self._restore_report_provenance(session)
+            injected = self._terminal_message(job_id, "failed", body)
             await self._session_manager.send(
                 session.id,
-                self._terminal_message(job_id, "failed", body),
+                injected,
+                provenance=injected.provenance,
             )
             logger.warning(f"bg_job {job_id}: FAILED → notified {target_name}: {error}")
         except Exception as e:
             logger.error(f"bg_job {job_id}: failure-notify failed: {e}")
 
@@ -688,13 +698,15 @@ class BgJobManager:
             session, _failure = await self._load_job_target(job_id, target_name)
             if not session:
                 return
             body = f"[Background job INTERRUPTED] {message}\n{reason}"
             self._restore_report_provenance(session)
+            injected = self._terminal_message(job_id, "interrupted", body)
             await self._session_manager.send(
                 session.id,
-                self._terminal_message(job_id, "interrupted", body),
+                injected,
+                provenance=injected.provenance,
             )
             logger.warning(
                 "bg_job %s: interrupted by service restart → notified %s",
                 job_id, target_name,
             )
@@ -759,12 +771,17 @@ class BgJobManager:
         try:
             session, _failure = await self._load_job_target(job_id, target_name)
             if not session:
                 # Расписание живёт дальше: цель могла быть выгружена временно.
                 return
+            provenance = MessageProvenance(
+                origin="background_task", senders=(job_id,),
+                subtype="cron", ref=job_id,
+            )
             await self._session_manager.send(
                 session.id, f"[Cron job fired] {message}",
+                provenance=provenance,
             )
             bg_cron_record_fire(job_id)
             logger.info(f"cron {job_id}: fired → {target_name}")
         except Exception as e:
             logger.error(f"cron {job_id}: fire failed (continuing schedule): {e}")
@@ -817,11 +834,17 @@ class BgJobManager:
                 return
             self._restore_report_provenance(session)
             body = f"[Cron command matched] {message}"
             if output:
                 body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
-            await self._session_manager.send(session.id, body)
+            provenance = MessageProvenance(
+                origin="background_task", senders=(job_id,),
+                subtype="cron_command", ref=job_id,
+            )
+            await self._session_manager.send(
+                session.id, body, provenance=provenance,
+            )
             bg_cron_record_fire(job_id)
             bg_update_output(job_id, output)
             logger.info("cron_command %s: matched → %s", job_id, target_name)
         except asyncio.CancelledError:
             raise
diff --git a/tests/test_bg_jobs.py b/tests/test_bg_jobs.py
index 560073e4c..fe3948a13 100644
--- a/tests/test_bg_jobs.py
+++ b/tests/test_bg_jobs.py
@@ -9,10 +9,11 @@ import threading
 from datetime import datetime, timedelta, timezone
 from unittest.mock import AsyncMock, MagicMock
### 498c0d149 Orchestra: migrate project state to .orchestra

diff --git a/docs/workers/grok-36.md b/docs/workers/grok-36.md
deleted file mode 100644
index aace5fa7b..000000000
--- a/docs/workers/grok-36.md
+++ /dev/null
@@ -1,7 +0,0 @@
-# grok-36
-
-- `#36`: `validate_spawn` fail-open существовал только чтобы пропустить неизвестную роль. После фикса режимы на этом шве совпадают; `can_spawn: ['*']` = любая *известная* роль.
-- Контракт дыры жил в `tests/test_pipeline.py` и `tests/test_default_pipeline.py` (`test_fail_open_unknown_*_passes`). Меняешь семантику — эти имена больше не истина, читай текущий `validate_spawn`.
-- `#271`: пустой вывод сканера ≠ «процессов нет». `check` на пустом файле делал 0 итераций и выходил 0 — тот же ответ, что у слепого матчера. Fail-closed в обе стороны: живой CLI при пустом снимке, и канарейка, которой `live()` не видит. Не проверять через `ps|grep` — видит сам себя.
-- `#180`: `_run_exec` доверял rc=0 + непустому файлу. Вердикта нет / «Unable to perform an evidence-backed review» / `bwrap:` — это слепое ревью, не успех. Не копировать широкий `sandbox.*fail` из mcp_stdio на весь артефакт: честный finding про sandbox ловится ложно. Правка в app/ живёт до рестарта orchestra.
-- `#250`: потолок диффа — вставки, не удаления. Гейт на `merge_worktree_to_main`, не в промпте. Порог 2000 (бэктест 1871, 2.6%); 800 резал 8.3% и живые фичи. Обход: `waive_diff_budget=True` только оркестратор/cookie; дыра — INTERNAL_TOKEN + поддельный X-Orchestra-Session-Id оркестратора.
### f8e00522e #430: research .orchestra path migration

diff --git a/tests/test_bg_jobs.py b/tests/test_bg_jobs.py
index fe3948a13..76f077695 100644
--- a/tests/test_bg_jobs.py
+++ b/tests/test_bg_jobs.py
@@ -709,11 +709,11 @@ class TestRunExecOutcome:
         mgr.set_session_manager(manager)
         bg_save_job(self._job("run-blind", datetime.now(timezone.utc)))
 
         await mgr._run_exec(
             "run-blind", "true",
-            "Codex review → docs/tasks/174/codex-review-plan.md",
+            "Codex review → .orchestra/tasks/174/codex-review-plan.md",
             "w1", "/s", 10,
             success_file=str(artifact),
         )
 
         row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-blind")
@@ -760,11 +760,11 @@ class TestRunExecOutcome:
         manager, session = mgr_mock
         mgr.set_session_manager(manager)
         bg_save_job(self._job("run-bwrap", datetime.now(timezone.utc)))
 
         await mgr._run_exec(
-            "run-bwrap", "true", "Codex review → docs/tasks/179/codex-review-impl.md",
+            "run-bwrap", "true", "Codex review → .orchestra/tasks/179/codex-review-impl.md",
             "w1", "/s", 10,
             success_file=str(artifact),
         )
 
         row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-bwrap")
### eb75808cc refactor: consolidate lifecycle and validation paths

diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index faad6e2b8..bc3da4714 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -68,75 +68,62 @@ _SSH_OPTS = [
     "-o", "ServerAliveCountMax=3",
     "-o", "StrictHostKeyChecking=accept-new",
 ]
 
 
+def _validate_regex(
+    config: dict, field: str = "pattern", *, required: bool = True,
+) -> str | None:
+    value = config.get(field, "")
+    if not value:
+        return f"{field} is required" if required else None
+    try:
+        re.compile(value)
+    except re.error as error:
+        label = "regex pattern" if field == "pattern" else field
+        return f"invalid {label}: {error}"
+    return None
+
+
 def _validate_config(job_type: str, config: dict) -> str | None:
     if job_type == "timer":
         delay = config.get("delay_seconds")
         if not isinstance(delay, (int, float)) or delay <= 0:
             return "delay_seconds must be a positive number"
     elif job_type == "file":
         if not config.get("path"):
             return "path is required"
-        pattern = config.get("pattern", "")
-        if not pattern:
-            return "pattern is required"
-        try:
-            re.compile(pattern)
-        except re.error as e:
-            return f"invalid regex pattern: {e}"
+        return _validate_regex(config)
     elif job_type == "command":
         if not config.get("command"):
             return "command is required"
-        pattern = config.get("pattern", "")
-        if not pattern:
-            return "pattern is required"
-        try:
-            re.compile(pattern)
-        except re.error as e:
-            return f"invalid regex pattern: {e}"
+        error = _validate_regex(config)
+        if error:
+            return error
         interval = config.get("interval_seconds", 60)
         if not isinstance(interval, (int, float)) or interval < 5:
             return "interval_seconds must be >= 5"
     elif job_type == "ssh":
         if not config.get("command"):
             return "command is required"
         if not config.get("host"):
             return "host is required"
-        pattern = config.get("pattern", "")
-        if not pattern:
-            return "pattern is required"
-        try:
-            re.compile(pattern)
-        except re.error as e:
-            return f"invalid regex pattern: {e}"
+        return _validate_regex(config)
     elif job_type == "run":
         if not config.get("command"):
             return "command is required"
-        success_pattern = config.get("success_pattern", "")
-        if success_pattern:
-            try:
-                re.compile(success_pattern)
-            except re.error as e:
-                return f"invalid success_pattern: {e}"
+        return _validate_regex(config, "success_pattern", required=False)
     elif job_type in ("cron", "cron_command"):
         expr = config.get("cron_expr", "")
         if not expr:
             return "cron_expr is required"
         if not croniter.is_valid(expr):
             return f"invalid cron expression: {expr!r}"
         if job_type == "cron_command":
             if not config.get("command"):
                 return "command is required"
-            pattern = config.get("pattern", "")
-            if not pattern:
-                return "pattern is required"
-            try:
-                re.compile(pattern)
-            except re.error as e:
-                return f"invalid regex pattern: {e}"
+            return _validate_regex(config)
     else:
         return f"unknown job type: {job_type}"
     return None
 
 