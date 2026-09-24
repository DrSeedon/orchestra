"""pytest-плагин диагностики V-624: при зависании фазы теста печатает стеки всех asyncio-задач.

faulthandler показывает только потоки; зависший lifespan ждёт внутри корутины, и её видно
лишь через стек задачи. Порог — HANGDUMP_S секунд на одну фазу (setup/call/teardown).
"""
import asyncio
import gc
import os
import sys
import threading
import time

import pytest

_state = {"node": None, "phase": None, "since": time.monotonic()}
LIMIT = float(os.environ.get("HANGDUMP_S", "90"))


def _chain(coro, out, depth=0):
    """Полная цепочка await: print_stack задачи показывает только верхний кадр."""
    while coro is not None and depth < 60:
        frame = getattr(coro, "cr_frame", None) or getattr(coro, "ag_frame", None) or getattr(coro, "gi_frame", None)
        if frame is not None:
            print(f"    {frame.f_code.co_filename}:{frame.f_lineno} in {frame.f_code.co_name}", file=out)
        nxt = getattr(coro, "cr_await", None) or getattr(coro, "gi_yieldfrom", None) or getattr(coro, "ag_await", None)
        if nxt is None:
            print(f"    awaiting leaf: {coro!r}"[:300], file=out)
        coro = nxt
        depth += 1


def _dump():
    # sys.stderr и даже fd 2 перехвачены capture-плагином pytest: пишем в отдельный файл.
    out = open(os.environ["HANGDUMP_OUT"], "a")
    print(f"\n=== HANGDUMP {_state['node']} phase={_state['phase']} ===", file=out, flush=True)
    for obj in gc.get_objects():
        if isinstance(obj, asyncio.AbstractEventLoop) and not obj.is_closed():
            try:
                tasks = asyncio.all_tasks(obj)
            except RuntimeError:
                continue
            print(f"--- loop {obj!r} running={obj.is_running()} tasks={len(tasks)}", file=out)
            for task in tasks:
                print(f"TASK {task.get_name()} {task!r}"[:400], file=out)
                _chain(task.get_coro(), out)
    import types
    for obj in gc.get_objects():
        if isinstance(obj, types.AsyncGeneratorType) and obj.ag_running and obj.ag_frame is not None:
            print(f"ASYNCGEN {obj.ag_code.co_qualname}", file=out)
            _chain(obj, out)
    out.close()


def _watch():
    while True:
        time.sleep(5)
        if _state["phase"] and time.monotonic() - _state["since"] > LIMIT:
            _dump()
            os._exit(99)


def pytest_configure(config):
    threading.Thread(target=_watch, daemon=True, name="hangdump").start()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    _state.update(node=item.nodeid, phase="setup", since=time.monotonic())
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    _state.update(phase="call", since=time.monotonic())
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item):
    _state.update(phase="teardown", since=time.monotonic())
    yield
    _state.update(phase=None)


def pytest_sessionstart(session):
    """Кто поднимает настоящий браузер карточки /limits (модульный синглтон на весь процесс)."""
    import app.limits_card as card
    real = card.render_limits_card

    async def spy(*args, **kwargs):
        with open(os.environ["HANGDUMP_OUT"], "a") as out:
            print(f"RENDER_LIMITS_CARD by {_state['node']}", file=out)
        try:
            return await real(*args, **kwargs)
        finally:
            with open(os.environ["HANGDUMP_OUT"], "a") as out:
                print(f"  after render: browser={card._renderer_browser!r}"[:200], file=out)

    card.render_limits_card = spy
