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
    get_session,
    bg_save_job, bg_claim_trigger, bg_finish_trigger, bg_fail_job,
    bg_cancel_job, bg_cancel_removed_idle, bg_expire_job, bg_update_output, bg_get_active_all,
    bg_expire_overdue, bg_count_active, bg_cancel_by_session,
    bg_reset_stale_triggering, bg_cleanup_old,
    bg_cron_should_fire, bg_cron_record_fire,
    bg_get_jobs, bg_get_job, bg_fail_job_if_active, bg_replace_job,
    bg_reset_wake_triggering, bg_record_process,
)
from app.pidfd_exec import pidfd_send_group
from app.session_state import AgentStatus
from app.events import InjectedMessage, MessageProvenance
from app.tasks import spawn_supervised

logger = logging.getLogger(__name__)

MAX_JOBS_PER_SCOPE = 50
MAX_TIMEOUT = 86400
DEFAULT_TIMEOUT = 3600
OUTPUT_PROGRESS_INTERVAL = 30
_CRON_COMMAND_TIMEOUT_SECONDS = 600
_NO_EXPIRY_TYPES = frozenset({"file", "command", "ssh", "cron", "cron_command"})
# A plain cron only sends the agent a recurring message and never completes, so it is a
# reminder, not a pending result: it must not hold the agent in `waiting` (V-952).
_RECURRING_REMINDER_TYPES = frozenset({"cron"})


def jobs_holding_waiting(session_id: str) -> list[dict]:
    """Active jobs whose completion the agent is still waiting for."""
    return [
        job for job in bg_get_jobs(session_id=session_id, active_only=True)
        if job["type"] not in _RECURRING_REMINDER_TYPES
    ]
_PIDFD_EXEC = str(Path(__file__).with_name("pidfd_exec.py"))
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


def _validate_regex(
    config: dict, field: str = "pattern", *, required: bool = True,
) -> str | None:
    value = config.get(field, "")
    if not value:
        return f"{field} is required" if required else None
    try:
        re.compile(value)
    except re.error as error:
        label = "regex pattern" if field == "pattern" else field
        return f"invalid {label}: {error}"
    return None


def _validate_config(job_type: str, config: dict) -> str | None:
    if job_type == "timer":
        delay = config.get("delay_seconds")
        if not isinstance(delay, (int, float)) or delay <= 0:
            return "delay_seconds must be a positive number"
    elif job_type == "file":
        if not config.get("path"):
            return "path is required"
        return _validate_regex(config)
    elif job_type == "command":
        if not config.get("command"):
            return "command is required"
        error = _validate_regex(config)
        if error:
            return error
        interval = config.get("interval_seconds", 60)
        if not isinstance(interval, (int, float)) or interval < 5:
            return "interval_seconds must be >= 5"
    elif job_type == "ssh":
        if not config.get("command"):
            return "command is required"
        if not config.get("host"):
            return "host is required"
        return _validate_regex(config)
    elif job_type == "run":
        if not config.get("command"):
            return "command is required"
        return _validate_regex(config, "success_pattern", required=False)
    elif job_type == "merge":
        if not isinstance(config.get("operation_id"), str) or not config["operation_id"].strip():
            return "operation_id is required"
    elif job_type in ("cron", "cron_command"):
        expr = config.get("cron_expr", "")
        if not expr:
            return "cron_expr is required"
        if not croniter.is_valid(expr):
            return f"invalid cron expression: {expr!r}"
        if job_type == "cron_command":
            if not config.get("command"):
                return "command is required"
            return _validate_regex(config)
    elif job_type == "idle":
        return ("job type 'idle' was removed: the platform itself tells the parent when a "
                "worker's turn ends without a report")
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
    received_pidfd = None

    def receive() -> None:
        nonlocal received_pidfd
        try:
            data, ancillary, _flags, _address = control.recvmsg(
                256,
                socket.CMSG_SPACE(fd_size),
                socket.MSG_CMSG_CLOEXEC,
            )
            received_pidfd = _extract_pidfd(data, ancillary)
        except BlockingIOError:
            return
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
        else:
            if not future.done():
                future.set_result(received_pidfd)
        finally:
            if future.done():
                loop.remove_reader(control.fileno())

    control.setblocking(False)
    loop.add_reader(control.fileno(), receive)
    try:
        return await future
    except BaseException:
        # A ready callback can receive the fd just before cancellation wins the
        # awaiting task's next step, even after set_result(). Ownership stays here.
        if received_pidfd is not None:
            os.close(received_pidfd)
        raise
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


