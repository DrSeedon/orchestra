#!/usr/bin/env python3
"""Read-only retroactive knowledge_pending inventory for task #454."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = Path("/mnt/data/Projects/Python/orchestra/data/orchestra.db")


def load_inventory_module():
    path = HERE / "measure_inventory.py"
    spec = importlib.util.spec_from_file_location("task454_inventory", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    inventory = load_inventory_module()
    files = inventory.candidate_files(inventory.TASKS)
    directories = {path.relative_to(inventory.TASKS).parts[0] for path in files}
    structured_task_keys: set[str] = set()
    for _path, _status, text in inventory.knowledge_bullets():
        if "`fact:" not in text:
            continue
        for token in inventory.path_tokens(text):
            key = inventory.task_key_from_token(token)
            if key:
                structured_task_keys.add(key)
        structured_task_keys.update(inventory.TASK_NUMBER.findall(text))

    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("BEGIN")
    rows = connection.execute(
        "SELECT par_number,status,updated_at FROM tm_tasks WHERE project_id='orchestra'"
    ).fetchall()
    connection.rollback()
    connection.close()
    status_counts = Counter(str(row["status"]) for row in rows)
    done = {str(row["par_number"]) for row in rows if row["status"] == "done"}
    done_with_source = done & directories
    done_without_source = done - directories
    zero_strict = done_with_source - structured_task_keys
    some_strict = done_with_source & structured_task_keys

    def selected(keys: set[str]) -> list[Path]:
        return [
            path
            for path in files
            if path.relative_to(inventory.TASKS).parts[0] in keys
        ]

    def file_stats(keys: set[str]) -> dict[str, int]:
        paths = selected(keys)
        markdown = [path for path in paths if path.suffix.lower() == ".md"]
        return {
            "task_directories": len(keys),
            "files": len(paths),
            "apparent_bytes": sum(path.stat().st_size for path in paths),
            "markdown_files": len(markdown),
            "markdown_apparent_bytes": sum(path.stat().st_size for path in markdown),
        }

    output = {
        "counting_rule": (
            "retroactive strict state migration: every current DB task with status=done and a "
            "matching non-empty .orchestra/tasks/<par>/ directory lacks the new #454 drain receipt "
            "and enters knowledge_pending; done without source enters extraction_blocked_source_missing"
        ),
        "snapshot": {
            "git_head": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "db": str(DB),
            "task_updated_at_max": max(str(row["updated_at"]) for row in rows),
        },
        "task_status_counts": dict(sorted(status_counts.items())),
        "retroactive_state": {
            "knowledge_pending": file_stats(done_with_source),
            "extraction_blocked_source_missing_tasks": len(done_without_source),
            "zero_structured_promoted_fact": file_stats(zero_strict),
            "at_least_one_structured_fact_but_no_new_drain_receipt": file_stats(some_strict),
        },
        "prospective_only_initial_knowledge_pending": 0,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
