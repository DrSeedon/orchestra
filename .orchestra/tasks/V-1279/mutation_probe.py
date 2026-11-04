"""Negative controls: the repaired test must reject actual retry regressions."""
import pytest


def pytest_addoption(parser):
    parser.addoption("--topic-mutation", choices=("retry", "forget-on-load"))


@pytest.fixture(autouse=True)
def topic_retry_mutation(request, monkeypatch):
    if request.node.originalname != "test_topic_create_timeout_is_not_blindly_retried":
        return
    from app import tg_bridge

    mutation = request.config.getoption("--topic-mutation")
    if mutation == "retry":
        ensure_primary = tg_bridge._ensure_primary_topic

        async def blindly_retry(name):
            tg_bridge.config.setdefault("topic_create_uncertain", {}).pop(
                f"primary:{name}", None,
            )
            await ensure_primary(name)

        monkeypatch.setattr(tg_bridge, "_ensure_primary_topic", blindly_retry)
    elif mutation == "forget-on-load":
        load_config = tg_bridge.load_config

        def forget_guard():
            load_config()
            tg_bridge.config.pop("topic_create_uncertain", None)

        monkeypatch.setattr(tg_bridge, "load_config", forget_guard)
