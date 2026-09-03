import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest


def test_parallel_round_finalizers_keep_both_artifacts_and_session_updates(tmp_path):
    from app.codex_review_artifact import finalize_review_artifact

    output = tmp_path / "review.md"
    output.write_text("base\n")
    sessions = tmp_path / "codex_sessions.json"
    sessions.write_text(json.dumps({"sessions": {"review": {
        "uuid": "base-thread", "turns": 1,
    }}}))
    jobs = []
    for label in ("first", "second"):
        round_file = tmp_path / f"{label}.round"
        round_file.write_text(f"## Verdict\n{label}\n")
        jsonl = tmp_path / f"{label}.jsonl"
        jsonl.write_text(json.dumps({
            "type": "thread.started", "thread_id": f"{label}-thread",
        }) + "\n")
        jobs.append((round_file, jsonl, label))
    start = Barrier(2)

    def finalize(job):
        round_file, jsonl, label = job
        start.wait()
        finalize_review_artifact(
            output=output,
            round_file=round_file,
            sessions_file=sessions,
            slug="review",
            jsonl_file=jsonl,
            resume=True,
            require_verdict=True,
            receipt_id=f"review-receipt:{label}",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(finalize, jobs))
    content = output.read_text()
    assert "## Verdict\nfirst" in content, "T6 first concurrent round was lost"
    assert "## Verdict\nsecond" in content, "T6 second concurrent round was lost"
    saved = json.loads(sessions.read_text())
    assert saved["sessions"]["review"]["turns"] == 3


def test_backup_symlink_alias_is_rejected_before_backup(tmp_path):
    from scripts.migrate_review_receipts import _backup_database

    database = tmp_path / "database.sqlite"
    database.write_bytes(b"not a real sqlite database")
    alias = tmp_path / "backup.sqlite"
    alias.symlink_to(database)

    with pytest.raises(ValueError, match="aliases"):
        _backup_database(database, alias)
    assert alias.is_symlink(), "T7 alias rejection must not replace the symlink"
