import json


def test_zero_rc_empty_artifact_is_not_success_and_jsonl_recovery_is_positive(tmp_path):
    from app.codex_review_artifact import finalize_review_artifact

    output = tmp_path / "review.md"
    round_file = tmp_path / "review.md.round"
    sessions = tmp_path / "codex_sessions.json"
    jsonl = tmp_path / "review.jsonl"
    round_file.write_text("")
    jsonl.write_text(json.dumps({
        "item": {
            "type": "agent_message",
            "text": "## Summary\nRecovered\n\n## Verdict\nPASS",
        },
    }) + "\n")

    error = None
    try:
        finalize_review_artifact(
            output=output,
            round_file=round_file,
            sessions_file=sessions,
            slug="review",
            jsonl_file=jsonl,
            resume=False,
            require_verdict=True,
        )
    except Exception as caught:
        error = caught

    assert error is None, "T3 terminal path must recover a terminal JSONL agent message"
    assert output.read_text() == "## Summary\nRecovered\n\n## Verdict\nPASS\n"
