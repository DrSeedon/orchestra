#!/usr/bin/env python3
"""Read-only extraction for #506. Writes only the requested JSON output."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


REVIEW_PREFIX = "review-receipt:%"
ROUND_SEPARATOR = re.compile(r"(?m)^## Round \(\d{4}-\d\d-\d\dT[^\n]+\)\s*$")
MODEL_CHANGE = re.compile(
    r"(?:fresh )?model change: (?P<source>[^ ]+) \([^)]*\) → "
    r"(?P<target>[^ ]+) \([^)]*\)"
)


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def numstat(result: subprocess.CompletedProcess[str]) -> dict:
    measured = {
        "measurable": False,
        "lines": None,
        "files": None,
        "binary_files": 0,
        "error": result.stderr.strip() if result.returncode else "",
    }
    if result.returncode != 0:
        return measured
    lines = 0
    files = 0
    binary = 0
    for line in result.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        files += 1
        if parts[0] == "-" or parts[1] == "-":
            binary += 1
        else:
            lines += int(parts[0]) + int(parts[1])
    measured.update(measurable=True, lines=lines, files=files, binary_files=binary, error="")
    return measured


def repo_root(scope: str) -> Path | None:
    result = run_git(Path(scope), "rev-parse", "--show-toplevel")
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def artifact_candidates(row: dict, root: Path | None) -> list[Path]:
    original = Path(row["artifact_path"])
    candidates = [original]
    if root is None:
        return candidates

    parts = original.parts
    worker = row["worker_name"]
    if worker in parts:
        index = len(parts) - 1 - list(reversed(parts)).index(worker)
        relative = Path(*parts[index + 1 :])
        candidates.append(root / relative)
        if relative.parts[:2] == ("docs", "tasks"):
            candidates.append(root / ".orchestra" / Path(*relative.parts[1:]))

    match = re.search(r"/(?:docs|\.orchestra)/tasks/(\d+)/(.*)$", str(original))
    if match:
        candidates.append(root / ".orchestra" / "tasks" / match.group(1) / match.group(2))
        candidates.append(root / "docs" / "tasks" / match.group(1) / match.group(2))

    task = str(row.get("task_id") or "")
    if task:
        candidates.append(root / ".orchestra" / "tasks" / task / original.name)
        candidates.append(root / "docs" / "tasks" / task / original.name)

    seen: set[Path] = set()
    return [path for path in candidates if not (path in seen or seen.add(path))]


def resolve_artifact(row: dict, root: Path | None) -> Path | None:
    for candidate in artifact_candidates(row, root):
        if candidate.is_file():
            return candidate
    if root is None:
        return None
    matches = list((root / ".orchestra" / "tasks").glob(f"*/{Path(row['artifact_path']).name}"))
    return matches[0] if len(matches) == 1 else None


def historical_artifact_text(row: dict, root: Path | None) -> tuple[str, str]:
    """Find the exact receipt-time artifact by its recorded SHA-256 in git history."""
    wanted = str(row.get("artifact_sha256") or "")
    if root is None or not wanted:
        return "", ""
    relative_paths = []
    for candidate in artifact_candidates(row, root):
        try:
            relative_paths.append(candidate.relative_to(root).as_posix())
        except ValueError:
            continue
    for relative in dict.fromkeys(relative_paths):
        history = run_git(root, "log", "--all", "--format=%H", "--", relative)
        if history.returncode != 0:
            continue
        for commit in history.stdout.splitlines():
            shown = run_git(root, "show", f"{commit}:{relative}")
            if shown.returncode != 0:
                continue
            if hashlib.sha256(shown.stdout.encode()).hexdigest() == wanted:
                return shown.stdout, f"git:{commit}:{relative}"
    return "", ""


def classify(text: str, verdict: str) -> str:
    findings_match = re.search(
        r"(?ims)^##\s+Findings[^\n]*\n(.*?)(?=^##\s+Verdict\b|\Z)", text
    )
    findings = findings_match.group(1).lower() if findings_match else ""
    combined = f"{findings}\n## RECEIPT VERDICT\n{verdict}".lower()
    scrubbed = re.sub(
        r"\b(?:no|without|zero)\s+(?:new\s+)?blocking\b|\bnon[- ]blocking\b",
        "",
        findings,
    )
    blocking_patterns = (
        r"(?m)^\s*(?:[-*]\s*)?(?:\*\*)?blocking(?:\*\*)?\s*[:—-]",
        r"(?m)^\s*#{2,4}\s+blocking\b",
        r"\bblocking (?:finding|issue|bug|defect|risk)s?\b",
        r"\b[1-9]\d* blocking\b",
        r"\[(?:p0|p1)\]",
        r"\bpriority\s*[:=]\s*(?:p0|p1)\b",
    )
    if findings and any(re.search(pattern, scrubbed) for pattern in blocking_patterns):
        return "blocking"
    if re.search(r"\bno (?:new )?blocking\b|\bwithout blocking\b|\bzero blocking\b", combined):
        if re.search(r"\bsuggestion\b|\bnit\b|\bquestion\b|\bthought\b|\bp2\b|\bp3\b", combined):
            return "suggestion-only"
        return "nothing"
    if findings and re.search(r"\bsuggestion\b|\bnit\b|\bquestion\b|\bthought\b|\bp2\b|\bp3\b", findings):
        return "suggestion-only"
    if findings and re.search(r"(?m)^\s*(?:none\.?|нет находок\.?|no findings\.?|nothing\.?)\s*$", findings):
        return "nothing"
    verdict_only = verdict.lower()
    verdict_scrubbed = re.sub(
        r"\b(?:no|without|zero)\s+(?:new\s+)?blocking\b|\bnon[- ]blocking\b",
        "",
        verdict_only,
    )
    if any(re.search(pattern, verdict_scrubbed) for pattern in blocking_patterns):
        return "blocking"
    if re.search(
        r"\bapproved\b|\bcorrect\b|\back\b|\bno findings\b|\bfindings?\s*[:—-]\s*(?:none|0)\b",
        verdict_only,
    ):
        return "nothing"
    if re.search(r"\bincorrect\b|\breject\b|\bneeds work\b|\brequest changes\b|\bnot approved\b", verdict_only):
        return "negative-unclassified"
    return "unclassified"


def author_model_at(con: sqlite3.Connection, session_id: str, requested_at: str, current: str) -> tuple[str, str]:
    changes = []
    for row in con.execute(
        "SELECT ts,content FROM logs WHERE session_id=? AND type='status' "
        "AND content LIKE '%model change:%' ORDER BY ts",
        (session_id,),
    ):
        match = MODEL_CHANGE.search(row["content"])
        if match:
            changes.append((row["ts"], match.group("source"), match.group("target")))
    before = [change for change in changes if change[0] <= requested_at]
    if before:
        return before[-1][2], "last_model_change_before_review"
    after = [change for change in changes if change[0] > requested_at]
    if after:
        return after[0][1], "source_of_first_model_change_after_review"
    return current, "current_sessions_model_no_change_marker"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    con = sqlite3.connect(f"file:{Path(args.database).resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = [
        dict(row)
        for row in con.execute(
            "SELECT r.*,s.model AS current_author_model,b.config AS bg_config,"
            "b.last_output AS bg_last_output FROM review_receipts r "
            "LEFT JOIN sessions s ON s.id=r.session_id "
            "LEFT JOIN bg_jobs b ON b.id=r.job_id "
            "WHERE r.receipt_id LIKE ? AND r.status='completed' ORDER BY r.requested_at",
            (REVIEW_PREFIX,),
        )
    ]

    roots = {scope: repo_root(scope) for scope in {row["scope"] for row in rows}}
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["artifact_path"]].append(row)

    artifact_cache: dict[str, tuple[Path | None, list[str], str]] = {}
    for artifact_path, members in groups.items():
        resolved = resolve_artifact(members[-1], roots[members[-1]["scope"]])
        text = resolved.read_text(encoding="utf-8", errors="replace") if resolved else ""
        current_sha = hashlib.sha256(text.encode()).hexdigest() if text else ""
        artifact_cache[artifact_path] = (
            resolved,
            ROUND_SEPARATOR.split(text) if text else [],
            current_sha,
        )

    extracted = []
    for row in rows:
        root = roots[row["scope"]]
        paths = json.loads(row["production_paths_json"] or "[]")
        size = {
            "measurable": False,
            "lines": None,
            "files": None,
            "binary_files": 0,
            "error": "empty production_paths_json" if not paths else "",
        }
        full_size = {
            "measurable": False,
            "lines": None,
            "files": None,
            "binary_files": 0,
            "error": "repository or refs unavailable",
        }
        if root is not None and row["target_sha"] and row["worker_head"]:
            full_size = numstat(run_git(
                root,
                "diff",
                "--numstat",
                f"{row['target_sha']}...{row['worker_head']}",
            ))
        if root is not None and paths:
            size = numstat(run_git(
                root,
                "diff",
                "--numstat",
                f"{row['target_sha']}...{row['worker_head']}",
                "--",
                *paths,
            ))

        resolved, segments, current_sha = artifact_cache[row["artifact_path"]]
        members = groups[row["artifact_path"]]
        member_index = members.index(row)
        round_text = ""
        mapping = "unavailable"
        if current_sha and current_sha == row["artifact_sha256"]:
            round_text = segments[-1]
            mapping = "current_sha_matches_receipt"
        else:
            historical_text, historical_source = historical_artifact_text(row, root)
            if historical_text:
                round_text = ROUND_SEPARATOR.split(historical_text)[-1]
                mapping = historical_source
        if not round_text and len(segments) == len(members) and len(segments) > 1:
            round_text = segments[member_index]
            mapping = "one_segment_per_completed_receipt"

        config = row.get("bg_config") or ""
        last_output = row.get("bg_last_output") or ""
        requested_resume = " exec resume " in config
        fallback_fresh = "resume failed" in last_output.lower()
        usage_rows = [
            dict(item)
            for item in con.execute(
                "SELECT event_id,ts,model,cost_usd,input_tokens,output_tokens,"
                "cache_read_tokens,cache_create_tokens FROM turn_usage "
                "WHERE event_id LIKE ? ORDER BY ts",
                (row["usage_event_id"] + ":%",),
            )
        ]
        author_model, author_source = author_model_at(
            con,
            row["session_id"],
            row["requested_at"],
            row.get("current_author_model") or "",
        )
        extracted.append(
            {
                "receipt_id": row["receipt_id"],
                "task_id": row["task_id"],
                "worker_name": row["worker_name"],
                "scope": row["scope"],
                "requested_at": row["requested_at"],
                "completed_at": row["completed_at"],
                "mode": row["mode"],
                "subject_kind": row["subject_kind"],
                "round": row["round"],
                "reviewer_model": row["reviewer_model"],
                "author_model": author_model,
                "author_model_source": author_source,
                "artifact_path": row["artifact_path"],
                "resolved_artifact": str(resolved) if resolved else "",
                "artifact_round_mapping": mapping,
                "round_text": round_text,
                "verdict_value": row["verdict_value"],
                "classification": classify(round_text, row["verdict_value"]),
                "author_outcome": row["author_outcome"],
                "target_sha": row["target_sha"],
                "worker_head": row["worker_head"],
                "production_paths": paths,
                "size": size,
                "full_size": full_size,
                "resume": {
                    "bg_job_retained": bool(config),
                    "requested_and_uuid_found": requested_resume,
                    "fallback_fresh_marker": fallback_fresh,
                },
                "usage_event_id": row["usage_event_id"],
                "usage_rows": usage_rows,
            }
        )

    historical_usage = [
        dict(row)
        for row in con.execute(
            "SELECT model,COUNT(*) AS runs,SUM(input_tokens) AS input_tokens,"
            "SUM(output_tokens) AS output_tokens,SUM(cache_read_tokens) AS cache_read_tokens,"
            "SUM(cache_create_tokens) AS cache_create_tokens,SUM(cost_usd) AS cost_usd "
            "FROM turn_usage WHERE event_id LIKE 'codex-review:%' GROUP BY model ORDER BY model"
        )
    ]
    payload = {
        "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
        "database": str(Path(args.database).resolve()),
        "database_max_review_requested_at": con.execute(
            "SELECT MAX(requested_at) FROM review_receipts"
        ).fetchone()[0],
        "database_max_review_usage_ts": con.execute(
            "SELECT MAX(ts) FROM turn_usage WHERE event_id LIKE 'codex-review:%'"
        ).fetchone()[0],
        "completed_review_receipts": len(extracted),
        "completed_receipts_with_prefix_usage": sum(bool(row["usage_rows"]) for row in extracted),
        "historical_review_usage": historical_usage,
        "reviews": extracted,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
