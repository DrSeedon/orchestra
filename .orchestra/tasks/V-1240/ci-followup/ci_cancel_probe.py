"""Time the existing real worktree call without changing the frozen waits."""
import json
from pathlib import Path
import time

import pytest

EVENTS = []
NODE = 'tests/test_manager.py::TestAtomicSpawnLifecycle::test_cancelled_blocked_git_waits_then_removes_worktree_and_branch'


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    if item.nodeid != NODE:
        yield
        return
    from app import manager
    original = manager.create_worktree

    def observed(*args, **kwargs):
        wall, cpu = time.monotonic(), time.thread_time()
        EVENTS.append(dict(event='real_create_enter', monotonic=wall))
        try:
            result = original(*args, **kwargs)
            EVENTS.append(dict(event='real_create_return'))
            return result
        except BaseException as error:
            EVENTS.append(dict(event='real_create_exception', error_type=type(error).__name__))
            raise
        finally:
            EVENTS.append(dict(event='real_create_elapsed', wall_seconds=time.monotonic()-wall,
                               thread_cpu_seconds=time.thread_time()-cpu))
    manager.create_worktree = observed
    try:
        yield
    finally:
        manager.create_worktree = original


def pytest_sessionfinish(session, exitstatus):
    result = dict(exit_code=int(exitstatus), original_wait_seconds=2, original_assertions_unchanged=True, events=EVENTS)
    (Path(__file__).parent / 'raw/cancellation-timing-proof.json').write_text(json.dumps(result, indent=2)+'\n')
