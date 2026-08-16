import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.codex_review_artifact import finalize_review_artifact


def _jsonl(path, thread_id="thread-1"):
    path.write_text(json.dumps({"type": "thread.started", "thread_id": thread_id}) + "\n")


def test_fresh_review_is_atomic_and_persists_session(tmp_path):
    output = tmp_path / "review.md"
    round_file = tmp_path / "review.md.round"
    sessions = tmp_path / "codex_sessions.json"
    jsonl = tmp_path / "review.jsonl"
    round_file.write_text("## Summary\nOK\n\n## Verdict\nPASS\n")
    _jsonl(jsonl)

    finalize_review_artifact(
        output=output, round_file=round_file, sessions_file=sessions,
        slug="review", jsonl_file=jsonl, resume=False, require_verdict=True,
    )

    assert "## Verdict" in output.read_text()
    assert not round_file.exists()
    saved = json.loads(sessions.read_text())
    assert saved["sessions"]["review"]["uuid"] == "thread-1"
    assert saved["sessions"]["review"]["turns"] == 1


def test_resume_appends_without_overwriting_prior_review(tmp_path):
    output = tmp_path / "review.md"
    output.write_text("original findings\n")
    round_file = tmp_path / "review.md.round"
    round_file.write_text("## Verdict\nPASS after fixes\n")
    sessions = tmp_path / "codex_sessions.json"
    sessions.write_text(json.dumps({"sessions": {"review": {
        "uuid": "thread-1", "started": "old", "last_used": "old", "turns": 1,
    }}}))
    jsonl = tmp_path / "review.jsonl"
    _jsonl(jsonl)

    finalize_review_artifact(
        output=output, round_file=round_file, sessions_file=sessions,
        slug="review", jsonl_file=jsonl, resume=True, require_verdict=True,
    )

    content = output.read_text()
    assert content.startswith("original findings")
    assert "## Round" in content
    assert "PASS after fixes" in content
    assert json.loads(sessions.read_text())["sessions"]["review"]["turns"] == 2


def test_resume_labels_the_model_used_for_that_round(tmp_path):
    output = tmp_path / "review.md"
    output.write_text(
        '<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->\n\n'
        "prior review\n"
    )
    round_file = tmp_path / "review.md.round"
    round_file.write_text("## Verdict\nPASS after Luna follow-up\n")
    sessions = tmp_path / "codex_sessions.json"
    sessions.write_text(json.dumps({"sessions": {"review": {
        "uuid": "thread-1",
        "reviewer_model": "gpt-5.6-sol",
        "turns": 1,
    }}}))
    jsonl = tmp_path / "review.jsonl"
    _jsonl(jsonl)

    finalize_review_artifact(
        output=output,
        round_file=round_file,
        sessions_file=sessions,
        slug="review",
        jsonl_file=jsonl,
        resume=True,
        require_verdict=True,
        usage_model="gpt-5.6-luna",
    )

    content = output.read_text()
    assert content.count('"reviewer_model": "gpt-5.6-sol"') == 1
    assert content.count('"reviewer_model": "gpt-5.6-luna"') == 1
    saved = json.loads(sessions.read_text())["sessions"]["review"]
    assert saved["reviewer_model"] == "gpt-5.6-luna"
    assert saved["turns"] == 2


def test_missing_verdict_fails_without_touching_existing_output(tmp_path):
    output = tmp_path / "review.md"
    output.write_text("keep me\n")
    round_file = tmp_path / "review.md.round"
    round_file.write_text("Looks fine, probably.\n")
    jsonl = tmp_path / "review.jsonl"
    _jsonl(jsonl)

    with pytest.raises(ValueError, match="Verdict"):
        finalize_review_artifact(
            output=output, round_file=round_file,
            sessions_file=tmp_path / "sessions.json", slug="review",
            jsonl_file=jsonl, resume=False, require_verdict=True,
        )

    assert output.read_text() == "keep me\n"


