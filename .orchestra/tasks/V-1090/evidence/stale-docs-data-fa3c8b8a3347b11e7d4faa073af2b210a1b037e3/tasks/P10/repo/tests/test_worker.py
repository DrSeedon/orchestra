import pytest

from jobqueue.queue import JobQueue
from jobqueue.states import JobState
from jobqueue.worker import run_all, run_next


def double(payload):
    return payload["n"] * 2


def explode(payload):
    raise RuntimeError("bad payload")


def test_run_next_completes_job():
    queue = JobQueue()
    job = queue.submit("double", {"n": 21})
    assert run_next(queue, {"double": double}) is job
    assert job.state == JobState.DONE
    assert job.result == 42


def test_run_next_with_empty_queue():
    assert run_next(JobQueue(), {}) is None


def test_failing_handler_is_recorded():
    queue = JobQueue()
    job = queue.submit("explode", max_attempts=1)
    run_next(queue, {"explode": explode})
    assert job.state == JobState.FAILED
    assert job.error == "RuntimeError: bad payload"


def test_missing_handler():
    queue = JobQueue()
    queue.submit("unknown")
    with pytest.raises(LookupError):
        run_next(queue, {})


def test_run_all_retries_until_failed():
    queue = JobQueue()
    queue.submit("double", {"n": 1})
    queue.submit("explode", max_attempts=2)
    runs = run_all(queue, {"double": double, "explode": explode})
    assert runs == 3
    assert [job.state for job in queue.jobs()] == [JobState.DONE, JobState.FAILED]


def test_run_all_limit():
    queue = JobQueue()
    for _ in range(5):
        queue.submit("double", {"n": 1})
    assert run_all(queue, {"double": double}, limit=2) == 2
