"""Background Jobs — server-side one-shot tasks that survive hibernate."""

import asyncio
import array
import json
import logging
import os
import re
import signal
import socket
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

from croniter import croniter

from app.db import (
    bg_save_job, bg_claim_trigger, bg_finish_trigger, bg_fail_job,
    bg_cancel_job, bg_expire_job, bg_update_output, bg_get_active_all,
    bg_expire_overdue, bg_count_active, bg_cancel_by_session,
    bg_reset_stale_triggering, bg_cleanup_old,
    bg_cron_should_fire, bg_cron_record_fire,
    bg_get_jobs, bg_get_job, bg_fail_job_if_active, bg_replace_job,
    bg_reset_wake_triggering,
)
from app.pidfd_exec import pidfd_send_group
from app.events import InjectedMessage
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
# #180: rc=0 + nonempty file is not a review. Same markers as mcp_stdio's
# first-line detector, plus the #174 opening that has no ## Verdict at all.
_BLIND_REVIEW = re.compile(
    r"Unable to perform an evidence-backed review|"
    r"bwrap:|failed rtm_newaddr|setting up uid map: permission denied",
    re.IGNORECASE,
)
_REVIEW_VERDICT = re.compile(r"(?im)^##\s+Verdict\b")


def _blind_review_error(artifact: str, output: str = "") -> str:
    """Empty string if the artifact looks like a real review; else why it does not."""
    if _BLIND_REVIEW.search(artifact) or _BLIND_REVIEW.search(output):
        return "review artifact is blind: execution never happened"
    if _REVIEW_VERDICT.search(artifact) is None:
        return "review artifact has no '## Verdict' section"
    return ""
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
    elif job_type in ("cron", "cron_command"):
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


def _extract_pidfd(data: bytes, ancillary: list[tuple[int, int, bytes]]) -> int:
    received: list[int] = []
    for level, kind, payload in ancillary:
        if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
            continue
        rights = array.array("i")
        rights.frombytes(payload[:len(payload) - len(payload) % rights.itemsize])
        received.extend(rights)
    if data != b"P":
        for fd in received:
            os.close(fd)
        detail = data.decode(errors="replace") or "EOF"
        raise RuntimeError(f"pidfd exec handshake failed: {detail}")
    if len(received) != 1:
        for fd in received:
            os.close(fd)
        raise RuntimeError(f"pidfd exec handshake received {len(received)} fds")
    return received[0]


async def _recv_pidfd(control: socket.socket) -> int:
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    fd_size = array.array("i").itemsize

    def receive() -> None:
        try:
            data, ancillary, _flags, _address = control.recvmsg(
                256,
                socket.CMSG_SPACE(fd_size),
                socket.MSG_CMSG_CLOEXEC,
            )
            result = _extract_pidfd(data, ancillary)
        except BlockingIOError:
            return
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
        else:
            if not future.done():
                future.set_result(result)
        finally:
            if future.done():
                loop.remove_reader(control.fileno())

    control.setblocking(False)
    loop.add_reader(control.fileno(), receive)
    try:
        return await future
    finally:
        loop.remove_reader(control.fileno())


async def _spawn_bg_process(
    command: str | list[str],
    *,
    shell: bool,
    **kwargs,
) -> asyncio.subprocess.Process:
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    proc = None
    pidfd = None
    try:
        mode = "shell" if shell else "argv"
        target = [command] if shell else list(command)
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            _PIDFD_EXEC,
            str(child.fileno()),
            mode,
            *target,
            pass_fds=(child.fileno(),),
            start_new_session=True,
            **kwargs,
        )
        child.close()
        pidfd = await asyncio.wait_for(
            _recv_pidfd(parent), timeout=_PIDFD_HANDSHAKE_TIMEOUT,
        )
        if not pidfd_send_group(pidfd, 0):
            raise RuntimeError("pidfd process group disappeared before exec ACK")
        proc._orchestra_pidfd = pidfd
        pidfd = None
        try:
            await asyncio.get_running_loop().sock_sendall(parent, b"A")
        except BaseException:
            parent.close()
            await _kill_proc(proc)
            raise
        return proc
    except BaseException:
        if pidfd is not None:
            os.close(pidfd)
        if proc is not None and getattr(proc, "_orchestra_pidfd", None) is None:
            child.close()
            parent.close()
            try:
                await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.error(
                    "pidfd exec shim pid=%s did not exit after handshake failure",
                    proc.pid,
                )
        raise
    finally:
        child.close()
        parent.close()


