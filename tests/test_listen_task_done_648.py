"""V-648: штатный конец listener не пишется как авария, обрыв во время хода — пишется и завершает ход."""
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.session_state import AgentStatus
from app.session import AgentSession


def _stub(status):
    task = _finished_task()
    session = SimpleNamespace(
        name="w648", status=status, _auto_continue_count=0,
        _finish_failed_running_turn=MagicMock(), _log=MagicMock(),
        _turns=SimpleNamespace(publish_turn_finished=MagicMock()),
    )
    session._listen_task = task
    return session, task


def _finished_task():
    task = MagicMock()
    task.exception.return_value = None
    return task


@pytest.mark.parametrize("status", [AgentStatus.IDLE, AgentStatus.WAITING])
def test_normal_listener_end_is_not_a_warning(status, caplog):
    session, task = _stub(status)
    with caplog.at_level(logging.WARNING, logger="app.session"):
        AgentSession._on_task_done(session, task)
    assert not [r for r in caplog.records if "silent death" in r.getMessage()]
    session._finish_failed_running_turn.assert_not_called()


def test_listener_end_while_running_warns_and_fails_turn(caplog):
    session, task = _stub(AgentStatus.RUNNING)
    with caplog.at_level(logging.WARNING, logger="app.session"):
        AgentSession._on_task_done(session, task)
    assert [r for r in caplog.records if "silent death" in r.getMessage()]
    session._finish_failed_running_turn.assert_called_once_with(
        "listen task exited unexpectedly while RUNNING"
    )


def test_stale_listener_end_does_not_fail_a_new_running_turn(caplog):
    session, old_task = _stub(AgentStatus.RUNNING)
    session._listen_task = _finished_task()

    with caplog.at_level(logging.WARNING, logger="app.session"):
        AgentSession._on_task_done(session, old_task)

    assert not [r for r in caplog.records if "silent death" in r.getMessage()]
    session._finish_failed_running_turn.assert_not_called()
    session._turns.publish_turn_finished.assert_not_called()
