"""pytest-плагин диагностики V-624: кто вооружает restart_guard на pid самого pytest."""
import os
import pytest

_current = {"node": None}


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    _current["node"] = item.nodeid


def pytest_configure(config):
    from app import restart_guard
    real = restart_guard.arm_guard

    def spy(**kwargs):
        with open(os.environ["ARMSPY_OUT"], "a") as out:
            out.write(f"{_current['node']}\ttarget={kwargs.get('target_pid')}\tself={os.getpid()}\n")
        return real(**kwargs)

    restart_guard.arm_guard = spy
