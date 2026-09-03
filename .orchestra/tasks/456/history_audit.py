#!/usr/bin/env python3
"""Reproduce the #456 historical-review evidence from git, artifacts, and read-only logs."""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "history-audit.json"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True, stdout=subprocess.PIPE
    ).stdout


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> None:
    common_git_dir = Path(
        git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    )
    database = common_git_dir.parent / "data" / "orchestra.db"
    conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    task_store_diff = git("show", "--format=", "baf501c7", "--", "app/tm.py")
    task_store_session = "d2d262b5-878a-4426-b1ab-f20f2afbcd9b"
    task_store_review_calls = conn.execute(
        "SELECT COUNT(*) FROM logs WHERE session_id=? "
        "AND type='tool' AND tool_name='mcp__orchestra__codex_review'",
        (task_store_session,),
    ).fetchone()[0]
    task_store_codex_exec = conn.execute(
        "SELECT COUNT(*) FROM logs WHERE session_id=? AND type='tool' "
        "AND lower(content) LIKE '%codex exec%'",
        (task_store_session,),
    ).fetchone()[0]
    task_store_done = conn.execute(
        "SELECT content FROM logs WHERE session_id=? AND type='tool' "
        "AND tool_name='mcp__orchestra__send_message' "
        "AND content LIKE '%DONE #341%' ORDER BY ts DESC LIMIT 1",
        (task_store_session,),
    ).fetchone()[0]

    fact_diff = git(
        "show", "--format=", "e3f95f98", "--", "scripts/kb_promote_facts.py"
    )
    fact_review = text(".orchestra/tasks/409/codex-review-impl.md")
    fact_session = "783e5f9b-a118-45b0-a0c5-be86a464ea42"
    fact_review_calls = conn.execute(
        "SELECT COUNT(*) FROM logs WHERE session_id=? "
        "AND type='tool' AND tool_name='mcp__orchestra__codex_review'",
        (fact_session,),
    ).fetchone()[0]
    fact_usage_rows = [
        dict(row)
        for row in conn.execute(
            "SELECT input_tokens, cache_read_tokens, output_tokens, cost_usd "
            "FROM turn_usage WHERE session_id=? AND model='gpt-5.6-luna' "
            "AND ts BETWEEN '2026-08-26T09:40:00+00:00' "
            "AND '2026-08-26T10:12:00+00:00' ORDER BY ts",
            (fact_session,),
        )
    ]

    session_diff = git(
        "show", "--format=", "01a666ed", "--", "app/routes/subagent.py"
    )
    session_plan_review = text(
        ".orchestra/tasks/subagent-telemetry/codex-review-plan.md"
    )
    session_report = text(".orchestra/tasks/subagent-telemetry/report.md")
    session_commit_files = git("show", "--name-only", "--format=", "01a666ed")
    session_review_files = sorted(
        line for line in session_commit_files.splitlines() if "review" in line.casefold()
    )

    result = {
        "task_counter": {
            "commit": "baf501c7",
            "hunk_has_canonical_writer": "candidate = store.task_create(" in task_store_diff,
            "hunk_has_legacy_writer": "legacy = _legacy_api_create_task(" in task_store_diff,
            "codex_review_tool_calls": task_store_review_calls,
            "codex_exec_calls": task_store_codex_exec,
            "done_report_explicitly_says_no_review": (
                "Review: none — explicitly prohibited" in task_store_done
            ),
            "later_proof_has_counter_mismatch": (
                "There are **2 semantic collisions**"
                in text(".orchestra/tasks/406/report.md")
                and "disagreement raises"
                in text(".orchestra/tasks/406/report.md")
            ),
        },
        "fact_key": {
            "commit": "e3f95f98",
            "hunk_has_content_derived_identity": all(
                anchor in fact_diff
                for anchor in ("def stable_fact_id", 'value.get("statement")', "uuid.uuid5")
            ),
            "review_artifact": ".orchestra/tasks/409/codex-review-impl.md",
            "review_mentions_same_hunk": (
                "The stable ID excludes `topic`, `status`" in fact_review
            ),
            "review_mentions_rephrase_instability": bool(
                re.search(r"rephras|statement.{0,20}(change|edit|mutab)", fact_review, re.I)
            ),
            "review_incorrect_verdict_count": fact_review.count(
                "**Overall Correctness:** ❌ Incorrect"
            ),
            "review_approved_verdict_count": len(
                re.findall(r"\bAPPROVED\b", fact_review)
            ),
            "codex_review_tool_calls": fact_review_calls,
            "luna_review_usage_rows": fact_usage_rows,
            "luna_review_usage_total": {
                key: sum(row[key] for row in fact_usage_rows)
                for key in ("input_tokens", "cache_read_tokens", "output_tokens", "cost_usd")
            },
            "later_proof_has_rephrase_failure": (
                "rephrasing therefore produces a new UUID"
                in git("show", "3cfa301b:docs/tasks/429/plan.md")
            ),
        },
        "session_key": {
            "commit": "01a666ed",
            "hunk_uses_current_session_id_for_transcript": (
                'sdk_id = sess.get("session_id") or ""' in session_diff
                and "get_subagent_messages(sdk_id" in session_diff
            ),
            "plan_review_caught_sdk_session_lifecycle": (
                "После compact/current-session смены без `sdk_session_id` старые транскрипты можно потерять"
                in session_plan_review
            ),
            "implementation_review_files_in_commit": session_review_files,
            "implementation_report_says_codex_unavailable": (
                "## Codex\nНедоступен" in session_report
                and "Codex review impl — переспросить" in session_report
            ),
            "later_fix_has_historical_sdk_test": (
                "test_transcript_uses_historical_sdk_session_from_telemetry"
                in git("show", "--format=", "38caf30b", "--", "tests/test_subagent_routes.py")
            ),
        },
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    OUT.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
