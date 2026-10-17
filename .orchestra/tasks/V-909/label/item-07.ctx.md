# Context for item-07

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index a94924b45..50d9553a8 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -1,53 +1,63 @@
 """Background Jobs — server-side one-shot tasks that survive hibernate."""
 
 import asyncio
+import array
 import json
 import logging
 import os
 import re
 import signal
+import socket
+import sys
 import time
 from datetime import datetime, timezone, timedelta
+from pathlib import Path
 from uuid import uuid4
 
 from croniter import croniter
 
 from app.db import (
     bg_save_job, bg_claim_trigger, bg_finish_trigger, bg_fail_job,
     bg_cancel_job, bg_expire_job, bg_update_output, bg_get_active_all,
     bg_expire_overdue, bg_count_active, bg_cancel_by_session,
     bg_reset_stale_triggering, bg_cleanup_old,
     bg_cron_should_fire, bg_cron_record_fire,
     bg_get_jobs, bg_fail_job_if_active, bg_replace_job,
     bg_reset_wake_triggering,
 )
+from app.pidfd_exec import pidfd_send_group
 
 logger = logging.getLogger(__name__)
 
 MAX_JOBS_PER_SCOPE = 50
 MAX_TIMEOUT = 86400
 MAX_TIMER_TIMEOUT = 8 * 86400
 DEFAULT_TIMEOUT = 3600
 OUTPUT_PROGRESS_INTERVAL = 30
 _CRON_COMMAND_TIMEOUT_SECONDS = 30
 _NO_EXPIRY_TYPES = frozenset({"file", "command", "ssh", "cron", "cron_command"})
+_PIDFD_EXEC = str(Path(__file__).with_name("pidfd_exec.py"))
+_PIDFD_HANDSHAKE_TIMEOUT = 5
+_PIDFD_TERM_GRACE = 3
+_PIDFD_KILL_GRACE = 2
+_PIDFD_POLL_INTERVAL = 0.05
 
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
         if not config.get("path"):
             return "path is required"
         pattern = config.get("pattern", "")
         if not pattern:
@@ -94,60 +104,183 @@ def _validate_config(job_type: str, config: dict) -> str | None:
         expr = config.get("cron_expr", "")
         if not expr:
             return "cron_expr is required"
         if not croniter.is_valid(expr):
             return f"invalid cron expression: {expr!r}"
         if job_type == "cron_command":
             if not config.get("command"):
                 return "command is required"
             pattern = config.get("pattern", "")
             if not pattern:
                 return "pattern is required"
             try:
                 re.compile(pattern)
             except re.error as e:
                 return f"invalid regex pattern: {e}"
     else:
         return f"unknown job type: {job_type}"
     return None
 
 
-async def _kill_proc(proc: asyncio.subprocess.Process) -> None:
-    if proc.returncode is not None:
-        return
+def _extract_pidfd(data: bytes, ancillary: list[tuple[int, int, bytes]]) -> int:
+    received: list[int] = []
+    for level, kind, payload in ancillary:
+        if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
+            continue
+        rights = array.array("i")
+        rights.frombytes(payload[:len(payload) - len(payload) % rights.itemsize])
+        received.extend(rights)
+    if data != b"P":
+        for fd in received:
+            os.close(fd)
+        detail = data.decode(errors="replace") or "EOF"
+        raise RuntimeError(f"pidfd exec handshake failed: {detail}")
+    if len(received) != 1:
+        for fd in received:
+            os.close(fd)
+        raise RuntimeError(f"pidfd exec handshake received {len(received)} fds")
+    return received[0]
+
+
+async def _recv_pidfd(control: socket.socket) -> int:
+    loop = asyncio.get_running_loop()
+    future = loop.create_future()
+    fd_size = array.array("i").itemsize
+
+    def receive() -> None:
+        try:
+            data, ancillary, _flags, _address = control.recvmsg(
+                256,
+                socket.CMSG_SPACE(fd_size),
+                socket.MSG_CMSG_CLOEXEC,
+            )
+            result = _extract_pidfd(data, ancillary)
+        except BlockingIOError:
+            return
+        except BaseException as exc:
+            if not future.done():
+                future.set_exception(exc)
+        else:
+            if not future.done():
+                future.set_result(result)
+        finally:
+            if future.done():
+                loop.remove_reader(control.fileno())
+
+    control.setblocking(False)
+    loop.add_reader(control.fileno(), receive)
     try:
-        pgid = os.getpgid(proc.pid)
-        os.killpg(pgid, signal.SIGTERM)
-    except (ProcessLookupError, PermissionError):
-        pass
+        return await future
+    finally:
+        loop.remove_reader(control.fileno())
+
+
+async def _spawn_bg_process(
+    command: str | list[str],
+    *,
+    shell: bool,
+    **kwargs,
+) -> asyncio.subprocess.Process:
+    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
+    proc = None
+    pidfd = None
     try:
-        await asyncio.wait_for(proc.wait(), timeout=3)
-    except (asyncio.TimeoutError, ProcessLookupError):
+        mode = "shell" if shell else "argv"
+        target = [command] if shell else list(command)
+        proc = await asyncio.create_subprocess_exec(
+            sys.executable,
+            _PIDFD_EXEC,
+            str(child.fileno()),
+            mode,
+            *target,
+            pass_fds=(child.fileno(),),
+            start_new_session=True,
+            **kwargs,
+        )
+        child.close()
+        pidfd = await asyncio.wait_for(
+            _recv_pidfd(parent), timeout=_PIDFD_HANDSHAKE_TIMEOUT,
+        )
+        if not pidfd_send_group(pidfd, 0):
+            raise RuntimeError("pidfd process group disappeared before exec ACK")
+        proc._orchestra_pidfd = pidfd
+        pidfd = None
         try:
-            pgid = os.getpgid(proc.pid)
-            os.killpg(pgid, signal.SIGKILL)
-        except (ProcessLookupError, PermissionError):
-            pass
+            await asyncio.get_running_loop().sock_sendall(parent, b"A")
+        except BaseException:
+            parent.close()
+            await _kill_proc(proc)
+            raise
+        return proc
+    except BaseException:
+        if pidfd is not None:
+            os.close(pidfd)
+        if proc is not None and getattr(proc, "_orchestra_pidfd", None) is None:
+            child.close()
+            parent.close()
+            try:
+                await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=2)
+            except (asyncio.TimeoutError, asyncio.CancelledError):
+                logger.error(
+                    "pidfd exec shim pid=%s did not exit after handshake failure",
+                    proc.pid,
+                )
+        raise
+    finally:
+        child.close()
+        parent.close()
+
+
+async def _cleanup_pidfd_group(proc: asyncio.subprocess.Process) -> None:
+    pidfd = getattr(proc, "_orchestra_pidfd", None)
+    if pidfd is None:
+        raise RuntimeError(f"process pid={proc.pid} has no stable pidfd identity")
+    proc._orchestra_pidfd = None
+    try:
+        alive = pidfd_send_group(pidfd, signal.SIGTERM)
+        deadline = asyncio.get_running_loop().time() + _PIDFD_TERM_GRACE
+        while alive and asyncio.get_running_loop().time() < deadline:
+            await asyncio.sleep(_PIDFD_POLL_INTERVAL)
+            alive = pidfd_send_group(pidfd, 0)
+        if alive:
+            pidfd_send_group(pidfd, signal.SIGKILL)
+            deadline = asyncio.get_running_loop().time() + _PIDFD_KILL_GRACE
+            while asyncio.get_running_loop().time() < deadline:
+                await asyncio.sleep(_PIDFD_POLL_INTERVAL)
+                if not pidfd_send_group(pidfd, 0):
+                    break
+            else:
+                raise RuntimeError(f"process group for pid={proc.pid} survived SIGKILL")
         try:
