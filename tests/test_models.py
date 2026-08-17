import pytest

from app.models import resolve_model
from app.routes import sessions as sessmod


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("sol", "gpt-5.6-sol"),
        ("luna", "gpt-5.6-luna"),
    ],
)
def test_resolve_model_aliases(alias: str, expected: str) -> None:
    assert resolve_model(alias) == expected


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("sol", "gpt-5.6-sol"),
        ("luna", "gpt-5.6-luna"),
    ],
)
def test_create_session_request_resolves_model_alias(alias: str, expected: str) -> None:
    req = sessmod.CreateSessionRequest(name="w-child", cwd="/tmp", model=alias)
    assert req.model == expected
