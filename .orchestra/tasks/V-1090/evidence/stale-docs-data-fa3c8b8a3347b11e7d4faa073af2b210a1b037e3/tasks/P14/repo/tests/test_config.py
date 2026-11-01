import pytest

from loandesk.config import Settings, load_settings
from loandesk.errors import ConfigError


def test_defaults():
    assert load_settings() == Settings()
    assert load_settings().loan_days == 21


def test_overrides_and_comments():
    settings = load_settings(["# branch north", "", "loan_days = 14", "fine_per_day=0.5"])
    assert settings.loan_days == 14
    assert settings.fine_per_day == 0.5
    assert settings.max_loans == 6


@pytest.mark.parametrize("line", ["loan_days 14", "colour = red", "max_loans = many"])
def test_bad_lines(line):
    with pytest.raises(ConfigError):
        load_settings([line])
