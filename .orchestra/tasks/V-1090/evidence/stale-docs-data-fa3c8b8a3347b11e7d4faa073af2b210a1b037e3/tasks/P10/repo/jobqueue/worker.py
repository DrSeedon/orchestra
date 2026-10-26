"""Running queued jobs with registered handler functions."""
from typing import Callable, Optional

from jobqueue.queue import Job, JobQueue

Handler = Callable[[dict[str, object]], object]


def run_next(queue: JobQueue, handlers: dict[str, Handler]) -> Optional[Job]:
    """Run the oldest pending job; return it, or None if nothing was pending."""
    job = queue.next_pending()
    if job is None:
        return None
    if job.name not in handlers:
        raise LookupError("no handler for job name {!r}".format(job.name))
    queue.start(job.id)
    try:
        result = handlers[job.name](job.payload)
    except Exception as exc:  # a failing handler must not stop the worker
        return queue.fail(job.id, "{}: {}".format(type(exc).__name__, exc))
    return queue.complete(job.id, result)


def run_all(queue: JobQueue, handlers: dict[str, Handler], limit: Optional[int] = None) -> int:
    """Run pending jobs until none are left or limit runs happened; return the run count."""
    runs = 0
    while limit is None or runs < limit:
        if run_next(queue, handlers) is None:
            break
        runs += 1
    return runs
