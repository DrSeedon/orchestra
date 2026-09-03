#!/usr/bin/env python3
"""Read-only tracked-Markdown inventory for registered project repositories."""

from __future__ import annotations

import json
import os
import sqlite3
import statistics
import subprocess
from pathlib import Path


DB = Path("/mnt/data/Projects/Python/orchestra/data/orchestra.db")
OWNER_PREFIXES = (
    ".orchestra/kb/",
    ".orchestra/pipelines/",
    ".claude/skills/",
    ".codex/skills/",
)


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", root, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"git -C {root} {' '.join(args)} failed: "
            f"{result.stderr.decode(errors='replace')}"
        )
    return result.stdout


def percentile_nearest_rank(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    rank = max(1, int(len(ordered) * fraction + 0.999999999))
    return ordered[rank - 1]


def main() -> None:
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    project_rows = connection.execute(
        "SELECT id, scope FROM tm_projects "
        "WHERE scope IS NOT NULL AND TRIM(scope)!='' ORDER BY id"
    ).fetchall()
    connection.close()

    repositories: dict[str, dict] = {}
    failures: list[dict] = []
    for row in project_rows:
        scope = Path(str(row["scope"]))
        try:
            root = Path(
                os.fsdecode(git(scope, "rev-parse", "--show-toplevel")).strip()
            ).resolve()
        except (OSError, RuntimeError) as error:
            failures.append({"project_id": row["id"], "scope": str(scope), "error": str(error)})
            continue
        key = str(root)
        entry = repositories.setdefault(
            key,
            {
                "repo_root": key,
                "project_ids": [],
            },
        )
        entry["project_ids"].append(str(row["id"]))

    results: list[dict] = []
    for root_text, entry in sorted(repositories.items()):
        root = Path(root_text)
        tracked = [
            Path(os.fsdecode(raw))
            for raw in git(root, "ls-files", "-z", "--", "*.md").split(b"\0")
            if raw
        ]
        existing = [path for path in tracked if (root / path).is_file()]
        nested = [path for path in existing if len(path.parts) > 1]
        eligible = [
            path
            for path in nested
            if not path.as_posix().startswith(OWNER_PREFIXES)
        ]
        task_worker = [
            path
            for path in existing
            if path.as_posix().startswith(
                (".orchestra/tasks/", ".orchestra/workers/")
            )
        ]
        result = {
            **entry,
            "head": git(root, "rev-parse", "HEAD").decode().strip(),
            "tracked_markdown_files": len(existing),
            "tracked_markdown_bytes": sum((root / path).stat().st_size for path in existing),
            "top_level_markdown_files": len(existing) - len(nested),
            "eligible_nested_markdown_files": len(eligible),
            "eligible_nested_markdown_bytes": sum(
                (root / path).stat().st_size for path in eligible
            ),
            "task_worker_markdown_files": len(task_worker),
            "task_worker_markdown_bytes": sum(
                (root / path).stat().st_size for path in task_worker
            ),
        }
        results.append(result)

    eligible_counts = [row["eligible_nested_markdown_files"] for row in results]
    tracked_counts = [row["tracked_markdown_files"] for row in results]
    output = {
        "counting_rule": (
            "git ls-files -- '*.md'; eligible excludes all top-level Markdown and canonical "
            "owner prefixes .orchestra/kb, .orchestra/pipelines, .claude/skills, .codex/skills"
        ),
        "registered_project_rows": len(project_rows),
        "unique_accessible_repositories": len(results),
        "failures": failures,
        "repositories": results,
        "distribution": {
            "tracked_markdown_files_total": sum(tracked_counts),
            "tracked_markdown_files_median": statistics.median(tracked_counts),
            "eligible_nested_markdown_files_total": sum(eligible_counts),
            "eligible_nested_markdown_files_min": min(eligible_counts),
            "eligible_nested_markdown_files_p25_nearest_rank": percentile_nearest_rank(
                eligible_counts, 0.25
            ),
            "eligible_nested_markdown_files_median": statistics.median(eligible_counts),
            "eligible_nested_markdown_files_p75_nearest_rank": percentile_nearest_rank(
                eligible_counts, 0.75
            ),
            "eligible_nested_markdown_files_max": max(eligible_counts),
            "eligible_nested_markdown_bytes_total": sum(
                row["eligible_nested_markdown_bytes"] for row in results
            ),
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
