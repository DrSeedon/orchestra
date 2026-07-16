import json

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