def test_missing_thread_id_fails_loud(tmp_path):
    round_file = tmp_path / "review.md.round"
    round_file.write_text("## Verdict\nPASS\n")
    jsonl = tmp_path / "review.jsonl"
    jsonl.write_text("{}\n")
    with pytest.raises(ValueError, match="UUID"):
        finalize_review_artifact(
            output=tmp_path / "review.md", round_file=round_file,
            sessions_file=tmp_path / "sessions.json", slug="review",
            jsonl_file=jsonl, resume=False, require_verdict=True,
        )


def test_review_usage_is_persisted_once_for_requesting_agent(tmp_path, monkeypatch):
    import app.db as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "usage.db")
    db.init_db()
    output = tmp_path / "review.md"
    round_file = tmp_path / "review.md.round"
    sessions = tmp_path / "sessions.json"
    jsonl = tmp_path / "review.jsonl"
    jsonl.write_text("\n".join([
        json.dumps({"type": "thread.started", "thread_id": "thread-usage"}),
        json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 100,
            "cached_input_tokens": 60,
            "cache_write_input_tokens": 10,
            "output_tokens": 20,
        }}),
    ]) + "\n")

    for _ in range(2):
        round_file.write_text("## Verdict\nPASS\n")
        finalize_review_artifact(
            output=output, round_file=round_file, sessions_file=sessions,
            slug="review", jsonl_file=jsonl, resume=False, require_verdict=True,
            usage_event_id="codex-review:attempt-1",
            usage_session_id="requesting-agent-id",
            usage_scope="/scope",
            usage_task_id="215",
            usage_model="gpt-5.6-luna",
        )

    with sqlite3.connect(db.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute("SELECT * FROM turn_usage")]
    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] == "requesting-agent-id"
    assert row["scope"] == "/scope"
    assert row["task_id"] == "215"
    assert row["runtime"] == "codex"
    assert row["model"] == "gpt-5.6-luna"
    assert row["input_tokens"] == 100
    assert row["output_tokens"] == 20
    assert row["cache_read_tokens"] == 60
    assert row["cache_create_tokens"] == 10
    assert row["cost_usd"] > 0
    assert json.loads(sessions.read_text())["sessions"]["review"]["reviewer_model"] == (
        "gpt-5.6-luna"
    )
    assert output.read_text().startswith(
        '<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->\n'
    )


def test_old_cli_without_usage_arguments_preserves_review_and_exits_zero(tmp_path):
    output = tmp_path / "review.md"
    round_file = tmp_path / "review.md.round"
    sessions = tmp_path / "sessions.json"
    jsonl = tmp_path / "review.jsonl"
    round_file.write_text("## Summary\nRecovered result\n\n## Verdict\nAPPROVED\n")
    _jsonl(jsonl, "old-mcp-thread")

    result = subprocess.run([
        sys.executable,
        str(Path(__file__).parents[1] / "app" / "codex_review_artifact.py"),
        "--output", str(output),
        "--round-file", str(round_file),
        "--sessions-file", str(sessions),
        "--slug", "review",
        "--jsonl-file", str(jsonl),
        "--require-verdict",
    ], capture_output=True, text=True)

    assert result.returncode == 0
    assert "Recovered result" in output.read_text()
    assert "Codex usage unaccounted" in output.read_text()
    assert "Codex usage unaccounted" in result.stderr


def test_usage_failure_is_nonfatal_after_review_is_persisted(tmp_path, monkeypatch):
    import app.db as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "usage.db")
    db.init_db()
    output = tmp_path / "review.md"
    round_file = tmp_path / "review.md.round"
    round_file.write_text("## Verdict\nAPPROVED\n")
    jsonl = tmp_path / "review.jsonl"
    jsonl.write_text("\n".join([
        json.dumps({"type": "thread.started", "thread_id": "zero-thread"}),
        json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 0, "output_tokens": 0,
        }}),
    ]) + "\n")

    finalize_review_artifact(
        output=output, round_file=round_file,
        sessions_file=tmp_path / "sessions.json", slug="review",
        jsonl_file=jsonl, resume=False, require_verdict=True,
        usage_event_id="codex-review:zero",
        usage_session_id="requester",
        usage_model="gpt-5.6-sol",
    )

    content = output.read_text()
    assert "## Verdict\nAPPROVED" in content
    assert "Codex usage unaccounted" in content
    with sqlite3.connect(db.DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM turn_usage").fetchone()[0] == 0
