"""Saving a queue to a JSON file and loading it back.

A queue file holds one object with a "jobs" list, in submission order:

    {"jobs": [{"id": "job-1", "name": "email", "state": "pending", ...}]}
"""
import json
from typing import Any, Optional

from jobqueue.queue import Job, JobQueue
from jobqueue.states import JobState


def job_to_dict(job: Job) -> dict[str, Any]:
    """Return the JSON-ready fields of one job."""
    return {
        "id": job.id,
        "name": job.name,
        "payload": job.payload,
        "state": job.state.value,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "deadline": job.deadline,
        "error": job.error,
        "result": job.result,
        "created_at": job.created_at,
    }


def job_from_dict(data: dict[str, Any]) -> Job:
    """Build a job from fields read from a queue file."""
    return Job(
        id=data["id"],
        name=data["name"],
        payload=dict(data.get("payload") or {}),
        state=JobState(data.get("state", JobState.PENDING.value)),
        attempts=data.get("attempts", 0),
        max_attempts=data.get("max_attempts", 3),
        deadline=data.get("deadline"),
        error=data.get("error"),
        result=data.get("result"),
        created_at=data.get("created_at", 0.0),
    )


def save_queue(queue: JobQueue, file_name: str) -> None:
    """Write every job of a queue to a JSON file."""
    data = {"jobs": [job_to_dict(job) for job in queue.jobs()]}
    with open(file_name, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def load_queue(file_name: str, capacity: Optional[int] = None) -> JobQueue:
    """Read a queue file written by save_queue."""
    with open(file_name, encoding="utf-8") as handle:
        data = json.load(handle)
    queue = JobQueue(capacity=capacity)
    for item in data["jobs"]:
        queue.add(job_from_dict(item))
    return queue
