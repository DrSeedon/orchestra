from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile


SCHEMA = """
CREATE TABLE tasks(task_id TEXT PRIMARY KEY, status TEXT NOT NULL);
CREATE TABLE runs(
  run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, worker TEXT NOT NULL,
  status TEXT NOT NULL, reason TEXT, note TEXT, head TEXT
);
CREATE TABLE bindings(worker TEXT PRIMARY KEY, task_id TEXT NOT NULL, run_id TEXT NOT NULL);
"""


def load(path: Path):
    candidate = path / "src" / "task_binding.py"
    if not candidate.exists():
        candidate = path / "task_binding.py"
    spec = importlib.util.spec_from_file_location("candidate_task_binding", candidate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def make_repo(root: Path, *, dirty: bool = False, ahead: bool = False) -> Path:
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    git(repo, "config", "user.name", "Fixture Author")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "base.txt").write_text("base\n")
    git(repo, "add", "base.txt")
    git(repo, "commit", "-qm", "base")
    git(repo, "checkout", "-qb", "worker")
    if dirty:
        (repo / "untracked.txt").write_text("unlanded\n")
    if ahead:
        (repo / "ahead.txt").write_text("unmerged\n")
        git(repo, "add", "ahead.txt")
        git(repo, "commit", "-qm", "unmerged worker work")
    return repo


def make_db(path: Path):
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO tasks VALUES ('old', 'in_progress')")
        db.execute("INSERT INTO tasks VALUES ('next', 'new')")
        db.execute("INSERT INTO runs VALUES ('run-old', 'old', 'worker-a', 'requested', NULL, NULL, NULL)")
        db.execute("INSERT INTO bindings VALUES ('worker-a', 'old', 'run-old')")


def state(path: Path):
    with sqlite3.connect(path) as db:
        return (
            tuple(db.execute("SELECT task_id,status FROM tasks ORDER BY task_id")),
            tuple(db.execute("SELECT run_id,task_id,status,reason,note FROM runs ORDER BY run_id")),
            tuple(db.execute("SELECT worker,task_id,run_id FROM bindings ORDER BY worker")),
        )


def rejected_without_mutation(module, db_path: Path, repo: Path, **kwargs):
    before = state(db_path)
    try:
        module.switch_worker(str(db_path), str(repo), "worker-a", "next", **kwargs)
    except Exception:
        pass
    else:
        raise AssertionError("unsafe transition was accepted")
    assert state(db_path) == before, "refused transition changed task/run state"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True, type=Path)
    args = parser.parse_args()
    module = load(args.candidate)

    with tempfile.TemporaryDirectory(prefix="v1162-v620-") as temp:
        root = Path(temp)
        repo = make_repo(root)
        db_path = root / "state.db"
        make_db(db_path)
        module.switch_worker(str(db_path), str(repo), "worker-a", "next")
        rows = state(db_path)
        assert rows[0] == (("next", "in_progress"), ("old", "new"))
        new_run = next(row for row in rows[1] if row[1] == "next")
        assert new_run[2] == "requested"
        assert rows[2] == (("worker-a", "next", new_run[0]),)
        old = next(row for row in rows[1] if row[0] == "run-old")
        assert old[2:4] == ("interrupted", "binding_released")

    with tempfile.TemporaryDirectory(prefix="v1162-v620-note-") as temp:
        root = Path(temp)
        repo = make_repo(root)
        db_path = root / "state.db"
        make_db(db_path)
        rejected_without_mutation(module, db_path, repo, complete_previous=True, note=" ")
        module.switch_worker(
            str(db_path), str(repo), "worker-a", "next",
            complete_previous=True, note="validated previous work",
        )
        rows = state(db_path)
        old = next(row for row in rows[1] if row[0] == "run-old")
        assert old[2] == "completed" and old[4] == "validated previous work"
        assert rows[0][0] == ("next", "in_progress")
        assert rows[0][1] == ("old", "done")

    with tempfile.TemporaryDirectory(prefix="v1162-v620-shared-") as temp:
        root = Path(temp)
        repo = make_repo(root)
        db_path = root / "state.db"
        make_db(db_path)
        with sqlite3.connect(db_path) as db:
            db.execute("INSERT INTO runs VALUES ('run-other', 'old', 'worker-b', 'requested', NULL, NULL, NULL)")
            db.execute("INSERT INTO bindings VALUES ('worker-b', 'old', 'run-other')")
        rejected_without_mutation(
            module, db_path, repo, complete_previous=True, note="validated previous work",
        )
        module.switch_worker(str(db_path), str(repo), "worker-a", "next")
        rows = state(db_path)
        assert rows[0][1] == ("old", "in_progress")
        assert ("worker-b", "old", "run-other") in rows[2]

    for flag in ("dirty", "ahead"):
        with tempfile.TemporaryDirectory(prefix=f"v1162-v620-{flag}-") as temp:
            root = Path(temp)
            repo = make_repo(root, **{flag: True})
            db_path = root / "state.db"
            make_db(db_path)
            rejected_without_mutation(module, db_path, repo)

    with tempfile.TemporaryDirectory(prefix="v1162-v620-rollback-") as temp:
        root = Path(temp)
        repo = make_repo(root)
        db_path = root / "state.db"
        make_db(db_path)
        with sqlite3.connect(db_path) as db:
            db.execute("""CREATE TRIGGER fail_new_run BEFORE INSERT ON runs
                           WHEN NEW.task_id='next'
                           BEGIN SELECT RAISE(ABORT, 'synthetic insert failure'); END""")
        rejected_without_mutation(module, db_path, repo)

    with tempfile.TemporaryDirectory(prefix="v1162-v620-complete-") as temp:
        root = Path(temp)
        repo = make_repo(root, ahead=True)
        db_path = root / "state.db"
        make_db(db_path)
        head = module.complete_committed_work(str(db_path), str(repo), "worker-a")
        assert git(repo, "rev-parse", "main") == head
        assert state(db_path)[0] == (("next", "new"), ("old", "done"))
    print("PASS: clean release, explicit completion note, dirty/unmerged refusal, ordinary commit completion")


if __name__ == "__main__":
    main()
