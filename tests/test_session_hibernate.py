"""Heartbeat health checks for long-running Codex turns."""

from types import SimpleNamespace

from app.session_hibernate import HibernateManager


def _session(*, backend=None, listener_done=False):
    listener = SimpleNamespace(done=lambda: listener_done)
    return SimpleNamespace(_backend=backend, _listen_task=listener)


def test_live_codex_process_and_listener_are_not_zombie():
    backend = SimpleNamespace(is_alive=True)
    assert HibernateManager._codex_runtime_dead(_session(backend=backend)) is False


def test_dead_codex_process_is_zombie_even_with_live_listener():
    backend = SimpleNamespace(is_alive=False)
    assert HibernateManager._codex_runtime_dead(_session(backend=backend)) is True


def test_missing_backend_or_dead_listener_is_zombie():
    assert HibernateManager._codex_runtime_dead(_session(backend=None)) is True
    backend = SimpleNamespace(is_alive=True)
    assert HibernateManager._codex_runtime_dead(
        _session(backend=backend, listener_done=True)
    ) is True
