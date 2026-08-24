from src.lifecycle import Barrier


def test_killed_primitive():
    barrier = Barrier()
    barrier.on_child_killed("worker-1")
    assert barrier.tokens == [("worker-1", "killed")]

