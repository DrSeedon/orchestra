"""Background Jobs — server-side one-shot tasks that survive hibernate."""

import asyncio
import json
import logging
import os
import re
import signal
import time
from datetime import datetime, timezone, timedelta
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

logger = logging.getLogger(__name__)

MAX_JOBS_PER_SCOPE = 50
MAX_TIMEOUT = 86400
MAX_TIMER_TIMEOUT = 8 * 86400
DEFAULT_TIMEOUT = 3600
OUTPUT_PROGRESS_INTERVAL = 30

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
            return "pattern is required"
        try:
            re.compile(pattern)
        except re.error as e:
            return f"invalid regex pattern: {e}"
    elif job_type == "command":
        if not config.get("command"):
            return "command is required"
        pattern = config.get("pattern", "")
        if not pattern:
            return "pattern is required"
        try:
            re.compile(pattern)
        except re.error as e:
            return f"invalid regex pattern: {e}"
        interval = config.get("interval_seconds", 60)
        if not isinstance(interval, (int, float)) or interval < 5:
            return "interval_seconds must be >= 5"
    elif job_type == "ssh":
        if not config.get("command"):
            return "command is required"
        if not config.get("host"):
            return "host is required"
        pattern = config.get("pattern", "")
        if not pattern:
            return "pattern is required"
        try:
            re.compile(pattern)
        except re.error as e:
            return f"invalid regex pattern: {e}"
    elif job_type == "run":
        if not config.get("command"):
            return "command is required"
        success_pattern = config.get("success_pattern", "")
        if success_pattern:
            try:
                re.compile(success_pattern)
            except re.error as e:
                return f"invalid success_pattern: {e}"
    elif job_type == "cron":
        expr = config.get("cron_expr", "")
        if not expr:
            return "cron_expr is required"
        if not croniter.is_valid(expr):
            return f"invalid cron expression: {expr!r}"
    else:
        return f"unknown job type: {job_type}"
    return None


async def _kill_proc(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=3)
    except (asyncio.TimeoutError, ProcessLookupError):
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except Exception:
            pass


