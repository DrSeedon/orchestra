"""The job record and the in-memory FIFO queue."""
import time
from dataclasses import dataclass, field
from typing import Optional

from jobqueue.states import JobState, check_transition


@dataclass
class Job:
    """One unit of work and its progress."""

    id: str
    name: str
    payload: dict[str, object] = field(default_factory=dict)
    state: JobState = JobState.PENDING
    attempts: int = 0
    max_attempts: int = 3
    deadline: Optional[float] = None
    error: Optional[str] = None
    result: Optional[object] = None
    created_at: float = field(default_factory=time.time)


class JobQueue:
    """Holds jobs in submission order; pending jobs run first in, first out."""

    def __init__(self, capacity: Optional[int] = None) -> None:
        self._capacity = capacity
        self._jobs: dict[str, Job] = {}
        self._next_id = 1

    def submit(
        self,
        name: str,
        payload: Optional[dict[str, object]] = None,
        max_attempts: int = 3,
        deadline: Optional[float] = None,
    ) -> Job:
        """Add a new pending job and return it."""
        if self._capacity is not None and len(self.jobs(JobState.PENDING)) >= self._capacity:
            raise RuntimeError("queue is full ({} pending jobs)".format(self._capacity))
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        job = Job(
            id="job-{}".format(self._next_id),
            name=name,
            payload=dict(payload or {}),
            max_attempts=max_attempts,
            deadline=deadline,
        )
        self._next_id += 1
        self._jobs[job.id] = job
        return job

    def add(self, job: Job) -> None:
        """Put a job that already has an id into the queue, e.g. one loaded from a file."""
        if job.id in self._jobs:
            raise ValueError("duplicate job id {}".format(job.id))
        self._jobs[job.id] = job
        number = job.id.rpartition("-")[2]
        if number.isdigit():
            self._next_id = max(self._next_id, int(number) + 1)

    def get(self, job_id: str) -> Job:
        """Return a job by id."""
        try:
            return self._jobs[job_id]
        except KeyError:
            raise KeyError("no job with id {}".format(job_id)) from None

    def find(self, job_id: str) -> Optional[Job]:
        """Return a job by id, or None if there is no such job."""
        return self._jobs.get(job_id)

    def jobs(self, state: Optional[JobState] = None) -> list[Job]:
        """Return all jobs in submission order, optionally only those in one state."""
        return [job for job in self._jobs.values() if state is None or job.state == state]

    def next_pending(self) -> Optional[Job]:
        """Return the oldest pending job, or None if nothing is pending."""
        pending = self.jobs(JobState.PENDING)
        return pending[0] if pending else None

    def start(self, job_id: str) -> Job:
        """Move a pending job to running."""
        job = self.get(job_id)
        check_transition(job.state, JobState.RUNNING)
        job.state = JobState.RUNNING
        job.attempts += 1
        return job

    def complete(self, job_id: str, result: Optional[object] = None) -> Job:
        """Mark a running job as done."""
        job = self.get(job_id)
        check_transition(job.state, JobState.DONE)
        job.state = JobState.DONE
        job.result = result
        return job

    def fail(self, job_id: str, error: str) -> Job:
        """Record a failure; the job is retried until it runs out of attempts."""
        job = self.get(job_id)
        target = JobState.PENDING if job.attempts < job.max_attempts else JobState.FAILED
        check_transition(job.state, target)
        job.state = target
        job.error = error
        return job

    def __len__(self) -> int:
        return len(self._jobs)
