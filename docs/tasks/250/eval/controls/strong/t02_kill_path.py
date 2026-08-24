from src.lifecycle import default_manager


def test_remove_archives_and_publishes_killed_token():
    manager, barrier = default_manager()
    session = manager.sessions["worker-1"]

    assert manager.remove("worker-1") is True
    assert session.archived is True
    assert barrier.tokens == [("worker-1", "killed")]

