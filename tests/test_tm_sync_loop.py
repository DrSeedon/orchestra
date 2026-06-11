"""P0: YouGile sync scheduling must survive asyncio.to_thread (routes/tm wraps tm.api_* in threads)."""

import asyncio

import pytest

import app.tm as tm


@pytest.fixture(autouse=True)
def _reset_main_loop():
    old = tm._MAIN_LOOP
    yield
    tm._MAIN_LOOP = old


def test_schedule_on_running_loop():
    async def main():
        fired = asyncio.Event()

        async def coro():
            fired.set()

        tm._schedule(coro())
        await asyncio.wait_for(fired.wait(), 2)

    asyncio.run(main())


def test_schedule_from_worker_thread_uses_captured_loop():
    async def main():
        tm.set_main_loop(asyncio.get_running_loop())
        fired = asyncio.Event()

        async def coro():
            fired.set()

        # to_thread → no running loop in that thread → must fall back to _MAIN_LOOP
        await asyncio.to_thread(tm._schedule, coro())
        await asyncio.wait_for(fired.wait(), 2)

    asyncio.run(main())


def test_schedule_without_any_loop_raises():
    tm._MAIN_LOOP = None

    async def coro():  # pragma: no cover — never awaited
        pass

    with pytest.raises(RuntimeError):
        tm._schedule(coro())
