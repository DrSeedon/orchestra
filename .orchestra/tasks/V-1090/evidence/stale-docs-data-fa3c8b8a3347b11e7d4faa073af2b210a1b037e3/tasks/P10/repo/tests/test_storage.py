import json

from jobqueue.queue import JobQueue
from jobqueue.states import JobState
from jobqueue.storage import load_queue, save_queue


def test_round_trip(tmp_path):
    queue = JobQueue()
    first = queue.submit("email", {"to": "a@example.com"}, deadline=1700000000.0)
    queue.submit("report", max_attempts=1)
    queue.start(first.id)
    queue.complete(first.id, "sent")
    queue_file = tmp_path / "queue.json"
    save_queue(queue, str(queue_file))

    loaded = load_queue(str(queue_file))
    assert [job.id for job in loaded.jobs()] == ["job-1", "job-2"]
    job = loaded.get("job-1")
    assert job.state == JobState.DONE
    assert job.payload == {"to": "a@example.com"}
    assert job.deadline == 1700000000.0
    assert job.result == "sent"
    assert loaded.get("job-2").max_attempts == 1


def test_loaded_queue_continues_ids(tmp_path):
    queue_file = tmp_path / "queue.json"
    queue_file.write_text(
        json.dumps({"jobs": [{"id": "job-7", "name": "a", "state": "pending"}]}),
        encoding="utf-8",
    )
    queue = load_queue(str(queue_file))
    assert queue.submit("b").id == "job-8"
    assert queue.next_pending().id == "job-7"


def test_file_lists_jobs_in_order(tmp_path):
    queue = JobQueue()
    queue.submit("a")
    queue.submit("b")
    queue_file = tmp_path / "queue.json"
    save_queue(queue, str(queue_file))
    data = json.loads(queue_file.read_text(encoding="utf-8"))
    assert [item["name"] for item in data["jobs"]] == ["a", "b"]
    assert data["jobs"][0]["state"] == "pending"