-            await asyncio.wait_for(proc.wait(), timeout=2)
-        except Exception:
-            pass
+            await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=2)
+        except asyncio.TimeoutError:
+            logger.warning("process leader pid=%s was not reaped after group exit", proc.pid)
+    finally:
+        os.close(pidfd)
+
+
+async def _kill_proc(proc: asyncio.subprocess.Process) -> None:
+    cleanup = getattr(proc, "_orchestra_cleanup_task", None)
+    if cleanup is None:
+        cleanup = asyncio.create_task(_cleanup_pidfd_group(proc))
+        proc._orchestra_cleanup_task = cleanup
+    await asyncio.shield(cleanup)
 
 
 def _orphan_session_stats(session_id: int) -> tuple[int, float]:
     """Return process count and oldest process age for a finished job's session."""
     try:
         with open("/proc/uptime", encoding="ascii") as fh:
             uptime = float(fh.read().split()[0])
         clock_ticks = os.sysconf("SC_CLK_TCK")
         entries = os.scandir("/proc")
     except (OSError, ValueError) as e:
         logger.warning(
             "bg_job: orphan observation unavailable error=%s:%s",
             type(e).__name__, e,
         )
         return 0, 0.0
 
     count = 0
     oldest_age = 0.0
     with entries:
         for entry in entries:
@@ -502,45 +635,45 @@ class BgJobManager:
             session = await self._session_manager.ensure_loaded(target_name, target_scope)
             if not session:
                 logger.warning(f"cron {job_id}: target {target_name} not found, skipping fire")
                 return
             await self._session_manager.send(
                 session.id, f"[Cron job fired] {message}",
             )
             bg_cron_record_fire(job_id)
             logger.info(f"cron {job_id}: fired → {target_name}")
         except Exception as e:
             logger.error(f"cron {job_id}: fire failed (continuing schedule): {e}")
 
     async def _fire_cron_command(
         self, job_id, command, pattern, message, target_name, target_scope,
     ):
         if not bg_cron_should_fire(job_id):
             return
         proc = None
         output = ""
         try:
