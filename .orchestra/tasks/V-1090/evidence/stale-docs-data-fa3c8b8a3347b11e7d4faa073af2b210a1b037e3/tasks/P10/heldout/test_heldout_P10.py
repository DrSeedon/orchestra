import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = "jobqueue.cancel"


def job(number, state="pending", deadline=None):
    return {
        "id": "job-%d" % number,
        "name": "task%d" % number,
        "payload": {"n": number},
        "state": state,
        "attempts": 0 if state == "pending" else 1,
        "max_attempts": 3,
        "deadline": deadline,
        "error": None,
        "result": None,
        "created_at": 1000.0 + number,
    }


def write_queue(path, jobs):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"jobs": jobs}, handle, indent=2)


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def states(path):
    return {item["id"]: item["state"] for item in read_json(path)["jobs"]}


def run(queue_file, report_file, *options):
    return subprocess.run(
        [sys.executable, "-m", ENTRY, str(queue_file), str(report_file), *options],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )


def test_cancel_by_id(tmp_path):
    queue_file = tmp_path / "queue.json"
    report = tmp_path / "report.json"
    write_queue(queue_file, [job(1), job(2), job(3, state="done"), job(4)])
    proc = run(queue_file, report, "--job", "job-4", "--job", "job-2", "--now", "5000")
    assert proc.returncode == 0, proc.stderr
    assert read_json(report) == {
        "cancelled": [{"id": "job-2", "reason": "user"}, {"id": "job-4", "reason": "user"}],
        "pending": ["job-1"],
    }
    assert states(queue_file) == {
        "job-1": "pending", "job-2": "cancelled", "job-3": "done", "job-4": "cancelled",
    }


def test_deadlines_against_given_time(tmp_path):
    queue_file = tmp_path / "queue.json"
    report = tmp_path / "report.json"
    write_queue(queue_file, [
        job(1, deadline=500.0),
        job(2, deadline=1500.0),
        job(3),
        job(4, state="running", deadline=100.0),
        job(5, deadline=1000.0),
        job(6, deadline=999.5),
    ])
    proc = run(queue_file, report, "--now", "1000")
    assert proc.returncode == 0, proc.stderr
    assert read_json(report) == {
        "cancelled": [{"id": "job-1", "reason": "deadline"}, {"id": "job-6", "reason": "deadline"}],
        "pending": ["job-2", "job-3", "job-5"],
    }
    assert states(queue_file)["job-4"] == "running"


def test_all_steps_in_queue_order(tmp_path):
    queue_file = tmp_path / "queue.json"
    report = tmp_path / "report.json"
    write_queue(queue_file, [
        job(1, deadline=500.0),
        job(2),
        job(3, deadline=500.0),
        job(4, state="failed"),
        job(5, deadline=9000.0),
    ])
    proc = run(queue_file, report, "--all", "--job", "job-3", "--now", "1000")
    assert proc.returncode == 0, proc.stderr
    assert read_json(report) == {
        "cancelled": [
            {"id": "job-1", "reason": "deadline"},
            {"id": "job-2", "reason": "shutdown"},
            {"id": "job-3", "reason": "user"},
            {"id": "job-5", "reason": "shutdown"},
        ],
        "pending": [],
    }
    assert states(queue_file) == {
        "job-1": "cancelled", "job-2": "cancelled", "job-3": "cancelled",
        "job-4": "failed", "job-5": "cancelled",
    }


def test_current_time_when_now_left_out(tmp_path):
    queue_file = tmp_path / "queue.json"
    report = tmp_path / "report.json"
    now = time.time()
    write_queue(queue_file, [job(1, deadline=now - 3600), job(2, deadline=now + 86400), job(3)])
    proc = run(queue_file, report)
    assert proc.returncode == 0, proc.stderr
    assert read_json(report) == {
        "cancelled": [{"id": "job-1", "reason": "deadline"}],
        "pending": ["job-2", "job-3"],
    }


def test_bad_job_fails_and_changes_nothing(tmp_path):
    queue_file = tmp_path / "queue.json"
    report = tmp_path / "report.json"
    write_queue(queue_file, [
        job(1, deadline=500.0),
        job(2, state="running"),
        job(3, state="cancelled"),
        job(4, state="done"),
    ])
    with open(queue_file, encoding="utf-8") as handle:
        before = handle.read()
    for job_id in ("job-99", "job-2", "job-3", "job-4"):
        proc = run(queue_file, report, "--job", job_id, "--all", "--now", "1000")
        assert proc.returncode == 2, job_id
        assert not report.exists()
        with open(queue_file, encoding="utf-8") as handle:
            assert handle.read() == before
