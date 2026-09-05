"""Scratch-repository reproductions for task #502 Phase 1."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.diff_budget import MAX_DIFF_INSERTIONS, budget_error, measure_insertions
from app.review_coverage import production_snapshot
from app.workspace import branch_wip_status, merge_worktree_to_main


def git(repo: Path, *args: str, input_text: str | None = None) -> str:
    done = subprocess.run(
        ["git", *args], cwd=repo, input=input_text, capture_output=True, text=True,
        check=False,
    )
    if done.returncode:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({done.returncode}): "
            f"{done.stderr.strip() or done.stdout.strip()}"
        )
    return done.stdout.strip()


def commit_file(repo: Path, path: str, text: str, message: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git(repo, "add", path)
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="orchestra-502-", dir="/mnt/data"))
    result: dict[str, object] = {"scratch": str(scratch)}
    try:
        git(scratch, "init", "-b", "main")
        git(scratch, "config", "user.name", "Task 502")
        git(scratch, "config", "user.email", "task-502@example.invalid")
        root = commit_file(scratch, "README.md", "root\n", "root")

        # A foreign merge-result commit and main's content-equivalent squash have
        # different identities. The current worker inherits the former.
        git(scratch, "checkout", "-b", "foreign-base", root)
        foreign = commit_file(
            scratch,
            "app/shared.py",
            "VALUE = 1\n",
            "#493: foreign merge result\n\nOrchestra-Operation: foreign-operation",
        )
        git(scratch, "checkout", "main")
        squash = commit_file(
            scratch,
            "app/shared.py",
            "VALUE = 1\n",
            "#493: content-equivalent squash\n\nOrchestra-Operation: target-operation",
        )

        git(scratch, "checkout", "-b", "worker", foreign)
        author = commit_file(
            scratch,
            ".orchestra/tasks/502/research.md",
            "author research\n",
            "#502: author research",
        )

        target = git(scratch, "rev-parse", "main")
        stale_snapshot = production_snapshot(
            str(scratch), target_sha=target, worker_head=author,
        )
        two_tree_app = git(scratch, "diff", "--name-only", "main", "worker", "--", "app")

        # The documented stale-branch remedy creates a merge commit whose second
        # parent is main. The inherited foreign trailer nevertheless remains in
        # main..worker because its SHA is not in main.
        git(scratch, "merge", "main", "--no-edit")
        merged_worker = git(scratch, "rev-parse", "HEAD")
        trailer_refusal = merge_worktree_to_main(
            str(scratch), str(scratch), target_branch="main",
            expected_worker_branch="worker", expected_worker_head=merged_worker,
            expected_candidate_refs=[], validated_task_refs=[], primary_task_ref="502",
            operation_id="50250250-2502-4502-8502-502502502502",
        )

        # Current worker_wip uses merge-base semantics. A raw two-tree diff still
        # reports target-only work as a deletion, but worker_wip must not.
        git(scratch, "checkout", "main")
        target_only = commit_file(scratch, "app/target_only.py", "TARGET = 1\n", "target advances")
        git(scratch, "checkout", "-b", "merely-behind", squash)
        raw_two_dot = git(scratch, "diff", "--numstat", "main", "HEAD")
        wip = branch_wip_status(str(scratch), "main")

        # A single-parent rebuild remains a valid author delta after main advances.
        git(scratch, "checkout", "main")
        git(scratch, "checkout", "-b", "rebuilt", target_only)
        commit_file(scratch, ".orchestra/tasks/502/rebuilt.md", "rebuilt work\n", "#502: rebuilt")
        rebuilt_head = git(scratch, "rev-parse", "HEAD")
        git(scratch, "checkout", "main")
        commit_file(scratch, "app/later.py", "LATER = 1\n", "later target advance")
        git(scratch, "checkout", "rebuilt")
        rebuilt_snapshot = production_snapshot(
            str(scratch), target_sha=git(scratch, "rev-parse", "main"), worker_head=rebuilt_head,
        )
        rebuilt_insertions = measure_insertions(str(scratch), "main")

        # Research-only evidence currently consumes the same insertion budget as
        # production. A production control proves the ceiling itself still fires.
        git(scratch, "checkout", "main")
        git(scratch, "checkout", "-b", "research-only")
        evidence = "".join(f"evidence-{index}\n" for index in range(MAX_DIFF_INSERTIONS + 1))
        commit_file(scratch, ".orchestra/tasks/502/raw.txt", evidence, "#502: raw evidence")
        research_insertions = measure_insertions(str(scratch), "main")
        research_refusal = budget_error(research_insertions)

        git(scratch, "checkout", "main")
        git(scratch, "checkout", "-b", "production-too-large")
        production = "".join(f"VALUE_{index} = {index}\n" for index in range(MAX_DIFF_INSERTIONS + 1))
        commit_file(scratch, "app/too_large.py", production, "#502: oversized production")
        production_insertions = measure_insertions(str(scratch), "main")
        production_refusal = budget_error(production_insertions)

        result.update(
            root=root,
            foreign_commit=foreign,
            target_squash=squash,
            stale_author_head=author,
            stale_review_subject={
                "two_tree_app_paths": two_tree_app.splitlines(),
                "three_dot_production_paths": stale_snapshot["production_paths"],
                "production_diff_sha256_nonempty": bool(stale_snapshot["production_diff_sha256"]),
            },
            after_merge_main={
                "worker_head": merged_worker,
                "refusal": trailer_refusal.get("error"),
                "state": trailer_refusal.get("state"),
                "commit_point": trailer_refusal.get("commit_point"),
            },
            merely_behind={
                "raw_two_dot_numstat": raw_two_dot.splitlines(),
                "worker_wip_insertions": wip.get("insertions"),
                "worker_wip_deletions": wip.get("deletions"),
                "worker_wip_changed_files": wip.get("changed_files"),
            },
            rebuild_after_target_advance={
                "production_paths": rebuilt_snapshot["production_paths"],
                "insertions": rebuilt_insertions,
            },
            diff_budget={
                "research_only_insertions": research_insertions,
                "research_only_refusal": research_refusal,
                "production_insertions": production_insertions,
                "production_refusal": production_refusal,
            },
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        shutil.rmtree(scratch)


if __name__ == "__main__":
    main()
