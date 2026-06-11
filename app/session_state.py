"""Session state primitives — leaf shared by AgentSession and its systems.

Lives outside session.py so session_cost/session_turns/session_hibernate can
import status/timeouts without importing the session module (no cycles).
"""

from enum import Enum


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"


# Orchestrators get 2x idle time: they manage long-running workflows and get TG
# messages from users, so premature hibernate kills useful context.
IDLE_TIMEOUT_WORKER = 300
IDLE_TIMEOUT_ORCHESTRATOR = 600
