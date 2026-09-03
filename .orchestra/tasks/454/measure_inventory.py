#!/usr/bin/env python3
"""Read-only inventory for task #454.

The script excludes .orchestra/tasks/454 because that directory contains the
measurement itself and did not exist at the start of the snapshot.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TASKS = ROOT / ".orchestra" / "tasks"
WORKERS = ROOT / ".orchestra" / "workers"
KB = ROOT / ".orchestra" / "kb"
DB = Path("/mnt/data/Projects/Python/orchestra/data/orchestra.db")
EXCLUDED_TASK_DIRS = {"454"}
TERMINAL_TASK_STATES = {"done", "cancelled"}
CURRENT_PREFIXES = (".orchestra/tasks/", ".orchestra/workers/")
HISTORICAL_PREFIXES = ("docs/tasks/", "docs/workers/")
PATH_TOKEN = re.compile(
    r"(?:\.orchestra|\.\.|docs)/(?:tasks|workers)/[^\s`\]\[(){};,]+"
)
TASK_NUMBER = re.compile(r"(?<![A-Za-z0-9])#([0-9]+)\b")


def run(*args: str, check: bool = True, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(
        args,
        cwd=ROOT,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}\n"
            f"{result.stderr.decode(errors='replace')}"
        )
    return result.stdout


def candidate_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if root == TASKS and path.relative_to(root).parts[0] in EXCLUDED_TASK_DIRS:
            continue
        files.append(path)
    return sorted(files)


def sizes(paths: list[Path]) -> dict[str, int]:
    stats = [path.stat() for path in paths]
    return {
        "files": len(paths),
        "apparent_bytes": sum(item.st_size for item in stats),
        "allocated_bytes": sum(item.st_blocks * 512 for item in stats),
        "markdown_files": sum(path.suffix.lower() == ".md" for path in paths),
        "markdown_apparent_bytes": sum(
            path.stat().st_size for path in paths if path.suffix.lower() == ".md"
        ),
    }


def knowledge_bullets() -> list[tuple[Path, str, str]]:
    bullets: list[tuple[Path, str, str]] = []
    accepted_sections = {"## Установлено": "current", "## Отвергнуто": "rejected"}
    for path in sorted(KB.rglob("*.md")):
        section = ""
        current: list[str] = []

        def flush() -> None:
            nonlocal current
            if current:
                bullets.append((path, section, "\n".join(current)))
                current = []

        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("## "):
                flush()
                section = accepted_sections.get(line.strip(), "")
                continue
            if not section:
                continue
            if line.startswith("- "):
                flush()
                current = [line]
            elif current:
                current.append(line)
        flush()
    return bullets


def clean_path_token(token: str) -> str:
    token = re.sub(r":\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*$", "", token)
    token = token.rstrip(".:\"'")
    if token.startswith("../tasks/"):
        return ".orchestra/tasks/" + token[len("../tasks/") :]
    if token.startswith("../workers/"):
        return ".orchestra/workers/" + token[len("../workers/") :]
    return token


def path_tokens(text: str) -> set[str]:
    return {clean_path_token(match.group(0)) for match in PATH_TOKEN.finditer(text)}


def resolve_current_reference(token: str) -> Path | None:
    if not token.startswith(CURRENT_PREFIXES):
        return None
    path = ROOT / token
    return path if path.is_file() else None


def task_key_from_token(token: str) -> str | None:
    for prefix in (".orchestra/tasks/", "docs/tasks/"):
        if token.startswith(prefix):
            rest = token[len(prefix) :]
            return rest.split("/", 1)[0] or None
    return None


def git_tracked_external_references() -> set[Path]:
    """Exact current-path consumers outside both candidate roots.

    Immutable evidence JSON is excluded: its source_path is interpreted only
    under the paired git_commit, never as a HEAD path.
    """

    referenced: set[Path] = set()
    tracked = run("git", "ls-files", "-z").split(b"\0")
    for raw in tracked:
        if not raw:
            continue
        relative = Path(os.fsdecode(raw))
        text_path = ROOT / relative
        relative_posix = relative.as_posix()
        if relative_posix.startswith(CURRENT_PREFIXES):
            continue
        if relative_posix.startswith(".orchestra/kb/records/evidence/"):
            continue
        try:
            if text_path.stat().st_size > 5_000_000:
                continue
            text = text_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for token in path_tokens(text):
            current = resolve_current_reference(token)
            if current is not None:
                referenced.add(current)
    return referenced


def task_state_and_session_snapshot() -> tuple[dict[str, str], dict[str, set[str]], set[str], dict]:
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("BEGIN")
    projects = connection.execute(
        "SELECT id FROM tm_projects WHERE RTRIM(scope, '/') = RTRIM(?, '/')",
        ("/mnt/data/Projects/Python/orchestra",),
    ).fetchall()
    project_ids = {str(row["id"]) for row in projects} | {"orchestra"}
    placeholders = ",".join("?" for _ in project_ids)
    task_states = {
        str(row["par_number"]): str(row["status"])
        for row in connection.execute(
            f"SELECT par_number, status FROM tm_tasks WHERE project_id IN ({placeholders})",
            tuple(sorted(project_ids)),
        )
    }
    session_states: dict[str, set[str]] = defaultdict(set)
    roles: set[str] = set()
    for row in connection.execute(
        "SELECT name, status, role FROM sessions "
        "WHERE RTRIM(scope, '/') = RTRIM(?, '/')",
        ("/mnt/data/Projects/Python/orchestra",),
    ):
        session_states[str(row["name"])].add(str(row["status"]))
        if row["role"]:
            roles.add(str(row["role"]))

    log_stats = dict(
        connection.execute(
            "SELECT COUNT(*) AS logs, "
            "COALESCE(SUM(LENGTH(CAST(l.content AS BLOB))), 0) AS content_bytes, "
            "SUM(CASE WHEN s.status='archived' THEN 1 ELSE 0 END) AS archived_logs, "
            "COALESCE(SUM(CASE WHEN s.status='archived' "
            "THEN LENGTH(CAST(l.content AS BLOB)) ELSE 0 END), 0) AS archived_content_bytes "
            "FROM logs l JOIN sessions s ON s.id=l.session_id"
        ).fetchone()
    )
    log_watermark = dict(
        connection.execute(
            "SELECT COALESCE(MAX(id), 0) AS max_id, COALESCE(MAX(ts), '') AS max_ts FROM logs"
        ).fetchone()
    )
    summary_stats = dict(
        connection.execute(
            "SELECT COUNT(*) AS sessions, "
            "SUM(CASE WHEN LENGTH(last_summary)>0 THEN 1 ELSE 0 END) AS summaries, "
            "COALESCE(SUM(LENGTH(CAST(last_summary AS BLOB))), 0) AS summary_bytes, "
            "SUM(CASE WHEN status='archived' THEN 1 ELSE 0 END) AS archived_sessions "
            "FROM sessions"
        ).fetchone()
    )
    connection.rollback()
    connection.close()
    return task_states, session_states, roles, {
        "logs": log_stats,
        "log_watermark": log_watermark,
        "summaries": summary_stats,
    }


def validated_evidence_for_current_bytes(paths: list[Path]) -> tuple[set[Path], dict[str, int]]:
    by_relative: dict[str, list[dict]] = defaultdict(list)
    evidence_records = 0
    for record_path in sorted((KB / "records" / "evidence").glob("*.json")):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        evidence_records += 1
        source_path = str(record.get("source_path") or "")
        if source_path.startswith("docs/tasks/"):
            relative = ".orchestra/tasks/" + source_path[len("docs/tasks/") :]
        elif source_path.startswith("docs/workers/"):
            relative = ".orchestra/workers/" + source_path[len("docs/workers/") :]
        else:
            continue
        by_relative[relative].append(record)

    candidate_relatives = {path.relative_to(ROOT).as_posix(): path for path in paths}
    current_digests = {
        relative: "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        for relative, path in candidate_relatives.items()
    }
    matching_records: list[dict] = []
    paths_with_digest_match: set[str] = set()
    for relative, digest in current_digests.items():
        for record in by_relative.get(relative, ()):
            if record.get("source_sha256") == digest:
                matching_records.append(record)
                paths_with_digest_match.add(relative)

    commits = sorted({str(record["git_commit"]) for record in matching_records})
    valid_commits: set[str] = set()
    trees: dict[str, dict[str, str]] = {}
    for commit in commits:
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=ROOT
        ).returncode == 0
        reachable = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "main"], cwd=ROOT
        ).returncode == 0
        if not (exists and reachable):
            continue
        valid_commits.add(commit)
        entries: dict[str, str] = {}
        raw_tree = run("git", "ls-tree", "-r", "-z", commit)
        for entry in raw_tree.split(b"\0"):
            if not entry:
                continue
            metadata, raw_path = entry.split(b"\t", 1)
            blob = metadata.split()[2].decode("ascii")
            entries[os.fsdecode(raw_path)] = blob
        trees[commit] = entries

    blob_ids = sorted(
        {
            str(record["git_blob"])
            for record in matching_records
            if str(record["git_commit"]) in valid_commits
            and trees[str(record["git_commit"])].get(str(record["source_path"]))
            == str(record["git_blob"])
        }
    )
    blob_contents: dict[str, bytes] = {}
    if blob_ids:
        process = subprocess.Popen(
            ["git", "cat-file", "--batch"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write("".join(f"{blob}\n" for blob in blob_ids).encode("ascii"))
        process.stdin.close()
        for expected_blob in blob_ids:
            header = process.stdout.readline().decode("ascii").strip().split()
            if len(header) != 3 or header[0] != expected_blob or header[1] != "blob":
                raise RuntimeError(f"unexpected cat-file header: {header}")
            size = int(header[2])
            blob_contents[expected_blob] = process.stdout.read(size)
            if process.stdout.read(1) != b"\n":
                raise RuntimeError("missing cat-file record separator")
        if process.wait() != 0:
            raise RuntimeError(process.stderr.read().decode(errors="replace"))

    recoverable: set[Path] = set()
    valid_bindings = 0
    for record in matching_records:
        commit = str(record["git_commit"])
        blob = str(record["git_blob"])
        if commit not in valid_commits:
            continue
        if trees[commit].get(str(record["source_path"])) != blob:
            continue
        content = blob_contents.get(blob)
        if content is None:
            continue
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if digest != record.get("source_sha256"):
            continue
        source_path = str(record["source_path"])
        if source_path.startswith("docs/tasks/"):
            relative = ".orchestra/tasks/" + source_path[len("docs/tasks/") :]
        else:
            relative = ".orchestra/workers/" + source_path[len("docs/workers/") :]
        current = candidate_relatives.get(relative)
        if current is not None:
            recoverable.add(current)
            valid_bindings += 1

    return recoverable, {
        "evidence_records_scanned": evidence_records,
        "candidate_paths_with_any_historical_record": sum(
            relative in by_relative for relative in candidate_relatives
        ),
        "candidate_paths_with_current_digest_match": len(paths_with_digest_match),
        "valid_matching_bindings": valid_bindings,
        "candidate_paths_recoverable": len(recoverable),
    }


def extraction_cost_snapshot() -> dict:
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = [
        dict(row)
        for row in connection.execute(
            "SELECT task_id, COUNT(*) AS model_turns, "
            "ROUND(SUM(COALESCE(cost_usd, 0)), 9) AS virtual_cost_usd "
            "FROM turn_usage WHERE task_id IN ('399','400','401','402','403') "
            "GROUP BY task_id ORDER BY CAST(task_id AS INTEGER)"
        )
    ]
    connection.close()
    facts_by_part: dict[str, int] = {}
    source_files_by_part: dict[str, int] = {}
    for part in range(1, 6):
        values = json.loads(
            (TASKS / "kb-extract" / f"part-{part}.json").read_text(encoding="utf-8")
        )
        facts_by_part[str(398 + part)] = len(values)
        source_files_by_part[str(398 + part)] = len(
            {str(value["source_file"]) for value in values}
        )
    for row in rows:
        key = str(row["task_id"])
        row["facts"] = facts_by_part[key]
        row["source_files"] = source_files_by_part[key]
    costs = [float(row["virtual_cost_usd"]) for row in rows]
    turns = [int(row["model_turns"]) for row in rows]
    return {
        "batches": rows,
        "total_batches": len(rows),
        "total_source_files": sum(source_files_by_part.values()),
        "total_facts": sum(facts_by_part.values()),
        "total_model_turns": sum(turns),
        "total_virtual_cost_usd": round(sum(costs), 9),
        "median_batch_model_turns": statistics.median(turns),
        "median_batch_virtual_cost_usd": round(statistics.median(costs), 9),
        "min_batch_virtual_cost_usd": min(costs),
        "max_batch_virtual_cost_usd": max(costs),
    }


def main() -> None:
    task_files = candidate_files(TASKS)
    worker_files = candidate_files(WORKERS)
    all_candidates = task_files + worker_files
    task_dirs = sorted({path.relative_to(TASKS).parts[0] for path in task_files})
    bullets = knowledge_bullets()
    exact_fact_refs: set[Path] = set()
    structured_exact_fact_refs: set[Path] = set()
    promoted_task_keys: set[str] = set()
    structured_promoted_task_keys: set[str] = set()
    exact_path_task_keys: set[str] = set()
    structured_facts = 0
    for _kb_file, _status, text in bullets:
        structured = "`fact:" in text
        if structured:
            structured_facts += 1
        tokens = path_tokens(text)
        for token in tokens:
            current = resolve_current_reference(token)
            if current is not None:
                exact_fact_refs.add(current)
                if structured:
                    structured_exact_fact_refs.add(current)
            task_key = task_key_from_token(token)
            if task_key:
                promoted_task_keys.add(task_key)
                exact_path_task_keys.add(task_key)
                if structured:
                    structured_promoted_task_keys.add(task_key)
        numbered_keys = set(TASK_NUMBER.findall(text))
        promoted_task_keys.update(numbered_keys)
        if structured:
            structured_promoted_task_keys.update(numbered_keys)

    task_states, session_states, roles, dialog_stats = task_state_and_session_snapshot()
    external_refs = git_tracked_external_references()
    recoverable, evidence_stats = validated_evidence_for_current_bytes(all_candidates)

    owner_terminal: set[Path] = set()
    owner_active: set[Path] = set()
    owner_unknown: set[Path] = set()
    for path in task_files:
        key = path.relative_to(TASKS).parts[0]
        status = task_states.get(key)
        if status in TERMINAL_TASK_STATES:
            owner_terminal.add(path)
        elif status:
            owner_active.add(path)
        else:
            owner_unknown.add(path)
    for path in worker_files:
        key = path.stem
        states = session_states.get(key, set())
        if key in roles or any(state != "archived" for state in states):
            owner_active.add(path)
        elif states and states <= {"archived"}:
            owner_terminal.add(path)
        else:
            owner_unknown.add(path)

    head_consumers = external_refs | owner_active
    storage_eligible = owner_terminal & recoverable - head_consumers
    kept = set(all_candidates) - storage_eligible

    reasons = {
        "active_owner": owner_active,
        "unknown_owner_or_no_approval": owner_unknown,
        "current_head_consumer": external_refs,
        "missing_exact_reachable_blob_receipt": set(all_candidates) - recoverable,
    }

    def sample(paths: set[Path], limit: int = 5) -> list[str]:
        return [path.relative_to(ROOT).as_posix() for path in sorted(paths)[:limit]]

    output = {
        "snapshot": {
            "git_head": run("git", "rev-parse", "HEAD").decode().strip(),
            "git_main": run("git", "rev-parse", "main").decode().strip(),
            "excluded_task_dirs": sorted(EXCLUDED_TASK_DIRS),
            "db": str(DB),
        },
        "corpus": {
            "tasks": sizes(task_files),
            "workers": sizes(worker_files),
            "task_directories_with_files": len(task_dirs),
            "numeric_task_directories_with_files": sum(key.isdigit() for key in task_dirs),
        },
        "kb_live_facts": {
            "facts_current_or_rejected": len(bullets),
            "structured_fact_key_lines": structured_facts,
            "task_files_referenced_by_exact_current_path": sum(
                path in exact_fact_refs for path in task_files
            ),
            "worker_files_referenced_by_exact_current_path": sum(
                path in exact_fact_refs for path in worker_files
            ),
            "task_files_referenced_by_structured_fact_exact_current_path": sum(
                path in structured_exact_fact_refs for path in task_files
            ),
            "worker_files_referenced_by_structured_fact_exact_current_path": sum(
                path in structured_exact_fact_refs for path in worker_files
            ),
            "exact_current_path_reference_examples": sample(
                exact_fact_refs & set(all_candidates)
            ),
            "referenced_files_apparent_bytes": sum(
                path.stat().st_size for path in exact_fact_refs if path in set(all_candidates)
            ),
            "task_directories_with_at_least_one_promoted_fact": sum(
                key in promoted_task_keys for key in task_dirs
            ),
            "task_directories_with_artifacts_and_no_promoted_fact": sum(
                key not in promoted_task_keys for key in task_dirs
            ),
            "task_directories_with_exact_path_from_fact": sum(
                key in exact_path_task_keys for key in task_dirs
            ),
            "task_directories_with_structured_promoted_fact": sum(
                key in structured_promoted_task_keys for key in task_dirs
            ),
            "task_directories_without_structured_promoted_fact": sum(
                key not in structured_promoted_task_keys for key in task_dirs
            ),
            "promoted_task_keys_matching_current_directories": sorted(
                set(task_dirs) & promoted_task_keys
            ),
        },
        "non_derivable_storage_predicate": {
            "definition": (
                "allow only when owner is terminal (or separately human-approved), "
                "no tracked current-HEAD consumer names the file, and exact current bytes "
                "match a git_commit:path->blob->sha256 receipt reachable from main"
            ),
            "candidate_files": len(all_candidates),
            "kept_by_predicate": len(kept),
            "kept_apparent_bytes": sum(path.stat().st_size for path in kept),
            "passed_by_storage_predicate": len(storage_eligible),
            "passed_apparent_bytes": sum(path.stat().st_size for path in storage_eligible),
            "passed_task_files": sum(path in set(task_files) for path in storage_eligible),
            "passed_worker_files": sum(path in set(worker_files) for path in storage_eligible),
            "passed_examples": sample(storage_eligible),
            "reason_counts_not_mutually_exclusive": {
                name: len(paths) for name, paths in reasons.items()
            },
            "reason_examples": {name: sample(paths) for name, paths in reasons.items()},
            "head_consumer_exact_paths": len(head_consumers),
            "owner_terminal_files": len(owner_terminal),
            "owner_active_files": len(owner_active),
            "owner_unknown_files": len(owner_unknown),
            "important_limit": (
                "this is only the post-semantic storage gate; without candidate manifests "
                "and external completeness approval, production deletion remains forbidden"
            ),
        },
        "evidence": evidence_stats,
        "dialog_source": dialog_stats,
        "historical_luna_extraction_cost": extraction_cost_snapshot(),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
