"""Session state primitives — leaf shared by AgentSession and its systems.

Lives outside session.py so session_cost/session_turns/session_hibernate can
import status/timeouts without importing the session module (no cycles).
"""

from enum import Enum


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    # Ход оборван выключением сервера, а не завершён. Живёт в БД от stop() на
    # shutdown до auto_resume_all, который по нему решает кого будить, и тут же
    # нормализует в idle. Без него graceful-рестарт писал 'idle' поверх 'running'
    # и стирал сам факт прерванности — будить было некого (#160).
    INTERRUPTED = "interrupted"


# Orchestrators get 2x idle time: they manage long-running workflows and get TG
# messages from users, so premature hibernate kills useful context.
IDLE_TIMEOUT_WORKER = 300
IDLE_TIMEOUT_ORCHESTRATOR = 600
