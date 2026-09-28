"""V-648: штатный конец listener не пишется как авария, обрыв во время хода — пишется и завершает ход."""
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.session_state import AgentStatus
from app.session import AgentSession


def _stub(status):
    return SimpleNamespace(
        name="w648", status=status, _auto_continue_count=0,
        _finish_failed_running_turn=MagicMock(), _log=MagicMock(),
        _turns=SimpleNamespace(publish_turn_finished=MagicMock()),
    )


def _finished_task():
    task = MagicMock()
    task.exception.return_value = None
    return task


@pytest.mark.parametrize("status", [AgentStatus.IDLE, AgentStatus.WAITING])
def test_normal_listener_end_is_not_a_warning(status, caplog):
    session = _stub(status)
    with caplog.at_level(logging.WARNING, logger="app.session"):
        AgentSession._on_task_done(session, _finished_task())
    assert not [r for r in caplog.records if "silent death" in r.getMessage()]
    session._finish_failed_running_turn.assert_not_called()


def test_listener_end_while_running_warns_and_fails_turn(caplog):
    session = _stub(AgentStatus.RUNNING)
    with caplog.at_level(logging.WARNING, logger="app.session"):
        AgentSession._on_task_done(session, _finished_task())
    assert [r for r in caplog.records if "silent death" in r.getMessage()]
    session._finish_failed_running_turn.assert_called_once_with(
        "listen task exited unexpectedly while RUNNING"
    )
