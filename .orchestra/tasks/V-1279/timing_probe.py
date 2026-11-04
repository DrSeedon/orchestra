"""Reproduce the original watchdog race with synthetic local persistence delay."""
import time

import pytest


@pytest.fixture(autouse=True)
def delayed_uncertain_save(request, monkeypatch):
    if request.node.originalname != "test_topic_create_timeout_is_not_blindly_retried":
        return
    from app import tg_bridge

    save_config = tg_bridge.save_config

    def delayed_save():
        save_config()
        # A single bounded delay after the guard has been durably written.
        time.sleep(0.06)

    monkeypatch.setattr(tg_bridge, "save_config", delayed_save)