def _process_start_ticks(pid: int) -> str:
    """Kernel start time of `pid` (field 22 of /proc/<pid>/stat); "" when it is gone."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return ""
    return stat.rpartition(")")[2].split()[19]


async def _reap_orphan_run(process: dict | None) -> str:
    """Stop the process group a previous Orchestra generation left behind (V-915).

    systemd runs us with KillMode=process, so when the old process dies without reaching
    `BgJobManager.shutdown` (SIGKILL after a stalled stop) its run jobs' children live on
    with their stdout pipe cut. Their result can never be collected, so the only honest
    state for the job is "interrupted" with the process gone, not a second copy racing a
    restarted command. Identity is checked first: the leader must be the same process
    (start time) or gone with its group still alive (a pid is never reused while it is
    still a pgid).
    """
    if not process:
        return "процесс не был записан (задание создано старой версией)"
    pid = int(process.get("pid") or 0)
    if pid <= 1:
        return "процесс не был записан"
    ticks = _process_start_ticks(pid)
    if ticks and ticks != process.get("start"):
        return f"pid {pid} уже принадлежит другому процессу — не трогали"
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return f"процесса (pid {pid}) уже нет"
    except PermissionError:
        return f"pid {pid}: нет прав остановить группу"
    for sig, grace in ((signal.SIGTERM, _PIDFD_TERM_GRACE), (signal.SIGKILL, _PIDFD_KILL_GRACE)):
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            break
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            await asyncio.sleep(_PIDFD_POLL_INTERVAL)
            try:
                os.killpg(pid, 0)
            except ProcessLookupError:
                return f"осиротевший процесс (pid {pid}) найден живым и остановлен"
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return f"осиротевший процесс (pid {pid}) найден живым и остановлен"
    return f"осиротевший процесс (pid {pid}) НЕ удалось остановить"


# V-919: a run job writes its output and exit code to files, so its process outlives an
# Orchestra restart (KillMode=process) and the next generation adopts it instead of
# reporting INTERRUPTED. The outer shell records the inner command's code and exits with it.
_RUN_WRAPPER = (
    'rc_file=$1; shift; "$@"; rc=$?; '
    'printf "%s\\n" "$rc" > "$rc_file.tmp" && mv -f "$rc_file.tmp" "$rc_file"; exit $rc'
)
_RUN_TAIL_BYTES = 256 * 1024
_RUN_TAIL_LINES = 300
_ADOPT_POLL_INTERVAL = 0.5


def _run_files(job_id: str) -> tuple[Path, Path]:
    from app import db
    root = Path(db.DB_PATH).parent / "bg_runs"
    return root / f"{job_id}.out", root / f"{job_id}.rc"


def _unlink_run_files(process: dict | None) -> None:
    for key in ("out", "rc"):
        if process and process.get(key):
            Path(process[key]).unlink(missing_ok=True)


def _read_run_tail(path: Path) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(max(0, os.fstat(fh.fileno()).st_size - _RUN_TAIL_BYTES))
            data = fh.read()
    except OSError:
        return ""
    return "".join(data.decode(errors="replace").splitlines(True)[-_RUN_TAIL_LINES:])


def _read_run_rc(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _run_leader_alive(process: dict) -> bool:
    """The recorded leader still runs: same start time and not a zombie."""
    pid = int(process.get("pid") or 0)
    if pid <= 1:
        return False
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()
    except OSError:
        return False
    return fields[19] == process.get("start") and fields[0] not in ("Z", "X")


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


async def _cleanup_cancelled_spawn(spawn: asyncio.Task) -> None:
    proc = await spawn
    await _kill_proc(proc)


async def _await_owned_spawn(spawn: asyncio.Task) -> asyncio.subprocess.Process:
    try:
        return await asyncio.shield(spawn)
    except asyncio.CancelledError:
        # Keep an owner even if cancellation interrupts the second await too.
        cleanup = spawn_supervised(
            _cleanup_cancelled_spawn(spawn), "cancelled process spawn cleanup",
        )
        await asyncio.shield(cleanup)
        raise


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
        self._shutting_down = False

    def set_session_manager(self, mgr) -> None:
        self._session_manager = mgr

    async def _spawn_managed_process(self, job_id, command, *, shell, **kwargs):
        """Register a process or kill it if the owner is cancelled during spawn."""
        agent_workload = kwargs.pop("agent_workload", False)
        env = dict(kwargs.pop("env", os.environ))
        if agent_workload:
            env["ORCHESTRA_AGENT_WORKLOAD"] = "1"
            cgroup = os.environ.get("ORCHESTRA_AGENT_CGROUP", "")
            if not cgroup and os.environ.get("ORCHESTRA_AGENT_CGROUP_REQUIRED") != "1":
                logger.warning("starting workflow task without agent cgroup isolation")
            elif not cgroup or not (Path(cgroup) / "cgroup.procs").exists():
                raise RuntimeError("delegated agent cgroup is unavailable; workflow task remains queued")
            else:
                env["ORCHESTRA_AGENT_CGROUP"] = cgroup
        else:
            env.pop("ORCHESTRA_AGENT_WORKLOAD", None)
            env.pop("ORCHESTRA_AGENT_CGROUP", None)
        kwargs["env"] = env
        spawn_task = asyncio.create_task(
            _spawn_bg_process(command, shell=shell, **kwargs)
        )
        proc = await _await_owned_spawn(spawn_task)
        self._procs[job_id] = proc
        return proc

    async def create(self, job_type: str, config: dict, message: str,
                     target_session_id: str, target_name: str, target_scope: str,
                     created_by: str, timeout_seconds: int = DEFAULT_TIMEOUT,
                     replace_key: str = "") -> dict:
        err = _validate_config(job_type, config)
        if err:
            return {"error": err}
        if job_type == "merge":
            from app.merge_operations import get_operation_record

            record = await asyncio.to_thread(get_operation_record, config["operation_id"])
            if not record or record["scope"] != target_scope:
                return {"error": "merge operation not found in target scope"}
            # No await between this lookup and saving the job: concurrent requests on
            # this manager cannot install two active watches for the same recipient.
            for existing in bg_get_jobs(session_id=target_session_id, active_only=True):
                if (existing["type"] == "merge"
                        and json.loads(existing["config"]).get("operation_id") == config["operation_id"]):
                    return {"id": existing["id"], "type": "merge", "status": existing["status"]}
        count = bg_count_active(target_scope)
        if not replace_key and count >= MAX_JOBS_PER_SCOPE:
            return {"error": f"too many active jobs ({count}/{MAX_JOBS_PER_SCOPE})"}

        now = datetime.now(timezone.utc)
        no_expiry = job_type in _NO_EXPIRY_TYPES and timeout_seconds <= 0
        if no_expiry:
            config = {**config, "no_expiry": True}
            expires_at = (now + timedelta(days=36500)).isoformat()
        else:
            if job_type == "timer":
                # A timer lives until it fires: any delay is allowed, and its expiry must
                # never precede trigger_at (an 8-day cap made long timers silently dead).
                timeout_seconds = max(
                    min(max(timeout_seconds, 1), MAX_TIMEOUT),
                    int(config["delay_seconds"]) + 3600,
                )
            else:
                timeout_seconds = max(1, min(timeout_seconds, MAX_TIMEOUT))
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
        return {
            "id": job_id,
            "type": job_type,
            "status": "active",
            "config": stored_config,
            "target_name": target_name,
            "target_scope": target_scope,
            "timeout_seconds": timeout_seconds,
            "expires_at": expires_at,
            "trigger_at": trigger_at,
        }

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
        elif job_type == "run" and (config.get("_process") or {}).get("rc"):
            coro = self._adopt_run(job_id, config["_process"], message, target_name,
                                   target_scope, timeout,
                                   success_file=config.get("success_file"),
                                   success_pattern=config.get("success_pattern", ""))
        elif job_type == "run":
            host = config.get("host")
            coro = self._run_exec(job_id, config["command"], message, target_name,
                                  target_scope, timeout, host=host,
                                  cwd=config.get("cwd"),
                                  success_file=config.get("success_file"),
                                  success_pattern=config.get("success_pattern", ""),
                                  agent_workload=bool(config.get("agent_workload")))
        elif job_type == "merge":
            coro = self._run_merge_watch(job_id, config["operation_id"], message,
                                         target_name, target_scope, timeout)
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
        row = bg_get_job(job_id) or {}
        ok = bg_cancel_job(job_id)
        if not ok:
            return {"error": "job not found or not active"}
        task = self._tasks.pop(job_id, None)
        if task and not task.done():
            task.cancel()
        proc = self._procs.pop(job_id, None)
        if proc:
            await _kill_proc(proc)
        if row.get("type") == "run":
            await self._interrupt_run_notify(
                job_id, row.get("message") or "Background run", row.get("target_name") or "?",
                row.get("target_scope") or "",
                reason="Отменён вызывающим агентом; повторный запуск не выполнялся.",
                output=row.get("last_output") or "",
            )
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
            row = next((job for job in active if job["id"] == jid), {})
            if row.get("type") == "run":
                await self._report_undelivered_job(
                    jid, row.get("target_name") or "?", row.get("target_scope") or "",
                    "target session stopped while its run job was active",
                )
        if cancelled_count:
            logger.info(f"bg_jobs: cancelled {cancelled_count} jobs for session {session_id}")

    async def restore_from_db(self) -> None:
        legacy_idle = bg_cancel_removed_idle()
        if legacy_idle:
            logger.info("bg_jobs: cancelled %s legacy idle watches (type removed)", legacy_idle)
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
            row = bg_get_job(jid)
            if row and row.get("type") != "run":
                await self._job_ended(jid, "expired")
            if row and row.get("type") == "run":
                process = json.loads(row["config"]).get("_process")
                await _reap_orphan_run(process)
                _unlink_run_files(process)
                timeout = max(
                    1,
                    (datetime.fromisoformat(row["expires_at"])
                     - datetime.fromisoformat(row["created_at"])).total_seconds(),
                )
                await self._expire_notify(
                    jid, row["message"], row["target_name"], row["target_scope"],
                    timeout, row.get("last_output") or "",
                )
        reset_ids = bg_reset_stale_triggering()
        if reset_ids:
            logger.info(f"bg_jobs: reset {len(reset_ids)} stale triggering jobs")
        interrupted_delivery = set(reset_ids)
        active = bg_get_active_all()
        restored = 0
        for row in active:
            if row["id"] in self._tasks:
                continue
            if row["status"] != "active":
                continue
            config = json.loads(row["config"])
            if row["type"] == "run" and (config.get("_process") or {}).get("rc"):
                if row["id"] in interrupted_delivery:
                    await self._trigger(
                        row["id"], row["message"], row["target_name"],
                        row["target_scope"], row["last_output"],
                    )
                    _unlink_run_files(config["_process"])
                    continue
                # Fall through to _start_task: it adopts the surviving process (V-919).
            elif row["type"] == "run":
                if row["id"] in interrupted_delivery:
                    # 'triggering' у run значит, что команда УЖЕ вышла и рестарт убил
                    # ДОСТАВКУ её результата: «повторный запуск не выполнялся» здесь ложь,
                    # а результат лежит в строке. Досылаем его штатным путём триггера.
                    await self._trigger(
                        row["id"], row["message"], row["target_name"],
                        row["target_scope"], row["last_output"],
                    )
                    continue
                fate = await _reap_orphan_run(config.get("_process"))
                await self._interrupt_run_notify(
                    row["id"], row["message"], row["target_name"], row["target_scope"],
                    reason=f"Прерван рестартом сервиса, повторный запуск не выполнялся; {fate}.",
                )
                continue
            remaining = (datetime.fromisoformat(row["expires_at"]) - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                bg_expire_job(row["id"])
                await self._job_ended(row["id"], "expired")
                continue
            self._start_task(
                row["id"], row["type"], config, row["message"],
                row["target_session_id"], row["target_name"], row["target_scope"],
                remaining, trigger_at=row.get("trigger_at"),
            )
            restored += 1
        logger.info(f"bg_jobs: restored {restored} jobs, expired {len(expired_ids)}")

    async def shutdown(self) -> None:
        self._shutting_down = True
        for jid, task in list(self._tasks.items()):
            task.cancel()
        for jid, proc in list(self._procs.items()):
            if getattr(proc, "_orchestra_survives_restart", False):
                continue
            try:
                await _kill_proc(proc)
            except Exception as e:
                logger.error(
                    "bg_job %s: shutdown process kill failed (%s): %s",
                    jid, type(e).__name__, e,
                )
        self._tasks.clear()
        self._procs.clear()

    def has_active_jobs(self, session_id: str) -> bool:
        return bool(jobs_holding_waiting(session_id))

    # ── Trigger ──

    @staticmethod
    def _restore_report_provenance(session) -> None:
        if not session.last_task_sender and session.parent_name:
            session.last_task_sender = session.parent_name

    @staticmethod
    def _terminal_message(job_id: str, outcome: str, text: str) -> InjectedMessage:
        return InjectedMessage(
            text=text,
            provenance=MessageProvenance(
                origin="background_task",
                senders=(job_id,),
                subtype=outcome,
                ref=job_id,
            ),
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

    async def _notify_job_target(
        self, job_id: str, outcome: str, body: str,
        target_name: str, target_scope: str,
    ) -> str | None:
        try:
            session, failure = await self._load_job_target(job_id, target_name)
            if not session:
                raise RuntimeError(failure or "target session not found")
            self._restore_report_provenance(session)
            injected = self._terminal_message(job_id, outcome, body)
            await self._session_manager.send(
                session.id, injected, provenance=injected.provenance,
            )
            return None
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"
            logger.error("bg_job %s: %s notification failed: %s", job_id, outcome, reason)
            await self._report_undelivered_job(
                job_id, target_name, target_scope, reason,
            )
            return reason

    async def _report_undelivered_job(
        self, job_id: str, target_name: str, target_scope: str, reason: str,
    ) -> None:
        from app.notify import report_undelivered

        try:
            await report_undelivered(
                self._session_manager,
                scope=target_scope,
                worker=target_name,
                what=f"result of background job {job_id}",
                reason=reason,
                dedupe_key=f"bgjob:{job_id}",
            )
        except Exception as fallback_error:
            logger.error(
                "bg_job %s: undelivered report failed (%s): %s",
                job_id, type(fallback_error).__name__, fallback_error,
            )

    async def _trigger(self, job_id: str, message: str,
                       target_name: str, target_scope: str, output: str = "") -> None:
        claimed = bg_claim_trigger(job_id)
        if not claimed:
            return
        body = f"[Background job completed] {message}"
        if output:
            body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
        failure = await self._notify_job_target(
            job_id, "completed", body, target_name, target_scope,
        )
        if failure is None:
            bg_finish_trigger(job_id, output)
            logger.info(f"bg_job {job_id}: triggered → {target_name}")
        else:
            bg_fail_job(job_id, failure)

    def _expire(self, job_id: str) -> None:
        bg_expire_job(job_id)
        self._procs.pop(job_id, None)

    async def _expire_settle(self, job_id: str) -> None:
        self._expire(job_id)
        await self._job_ended(job_id, "expired")

    async def _fail_settle(self, job_id: str, error: str) -> None:
        self._fail_if_active(job_id, error)
        await self._job_ended(job_id, "failed", error)

    async def _job_ended(self, job_id: str, outcome: str, detail: str = "") -> None:
        """A watcher ended without telling its target (V-886).

        The target sits in WAITING only because of active jobs. When the last one ends
        silently nothing would ever move it, so: a cron running out its schedule is the
        normal end and just returns the session to IDLE; an expired/failed watcher wakes
        it with the reason. Another active job keeps the session waiting, untouched.
        """
        try:
            row = bg_get_job(job_id) or {}
            sid = str(row.get("target_session_id") or "")
            stored = get_session(sid) if sid else None
            if not stored or stored.get("status") != AgentStatus.WAITING.value or self.has_active_jobs(sid):
                return
            session = await self._session_manager.ensure_loaded_by_id(sid)
            if session is None or session.status != AgentStatus.WAITING:
                return
            if outcome == "expired" and row.get("type") in ("cron", "cron_command"):
                session._turns.finish_turn_status()
                session._hibernate.schedule()
                return
            reason = (
                "the deadline passed without a match" if outcome == "expired"
                else f"the watcher failed: {detail}"
            )
            body = (
                f"[Background job {outcome.upper()}] {row.get('message', '')}\n"
                f"{reason}. No other background jobs are active, so nothing else will wake you."
            )
            await self._notify_job_target(
                job_id, outcome, body, row.get("target_name", ""), row.get("target_scope", ""),
            )
        except Exception as error:
            logger.warning("bg_job %s: settling target failed: %s: %s",
                           job_id, type(error).__name__, error)

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
        body = f"[Background job TIMED OUT] {err}"
        if output:
            body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
        failure = await self._notify_job_target(
            job_id, "timed_out", body, target_name, target_scope,
        )
        if failure is None:
            logger.warning(f"bg_job {job_id}: TIMED OUT after {dur} → notified {target_name}")

    async def _fail_notify(self, job_id, message, target_name, target_scope,
                           error, output=""):
        """Persist a failed run and wake the waiting agent with an explicit failure."""
        bg_fail_job(job_id, error)
        body = f"[Background job FAILED] {message}\n{error}"
        if output:
            body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
        failure = await self._notify_job_target(
            job_id, "failed", body, target_name, target_scope,
        )
        if failure is None:
            logger.warning(f"bg_job {job_id}: FAILED → notified {target_name}: {error}")

    async def _interrupt_run_notify(
        self, job_id, message, target_name, target_scope,
        reason="Прерван рестартом сервиса, повторный запуск не выполнялся.",
        output="",
    ):
        bg_fail_job(job_id, reason)
        body = f"[Background job INTERRUPTED] {message}\n{reason}"
        if output:
            body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
        failure = await self._notify_job_target(
            job_id, "interrupted", body, target_name, target_scope,
        )
        if failure is None:
            logger.warning(
                "bg_job %s: interrupted → notified %s",
                job_id, target_name,
            )

    def _fail_if_active(self, job_id: str, error: str) -> None:
        bg_fail_job_if_active(job_id, error)

    # ── Runners ──

    async def _run_merge_watch(self, job_id, operation_id, message,
                               target_name, target_scope, timeout):
        """Observe a durable operation without occupying an agent/tool call.

        The existing job row pins the recipient and resumes observation after restart.
        This watcher never starts or retries a merge.
        """
        from app.merge_operations import get_operation_record

        try:
            async with asyncio.timeout(timeout):
                while True:
                    record = await asyncio.to_thread(get_operation_record, operation_id)
                    if not record or record["scope"] != target_scope:
                        raise ValueError("merge operation disappeared from target scope")
                    result = record["result"]
                    state = result["operation_state"]
                    if state not in {"PENDING", "RUNNING"} or result.get("error"):
                        # A nonterminal blocker also needs attention: sleeping until a
                        # terminal state would deadlock an operation needing caller action.
                        # Keep recovery last, since _trigger delivers the last 3000 chars.
                        output = json.dumps({
                            "operation_id": operation_id, "operation_state": state,
                            "git": result.get("git"),
                            "error": result.get("error"), "next_action": result.get("next_action"),
                        }, ensure_ascii=False)
                        bg_update_output(job_id, output)
                        await self._trigger(
                            job_id, f"Merge operation {operation_id}: {state}. {message}\n"
                            "Inspect the state and any blocker before further work; "
                            "do not start a duplicate merge.",
                            target_name, target_scope, output,
                        )
                        return
                    await asyncio.sleep(2)
        except asyncio.TimeoutError:
            await self._expire_notify(job_id, message, target_name, target_scope, timeout,
                                      f"Merge {operation_id} may still be running; check the same operation.")
        except Exception as exc:
            await self._fail_notify(job_id, message, target_name, target_scope, str(exc))

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
            await self._expire_settle(job_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            bg_fail_job(job_id, str(e)[:500])
            await self._job_ended(job_id, "failed", str(e)[:500])

    async def _fire_cron(self, job_id, message, target_name, target_scope):
        if not bg_cron_should_fire(job_id):
            return
        try:
            session, _failure = await self._load_job_target(job_id, target_name)
            if not session:
                # Расписание живёт дальше: цель могла быть выгружена временно.
                return
            provenance = MessageProvenance(
                origin="background_task", senders=(job_id,),
                subtype="cron", ref=job_id,
            )
            await self._session_manager.send(
                session.id, f"[Cron job fired] {message}",
                provenance=provenance,
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
            proc = await self._spawn_managed_process(
                job_id, command,
                shell=True,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._procs[job_id] = proc
            try:
                stdout, stderr = await _communicate_cron_command(proc)
            except asyncio.TimeoutError:
                previous = bg_get_job(job_id) or {}
                already_notified = str(previous.get("last_output") or "").startswith(
                    "[command timed out after "
                )
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
                if not already_notified and bg_cron_should_fire(job_id):
                    session, _failure = await self._load_job_target(job_id, target_name)
                    if session:
                        self._restore_report_provenance(session)
                        body = (
                            f"[Cron command timed out] bg job {job_id}; command: {command}; "
                            f"limit: {_CRON_COMMAND_TIMEOUT_SECONDS} seconds. "
                            "The command was stopped. Check its runtime/output and adjust "
                            "the command or schedule before the next run."
                        )
                        provenance = MessageProvenance(
                            origin="background_task", senders=(job_id,),
                            subtype="cron_command_timeout", ref=job_id,
                        )
                        await self._session_manager.send(
                            session.id, body, provenance=provenance,
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
            provenance = MessageProvenance(
                origin="background_task", senders=(job_id,),
                subtype="cron_command", ref=job_id,
            )
            await self._session_manager.send(
                session.id, body, provenance=provenance,
            )
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
            proc = await self._spawn_managed_process(
                job_id, ["tail", "-F", "-n", "0", path],
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
            await self._fail_settle(job_id, "tail exited without match")
        except asyncio.TimeoutError:
            await self._expire_settle(job_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await self._fail_settle(job_id, str(e)[:500])
        finally:
            self._procs.pop(job_id, None)
            if proc:
                await _kill_proc(proc)

    async def _run_command_watch(self, job_id, command, pattern, interval,
                                 message, target_name, target_scope, timeout):
        deadline = (time.time() + timeout) if timeout is not None else None
        try:
            while deadline is None or time.time() < deadline:
                proc = await self._spawn_managed_process(
                    job_id, command, shell=True,
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
                    await _kill_proc(proc)
                output = stdout.decode(errors="replace") + stderr.decode(errors="replace")
                if re.search(pattern, output):
                    await self._trigger(job_id, message, target_name, target_scope, output.strip())
                    return
                await asyncio.sleep(interval)
            if deadline is not None:
                await self._expire_settle(job_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            bg_fail_job(job_id, str(e)[:500])
            await self._job_ended(job_id, "failed", str(e)[:500])

    async def _run_ssh_watch(self, job_id, host, command, pattern, message,
                              target_name, target_scope, timeout):
        proc = None
        try:
            proc = await self._spawn_managed_process(
                job_id, ["ssh", *_SSH_OPTS, host, command],
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
            await self._fail_settle(job_id, "ssh exited without match")
        except asyncio.TimeoutError:
            await self._expire_settle(job_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await self._fail_settle(job_id, str(e)[:500])
        finally:
            self._procs.pop(job_id, None)
            if proc:
                await _kill_proc(proc)

    async def _run_exec(self, job_id, command, message, target_name,
                        target_scope, timeout, host=None, success_file=None,
                        success_pattern="", cwd=None, agent_workload=False):
        proc = None
        out_path, rc_path = _run_files(job_id)
        process = {"out": str(out_path), "rc": str(rc_path)}
        detached = False
        try:
            inner = ["ssh", *_SSH_OPTS, host, command] if host else ["/bin/sh", "-c", command]
            out_path.parent.mkdir(parents=True, exist_ok=True)
            rc_path.unlink(missing_ok=True)
            with open(out_path, "wb") as out:
                proc = await self._spawn_managed_process(
                    job_id,
                    ["/bin/sh", "-c", _RUN_WRAPPER, "orchestra-run", str(rc_path), *inner],
                    shell=False,
                    agent_workload=agent_workload,
                    stdout=out, stderr=asyncio.subprocess.STDOUT,
                    cwd=None if host else cwd,
                )
            proc._orchestra_survives_restart = True
            self._procs[job_id] = proc
            process.update(pid=proc.pid, start=_process_start_ticks(proc.pid))
            bg_record_process(job_id, process)
            where = host or "local"
            logger.info(f"bg_job {job_id}: run started pid={proc.pid} on={where} "
                        f"timeout={timeout}s cmd_len={len(command)}")

            async with asyncio.timeout(timeout):
                await self._wait_run(
                    job_id, lambda: proc.returncode is not None, out_path, _PIDFD_POLL_INTERVAL,
                )
                orphan_count, oldest_age = await asyncio.to_thread(
                    _orphan_session_stats, proc.pid,
                )
                if orphan_count:
                    logger.warning(
                        "bg_job %s: orphan_tree=1 session=%s processes=%s "
                        "oldest_process_age_seconds=%.1f observation_only=true",
                        job_id, proc.pid, orphan_count, oldest_age,
                    )
            logger.info(f"bg_job {job_id}: run done pid={proc.pid} exit={proc.returncode}")
            await self._finish_run(
                job_id, proc.returncode, _read_run_tail(out_path), message,
                target_name, target_scope, success_file, success_pattern,
            )
        except asyncio.TimeoutError:
            kill_error = ""
            if proc:
                try:
                    await _kill_proc(proc)
                except Exception as error:
                    kill_error = f"; process kill failed: {type(error).__name__}: {error}"
            output = _read_run_tail(out_path)
            if kill_error:
                output += f"\n{kill_error}"
            await self._expire_notify(
                job_id, message, target_name, target_scope, timeout,
                output,
            )
            if kill_error:
                logger.error("bg_job %s: %s", job_id, kill_error.lstrip("; "))
        except asyncio.CancelledError:
            # Shutdown leaves the command running for the next generation to adopt;
            # bg_cancel and session stop still kill it below.
            detached = bool(self._shutting_down and proc and proc.returncode is None)
        except Exception as e:
            await self._fail_notify(
                job_id, message, target_name, target_scope,
                f"{type(e).__name__}: {e}", _read_run_tail(out_path),
            )
        finally:
            self._procs.pop(job_id, None)
            if proc and not detached:
                await _kill_proc(proc)
                transport = getattr(proc, "_transport", None)
                if proc.returncode is not None and transport:
                    transport.close()
            if detached:
                logger.info(f"bg_job {job_id}: left running across shutdown pid={proc.pid}")
            else:
                _unlink_run_files(process)

    async def _adopt_run(self, job_id, process, message, target_name, target_scope,
                         timeout, success_file=None, success_pattern=""):
        """Finish a run job whose process a previous Orchestra generation started (V-919)."""
        out_path, rc_path = Path(process["out"]), Path(process["rc"])
        detached = False
        try:
            logger.info(f"bg_job {job_id}: adopting run pid={process.get('pid')}")
            async with asyncio.timeout(timeout):
                await self._wait_run(
                    job_id, lambda: not _run_leader_alive(process), out_path,
                    _ADOPT_POLL_INTERVAL,
                )
            exit_code = _read_run_rc(rc_path)
            output = _read_run_tail(out_path)
            if exit_code is None:
                await self._interrupt_run_notify(
                    job_id, message, target_name, target_scope,
                    reason="Процесс завершился во время рестарта, не записав код выхода "
                           "(убит извне); повторный запуск не выполнялся.",
                    output=output,
                )
                return
            await self._finish_run(
                job_id, exit_code, output, message, target_name, target_scope,
                success_file, success_pattern,
            )
        except asyncio.TimeoutError:
            await _reap_orphan_run(process)
            await self._expire_notify(
                job_id, message, target_name, target_scope, timeout, _read_run_tail(out_path),
            )
        except asyncio.CancelledError:
            detached = self._shutting_down
        except Exception as e:
            await self._fail_notify(
                job_id, message, target_name, target_scope,
                f"{type(e).__name__}: {e}", _read_run_tail(out_path),
            )
        finally:
            if not detached:
                await _reap_orphan_run(process)
                _unlink_run_files(process)

    async def _wait_run(self, job_id, finished, out_path: Path, interval: float) -> None:
        last_progress = time.time()
        while not finished():
            await asyncio.sleep(interval)
            now = time.time()
            if now - last_progress > OUTPUT_PROGRESS_INTERVAL:
                bg_update_output(job_id, _read_run_tail(out_path))
                last_progress = now

    async def _finish_run(self, job_id, exit_code, full_output, message, target_name,
                          target_scope, success_file, success_pattern) -> None:
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

bg_manager = BgJobManager()
