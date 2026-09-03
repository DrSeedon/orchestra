from src.classifier import visible_subagents


def test_explicit_signal_and_fallback_are_independent():
    events = [
        {"task_type": "local_bash", "task_id": "opaque-7"},
        {"task_id": "bash-legacy"},
        {"task_type": "local_agent", "task_id": "agent-1"},
    ]
    assert visible_subagents(events) == ["agent-1"]

