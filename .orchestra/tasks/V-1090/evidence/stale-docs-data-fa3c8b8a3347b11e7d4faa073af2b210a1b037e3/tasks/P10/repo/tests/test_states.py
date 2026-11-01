import pytest

from jobqueue.states import JobState, can_transition, check_transition, is_final


def test_allowed_transitions():
    assert can_transition(JobState.PENDING, JobState.RUNNING)
    assert can_transition(JobState.RUNNING, JobState.PENDING)
    assert not can_transition(JobState.DONE, JobState.RUNNING)


def test_check_transition_rejects():
    with pytest.raises(ValueError, match="done"):
        check_transition(JobState.DONE, JobState.PENDING)


def test_final_states():
    assert is_final(JobState.DONE)
    assert is_final(JobState.FAILED)
    assert not is_final(JobState.PENDING)


def test_state_values_are_strings():
    assert JobState.RUNNING == "running"
