#!/usr/bin/env python3
"""Freeze #455 merge metadata before opening structural metric results."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
from pathlib import Path


PROMPT_ANCHOR = "200 lines where 50 suffice"
KEYWORDS = re.compile(
    r"\b(simplif(?:y|ied|ication)?|refactor(?:ing|ed)?|consolidat(?:e|ed|ion)|"
    r"remove|removed|removal|cleanup|dead[ -]code|obsolete|inert)\b|"
    r"упрост\w*|рефактор\w*|удал\w*|м[её]ртв\w*|дублир\w*",
    re.IGNORECASE,
)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--scope", required=True)
    ap.add_argument("--through", required=True)
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{Path(args.db)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT m.operation_id, m.session_id, m.worker_name, m.accepted_task_id,
               m.finished_at, m.result_json, s.role, s.backend_type,
               s.system_prompt, t.title AS task_title, t.description AS task_description
        FROM merge_operations AS m
        LEFT JOIN sessions AS s ON s.id = m.session_id
        LEFT JOIN tm_tasks AS t
          ON t.project_id = 'orchestra'
         AND CAST(t.par_number AS TEXT) = m.accepted_task_id
        WHERE m.scope = ? AND m.state = 'SUCCEEDED' AND m.finished_at <= ?
        ORDER BY m.finished_at, m.operation_id
        """,
        (args.scope, args.through),
    ).fetchall()

    included: list[dict] = []
    excluded: list[dict] = []
    seen_targets: set[str] = set()
    for row in rows:
        rec = dict(row)
        try:
            result = json.loads(rec.pop("result_json") or "{}")
        except json.JSONDecodeError:
            excluded.append({"operation_id": rec["operation_id"], "reason": "bad_result_json"})
            continue
        target = (result.get("git") or {}).get("target_after")
        if not target:
            excluded.append({"operation_id": rec["operation_id"], "reason": "no_target_after"})
            continue
        try:
            target = git("rev-parse", f"{target}^{{commit}}").strip()
            parents = git("show", "-s", "--format=%P", target).strip().split()
        except subprocess.CalledProcessError:
            excluded.append({"operation_id": rec["operation_id"], "reason": "missing_git_object"})
            continue
        if target in seen_targets:
            excluded.append(
                {"operation_id": rec["operation_id"], "target": target, "reason": "duplicate_target"}
            )
            continue
        seen_targets.add(target)
        if len(parents) != 1:
            excluded.append(
                {"operation_id": rec["operation_id"], "target": target, "reason": "not_single_parent"}
            )
            continue

        parent = parents[0]
        subject = git("show", "-s", "--format=%s", target).strip()
        numstat = git("diff", "--numstat", parent, target, "--", "app")
        additions = deletions = files = 0
        for line in numstat.splitlines():
            fields = line.split("\t", 2)
            if len(fields) != 3 or not fields[2].endswith(".py"):
                continue
            if fields[0].isdigit() and fields[1].isdigit():
                additions += int(fields[0])
                deletions += int(fields[1])
                files += 1

        prompt_delivered = PROMPT_ANCHOR in (rec.pop("system_prompt") or "")
        task_description = rec.get("task_description") or ""
        classify_text = "\n".join(
            [rec.get("task_title") or "", task_description, subject]
        )
        hits = sorted({m.group(0).lower() for m in KEYWORDS.finditer(classify_text)})
        item = {
            "operation_id": rec["operation_id"],
            "session_id": rec["session_id"],
            "worker_name": rec["worker_name"],
            "task_id": rec["accepted_task_id"],
            "task_title": rec.get("task_title") or "",
            "task_description_length": len(task_description),
            "task_description_sha256": hashlib.sha256(task_description.encode()).hexdigest(),
            "finished_at": rec["finished_at"],
            "role": rec.get("role"),
            "backend_type_at_read_time": rec.get("backend_type"),
            "prompt_anchor_delivered": prompt_delivered,
            "target": target,
            "parent": parent,
            "subject": subject,
            "app_python_additions": additions,
            "app_python_deletions": deletions,
            "app_python_files": files,
            "classification_keyword_hits": hits,
            "structural_cohort": prompt_delivered and additions + deletions >= 10,
        }
        included.append(item)

    payload = {
        "source": {
            "db": str(Path(args.db)),
            "scope": args.scope,
            "through": args.through,
            "prompt_anchor": PROMPT_ANCHOR,
        },
        "counts": {
            "successful_rows": len(rows),
            "unique_single_parent_targets": len(included),
            "prompt_anchor_delivered": sum(x["prompt_anchor_delivered"] for x in included),
            "structural_cohort": sum(x["structural_cohort"] for x in included),
            "keyword_candidates_in_structural_cohort": sum(
                x["structural_cohort"] and bool(x["classification_keyword_hits"])
                for x in included
            ),
            "excluded": len(excluded),
        },
        "merges": included,
        "excluded": excluded,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
