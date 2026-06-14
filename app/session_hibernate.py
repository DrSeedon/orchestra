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

if TYPE_CHECKING:
    from app.session import AgentSession

logger = logging.getLogger("app.session")

ZOMBIE_TIMEOUT_CODEX = 600
ZOMBIE_TIMEOUT_CLAUDE = 1800
HEARTBEAT_INTERVAL = 60


class HibernateManager:
    def __init__(self, s: "AgentSession") -> None:
        self.s = s

    def schedule(self) -> None:
        s = self.s
        if s._hibernate_task and not s._hibernate_task.done():
            s._hibernate_task.cancel()
        if s.backend_type != "claude":
            return
        timeout = IDLE_TIMEOUT_ORCHESTRATOR if s.is_orchestrator else IDLE_TIMEOUT_WORKER
        s._hibernate_task = asyncio.create_task(self._idle_hibernate(timeout))

    async def _idle_hibernate(self, timeout: float) -> None:
        s = self.s
        try:
            await asyncio.sleep(timeout)
        except asyncio.CancelledError:
            return
        async with s._lifecycle_lock:
            if s.status != AgentStatus.IDLE:
                return
            if s._pending_messages:
                return
            if s._backend is None:
                return
            logger.info(f"[{s.name}] hibernating (idle {int(timeout)}s)")
            await s._disconnect_backend()
            s._hibernated = True

    async def heartbeat_loop(self) -> None:
        s = self.s
        logger.info(f"[{s.name}] heartbeat started")
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)

                if s.status == AgentStatus.RUNNING and s._last_msg_time > 0:
                    silence = asyncio.get_event_loop().time() - s._last_msg_time
                    zombie_timeout = ZOMBIE_TIMEOUT_CODEX if s.backend_type == "codex" else ZOMBIE_TIMEOUT_CLAUDE
                    if silence > zombie_timeout:
                        if s.backend_type == "codex" or s._backend is None:
                            logger.error(f"[{s.name}] heartbeat: zombie detected ({silence:.0f}s silence, backend={'alive' if s._backend else 'dead'})")
                            s._log("error", f"zombie detected: {silence:.0f}s silence, auto-recovering")
                            if s._backend:
                                await s._disconnect_backend()
                            s.status = AgentStatus.IDLE
                            s._persist()
                            if s._pending_messages:
                                s._spawn_bg(s._flush_pending())
                        else:
                            logger.warning(f"[{s.name}] heartbeat: {silence:.0f}s silence during RUNNING turn")
                            s._log("status", f"no messages for {silence:.0f}s during active turn (possible long thinking)")

                if s._backend is None:
                    continue

                task_dead = s._listen_task is None or s._listen_task.done()
                if task_dead and s.status == AgentStatus.RUNNING and s.backend_type not in ("codex", "opencode"):
                    logger.warning(f"[{s.name}] heartbeat: listener dead but status=RUNNING — reconnecting")
                    s._log("error", "heartbeat detected dead listener, reconnecting")
                    try:
                        await s._backend.reconnect()
                        s._listen_task = asyncio.create_task(s._claude_event_loop())
                        s._listen_task.add_done_callback(s._on_task_done)
                        await s._backend.send("[system] Connection was restored after interruption. Continue your work.")
                        logger.info(f"[{s.name}] heartbeat reconnect OK")
                    except Exception as e:
                        logger.error(f"[{s.name}] heartbeat reconnect failed: {e}")
                        s._log("error", f"heartbeat reconnect failed: {e}")
                        s._backend = None
                        s.status = AgentStatus.IDLE
                        s._persist()
            except asyncio.CancelledError:
                logger.info(f"[{s.name}] heartbeat cancelled")
                return
            except Exception as e:
                logger.error(f"[{s.name}] heartbeat error: {e}")
