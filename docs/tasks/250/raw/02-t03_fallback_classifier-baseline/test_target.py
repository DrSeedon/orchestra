"""Add focused regression tests here."""

import pytest

from src.classifier import visible_subagents


@pytest.mark.parametrize(
    "event",
    [
        {"task_type": "local_bash", "task_id": "opaque-7"},
        {"task_id": "bash-legacy"},
    ],
)
def test_local_bash_events_are_hidden_with_explicit_or_legacy_signal(event):
    assert visible_subagents([event]) == []
