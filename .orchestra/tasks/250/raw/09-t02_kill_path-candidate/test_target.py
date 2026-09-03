"""Add focused regression tests here."""

from src.lifecycle import default_manager


def test_remove_archives_session_and_publishes_killed_token():
    manager, barrier = default_manager()
    assert "worker-1" in manager.sessions

    assert manager.remove("worker-1") is True

    assert manager.sessions["worker-1"].archived is True
    assert barrier.tokens == [("worker-1", "killed")]
