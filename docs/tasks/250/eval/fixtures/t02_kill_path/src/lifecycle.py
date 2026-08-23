from dataclasses import dataclass


class Barrier:
    def __init__(self):
        self.tokens: list[tuple[str, str]] = []

    def record(self, child: str, outcome: str) -> None:
        self.tokens.append((child, outcome))

    def on_child_killed(self, child: str) -> None:
        self.record(child, "killed")


@dataclass
class Session:
    name: str
    archived: bool = False


class SessionManager:
    def __init__(self, sessions: list[Session], barrier: Barrier):
        self.sessions = {session.name: session for session in sessions}
        self.barrier = barrier

    def remove(self, name: str) -> bool:
        session = self.sessions.get(name)
        if session is None:
            return False
        self.barrier.on_child_killed(name)
        session.archived = True
        return True


def default_manager() -> tuple[SessionManager, Barrier]:
    barrier = Barrier()
    return SessionManager([Session("worker-1")], barrier), barrier

