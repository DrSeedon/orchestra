"""Synchronize the private Git task store and refresh the local SQLite projection."""
import argparse
import json
from pathlib import Path
from app import db
from app.task_runtime import TaskRuntime
from app.task_store import TaskStore
from app.task_refs import new_task_prefix


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--origin', choices=['', 'V'], default=new_task_prefix())
    args = parser.parse_args()
    db.init_db(args.database)
    runtime = TaskRuntime(TaskStore(args.repository, origin=args.origin), args.database)
    print(json.dumps(runtime.sync()))


if __name__ == '__main__':
    main()
