from decimal import Decimal

from meterread.settings import Settings, load_settings, setting_names


def test_defaults_without_file():
    settings, error = load_settings(None)
    assert error is None
    assert settings == Settings()
    assert settings.unit_price == Decimal("0.28")


def test_setting_names():
    names = setting_names()
    assert names[0] == "currency"
    assert "unit_price" in names
    assert "standing_charge" in names


def test_file_overrides_some_values(tmp_path):
    path = tmp_path / "meterread.conf"
    path.write_text("# prices 2026\ncurrency = CHF\n\nunit_price = 0.31\n", encoding="utf-8")
    settings, error = load_settings(str(path))
    assert error is None
    assert settings.currency == "CHF"
    assert settings.unit_price == Decimal("0.31")
    assert settings.standing_charge == Decimal("0.45")


def test_unknown_setting(tmp_path):
    path = tmp_path / "meterread.conf"
    path.write_text("unit_price = 0.31\ncolour = red\n", encoding="utf-8")
    settings, error = load_settings(str(path))
    assert settings is None
    assert error.endswith("line 2: unknown setting 'colour'")


def test_bad_amount(tmp_path):
    path = tmp_path / "meterread.conf"
    path.write_text("standing_charge = cheap\n", encoding="utf-8")
    settings, error = load_settings(str(path))
    assert settings is None
    assert "line 1: not an amount" in error


def test_missing_file(tmp_path):
    settings, error = load_settings(str(tmp_path / "nothing.conf"))
    assert settings is None
    assert error.startswith("cannot read")
