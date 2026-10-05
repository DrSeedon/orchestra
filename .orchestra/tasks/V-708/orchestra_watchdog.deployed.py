"""Bounded recovery for the Orchestra instance on this VPS."""

import asyncio
import json
import logging
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from config import NOTIFY_CHAT, WORK_DIR

logger = logging.getLogger("kesha.orchestra_watchdog")

POLL_SECONDS = 20
FAILURES_BEFORE_RECOVERY = 3
HEALTHY_CHECKS_BEFORE_RECOVERY_NOTICE = 3
MAX_START_ATTEMPTS = 3
STARTUP_WAIT_SECONDS = 90
HEALTH_TIMEOUT_SECONDS = 5
HEALTH_URL = "http://127.0.0.1:8888/login"
STATE_FILE = Path(WORK_DIR) / "storage" / "orchestra_watchdog.json"

_SENSITIVE = re.compile(
    r"(?i)(bearer\s+\S+|(?:token|secret|password|api[_-]?key)=\S+|sk-[A-Za-z0-9_-]{12,})"
)


def _health_request() -> bool:
    request = urllib.request.Request(HEALTH_URL, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=HEALTH_TIMEOUT_SECONDS) as response:
            return response.status < 500
    except urllib.error.HTTPError as exc:
        return exc.code < 500
    except Exception:
        return False


def _clean_reason(value: str) -> str:
    lines = [" ".join(line.split()) for line in value.splitlines() if line.strip()]
    text = _SENSITIVE.sub("[скрыто]", lines[-1] if lines else "нет записи об ошибке")
    return text[:400]