async def _cleanup_pidfd_group(proc: asyncio.subprocess.Process) -> None:
    pidfd = getattr(proc, "_orchestra_pidfd", None)
    if pidfd is None:
        raise RuntimeError(f"process pid={proc.pid} has no stable pidfd identity")
    proc._orchestra_pidfd = None
    try:
        alive = pidfd_send_group(pidfd, signal.SIGTERM)
        deadline = asyncio.get_running_loop().time() + _PIDFD_TERM_GRACE
        while alive and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(_PIDFD_POLL_INTERVAL)
            alive = pidfd_send_group(pidfd, 0)
        if alive:
            pidfd_send_group(pidfd, signal.SIGKILL)
            deadline = asyncio.get_running_loop().time() + _PIDFD_KILL_GRACE
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(_PIDFD_POLL_INTERVAL)
                if not pidfd_send_group(pidfd, 0):
                    break
            else:
                raise RuntimeError(f"process group for pid={proc.pid} survived SIGKILL")
        try:
            await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=2)
        except asyncio.TimeoutError:
            logger.warning("process leader pid=%s was not reaped after group exit", proc.pid)
    finally:
        os.close(pidfd)


async def _kill_proc(proc: asyncio.subprocess.Process) -> None:
    cleanup = getattr(proc, "_orchestra_cleanup_task", None)
    if cleanup is None:
        cleanup = asyncio.create_task(_cleanup_pidfd_group(proc))
        proc._orchestra_cleanup_task = cleanup
    await asyncio.shield(cleanup)


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
            if not entry.name.isdigit():
                continue
            try:
                with open(
                    f"/proc/{entry.name}/stat", encoding="utf-8", errors="replace",
                ) as fh:
                    stat = fh.read()
                fields = stat[stat.rfind(")") + 2:].split()
                if int(fields[3]) != session_id:
                    continue
                age = max(0.0, uptime - int(fields[19]) / clock_ticks)
            except (OSError, ValueError, IndexError):
                continue  # /proc entries routinely disappear during the scan
            count += 1
            oldest_age = max(oldest_age, age)
    return count, oldest_age


