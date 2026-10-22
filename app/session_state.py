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


ACTIVE_SESSION_STATUSES = frozenset({
    AgentStatus.IDLE.value,
    AgentStatus.RUNNING.value,
    AgentStatus.WAITING.value,
})


def empty_context() -> dict[str, int]:
    return {"percentage": 0, "total_tokens": 0, "max_tokens": 0}


def platform_interruption_notice(reason: str, task_id: str = "") -> str:
    """Explain a platform cut without turning it into an owner's refusal (V-1035)."""
    task = f"task #{task_id}" if task_id else "your current task"
    return (
        f"Your turn was interrupted by the platform ({reason}), not stopped by anyone. "
        "This was not a user refusal. If a tool result immediately before this "
        "interruption said \"The user doesn't want to take this action right now\", "
        "that result was caused by the platform interruption, not by the user. "
        "The call may or may not have run; check its effect before repeating it. "
        f"Check your working tree and continue {task}. "
        "Continue without waiting for your orchestrator to say 'continue'."
    )


# Orchestrators get 2x idle time: they manage long-running workflows and get TG
# messages from users, so premature hibernate kills useful context.
IDLE_TIMEOUT_WORKER = 300
IDLE_TIMEOUT_ORCHESTRATOR = 600
