"""Opt-in pytest plugin: reproduce a previous test's closed-loop log future.

Add this directory to PYTHONPATH and pass -p seed_previous_loop to pytest.
It creates no threads, provider sessions, database writes or signals.
"""

import asyncio

import pytest


@pytest.fixture(scope="session", autouse=True)
def previous_test_log_future():
    from app.deps import manager
    from app.session import AgentSession

    previous = manager.sessions
    loop = asyncio.new_event_loop()
    future = loop.create_future()
    loop.close()
    session = AgentSession(id="previous-test", name="previous-test", scope="/s", cwd="/tmp")
    session._log_futures.add(future)
    manager.sessions = {session.id: session}
    try:
        yield
    finally:
        manager.sessions = previous
