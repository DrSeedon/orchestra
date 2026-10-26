import pytest

from jobqueue.queue import Job, JobQueue
from jobqueue.states import JobState


def test_submit_assigns_ids_and_order():
    queue = JobQueue()
    first = queue.submit("email", {"to": "a@example.com"})
    second = queue.submit("email")
    assert (first.id, second.id) == ("job-1", "job-2")
    assert queue.next_pending() is first
    assert len(queue) == 2


def test_capacity():
    queue = JobQueue(capacity=1)
    queue.submit("a")
    with pytest.raises(RuntimeError):
        queue.submit("b")


def test_get_and_find():
    queue = JobQueue()
    job = queue.submit("a")
    assert queue.get(job.id) is job
    assert queue.find("job-99") is None
    with pytest.raises(KeyError):
        queue.get("job-99")


def test_lifecycle_done():
    queue = JobQueue()
    job = queue.submit("a")
    queue.start(job.id)
    queue.complete(job.id, 42)
    assert job.state == JobState.DONE
    assert job.result == 42
    assert queue.next_pending() is None


def test_fail_retries_then_gives_up():
    queue = JobQueue()
    job = queue.submit("a", max_attempts=2)
    queue.start(job.id)
    queue.fail(job.id, "boom")
    assert job.state == JobState.PENDING
    queue.start(job.id)
    queue.fail(job.id, "boom again")
    assert job.state == JobState.FAILED
    assert job.error == "boom again"


def test_invalid_transition():
    queue = JobQueue()
    job = queue.submit("a")
    with pytest.raises(ValueError):
        queue.complete(job.id)


def test_jobs_by_state():
    queue = JobQueue()
    a = queue.submit("a")
    queue.submit("b")
    queue.start(a.id)
    assert [job.name for job in queue.jobs(JobState.PENDING)] == ["b"]
    assert [job.name for job in queue.jobs()] == ["a", "b"]


def test_add_keeps_id_and_continues_numbering():
    queue = JobQueue()
    queue.add(Job(id="job-5", name="a"))
    assert queue.submit("b").id == "job-6"
    with pytest.raises(ValueError):
        queue.add(Job(id="job-5", name="c"))
