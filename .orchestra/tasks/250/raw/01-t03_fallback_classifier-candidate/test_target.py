"""Add focused regression tests here."""

from src.classifier import visible_subagents


def test_hides_explicit_and_legacy_local_bash_events():
    events = [
        {"task_type": "local_bash", "task_id": "opaque-new"},
        {"task_id": "bash-legacy"},
        {"task_type": "agent", "task_id": "opaque-visible"},
    ]

    assert visible_subagents(events) == ["opaque-visible"]