class BgJobManager:
    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}
        self._procs: dict[str, asyncio.subprocess.Process] = {}
        self._session_manager = None

    def set_session_manager(self, mgr) -> None:
        self._session_manager = mgr

    async def create(self, job_type: str, config: dict, message: str,
                     target_session_id: str, target_name: str, target_scope: str,
                     created_by: str, timeout_seconds: int = DEFAULT_TIMEOUT,
                     replace_key: str = "") -> dict:
        err = _validate_config(job_type, config)
        if err:
            return {"error": err}
        count = bg_count_active(target_scope)
        if not replace_key and count >= MAX_JOBS_PER_SCOPE:
            return {"error": f"too many active jobs ({count}/{MAX_JOBS_PER_SCOPE})"}

        now = datetime.now(timezone.utc)
        no_expiry = (job_type == "cron" and timeout_seconds <= 0)
        if no_expiry:
            config = {**config, "no_expiry": True}
            expires_at = (now + timedelta(days=36500)).isoformat()
        else:
            max_timeout = MAX_TIMER_TIMEOUT if job_type == "timer" else MAX_TIMEOUT
            if job_type == "timer":
                timeout_seconds = max(
                    timeout_seconds,
                    int(config["delay_seconds"]) + 3600,
                )
            timeout_seconds = max(1, min(timeout_seconds, max_timeout))
            expires_at = (now + timedelta(seconds=timeout_seconds)).isoformat()

        job_id = f"bg-{uuid4().hex[:10]}"
        trigger_at = None
        if job_type == "timer":
            trigger_at = (now + timedelta(seconds=config["delay_seconds"])).isoformat()

        stored_config = {**config, "replace_key": replace_key} if replace_key else config
        job = {
            "id": job_id, "type": job_type, "config": json.dumps(stored_config),
            "message": message, "target_session_id": target_session_id,
            "target_name": target_name, "target_scope": target_scope,
            "created_by_name": created_by, "status": "active",
            "expires_at": expires_at,
            "trigger_at": trigger_at, "created_at": now.isoformat(),
            "last_output": "",
        }
        if replace_key:
            replaced_ids = bg_replace_job(job, replace_key)
            for replaced_id in replaced_ids:
                previous = self._tasks.pop(replaced_id, None)
                if previous and not previous.done():
                    previous.cancel()
        else:
            bg_save_job(job)
        self._start_task(job_id, job_type, stored_config, message, target_session_id,
                         target_name, target_scope, timeout_seconds,
                         trigger_at)
        logger.info(f"bg_job created: {job_id} type={job_type} target={target_name}")
        return {"id": job_id, "type": job_type, "status": "active"}

    def _start_task(self, job_id, job_type, config, message, target_session_id,
                    target_name, target_scope, timeout, trigger_at=None):
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
                                        message, target_name, target_scope, timeout)
        elif job_type == "command":
            interval = max(5, config.get("interval_seconds", 60))
            coro = self._run_command_watch(job_id, config["command"], config["pattern"],
                                          interval, message, target_name, target_scope, timeout)
        elif job_type == "ssh":
            coro = self._run_ssh_watch(job_id, config["host"], config["command"],
                                       config["pattern"], message, target_name, target_scope, timeout)
        elif job_type == "run":
            host = config.get("host")
            coro = self._run_exec(job_id, config["command"], message, target_name,
                                  target_scope, timeout, host=host,
                                  success_file=config.get("success_file"),
                                  success_pattern=config.get("success_pattern", ""))
        elif job_type == "cron":
            cron_timeout = None if config.get("no_expiry") else timeout
            coro = self._run_cron(job_id, config["cron_expr"], message,
                                  target_name, target_scope, cron_timeout)
        else:
            return
        task = asyncio.create_task(coro)
        self._tasks[job_id] = task
        task.add_done_callback(
            lambda finished: (
                self._tasks.pop(job_id, None)
                if self._tasks.get(job_id) is finished
                else None
            )
        )

    async def cancel(self, job_id: str) -> dict:
        ok = bg_cancel_job(job_id)
        if not ok:
            return {"error": "job not found or not active"}
        task = self._tasks.pop(job_id, None)
        if task and not task.done():
            task.cancel()
        proc = self._procs.pop(job_id, None)
        if proc:
            await _kill_proc(proc)
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
        if cancelled_count:
            logger.info(f"bg_jobs: cancelled {cancelled_count} jobs for session {session_id}")

    async def restore_from_db(self) -> None:
        cleaned = bg_cleanup_old(24)
        if cleaned:
            logger.info(f"bg_jobs: cleaned up {cleaned} old terminated jobs")
        wake_reset_ids = bg_reset_wake_triggering()
        if wake_reset_ids:
            logger.info(
                "bg_jobs: reset %s interrupted wake jobs",
                len(wake_reset_ids),
            )
        expired_ids = bg_expire_overdue()
        for jid in expired_ids:
            task = self._tasks.pop(jid, None)
            if task and not task.done():
                task.cancel()
        reset_ids = bg_reset_stale_triggering()
        if reset_ids:
            logger.info(f"bg_jobs: reset {len(reset_ids)} stale triggering jobs")
        active = bg_get_active_all()
        restored = 0
        for row in active:
            if row["id"] in self._tasks:
                continue
            if row["status"] != "active":
                continue
            config = json.loads(row["config"])
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
            await _kill_proc(proc)
        self._tasks.clear()
        self._procs.clear()

    def has_active_jobs(self, session_id: str) -> bool:
        return len(bg_get_jobs(session_id=session_id, active_only=True)) > 0

    # ── Trigger ──

    @staticmethod
    def _restore_report_provenance(session) -> None:
        if not session.last_task_sender and session.parent_name:
            session.last_task_sender = session.parent_name

    async def _trigger(self, job_id: str, message: str,
                       target_name: str, target_scope: str, output: str = "") -> None:
        claimed = bg_claim_trigger(job_id)
        if not claimed:
            return
        try:
            session = await self._session_manager.ensure_loaded(target_name, target_scope)
            if not session:
                bg_fail_job(job_id, "target session not found")
                logger.warning(f"bg_job {job_id}: target {target_name} not found")
                return
            body = f"[Background job completed] {message}"
            if output:
                body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
            self._restore_report_provenance(session)
            await session.send(body)
            bg_finish_trigger(job_id, output)
            logger.info(f"bg_job {job_id}: triggered → {target_name}")
        except Exception as e:
            bg_fail_job(job_id, str(e)[:500])
            logger.error(f"bg_job {job_id}: trigger failed: {e}")

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
        try:
            session = await self._session_manager.ensure_loaded(target_name, target_scope)
            if not session:
                logger.warning(f"bg_job {job_id}: timeout, target {target_name} not found")
                return
            body = f"[Background job TIMED OUT] {err}"
            if output:
                body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
            self._restore_report_provenance(session)
            await session.send(body)
            logger.warning(f"bg_job {job_id}: TIMED OUT after {dur} → notified {target_name}")
        except Exception as e:
            logger.error(f"bg_job {job_id}: timeout-notify failed: {e}")

    async def _fail_notify(self, job_id, message, target_name, target_scope,
                           error, output=""):
        """Persist a failed run and wake the waiting agent with an explicit failure."""
        bg_fail_job(job_id, error)
        try:
            session = await self._session_manager.ensure_loaded(target_name, target_scope)
            if not session:
                logger.warning(f"bg_job {job_id}: failed, target {target_name} not found")
                return
            body = f"[Background job FAILED] {message}\n{error}"
            if output:
                body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
            self._restore_report_provenance(session)
            await session.send(body)
            logger.warning(f"bg_job {job_id}: FAILED → notified {target_name}: {error}")
        except Exception as e:
            logger.error(f"bg_job {job_id}: failure-notify failed: {e}")

    def _fail_if_active(self, job_id: str, error: str) -> None:
        bg_fail_job_if_active(job_id, error)

    # ── Runners ──

    async def _run_timer(self, job_id, delay, message, target_name, target_scope):
        try:
            await asyncio.sleep(delay)
            await self._trigger(job_id, message, target_name, target_scope)
        except asyncio.CancelledError:
            pass

    async def _run_wake_timer(self, job_id, delay, config):
        try:
            await asyncio.sleep(delay)
            from app.limit_wake import run_wake_job

            await run_wake_job(job_id, config, self._session_manager)
        except asyncio.CancelledError:
            pass
        except Exception as error:
            bg_fail_job(job_id, str(error)[:500])

    async def _run_cron(self, job_id, cron_expr, message, target_name, target_scope, timeout):
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
                await self._fire_cron(job_id, message, target_name, target_scope)
            self._expire(job_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            bg_fail_job(job_id, str(e)[:500])

    async def _fire_cron(self, job_id, message, target_name, target_scope):
        if not bg_cron_should_fire(job_id):
            return
        try:
            session = await self._session_manager.ensure_loaded(target_name, target_scope)
            if not session:
                logger.warning(f"cron {job_id}: target {target_name} not found, skipping fire")
                return
            await session.send(f"[Cron job fired] {message}")
            bg_cron_record_fire(job_id)
            logger.info(f"cron {job_id}: fired → {target_name}")
        except Exception as e:
            logger.error(f"cron {job_id}: fire failed (continuing schedule): {e}")

    async def _run_file_watch(self, job_id, path, pattern, message,
                              target_name, target_scope, timeout):
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "tail", "-F", "-n", "0", path,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                preexec_fn=os.setsid,
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
        deadline = time.time() + timeout
        try:
            while time.time() < deadline:
                proc = await asyncio.create_subprocess_shell(
                    command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    preexec_fn=os.setsid,
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
            self._expire(job_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            bg_fail_job(job_id, str(e)[:500])

    async def _run_ssh_watch(self, job_id, host, command, pattern, message,
                              target_name, target_scope, timeout):
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "ssh", *_SSH_OPTS, host, command,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                preexec_fn=os.setsid,
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
                proc = await asyncio.create_subprocess_exec(
                    "ssh", *_SSH_OPTS, host, command,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                    preexec_fn=os.setsid, limit=_STREAM_LIMIT,
                )
            else:
                proc = await asyncio.create_subprocess_shell(
                    command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                    preexec_fn=os.setsid, limit=_STREAM_LIMIT,
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
                # asyncio Process.wait() itself waits for pipe EOF. A grandchild that
                # inherited stdout can therefore keep it blocked after the command
                # leader has exited. Observe the leader's returncode independently.
                while proc.returncode is None:
                    await asyncio.sleep(0.05)
                try:
                    await asyncio.wait_for(asyncio.shield(reader_task), timeout=2)
                except asyncio.TimeoutError:
                    # Codex may leave an MCP child holding the inherited stdout FD.
                    # The job itself has exited, so terminate only its dedicated
                    # process group and stop waiting for an EOF that will never come.
                    logger.warning(
                        f"bg_job {job_id}: stdout still open after pid={proc.pid} exited; "
                        "terminating leftover process group"
                    )
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except (ProcessLookupError, PermissionError):
                        pass
                    try:
                        await asyncio.wait_for(asyncio.shield(reader_task), timeout=2)
                    except asyncio.TimeoutError:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except (ProcessLookupError, PermissionError):
                            pass
                        reader_task.cancel()
                        await asyncio.gather(reader_task, return_exceptions=True)
                        transport = getattr(proc, "_transport", None)
                        if transport:
                            transport.close()
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
                    elif success_pattern:
                        with open(success_file, encoding="utf-8", errors="replace") as fh:
                            artifact = fh.read()
                        if re.search(success_pattern, artifact) is None:
                            validation_error = (
                                f"Required output artifact does not match success pattern: "
                                f"{success_file}"
                            )
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
        finally:
            if reader_task and not reader_task.done():
                reader_task.cancel()
                await asyncio.gather(reader_task, return_exceptions=True)
            self._procs.pop(job_id, None)
            if proc:
                await _kill_proc(proc)


bg_manager = BgJobManager()
