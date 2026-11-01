"""Job states and the allowed transitions between them."""
from enum import Enum


class JobState(str, Enum):
    """The lifecycle state of a job."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.PENDING: frozenset({JobState.RUNNING}),
    JobState.RUNNING: frozenset({JobState.DONE, JobState.FAILED, JobState.PENDING}),
    JobState.DONE: frozenset(),
    JobState.FAILED: frozenset(),
}


def can_transition(current: JobState, target: JobState) -> bool:
    """Return True if a job may move from current to target."""
    return target in ALLOWED_TRANSITIONS[current]


def check_transition(current: JobState, target: JobState) -> None:
    """Raise ValueError if a job may not move from current to target."""
    if not can_transition(current, target):
        raise ValueError(
            "cannot move job from {} to {}".format(current.value, target.value)
        )


def is_final(state: JobState) -> bool:
    """Return True for states that a job never leaves."""
    return not ALLOWED_TRANSITIONS[state]