async def _communicate_cron_command(
    proc: asyncio.subprocess.Process,
) -> tuple[bytes, bytes]:
    return await asyncio.wait_for(
        proc.communicate(),
        timeout=_CRON_COMMAND_TIMEOUT_SECONDS,
    )


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
        no_expiry = job_type in _NO_EXPIRY_TYPES and timeout_seconds <= 0
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
        watch_timeout = None if config.get("no_expiry") else timeout
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
                                        message, target_name, target_scope, watch_timeout)
        elif job_type == "command":
            interval = max(5, config.get("interval_seconds", 60))
            coro = self._run_command_watch(job_id, config["command"], config["pattern"],
                                          interval, message, target_name, target_scope,
                                          watch_timeout)
        elif job_type == "ssh":
            coro = self._run_ssh_watch(job_id, config["host"], config["command"],
                                       config["pattern"], message, target_name, target_scope,
                                       watch_timeout)
        elif job_type == "run":
            host = config.get("host")
            coro = self._run_exec(job_id, config["command"], message, target_name,
                                  target_scope, timeout, host=host,
                                  success_file=config.get("success_file"),
                                  success_pattern=config.get("success_pattern", ""))
        elif job_type == "cron":
            coro = self._run_cron(job_id, config["cron_expr"], message,
                                  target_name, target_scope, watch_timeout)
        elif job_type == "cron_command":
            coro = self._run_cron(
                job_id, config["cron_expr"], message,
                target_name, target_scope, watch_timeout,
                command=config["command"], pattern=config["pattern"],
            )
        else:
            return
        task = spawn_supervised(coro, f"наблюдатель фоновой задачи {job_id}")
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

    @staticmethod
    def _terminal_message(job_id: str, outcome: str, text: str) -> InjectedMessage:
        return InjectedMessage(
            text=text,
            origin="orchestra.bg_jobs",
            job_id=job_id,
            event_id=f"bgjob:v1:{job_id}:{outcome}",
        )

    async def _load_job_target(self, job_id: str, target_name: str):
        """Найти цель джоба по НЕИЗМЕНЯЕМОМУ id из его же строки.

        Имя, записанное при создании, к моменту срабатывания могло смениться
        (`rename_worker`) или уже принадлежать ДРУГОМУ агенту — разбудить по нему значит
        либо не разбудить никого молча, либо разбудить чужого. Имя оставлено для человека.
        """
        row = bg_get_job(job_id) or {}
        target_session_id = str(row.get("target_session_id") or "")
        if not target_session_id:
            logger.error(
                f"bg_job {job_id}: no target_session_id "
                f"(name at creation: {target_name!r}) — refusing to wake by name"
            )
            return None, "job has no target_session_id"
        session = await self._session_manager.ensure_loaded_by_id(target_session_id)
        if not session:
            logger.warning(
                f"bg_job {job_id}: target session {target_session_id} "
                f"(name at creation: {target_name!r}) not found"
            )
            return None, "target session not found"
        return session, ""

    async def _trigger(self, job_id: str, message: str,
                       target_name: str, target_scope: str, output: str = "") -> None:
        claimed = bg_claim_trigger(job_id)
        if not claimed:
            return
        try:
            session, failure = await self._load_job_target(job_id, target_name)
            if not session:
                bg_fail_job(job_id, failure)
                return
            body = f"[Background job completed] {message}"
            if output:
                body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
            self._restore_report_provenance(session)
            await self._session_manager.send(
                session.id,
                self._terminal_message(job_id, "completed", body),
            )
            bg_finish_trigger(job_id, output)
            logger.info(f"bg_job {job_id}: triggered → {target_name}")
        except Exception as e:
            bg_fail_job(job_id, str(e)[:500])
            logger.error(f"bg_job {job_id}: trigger failed: {e}")
            # Факт в состоянии джоба виден только глазами в дашборде — это не уведомление.
            # Адресат — оркестратор scope: он ставил джоб, ему и решать (#30).
            from app.notify import report_undelivered

            await report_undelivered(
                self._session_manager,
                scope=target_scope,
                worker=target_name,
                what=f"результат фоновой задачи {job_id}",
                reason=f"{type(e).__name__}: {e}",
                dedupe_key=f"bgjob:{job_id}",
            )

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
            session, _failure = await self._load_job_target(job_id, target_name)
            if not session:
                return
            body = f"[Background job TIMED OUT] {err}"
            if output:
                body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
            self._restore_report_provenance(session)
            await self._session_manager.send(
                session.id,
                self._terminal_message(job_id, "timed_out", body),
            )
            logger.warning(f"bg_job {job_id}: TIMED OUT after {dur} → notified {target_name}")
        except Exception as e:
            logger.error(f"bg_job {job_id}: timeout-notify failed: {e}")

    async def _fail_notify(self, job_id, message, target_name, target_scope,
                           error, output=""):
        """Persist a failed run and wake the waiting agent with an explicit failure."""
        bg_fail_job(job_id, error)
        try:
            session, _failure = await self._load_job_target(job_id, target_name)
            if not session:
                return
            body = f"[Background job FAILED] {message}\n{error}"
            if output:
                body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
            self._restore_report_provenance(session)
            await self._session_manager.send(
                session.id,
                self._terminal_message(job_id, "failed", body),
            )
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

    async def _run_cron(
        self, job_id, cron_expr, message, target_name, target_scope, timeout,
        command="", pattern="",
    ):
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
                if command:
                    await self._fire_cron_command(
                        job_id, command, pattern, message,
                        target_name, target_scope,
                    )
                else:
                    await self._fire_cron(
                        job_id, message, target_name, target_scope,
                    )
            self._expire(job_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            bg_fail_job(job_id, str(e)[:500])

    async def _fire_cron(self, job_id, message, target_name, target_scope):
        if not bg_cron_should_fire(job_id):
            return
        try:
            session, _failure = await self._load_job_target(job_id, target_name)
            if not session:
                # Расписание живёт дальше: цель могла быть выгружена временно.
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
            proc = await _spawn_bg_process(
                command,
                shell=True,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
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
            )
            output = raw_output
            if proc.returncode:
                output += f"\n[exit code {proc.returncode}]"
            output = output.strip()
            bg_update_output(job_id, output)
            if not raw_output or re.search(pattern, raw_output) is None:
                return
            if not bg_cron_should_fire(job_id):
                return
            session, _failure = await self._load_job_target(job_id, target_name)
            if not session:
                return
            self._restore_report_provenance(session)
            body = f"[Cron command matched] {message}"
            if output:
                body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
            await self._session_manager.send(session.id, body)
            bg_cron_record_fire(job_id)
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
            proc = await _spawn_bg_process(
                ["tail", "-F", "-n", "0", path],
                shell=False,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
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
                proc = await _spawn_bg_process(
                    command, shell=True,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
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
            proc = await _spawn_bg_process(
                ["ssh", *_SSH_OPTS, host, command],
                shell=False,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
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
                proc = await _spawn_bg_process(
                    ["ssh", *_SSH_OPTS, host, command],
                    shell=False,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                    limit=_STREAM_LIMIT,
                )
            else:
                proc = await _spawn_bg_process(
                    command, shell=True,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                    limit=_STREAM_LIMIT,
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
                    logger.warning(
                        f"bg_job {job_id}: stdout still open after pid={proc.pid} exited; "
                        "detaching reader without signaling descendants"
                    )
                    reader_task.cancel()
                    await asyncio.gather(reader_task, return_exceptions=True)
                    transport = getattr(proc, "_transport", None)
                    if transport:
                        transport.close()
                orphan_count, oldest_age = await asyncio.to_thread(
                    _orphan_session_stats, proc.pid,
                )
                if orphan_count:
                    logger.warning(
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
                    else:
                        with open(success_file, encoding="utf-8", errors="replace") as fh:
                            artifact = fh.read()
                        if success_pattern and re.search(success_pattern, artifact) is None:
                            validation_error = (
                                f"Required output artifact does not match success pattern: "
                                f"{success_file}"
                            )
                        else:
                            validation_error = _blind_review_error(artifact, full_output)
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
                transport = getattr(proc, "_transport", None)
                if proc.returncode is not None and transport:
                    transport.close()


bg_manager = BgJobManager()
