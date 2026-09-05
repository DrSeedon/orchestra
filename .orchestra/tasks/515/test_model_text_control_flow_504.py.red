"""Cross-file RED oracles for task #504 that do not fit an existing test owner."""

import json
from pathlib import Path
import subprocess
import sys


def _guard_returncode(tmp_path, events):
    from app.mcp_stdio import (
        _CODEX_EXECUTION_FAILURE_JSONL_CHECK,
        _CODEX_EXECUTION_FAILURE_PATTERN,
    )

    path = tmp_path / "review.jsonl"
    path.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    return subprocess.run(
        [
            sys.executable,
            "-c",
            _CODEX_EXECUTION_FAILURE_JSONL_CHECK,
            str(path),
            _CODEX_EXECUTION_FAILURE_PATTERN,
        ],
        check=False,
    ).returncode


def test_t2_jsonl_agent_prose_does_not_signal_execution_failure(tmp_path):
    successful_command_with_prose = [
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "status": "completed",
                "exit_code": 0,
            },
        },
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": (
                    "bwrap: failed rtm_newaddr; setting up uid map: permission denied; "
                    "sandbox failed; no files were read; all local commands failed; "
                    "unable to review sandbox file."
                ),
            },
        },
    ]

    assert _guard_returncode(tmp_path, successful_command_with_prose) == 1, (
        "T2 JSONL seam: review-model prose still declares execution failure"
    )


def test_t2_jsonl_zero_command_events_signal_execution_failure(tmp_path):
    no_command_events = [{
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "Review finished."},
    }]

    assert _guard_returncode(tmp_path, no_command_events) == 0, (
        "T2 fail-closed seam: zero command_execution events were accepted"
    )


def test_t2_jsonl_failed_command_events_signal_execution_failure(tmp_path):
    all_commands_failed = [
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "status": "failed",
                "exit_code": 1,
            },
        },
    ]

    assert _guard_returncode(tmp_path, all_commands_failed) == 0, (
        "T2 JSONL seam: failed typed command events did not declare execution failure"
    )


def test_t2_jsonl_successful_command_event_is_accepted(tmp_path):
    successful_command = [{
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "status": "completed",
            "exit_code": 0,
        },
    }]

    assert _guard_returncode(tmp_path, successful_command) == 1, (
        "T2 positive control: completed typed command event was rejected"
    )


def test_t4_model_text_classifier_has_no_python_or_browser_owner():
    root = Path(__file__).resolve().parents[1]
    forbidden = (
        "looks_like_unexecuted_tool_call",
        "mark_unexecuted_tool_call",
        "_looksLikeUnexecutedToolCall",
        "_markUnexecutedToolCall",
    )
    hits = []
    for relative in (
        "app/tool_call_guard.py",
        "app/tg_bridge.py",
        "app/static/js/chat.js",
    ):
        path = root / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        hits.extend(f"{relative}:{symbol}" for symbol in forbidden if symbol in text)

    assert hits == [], (
        "T4 ownership seam: model-text classifier still has production owners: "
        + ", ".join(hits)
    )