-            proc = await asyncio.create_subprocess_shell(
+            proc = await _spawn_bg_process(
                 command,
+                shell=True,
                 stdout=asyncio.subprocess.PIPE,
                 stderr=asyncio.subprocess.PIPE,
-                preexec_fn=os.setsid,
             )
             self._procs[job_id] = proc
             try:
                 stdout, stderr = await _communicate_cron_command(proc)
             except asyncio.TimeoutError:
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
                 return
 
             raw_output = (
                 stdout.decode(errors="replace")
                 + stderr.decode(errors="replace")
@@ -573,141 +706,143 @@ class BgJobManager:
             bg_update_output(job_id, output)
             logger.info("cron_command %s: matched → %s", job_id, target_name)
         except asyncio.CancelledError:
             raise
         except Exception as e:
             logger.error(
                 "cron_command %s: fire failed (continuing schedule): %s",
                 job_id,
                 e,
             )
         finally:
             if self._procs.get(job_id) is proc:
                 self._procs.pop(job_id, None)
             if proc:
                 await _kill_proc(proc)
 
     async def _run_file_watch(self, job_id, path, pattern, message,
                               target_name, target_scope, timeout):
         proc = None
         try:
-            proc = await asyncio.create_subprocess_exec(
-                "tail", "-F", "-n", "0", path,
+            proc = await _spawn_bg_process(
+                ["tail", "-F", "-n", "0", path],
+                shell=False,
                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
-                preexec_fn=os.setsid,
             )
             self._procs[job_id] = proc
             async with asyncio.timeout(timeout):
                 async for line in proc.stdout:
                     text = line.decode(errors="replace")
                     if re.search(pattern, text):
                         await self._trigger(job_id, message, target_name, target_scope, text.strip())
                         return
             self._fail_if_active(job_id, "tail exited without match")
         except asyncio.TimeoutError:
             self._expire(job_id)
         except asyncio.CancelledError:
             pass
         except Exception as e:
             self._fail_if_active(job_id, str(e)[:500])
         finally:
             self._procs.pop(job_id, None)
             if proc:
                 await _kill_proc(proc)
 
     async def _run_command_watch(self, job_id, command, pattern, interval,
                                  message, target_name, target_scope, timeout):
         deadline = (time.time() + timeout) if timeout is not None else None
         try:
             while deadline is None or time.time() < deadline:
-                proc = await asyncio.create_subprocess_shell(
-                    command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
-                    preexec_fn=os.setsid,
+                proc = await _spawn_bg_process(
+                    command, shell=True,
+                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                 )
                 self._procs[job_id] = proc
                 try:
                     stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                 except asyncio.TimeoutError:
                     await _kill_proc(proc)
                     stdout, stderr = b"", b""
                 finally:
                     self._procs.pop(job_id, None)
                 output = stdout.decode(errors="replace") + stderr.decode(errors="replace")
                 if re.search(pattern, output):
                     await self._trigger(job_id, message, target_name, target_scope, output.strip())
                     return
                 await asyncio.sleep(interval)
             if deadline is not None:
                 self._expire(job_id)
         except asyncio.CancelledError:
             pass
         except Exception as e:
             bg_fail_job(job_id, str(e)[:500])
 
     async def _run_ssh_watch(self, job_id, host, command, pattern, message,
                               target_name, target_scope, timeout):
         proc = None
         try:
-            proc = await asyncio.create_subprocess_exec(
-                "ssh", *_SSH_OPTS, host, command,
+            proc = await _spawn_bg_process(
+                ["ssh", *_SSH_OPTS, host, command],
+                shell=False,
                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
-                preexec_fn=os.setsid,
             )
             self._procs[job_id] = proc
             async with asyncio.timeout(timeout):
                 async for line in proc.stdout:
                     text = line.decode(errors="replace")
                     if re.search(pattern, text):
                         await self._trigger(job_id, message, target_name, target_scope, text.strip())
                         return
             self._fail_if_active(job_id, "ssh exited without match")
         except asyncio.TimeoutError:
             self._expire(job_id)
         except asyncio.CancelledError:
             pass
         except Exception as e:
             self._fail_if_active(job_id, str(e)[:500])
         finally:
             self._procs.pop(job_id, None)
             if proc:
                 await _kill_proc(proc)
 
     async def _run_exec(self, job_id, command, message, target_name,
                         target_scope, timeout, host=None, success_file=None,
                         success_pattern=""):
         proc = None
         reader_task = None
         output_buf = []
         try:
             # 16MB readline limit: Codex JSONL contains base64 images / long JSON lines
             # that exceed asyncio's default 64KB StreamReader limit → ValueError
             _STREAM_LIMIT = 16 * 1024 * 1024
             if host:
-                proc = await asyncio.create_subprocess_exec(
-                    "ssh", *_SSH_OPTS, host, command,
+                proc = await _spawn_bg_process(
+                    ["ssh", *_SSH_OPTS, host, command],
+                    shell=False,
                     stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
-                    preexec_fn=os.setsid, limit=_STREAM_LIMIT,
+                    limit=_STREAM_LIMIT,
                 )
             else:
-                proc = await asyncio.create_subprocess_shell(
-                    command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
-                    preexec_fn=os.setsid, limit=_STREAM_LIMIT,
+                proc = await _spawn_bg_process(
+                    command, shell=True,
+                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
+                    limit=_STREAM_LIMIT,
                 )
             self._procs[job_id] = proc
             where = host or "local"
             logger.info(f"bg_job {job_id}: run started pid={proc.pid} on={where} "
                         f"timeout={timeout}s cmd_len={len(command)}")
             last_progress = time.time()
 
             async def read_output():
                 nonlocal last_progress, output_buf
                 async for line in proc.stdout:
                     output_buf.append(line.decode(errors="replace"))
                     if len(output_buf) > 500:
                         output_buf = output_buf[-300:]
                     now = time.time()
                     if now - last_progress > OUTPUT_PROGRESS_INTERVAL:
                         bg_update_output(job_id, "".join(output_buf))
                         last_progress = now
 
             async with asyncio.timeout(timeout):
                 reader_task = asyncio.create_task(read_output())
diff --git a/app/pidfd_exec.py b/app/pidfd_exec.py
new file mode 100644
index 000000000..2893cb8b6
--- /dev/null
+++ b/app/pidfd_exec.py
@@ -0,0 +1,89 @@
+"""Exec shim that hands its own pidfd to the parent before running a target."""
+
+import array
+import ctypes
+import errno
+import os
+import socket
+import sys
+
+
+PIDFD_SIGNAL_PROCESS_GROUP = 1 << 2
+
+_libc = ctypes.CDLL(None, use_errno=True)
+try:
+    _pidfd_open = _libc.pidfd_open
+    _pidfd_send_signal = _libc.pidfd_send_signal
+except AttributeError:
+    _pidfd_open = _pidfd_send_signal = None
+else:
+    _pidfd_open.argtypes = (ctypes.c_int, ctypes.c_uint)
+    _pidfd_open.restype = ctypes.c_int
+    _pidfd_send_signal.argtypes = (
+        ctypes.c_int,
+        ctypes.c_int,
+        ctypes.c_void_p,
+        ctypes.c_uint,
+    )
+    _pidfd_send_signal.restype = ctypes.c_int
+
+
+def pidfd_open_self() -> int:
+    if _pidfd_open is None:
+        raise OSError(errno.ENOSYS, "libc pidfd functions are unavailable")
+    fd = _pidfd_open(os.getpid(), 0)
+    if fd < 0:
+        error = ctypes.get_errno()
+        raise OSError(error, os.strerror(error))
+    return fd
+
+
+def pidfd_send_group(pidfd: int, sig: int) -> bool:
+    """Signal the retained process group; return False once the group is gone."""
+    if _pidfd_send_signal is None:
+        raise OSError(errno.ENOSYS, "libc pidfd functions are unavailable")
+    if _pidfd_send_signal(
+        pidfd, sig, None, PIDFD_SIGNAL_PROCESS_GROUP,
+    ) == 0:
+        return True
+    error = ctypes.get_errno()
+    if error == errno.ESRCH:
+        return False
+    raise OSError(error, os.strerror(error))
+
+
+def _send_pidfd(control: socket.socket, pidfd: int) -> None:
+    rights = array.array("i", [pidfd])
+    control.sendmsg(
+        [b"P"],
+        [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights)],
+    )
+
+
+def main() -> int:
+    if len(sys.argv) < 4 or sys.argv[2] not in {"shell", "argv"}:
+        return 64
+    control = socket.socket(fileno=int(sys.argv[1]))
+    try:
+        try:
+            pidfd = pidfd_open_self()
+        except OSError as exc:
+            control.send((f"E{exc.errno}:{exc.strerror}").encode())
+            return 70
+        try:
+            _send_pidfd(control, pidfd)
+        finally:
+            os.close(pidfd)
+        if control.recv(1) != b"A":
+            return 71
+    finally:
+        control.close()
+
+    if sys.argv[2] == "shell":
+        os.execv("/bin/sh", ["/bin/sh", "-c", sys.argv[3]])
+    os.execvp(sys.argv[3], sys.argv[3:])
+    return 72
+
+
+if __name__ == "__main__":
+    raise SystemExit(main())
diff --git a/docs/tasks/120/codex-review-plan.md b/docs/tasks/120/codex-review-plan.md
new file mode 100644
index 000000000..6014642bb
--- /dev/null
+++ b/docs/tasks/120/codex-review-plan.md
@@ -0,0 +1,35 @@
+The proposed process lifecycle can execute targets on unsupported kernels and allows concurrent cancellation to return before termination is complete. Both gaps undermine the safety contract the plan is intended to establish.
+
+Full review comments:
+
+- [P1] Probe group-signal support before sending ACK — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/120/plan.md:32-33
+  On Linux before 6.9, `pidfd_open` and the SCM_RIGHTS handoff can succeed while `PIDFD_SIGNAL_PROCESS_GROUP` is rejected, so this sequence ACKs the shim and executes the target before support is first exercised in `_kill_proc()`. That violates the fail-closed contract at lines 89–91 and can leave the group impossible to terminate safely; probe a signal-0 group operation on the received pidfd before ACK.
+
+- [P1] Make concurrent callers await the active cleanup — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/120/plan.md:39-40
+  When timeout/finally cleanup already owns the pidfd and is waiting through the TERM grace period, `BgJobManager.cancel()` can cancel that owner and then invoke `_kill_proc()` itself; making the second invocation a no-op lets cancellation return before cleanup finishes and can prevent escalation to KILL for a TERM-ignoring group. Store a shared, cancellation-shielded cleanup task and make concurrent callers await it while keeping signaling and closing single-shot.
+
+## Author resolution after Round 2
+
+- **Pre-ACK support probe — ACK.** Plan now requires a successful group signal-0
+  operation on the received pidfd before ACK. Unsupported kernels close the control
+  channel; shim exits without executing target.
+- **Concurrent cleanup — ACK.** `_kill_proc()` now creates/stores one cleanup task
+  synchronously and every caller awaits it via `asyncio.shield()`. Signaling and fd
+  close remain single-shot; cancellation of one caller cannot cancel escalation.
+
+## Round (2026-08-01T11:23:31Z)
+
+Ну надо же, третий раунд действительно закрыл оба P1 😏
+
+### Re-review status
+
+- **FIXED** — pre-ACK group signal-0 probe теперь обязателен; при ошибке target не исполняется ([plan.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/120/plan.md:32)).
+- **FIXED** — concurrent/repeated callers ожидают один shielded cleanup task; TERM→KILL и закрытие pidfd остаются single-shot ([plan.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/120/plan.md:39)).
+
+### New findings
+
+Нет.
+
+### Verdict
+
+**APPROVED.** Оба прежних P1 закрыты, новых блокеров в статическом diff нет. Теперь ACK хотя бы не выдаётся как пропуск на аттракцион до проверки ремней.
diff --git a/docs/tasks/120/plan.md b/docs/tasks/120/plan.md
new file mode 100644
index 000000000..25c9ae752
--- /dev/null
+++ b/docs/tasks/120/plan.md
@@ -0,0 +1,128 @@
+# #120 — план безопасного завершения процессов
+
+Статус: implementation approved 2026-08-01. Порядок и отдельные коммиты заданы
+оркестратором: T1, затем T2. Код #93/#114/#116 и `pipelines/` не затрагивается.
+
+## Решение
+
+### SSH
+
+Удалить `_kill_stale()` и единственный startup-вызов `pkill -f`. Никакого нового
+cross-process discovery: текущий process чистится через существующий `t.proc`, а
+остатки production service после restart — через systemd
+`KillMode=control-group`. Рядом с startup оставить WHY-комментарий: ручной
+`SIGKILL` запуска вне systemd может оставить SSH, но безопасно доказать ownership
+после restart невозможно, поэтому Orchestra не ищет и не сигнализирует процессы по
+командной строке.
+
+Остаточная числовая гонка внутри `asyncio Process.terminate()/kill()` зафиксирована
+в отчёте с координатами, но не меняется: постановка явно отнесла live handles к
+другому классу.
+
+### Background jobs
+
+`asyncio.create_subprocess_*()` не возвращает atomic pidfd, поэтому обычный
+post-spawn `pidfd_open(proc.pid)` запрещён. Перед исходной командой запускается
+короткий Python exec shim:
+
+1. Parent создаёт `SOCK_SEQPACKET` socketpair и запускает shim с
+   `start_new_session=True`.
+2. Shim открывает pidfd на самого себя, передаёт fd parent через `SCM_RIGHTS` и ждёт
+   ACK. Исходная команда ещё не исполняется и не может успеть завершиться.
+3. Parent получает fd с `MSG_CMSG_CLOEXEC` и **до ACK** делает group signal-0 probe
+   через `PIDFD_SIGNAL_PROCESS_GROUP`. Только успешный probe разрешает ACK; на kernel
+   без group-flag support shim получает EOF и target не исполняется.
+4. После ACK shim закрывает control socket и делает `execvp()` команды (для shell
+   mode — `/bin/sh -c <command>`). PID/PGID/SID и pidfd identity сохраняются,
+   лишнего runtime-процесса после `exec` нет.
+5. `_kill_proc()` синхронно создаёт и сохраняет на `Process` единственный cleanup
+   task либо получает уже существующий. Все concurrent callers ждут тот же task
+   через `asyncio.shield()`; cancellation caller не отменяет TERM->KILL escalation.
+6. Внутренний cleanup атомарно забирает pidfd, посылает group TERM через
+   `pidfd_send_signal(..., PIDFD_SIGNAL_PROCESS_GROUP)`, ждёт исчезновения группы
+   безопасными signal-0 probes, затем при необходимости посылает group KILL.
+7. Pidfd закрывается ровно один раз. Повторный/concurrent cleanup ждёт сохранённый
+   результат, а не запускает сигналы повторно. Даже если leader уже exited/reaped,
+   retained pidfd продолжает адресовать исходную группу.
+
+Нет numeric fallback. Ошибка libc/kernel/handshake происходит до ACK: исходная
+команда не запускается, shim выходит после закрытия control socket, caller получает
+явный exception/job failure.
+
+## Предзарегистрированный ресурсный гейт
+
+Измерение после T2, последовательно под `nice -n 15`:
+
+- 100 запусков `/bin/true`: direct asyncio baseline против tracked shim;
+  median и p95 added wall time.
+- 3 запуска shim, удержанного до ACK: `Pss+SwapPss` из `smaps_rollup`; сравнение с
+  direct `/bin/sleep` baseline.
+- FD count parent до/после 100 fast runs.
+
+**STOP и эскалация до commit T2**, если added median >50 ms, added p95 >100 ms,
+transient shim `Pss+SwapPss` >32 MiB или остаётся хотя бы один FD. Это не performance
+target продукта, а потолок, после которого новый launch contract уже нельзя считать
+малой платой за correctness.
+
+## Tickets
+
+### T1 — Удалить broad SSH cleanup
+
+- Files: `app/ssh_tunnel.py`, `tests/test_proxy.py`, `docs/tasks/120/report.md`.
+- Commit: `#120: remove broad SSH process matching`.
+- AC:
+  - В `app/ssh_tunnel.py` и его tests нет `pkill`, `pgrep` и `_kill_stale`.
+  - `start_tunnel()` по-прежнему adopts уже слушающий external port и запускает
+    `_tunnel_loop()` для managed port.
+  - WHY-комментарий документирует systemd cleanup и исключение ручного запуска.
+  - Реальный foreign process с command line, совпадающей со старым regex, остаётся
+    жив после startup/stop disposable tunnel manager.
+  - Disposable owned SSH tunnel на свободном local port поднимается и завершается;
+    production service и его порты не рестартятся/не меняются.
+- blocked-by: none.
+
+### T2 — Stable pidfd process-group lifecycle
+
+- Files: новый `app/pidfd_exec.py`, `app/bg_jobs.py`, `tests/test_bg_jobs.py`,
+  `docs/tasks/120/report.md`, `docs/tasks/120/codex-review-impl.md`.
+- Commit: `#120: signal background process groups through pidfd`.
+- AC:
+  - Все шесть background-job spawn sites используют один tracked-spawn contract;
+    `preexec_fn=os.setsid`, `os.getpgid` и `os.killpg` удалены из `app/bg_jobs.py`.
+  - Shim self-opens pidfd before ACK and never executes the target without successful
+    handoff; shell and argv modes preserve current command semantics, stdout/stderr
+    pipes and `limit`.
+  - Unsupported pidfd group signal обнаруживается signal-0 probe **до ACK**;
+    malformed/EOF handoff, spawn failure и cancellation fail closed: target не
+    запускается, numeric signal не посылается, socket/pidfd закрываются, ошибка
+    видима caller/job state.
+  - Concurrent/repeated `_kill_proc()` signals/closes once; все callers ждут один
+    shielded cleanup task, cancellation одного caller не отменяет escalation и не
+    вызывает EBADF/foreign signal.
+  - Live leader + child: TERM removes whole group; unrelated process survives.
+  - Leader already waited/reaped + TERM-ignoring child: TERM leaves child, KILL
+    removes it; unrelated process survives.
+  - Normal exit, timeout, explicit cancel, manager shutdown, cron command, file,
+    command and SSH watch paths retain their current DB/notification semantics.
+  - Resource gate above passes and exact median/p95/PSS/FD numbers are recorded in
+    `report.md`.
+  - Focused tests and full suite pass under global test lock with `nice -n 15`.
+  - Codex implementation review has no unresolved blocking findings.
+- blocked-by: T1.
+
+## Что не менять
+
+- `app/manager.py`, `app/workspace.py`, `app/routes/sessions.py` (#93).
+- `app/routes/system.py` (#114), `app/rag.py` (#116), `pipelines/`.
+- SSH `t.proc.terminate()/kill()` live-handle paths и остальные signal sites из карты
+  #113.
+- systemd units, `.env`, proxy selection, production processes и service lifecycle.
+
+## Проверка
+
+1. T1 focused `tests/test_proxy.py` + disposable real-process fact.
+2. T1 commit до начала T2.
+3. T2 focused `tests/test_bg_jobs.py`, resource benchmark, real leader/child/
+   unrelated fact.
+4. Codex review diff; blocking findings verify/fix/debate, round 2 mandatory.
+5. Global test lock → full suite exactly once, log read once → release lock.
diff --git a/tests/test_bg_jobs.py b/tests/test_bg_jobs.py
index 27a179aba..56187a892 100644
--- a/tests/test_bg_jobs.py
+++ b/tests/test_bg_jobs.py
@@ -1,24 +1,27 @@
 """Tests for bg_jobs.py cron support (#26)."""
 
 import asyncio
 import json
+import os
+import signal
+import sys
 import threading
 from datetime import datetime, timedelta, timezone
 from unittest.mock import AsyncMock, MagicMock
 
 import pytest
 
 
 @pytest.fixture
 def db(tmp_path, monkeypatch):
     db_path = tmp_path / "test.db"
     monkeypatch.setattr("app.db.DB_PATH", db_path)
     from app.db import init_db
     init_db()
     return db_path
 
 
 @pytest.fixture
 def mgr_mock():
     m = MagicMock()
     sess = MagicMock()
@@ -303,41 +306,42 @@ class TestCronCommand:
             "error": error,
         })()
 
     @pytest.mark.asyncio
     async def test_four_no_match_fires_do_not_wake_and_stay_active(
         self, db, mgr_mock, monkeypatch,
     ):
         import app.bg_jobs as module
         from app.bg_jobs import BgJobManager
         from app.db import bg_get_active_all, bg_save_job
 
         mgr = BgJobManager()
         manager, session = mgr_mock
         mgr.set_session_manager(manager)
         bg_save_job(self._job("cron-command-empty", datetime.now(timezone.utc)))
         processes = [
             self._proc(output=f"empty-{index}".encode())
             for index in range(4)
         ]
         create = AsyncMock(side_effect=processes)
-        monkeypatch.setattr(module.asyncio, "create_subprocess_shell", create)
+        monkeypatch.setattr(module, "_spawn_bg_process", create)
+        monkeypatch.setattr(module, "_kill_proc", AsyncMock())
 
         async def communicate(proc):
             return proc.output, proc.error
 
         monkeypatch.setattr(module, "_communicate_cron_command", communicate)
 
         for _ in range(4):
             await mgr._fire_cron_command(
                 "cron-command-empty",
                 "python monitor.py",
                 "ALERT",
                 "monitor found work",
                 "w1",
                 "/s",
             )
 
         assert create.await_count == 4
         manager.ensure_loaded.assert_not_awaited()
         session.send.assert_not_awaited()
         row = next(
@@ -345,45 +349,42 @@ class TestCronCommand:
             if job["id"] == "cron-command-empty"
         )
         assert row["status"] == "active"
         assert row["last_output"] == "empty-3"
 
     @pytest.mark.asyncio
     async def test_completed_nonzero_match_wakes_and_remains_active(
         self, db, mgr_mock, monkeypatch,
     ):
         import app.bg_jobs as module
         from app.bg_jobs import BgJobManager
         from app.db import bg_get_active_all, bg_save_job
 
         mgr = BgJobManager()
         manager, session = mgr_mock
         session.parent_name = "parent-orchestrator"
         session.last_task_sender = ""
         mgr.set_session_manager(manager)
         bg_save_job(self._job("cron-command-match", datetime.now(timezone.utc)))
         proc = self._proc(output=b"ALERT: item 42\n", returncode=7)
-        monkeypatch.setattr(
-            module.asyncio,
-            "create_subprocess_shell",
-            AsyncMock(return_value=proc),
-        )
+        monkeypatch.setattr(module, "_spawn_bg_process", AsyncMock(return_value=proc))
+        monkeypatch.setattr(module, "_kill_proc", AsyncMock())
 
         async def communicate(process):
             return process.output, process.error
 
         monkeypatch.setattr(module, "_communicate_cron_command", communicate)
 
         await mgr._fire_cron_command(
             "cron-command-match",
             "python monitor.py",
             "ALERT",
             "monitor found work",
             "w1",
             "/s",
         )
 
         sent = session.send.await_args.args[0]
         assert "monitor found work" in sent
         assert "ALERT: item 42" in sent
         assert "exit code 7" in sent
         assert session.last_task_sender == "parent-orchestrator"
@@ -392,126 +393,115 @@ class TestCronCommand:
             if job["id"] == "cron-command-match"
         )
         assert row["status"] == "active"
         config = json.loads(row["config"])
         assert config["fire_count"] == 1
         assert "ALERT: item 42" in row["last_output"]
 
     @pytest.mark.asyncio
     async def test_empty_output_never_wakes_even_if_regex_matches_empty(
         self, db, mgr_mock, monkeypatch,
     ):
         import app.bg_jobs as module
         from app.bg_jobs import BgJobManager
         from app.db import bg_save_job
 
         mgr = BgJobManager()
         manager, session = mgr_mock
         mgr.set_session_manager(manager)
         bg_save_job(self._job("cron-command-empty-output", datetime.now(timezone.utc)))
         proc = self._proc()
-        monkeypatch.setattr(
-            module.asyncio,
-            "create_subprocess_shell",
-            AsyncMock(return_value=proc),
-        )
+        monkeypatch.setattr(module, "_spawn_bg_process", AsyncMock(return_value=proc))
+        monkeypatch.setattr(module, "_kill_proc", AsyncMock())
 
         async def communicate(process):
             return process.output, process.error
 
         monkeypatch.setattr(module, "_communicate_cron_command", communicate)
 
         await mgr._fire_cron_command(
             "cron-command-empty-output",
             "python monitor.py",
             ".*",
             "monitor found work",
             "w1",
             "/s",
         )
 
         manager.ensure_loaded.assert_not_awaited()
         session.send.assert_not_awaited()
 
     @pytest.mark.asyncio
     async def test_timeout_never_wakes_even_after_partial_match(
         self, db, mgr_mock, monkeypatch,
     ):
         import app.bg_jobs as module
         from app.bg_jobs import BgJobManager
         from app.db import bg_get_active_all, bg_save_job
 
         mgr = BgJobManager()
         manager, session = mgr_mock
         mgr.set_session_manager(manager)
         bg_save_job(self._job("cron-command-timeout", datetime.now(timezone.utc)))
         proc = self._proc(output=b"ALERT: partial\n", returncode=None)
-        monkeypatch.setattr(
-            module.asyncio,
-            "create_subprocess_shell",
-            AsyncMock(return_value=proc),
-        )
+        monkeypatch.setattr(module, "_spawn_bg_process", AsyncMock(return_value=proc))
 
         async def timeout(_process):
             raise asyncio.TimeoutError
 
         killed = AsyncMock()
         monkeypatch.setattr(module, "_communicate_cron_command", timeout)
         monkeypatch.setattr(module, "_kill_proc", killed)
 
         await mgr._fire_cron_command(
             "cron-command-timeout",
             "python monitor.py",
             "ALERT",
             "monitor found work",
             "w1",
             "/s",
         )
 
         manager.ensure_loaded.assert_not_awaited()
         session.send.assert_not_awaited()
         killed.assert_awaited_once_with(proc)
         row = next(
             job for job in bg_get_active_all()
             if job["id"] == "cron-command-timeout"
         )
         assert row["status"] == "active"
         assert "timed out after 30 seconds" in row["last_output"]
 
     @pytest.mark.asyncio
     async def test_cancellation_while_communicate_blocked_kills_process(
         self, db, mgr_mock, monkeypatch,
     ):
         import app.bg_jobs as module
         from app.bg_jobs import BgJobManager
         from app.db import bg_save_job
 
         mgr = BgJobManager()
         manager, _session = mgr_mock
         mgr.set_session_manager(manager)
         bg_save_job(self._job("cron-command-cancel", datetime.now(timezone.utc)))
         proc = self._proc(returncode=None)
-        monkeypatch.setattr(
-            module.asyncio,
-            "create_subprocess_shell",
-            AsyncMock(return_value=proc),
-        )
+        monkeypatch.setattr(module, "_spawn_bg_process", AsyncMock(return_value=proc))
         communicating = asyncio.Event()
         never = asyncio.Event()
 
         async def blocked(_process):
             communicating.set()
             await never.wait()
 
         killed = AsyncMock()
         monkeypatch.setattr(module, "_communicate_cron_command", blocked)
         monkeypatch.setattr(module, "_kill_proc", killed)
         task = asyncio.create_task(mgr._fire_cron_command(
             "cron-command-cancel",
             "python monitor.py",
             "ALERT",
             "monitor found work",
             "w1",
             "/s",
         ))
         await communicating.wait()
 
@@ -560,83 +550,75 @@ class TestRunExecOutcome:
 
         mgr = BgJobManager()
         manager, session = mgr_mock
         session.parent_name = "parent-orchestrator"
         session.last_task_sender = ""
         mgr.set_session_manager(manager)
         bg_save_job(self._job("run-parent", datetime.now(timezone.utc)))
 
         await mgr._trigger(
             "run-parent",
             "review done",
             "w1",
             "/s",
             "review output",
         )
 
         assert session.last_task_sender == "parent-orchestrator"
         session.send.assert_awaited_once()
 
     @pytest.mark.asyncio
-    async def test_reports_child_that_keeps_stdout_open_without_signaling(
+    async def test_reports_child_that_keeps_stdout_open_before_safe_cleanup(
         self, db, mgr_mock, caplog, monkeypatch,
     ):
         from app.bg_jobs import BgJobManager
         from app.db import bg_get_jobs, bg_save_job
 
         caplog.set_level("WARNING", logger="app.bg_jobs")
-        monkeypatch.setattr(
-            "app.bg_jobs.os.killpg",
-            lambda *_: pytest.fail("observation must not signal a process group"),
-        )
         mgr = BgJobManager()
         manager, session = mgr_mock
         mgr.set_session_manager(manager)
         bg_save_job(self._job("run-open-pipe", datetime.now(timezone.utc)))
 
         await asyncio.wait_for(
             mgr._run_exec(
                 "run-open-pipe",
                 "/usr/bin/python3 -c 'import os,time; os.fork() and os._exit(0); time.sleep(3.5)'",
                 "review done", "w1", "/s", 10,
             ),
             timeout=12,
         )
 
         row = next(j for j in bg_get_jobs(scope="/s") if j["id"] == "run-open-pipe")
         assert row["status"] == "triggered"
         session.send.assert_awaited_once()
         assert "orphan_tree=1" in caplog.text
         assert "oldest_process_age_seconds=" in caplog.text
         assert "observation_only=true" in caplog.text
 
     @pytest.mark.asyncio
     async def test_cancellation_after_leader_exit_closes_transport(
         self, db, mgr_mock, monkeypatch,
     ):
         from app.bg_jobs import BgJobManager
         from app.db import bg_save_job
 
-        monkeypatch.setattr(
-            "app.bg_jobs.os.killpg",
-            lambda *_: pytest.fail("cancellation must not signal a stale process group"),
-        )
         mgr = BgJobManager()
         manager, _ = mgr_mock
         mgr.set_session_manager(manager)
         bg_save_job(self._job("run-cancel-open-pipe", datetime.now(timezone.utc)))
         task = asyncio.create_task(mgr._run_exec(
             "run-cancel-open-pipe",
             "/usr/bin/python3 -c 'import os,time; os.fork() and os._exit(0); time.sleep(3.5)'",
             "review done", "w1", "/s", 10,
         ))
 
         for _ in range(100):
             proc = mgr._procs.get("run-cancel-open-pipe")
             if proc and proc.returncode is not None:
                 break
             await asyncio.sleep(0.01)
         else:
             pytest.fail("job leader did not exit")
 
         transport = proc._transport
         close = MagicMock(wraps=transport.close)
@@ -673,20 +655,217 @@ class TestRunExecOutcome:
         assert scan_threads and scan_threads[0] != caller_thread
 
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
+
+
+class TestPidfdProcessLifecycle:
+    @pytest.mark.asyncio
+    async def test_shell_and_argv_modes_preserve_arguments(self):
+        from app.bg_jobs import _kill_proc, _spawn_bg_process
+
+        argv_proc = await _spawn_bg_process(
+            ["/usr/bin/printf", "%s", "argv value"],
+            shell=False,
+            stdout=asyncio.subprocess.PIPE,
+        )
+        argv_output, _ = await argv_proc.communicate()
+        await _kill_proc(argv_proc)
+
+        shell_proc = await _spawn_bg_process(
+            "printf '%s' 'shell value'",
+            shell=True,
+            stdout=asyncio.subprocess.PIPE,
+        )
+        shell_output, _ = await shell_proc.communicate()
+        await _kill_proc(shell_proc)
+
+        assert argv_output == b"argv value"
+        assert shell_output == b"shell value"
+
+    @pytest.mark.asyncio
+    async def test_unsupported_group_signal_fails_before_target_exec(
+        self, tmp_path, monkeypatch,
+    ):
+        import app.bg_jobs as module
+
+        marker = tmp_path / "must-not-exist"
+        monkeypatch.setattr(module, "pidfd_send_group", lambda _fd, _sig: False)
+
+        with pytest.raises(RuntimeError, match="disappeared before exec ACK"):
+            await module._spawn_bg_process(
+                f"touch {marker}", shell=True,
+                stdout=asyncio.subprocess.DEVNULL,
+                stderr=asyncio.subprocess.DEVNULL,
+            )
+
+        assert not marker.exists()
+
+    @pytest.mark.asyncio
+    async def test_cancelled_handshake_never_executes_target(
+        self, tmp_path, monkeypatch,
+    ):
+        import app.bg_jobs as module
+
+        marker = tmp_path / "must-not-exist"
+        receiving = asyncio.Event()
+
+        async def blocked_receive(_control):
+            receiving.set()
+            await asyncio.Event().wait()
+
+        monkeypatch.setattr(module, "_recv_pidfd", blocked_receive)
+        task = asyncio.create_task(module._spawn_bg_process(
+            f"touch {marker}", shell=True,
+            stdout=asyncio.subprocess.DEVNULL,
+            stderr=asyncio.subprocess.DEVNULL,
+        ))
+        await receiving.wait()
+        task.cancel()
+
+        with pytest.raises(asyncio.CancelledError):
+            await task
+        assert not marker.exists()
+
+    @pytest.mark.asyncio
+    async def test_concurrent_cleanup_is_single_and_cancellation_shielded(
+        self, monkeypatch,
+    ):
+        import app.bg_jobs as module
+
+        class Process:
+            pid = 12345
+            _orchestra_cleanup_task = None
+
+        proc = Process()
+        started = asyncio.Event()
+        release = asyncio.Event()
+        calls = 0
+
+        async def cleanup(_proc):
+            nonlocal calls
+            calls += 1
+            started.set()
+            await release.wait()
+
+        monkeypatch.setattr(module, "_cleanup_pidfd_group", cleanup)
+        first = asyncio.create_task(module._kill_proc(proc))
+        await started.wait()
+        second = asyncio.create_task(module._kill_proc(proc))
+        first.cancel()
+        with pytest.raises(asyncio.CancelledError):
+            await first
+        assert not second.done()
+
+        release.set()
+        await second
+        await module._kill_proc(proc)
+        assert calls == 1
+
+    @pytest.mark.asyncio
+    async def test_live_leader_and_child_are_terminated_but_unrelated_survives(self):
+        from app.bg_jobs import _kill_proc, _spawn_bg_process
+
+        code = """
+import os
+import time
+child = os.fork()
+if child == 0:
+    time.sleep(30)
+    os._exit(0)
+print(child, flush=True)
+time.sleep(30)
+"""
+        proc = await _spawn_bg_process(
+            [sys.executable, "-c", code],
+            shell=False,
+            stdout=asyncio.subprocess.PIPE,
+            stderr=asyncio.subprocess.DEVNULL,
+        )
+        child_pid = int((await asyncio.wait_for(proc.stdout.readline(), 2)).decode())
+        unrelated = await asyncio.create_subprocess_exec(
+            "/bin/sleep", "30", start_new_session=True,
+        )
+        try:
+            await _kill_proc(proc)
+            assert proc.returncode == -signal.SIGTERM
+            assert not os.path.exists(f"/proc/{child_pid}")
+            assert unrelated.returncode is None
+        finally:
+            if unrelated.returncode is None:
+                unrelated.terminate()
+            await unrelated.wait()
+
+    @pytest.mark.asyncio
+    async def test_reaped_leader_retains_group_identity_for_kill_escalation(
+        self, tmp_path, monkeypatch,
+    ):
+        import app.bg_jobs as module
+
+        child_file = tmp_path / "child.pid"
+        code = f"""
+import os
+import signal
+import time
+child = os.fork()
+if child == 0:
+    signal.signal(signal.SIGTERM, signal.SIG_IGN)
+    with open({str(child_file)!r}, "w") as fh:
+        fh.write(str(os.getpid()))
+    while True:
+        time.sleep(30)
+os._exit(0)
+"""
+        proc = await module._spawn_bg_process(
+            [sys.executable, "-c", code],
+            shell=False,
+            stdout=asyncio.subprocess.DEVNULL,
+            stderr=asyncio.subprocess.DEVNULL,
+        )
+        await asyncio.wait_for(proc.wait(), 2)
+        for _ in range(100):
+            if child_file.exists():
+                break
+            await asyncio.sleep(0.01)
+        else:
+            pytest.fail("TERM-ignoring child did not start")
+        child_pid = int(child_file.read_text())
+        unrelated = await asyncio.create_subprocess_exec(
+            "/bin/sleep", "30", start_new_session=True,
+        )
+        sent = []
+        real_send = module.pidfd_send_group
+
+        def record_send(pidfd, sig):
+            sent.append(sig)
+            return real_send(pidfd, sig)
+
+        monkeypatch.setattr(module, "pidfd_send_group", record_send)
+        monkeypatch.setattr(module, "_PIDFD_TERM_GRACE", 0.05)
+        monkeypatch.setattr(module, "_PIDFD_KILL_GRACE", 0.5)
+        monkeypatch.setattr(module, "_PIDFD_POLL_INTERVAL", 0.01)
+        try:
+            await module._kill_proc(proc)
+            assert signal.SIGTERM in sent
+            assert signal.SIGKILL in sent
+            assert not os.path.exists(f"/proc/{child_pid}")
+            assert unrelated.returncode is None
+        finally:
+            if unrelated.returncode is None:
+                unrelated.terminate()
+            await unrelated.wait()


## Later history of the touched files on main (after this commit)

32 later commits touch these paths; the first 40 (oldest first):
a36e1a236 2026-08-02 #120: restore cron_command test seam after pidfd spawn refactor
8a5ea9ec2 2026-08-03 #4, #5, #6, #7, #10, #12, #14: #4: WIP #4: снимок квот перестал врать при молчащем провайдере
f2ce77eba 2026-08-04 #30: #30: исследование — сообщение юзера из TG теряется молча, остальные четыре пути отвечают
750d0d0b2 2026-08-04 #50: #50: исследование — точка врезки в send() измерена, очередь обязана быть durable
9f777f912 2026-08-04 Squashed commits: - #82: исследование — имя как внешний ключ в трёх слоях, тихий путь не тот, что в репорте - #82: план — env чинится пересборкой, сохранённые ссылки предпочитают id, 4 тикета - #82: T1 — bg-джобы будят по неизменяемому id, а не по имени - WIP #82: T2 наполовину — в session.py есть флаг _identity_stale и его гашение на границе хода; НЕ сделано: manager.refresh_identity (пересборка mcp_servers) и вызов из rename_session, весь T3, T4 - #82: T2 — переименование пересобирает MCP-идентичность, перезапуск на границе хода - #82: T3 — держатель тест-лока по неизменяемому id, дети переименованного родителя - #82: T4 — живой прогон переименования, отчёт и личная память
208c7fcae 2026-08-14 #180: #180: _run_exec rejects blind review artifacts
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

### a36e1a236 #120: restore cron_command test seam after pidfd spawn refactor

diff --git a/tests/test_bg_jobs.py b/tests/test_bg_jobs.py
index 56187a892..1c0c1d759 100644
--- a/tests/test_bg_jobs.py
+++ b/tests/test_bg_jobs.py
@@ -836,17 +836,22 @@ os._exit(0)
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
### 8a5ea9ec2 #4, #5, #6, #7, #10, #12, #14: #4: WIP #4: снимок квот перестал врать при молчащем провайдере

diff --git a/app/pidfd_exec.py b/app/pidfd_exec.py
index 2893cb8b6..bf7b990f1 100644
--- a/app/pidfd_exec.py
+++ b/app/pidfd_exec.py
@@ -36,10 +36,64 @@ def pidfd_open_self() -> int:
         error = ctypes.get_errno()
         raise OSError(error, os.strerror(error))
     return fd
 
 
+def group_signal_supported() -> bool:
+    """Whether the kernel can signal a process group through a pidfd.
+
+    Probes the syscall instead of parsing a version: the capability arrived in
+    Linux 6.9, and only with it does a group stay reachable after its leader is
+    reaped. Below that we fall back to killpg, which is safe only while the
+    leader is unreaped — so callers that depend on the stronger guarantee must
+    ask here rather than assume.
+    """
+    if _pidfd_send_signal is None:
+        return False
+    fd = pidfd_open_self()
+    try:
+        if _pidfd_send_signal(fd, 0, None, PIDFD_SIGNAL_PROCESS_GROUP) == 0:
+            return True
+        return ctypes.get_errno() != errno.EINVAL
+    finally:
+        os.close(fd)
+
+
+def pidfd_pid(pidfd: int) -> int:
+    """PID behind a pidfd, or 0 once the kernel has reaped that process.
+
+    ``/proc/self/fdinfo/<fd>`` is the only way back from a pidfd to a pid. The
+    kernel reports ``Pid: 0`` (``-1`` when seen from another namespace) after
+    reaping — precisely the moment the number becomes free for reuse.
+    """
+    try:
+        with open(f"/proc/self/fdinfo/{pidfd}", encoding="ascii") as fh:
+            for line in fh:
+                if line.startswith("Pid:"):
+                    return int(line.split()[1])
+    except (OSError, ValueError, IndexError):
+        return 0
+    return 0
+
+
+def _send_group_via_killpg(pidfd: int, sig: int) -> bool:
+    """Group-signal fallback anchored on the pidfd, for kernels below 6.9.
+
+    Safe for the same reason the flag is: while the leader is unreaped its pid
+    cannot be recycled, so its pgid still names OUR group. Once the pidfd shows
+    no pid, we report the group gone instead of signalling a stranger.
+    """
+    pid = pidfd_pid(pidfd)
+    if pid <= 0:
+        return False
+    try:
+        os.killpg(pid, sig)
+    except ProcessLookupError:
+        return False
+    return True
+
+
 def pidfd_send_group(pidfd: int, sig: int) -> bool:
     """Signal the retained process group; return False once the group is gone."""
     if _pidfd_send_signal is None:
         raise OSError(errno.ENOSYS, "libc pidfd functions are unavailable")
     if _pidfd_send_signal(
@@ -47,10 +101,15 @@ def pidfd_send_group(pidfd: int, sig: int) -> bool:
     ) == 0:
         return True
     error = ctypes.get_errno()
     if error == errno.ESRCH:
         return False
+    if error == errno.EINVAL:
+        # PIDFD_SIGNAL_PROCESS_GROUP only exists since Linux 6.9; older kernels
+        # reject the flag outright, which killed every background job on a 6.8
+        # host. Probing the syscall beats parsing a version string.
+        return _send_group_via_killpg(pidfd, sig)
     raise OSError(error, os.strerror(error))
 
 
 def _send_pidfd(control: socket.socket, pidfd: int) -> None:
     rights = array.array("i", [pidfd])
diff --git a/tests/test_bg_jobs.py b/tests/test_bg_jobs.py
index 1c0c1d759..d0c4bed06 100644
--- a/tests/test_bg_jobs.py
+++ b/tests/test_bg_jobs.py
@@ -9,10 +9,12 @@ import threading
 from datetime import datetime, timedelta, timezone
 from unittest.mock import AsyncMock, MagicMock
 
 import pytest
 
+from app.pidfd_exec import group_signal_supported
+
 
 @pytest.fixture
 def db(tmp_path, monkeypatch):
     db_path = tmp_path / "test.db"
     monkeypatch.setattr("app.db.DB_PATH", db_path)
@@ -809,10 +811,20 @@ time.sleep(30)
         finally:
             if unrelated.returncode is None:
                 unrelated.terminate()
             await unrelated.wait()
 
+    @pytest.mark.skipif(
+        not group_signal_supported(),
+        reason=(
+            "reaching a group AFTER its leader is reaped requires "
+            "PIDFD_SIGNAL_PROCESS_GROUP (Linux 6.9+). Below that the pidfd is the only "
+            "safe anchor and it goes blank on reaping, so the killpg fallback reports "
+            "the group gone rather than signal a possibly recycled pgid. Deliberately "
+            "weaker: leaking an orphan beats killing a stranger's process group."
+        ),
+    )
     @pytest.mark.asyncio
     async def test_reaped_leader_retains_group_identity_for_kill_escalation(
         self, tmp_path, monkeypatch,
     ):
         import app.bg_jobs as module
### f2ce77eba #30: #30: исследование — сообщение юзера из TG теряется молча, остальные четыре пути отвечают

diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index 50d9553a8..7be7adbd4 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -24,10 +24,11 @@ from app.db import (
     bg_cron_should_fire, bg_cron_record_fire,
     bg_get_jobs, bg_fail_job_if_active, bg_replace_job,
     bg_reset_wake_triggering,
 )
 from app.pidfd_exec import pidfd_send_group
+from app.tasks import spawn_supervised
 
 logger = logging.getLogger(__name__)
 
 MAX_JOBS_PER_SCOPE = 50
 MAX_TIMEOUT = 86400
@@ -414,11 +415,11 @@ class BgJobManager:
                 target_name, target_scope, watch_timeout,
                 command=config["command"], pattern=config["pattern"],
             )
         else:
             return
-        task = asyncio.create_task(coro)
+        task = spawn_supervised(coro, f"наблюдатель фоновой задачи {job_id}")
         self._tasks[job_id] = task
         task.add_done_callback(
             lambda finished: (
                 self._tasks.pop(job_id, None)
                 if self._tasks.get(job_id) is finished
@@ -527,10 +528,21 @@ class BgJobManager:
             bg_finish_trigger(job_id, output)
             logger.info(f"bg_job {job_id}: triggered → {target_name}")
         except Exception as e:
             bg_fail_job(job_id, str(e)[:500])
             logger.error(f"bg_job {job_id}: trigger failed: {e}")
+            # Факт в состоянии джоба виден только глазами в дашборде — это не уведомление.
+            # Адресат — оркестратор scope: он ставил джоб, ему и решать (#30).
+            from app.notify import report_undelivered
+
+            await report_undelivered(
+                self._session_manager,
+                scope=target_scope,
+                worker=target_name,
+                what=f"результат фоновой задачи {job_id}",
+                reason=f"{type(e).__name__}: {e}",
+            )
 
     def _expire(self, job_id: str) -> None:
         bg_expire_job(job_id)
         self._procs.pop(job_id, None)
 
### 750d0d0b2 #50: #50: исследование — точка врезки в send() измерена, очередь обязана быть durable

diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index 7be7adbd4..d9f5a4740 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -538,10 +538,11 @@ class BgJobManager:
                 self._session_manager,
                 scope=target_scope,
                 worker=target_name,
                 what=f"результат фоновой задачи {job_id}",
                 reason=f"{type(e).__name__}: {e}",
+                dedupe_key=f"bgjob:{job_id}",
             )
 
     def _expire(self, job_id: str) -> None:
         bg_expire_job(job_id)
         self._procs.pop(job_id, None)
### 9f777f912 Squashed commits: - #82: исследование — имя как внешний ключ в трёх слоях, тихий путь не тот, что в репорте - #82: план — env чинится пересборкой, сохранённые ссылки предпочитают id, 4 тикета - #82: T1 — bg-джобы будят по неизменяемому id, а не по имени - WIP #82: T2 наполовину — в session.py есть флаг _identity_stale и его гашение на границе хода; НЕ сделано: manager.refresh_identity (пересборка mcp_servers) и вызов из rename_session, весь T3, T4 - #82: T2 — переименование пересобирает MCP-идентичность, перезапуск на границе хода - #82: T3 — держатель тест-лока по неизменяемому id, дети переименованного родителя - #82: T4 — живой прогон переименования, отчёт и личная память

diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index d9f5a4740..c7cd9c228 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -20,11 +20,11 @@ from app.db import (
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
 
@@ -507,20 +507,43 @@ class BgJobManager:
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
@@ -556,13 +579,12 @@ class BgJobManager:
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
@@ -574,13 +596,12 @@ class BgJobManager:
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
@@ -643,13 +664,13 @@ class BgJobManager:
 
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
@@ -698,19 +719,12 @@ class BgJobManager:
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
diff --git a/tests/test_bg_jobs.py b/tests/test_bg_jobs.py
index d0c4bed06..73fd562de 100644
--- a/tests/test_bg_jobs.py
+++ b/tests/test_bg_jobs.py
@@ -29,10 +29,12 @@ def mgr_mock():
     sess = MagicMock()
     sess.id = "s-1"
     sess.send = AsyncMock()
     m.ensure_loaded = AsyncMock(return_value=sess)
     m.ensure_loaded_any = AsyncMock(return_value=sess)
+    # #82: пробуждение идёт по неизменяемому id, а не по имени.
+    m.ensure_loaded_by_id = AsyncMock(return_value=sess)
 
     async def deliver(_session_id, message):
         await sess.send(message)
 
     m.send = AsyncMock(side_effect=deliver)
### 208c7fcae #180: #180: _run_exec rejects blind review artifacts

diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index c7cd9c228..72002babe 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -36,10 +36,27 @@ MAX_TIMER_TIMEOUT = 8 * 86400
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
 
@@ -913,18 +930,20 @@ class BgJobManager:
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
diff --git a/tests/test_bg_jobs.py b/tests/test_bg_jobs.py
index 73fd562de..2e88ae31c 100644
--- a/tests/test_bg_jobs.py
+++ b/tests/test_bg_jobs.py
@@ -677,10 +677,119 @@ class TestRunExecOutcome:
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