class OrchestraWatchdog:
    def __init__(self, bot, chat_id=NOTIFY_CHAT, state_file=STATE_FILE):
        self.bot = bot
        self.chat_id = chat_id
        self.state_file = Path(state_file)
        self.state = self._load_state()

    def _load_state(self):
        try:
            state = json.loads(self.state_file.read_text())
            if isinstance(state, dict) and isinstance(state.get("failures"), int):
                return state
        except (OSError, ValueError):
            pass
        return {"failures": 0, "healthy_checks": 0, "incident": None}

    def _save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_file.with_suffix(".tmp")
        temp.write_text(json.dumps(self.state, ensure_ascii=False))
        os.replace(temp, self.state_file)

    async def _command(self, *args, timeout=10):
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return 124, "", f"timed out: {' '.join(args)}"
        return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")

    async def _probe(self):
        code, output, error = await self._command(
            "systemctl", "show", "orchestra", "-p", "ActiveState", "-p", "SubState", timeout=5
        )
        fields = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        health = await asyncio.to_thread(_health_request)
        if code:
            return {"active": False, "serving": health, "state": "unknown/unknown", "health": health,
                    "detail": _clean_reason(error or output)}
        active_state = fields.get("ActiveState", "unknown")
        sub_state = fields.get("SubState", "unknown")
        return {
            "active": active_state == "active" and sub_state == "running" and health,
            "serving": health,
            "state": f"{active_state}/{sub_state}",
            "health": health,
            "detail": "",
        }

    async def _journal_reason(self):
        code, output, error = await self._command(
            "sudo", "-n", "journalctl", "-u", "orchestra", "--since=-10min",
            "-n", "30", "-o", "cat", "--no-pager", timeout=8,
        )
        if code or not output.strip():
            return _clean_reason(error or output)
        lines = [line for line in output.splitlines() if line.strip()]
        relevant = [line for line in lines if re.search(
            r"(?i)(error|exception|traceback|failed|killed|oom|signal|timeout)", line
        )]
        return _clean_reason((relevant or lines)[-1])

    async def _start_or_restart(self, probe):
        if probe["serving"] or await asyncio.to_thread(_health_request):
            return None, "health endpoint responded before recovery action"
        if probe["state"] == "failed/failed":
            code, _out, err = await self._command(
                "sudo", "-n", "systemctl", "reset-failed", "orchestra", timeout=10
            )
            if code:
                return False, _clean_reason(err)
            action = "start"
        else:
            action = "restart"
        code, _out, err = await self._command(
            "sudo", "-n", "systemctl", action, "--no-block", "orchestra", timeout=10
        )
        return code == 0, _clean_reason(err)

    async def _wait_for_healthy(self):
        deadline = asyncio.get_running_loop().time() + STARTUP_WAIT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(5)
            if (await self._probe())["active"]:
                return True
        return False

    async def _notify_once(self, incident, key, message):
        if incident.get(key):
            return
        incident[key] = True
        self._save_state()
        if not self.chat_id:
            logger.error("NOTIFY_CHAT is empty; skipped Orchestra incident notification")
            return
        try:
            await self.bot.send_message(self.chat_id, message, parse_mode=None)
        except Exception:
            logger.exception("Could not send Orchestra watchdog notification")

    async def _recover(self):
        incident = self.state["incident"]
        recovered = False
        last_error = ""
        while incident["attempts"] < MAX_START_ATTEMPTS:
            probe = await self._probe()
            if probe["active"]:
                recovered = True
                break
            if probe["serving"]:
                return
            if probe["state"] not in {"failed/failed", "active/running"}:
                return
            incident["attempts"] += 1
            self._save_state()
            action_ok, error = await self._start_or_restart(probe)
            if error:
                last_error = error
            if action_ok is None:
                incident["attempts"] -= 1
                self._save_state()
                return
            if action_ok and await self._wait_for_healthy():
                recovered = True
                break
        if not recovered:
            probe = await self._probe()
            if probe["serving"] or probe["state"] not in {"failed/failed", "active/running"}:
                return
            last_error = await self._journal_reason() or last_error or "health не отвечает"
        incident["exhausted"] = not recovered
        result = "поднял" if recovered else f"не поднял за {incident['attempts']} попытки"
        cause = incident["cause"]
        reason = f" Последняя ошибка: {last_error}." if last_error and not recovered else ""
        await self._notify_once(
            incident,
            "announced",
            f"⚠️ Orchestra на VPS упала. Причина в журнале: {cause}. Кеша {result}.{reason}",
        )

    async def check_once(self):
        probe = await self._probe()
        incident = self.state.get("incident")
        if probe["active"]:
            self.state["failures"] = 0
            if incident and incident.get("announced"):
                self.state["healthy_checks"] = self.state.get("healthy_checks", 0) + 1
                if self.state["healthy_checks"] >= HEALTHY_CHECKS_BEFORE_RECOVERY_NOTICE:
                    await self._notify_once(
                        incident,
                        "recovery_announced",
                        "✅ Orchestra на VPS восстановилась: startup complete и health отвечает.",
                    )
                    self.state["incident"] = None
                    self.state["healthy_checks"] = 0
            elif incident:
                self.state["incident"] = None
                self.state["healthy_checks"] = 0
            self._save_state()
            return

        if probe["serving"]:
            self.state["failures"] = 0
            self.state["healthy_checks"] = 0
            if incident and not incident.get("announced"):
                self.state["incident"] = None
            self._save_state()
            return

        if probe["state"] not in {"failed/failed", "active/running"}:
            self.state["failures"] = 0
            self.state["healthy_checks"] = 0
            self._save_state()
            return

        self.state["healthy_checks"] = 0
        if incident:
            if not incident.get("announced") and not incident.get("exhausted"):
                await self._recover()
            return

        self.state["failures"] += 1
        if self.state["failures"] < FAILURES_BEFORE_RECOVERY:
            self._save_state()
            return
        self.state["incident"] = {
            "cause": await self._journal_reason(),
            "attempts": 0,
            "announced": False,
            "recovery_announced": False,
            "exhausted": False,
        }
        self._save_state()
        await self._recover()

    async def run(self):
        while True:
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Orchestra watchdog check failed")
            await asyncio.sleep(POLL_SECONDS)
