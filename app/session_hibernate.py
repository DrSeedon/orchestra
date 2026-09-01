"""HibernateManager — idle timeout, hibernate, zombie heartbeat over AgentSession state.

Stateless method-holder: `_hibernate_task`/`_hibernated`/`_heartbeat_task` stay
on the session (read by send/stop/disconnect paths).
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from app.session_state import (
    AgentStatus, IDLE_TIMEOUT_ORCHESTRATOR, IDLE_TIMEOUT_WORKER,
)
from app.errtext import err_text
from app.runtime_registry import get_runtime

if TYPE_CHECKING:
    from app.session import AgentSession

logger = logging.getLogger("app.session")

CODEX_SILENCE_WARNING = 600
ZOMBIE_TIMEOUT_CLAUDE = 1800
HEARTBEAT_INTERVAL = 60


class HibernateManager:
    def __init__(self, s: "AgentSession") -> None:
        self.s = s
        self._last_codex_silence_warning = 0.0

    @staticmethod
    def _process_runtime_dead(s: "AgentSession") -> bool:
        """Return true only when a process-backed runtime component is gone.

        Silence alone is not proof: Codex may spend a long time reasoning or running a
        tool without producing JSONL events. Process and listener state are observable.
        """
        if s._backend is None:
            return True
        if s._listen_task is None or s._listen_task.done():
            return True
        return getattr(s._backend, "is_alive", None) is False

    def schedule(self) -> None:
        s = self.s
        if s._hibernate_task and not s._hibernate_task.done():
            s._hibernate_task.cancel()
        if not get_runtime(s.backend_type).capabilities.hibernate:
            return
        timeout = IDLE_TIMEOUT_ORCHESTRATOR if s.is_orchestrator else IDLE_TIMEOUT_WORKER
        s._hibernate_task = asyncio.create_task(self._idle_hibernate(timeout))

    async def _idle_hibernate(self, timeout: float) -> None:
        s = self.s
        try:
            await asyncio.sleep(timeout)
        except asyncio.CancelledError:
            return
        try:
            result = await self.hibernate_now()
        except Exception as exc:
            logger.error(f"[{s.name}] automatic hibernate failed: {err_text(exc)}")
            return
        if not result["ok"] and result["reason"] == "unsafe_backend":
            logger.warning(
                f"[{s.name}] automatic hibernate unavailable: {result['error']}"
            )

    async def hibernate_now(self, *, manual: bool = False) -> dict:
        s = self.s
        async with s._lifecycle_lock:
            if s.status != AgentStatus.IDLE:
                return {
                    "ok": False,
                    "reason": "not_idle",
                    "error": f"session is {s.status.value}",
                }
            if s._pending_messages:
                return {
                    "ok": False,
                    "reason": "pending_delivery",
                    "error": f"{len(s._pending_messages)} message(s) pending",
                }
            if s._compacting:
                return {
                    "ok": False,
                    "reason": "compacting",
                    "error": "context compact is in progress",
                }
            if s._backend is None:
                s._hibernated = True
                return {"ok": True, "state": "already_process_free"}
            capabilities = get_runtime(s.backend_type).capabilities
            backend_safe = getattr(s._backend, "hibernate_safe", None)
            if backend_safe is False:
                detail = getattr(
                    s._backend,
                    "hibernate_unavailable_reason",
                    "backend has no verified process owner",
                )
                return {
                    "ok": False,
                    "reason": "unsafe_backend",
                    "error": detail,
                }
            if not capabilities.hibernate and not (manual and backend_safe is True):
                return {
                    "ok": False,
                    "reason": "unsupported_runtime",
                    "error": f"{s.backend_type} does not support hibernation",
                }
            logger.info(f"[{s.name}] hibernating")
            await s._disconnect_backend()
            s._hibernated = True
            return {"ok": True, "state": "hibernated"}

    async def heartbeat_loop(self) -> None:
        s = self.s
        logger.info(f"[{s.name}] heartbeat started")
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)

                if s.status == AgentStatus.RUNNING and s._last_msg_time > 0:
                    capabilities = get_runtime(s.backend_type).capabilities
                    now = asyncio.get_event_loop().time()
                    silence = now - s._last_msg_time
                    zombie_timeout = (
                        CODEX_SILENCE_WARNING
                        if capabilities.process_liveness
                        else ZOMBIE_TIMEOUT_CLAUDE
                    )
                    if silence > zombie_timeout:
                        if capabilities.process_liveness and self._process_runtime_dead(s):
                            logger.error(f"[{s.name}] heartbeat: dead process runtime detected ({silence:.0f}s silence)")
                            s._log("error", f"zombie detected: {silence:.0f}s silence, auto-recovering")
                            if s._backend:
                                await s._disconnect_backend()
                            s.status = AgentStatus.IDLE
                            s._persist()
                            s._turns.publish_turn_finished()
                            if s._pending_messages:
                                s._spawn_bg(s._flush_pending())
                        elif capabilities.event_stream == "per_turn":
                            # Long quiet turns are valid. Keep them alive and report at
                            # most once per warning interval; manual interrupt remains
                            # available for a genuinely wedged upstream process.
                            if now - self._last_codex_silence_warning >= CODEX_SILENCE_WARNING:
                                logger.warning(
                                    f"[{s.name}] heartbeat: {silence:.0f}s silence, "
                                    "runtime process and listener still alive"
                                )
                                self._last_codex_silence_warning = now
                        elif s._backend is None:
                            logger.error(f"[{s.name}] heartbeat: zombie detected ({silence:.0f}s silence, backend=dead)")
                            s._log("error", f"zombie detected: {silence:.0f}s silence, auto-recovering")
                            s.status = AgentStatus.IDLE
                            s._persist()
                            s._turns.publish_turn_finished()
                            if s._pending_messages:
                                s._spawn_bg(s._flush_pending())
                        else:
                            logger.warning(f"[{s.name}] heartbeat: {silence:.0f}s silence during RUNNING turn")
                            s._log("status", f"no messages for {silence:.0f}s during active turn (possible long thinking)")

                if s._backend is None:
                    continue

                task_dead = s._listen_task is None or s._listen_task.done()
                capabilities = get_runtime(s.backend_type).capabilities
                if task_dead and s.status == AgentStatus.RUNNING and capabilities.reconnect:
                    logger.warning(f"[{s.name}] heartbeat: listener dead but status=RUNNING — reconnecting")
                    s._log("error", "heartbeat detected dead listener, reconnecting")
                    try:
                        await s._reconnect_backend()
                        s._listen_task = asyncio.create_task(s._persistent_event_loop())
                        s._listen_task.add_done_callback(s._on_task_done)
                        await s._backend.send("[system] Connection was restored after interruption. Continue your work.")
                        logger.info(f"[{s.name}] heartbeat reconnect OK")
                    except Exception as e:
                        logger.error(f"[{s.name}] heartbeat reconnect failed: {err_text(e)}")
                        s._log("error", f"heartbeat reconnect failed: {err_text(e)}")
                        s._backend = None
                        s.status = AgentStatus.IDLE
                        s._persist()
                        # Every RUNNING→IDLE publishes: switch/merge park on that event
                        # inside the session lock, and a missed publish holds the lock
                        # until the process restarts.
                        s._turns.publish_turn_finished()
            except asyncio.CancelledError:
                logger.info(f"[{s.name}] heartbeat cancelled")
                return
            except Exception as e:
                logger.error(f"[{s.name}] heartbeat error: {e}")
