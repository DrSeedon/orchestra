"""Observe the affected real auth/artifact startup in an isolated pytest child."""
import hashlib
import json
from pathlib import Path

import pytest

VIEWS = ('MODEL_SPECS', 'MODELS', 'BACKENDS', 'ALIASES', 'TOKEN_PRICES', 'CONTEXT_LIMITS', 'MODEL_PROVIDERS')
NODE = 'tests/test_artifacts_browser.py::test_t3_chromium_keeps_active_html_in_the_sandboxed_child'


def fingerprint(views):
    value = [(key, sorted((name, repr(spec)) for name, spec in view.items())) for key, view in views.items()]
    return hashlib.sha256(repr(value).encode()).hexdigest()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    if item.nodeid != NODE:
        yield
        return
    from app import models, model_catalog
    from app.auth import is_auth_enabled

    assert is_auth_enabled()
    model_catalog.apply_model_catalog()
    before = {key: dict(getattr(models, key)) for key in VIEWS}
    original = models.fetch_models_from_proxy
    calls = []

    async def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('external catalog discovery forbidden in the startup probe')

    models.fetch_models_from_proxy = forbidden
    try:
        yield
    finally:
        models.fetch_models_from_proxy = original
        after = {key: dict(getattr(models, key)) for key in VIEWS}
        result = dict(node=NODE, auth_enabled=True, catalog_fetch_calls=len(calls),
                      registry_equal=before == after, before_sha256=fingerprint(before),
                      after_sha256=fingerprint(after), model_count=len(before['MODEL_SPECS']))
        (Path(__file__).parent / 'raw/startup-path-proof.json').write_text(json.dumps(result, indent=2) + '\n')
        assert not calls
        assert after == before
