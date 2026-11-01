from sensorhub.settings import Settings, load_settings, parse_setting


def test_defaults_without_file():
    settings, error = load_settings(None)
    assert error is None
    assert settings == Settings(max_gap=30, decimals=1, min_readings=3)


def test_file_overrides_some_settings(write_file):
    path = write_file("hub.ini", "[sensorhub]\nmax_gap = 45\n")
    settings, error = load_settings(path)
    assert error is None
    assert settings.max_gap == 45
    assert settings.decimals == 1


def test_file_without_section_gives_defaults(write_file):
    path = write_file("hub.ini", "[other]\nmax_gap = 45\n")
    settings, error = load_settings(path)
    assert settings == Settings()


def test_unknown_setting(write_file):
    path = write_file("hub.ini", "[sensorhub]\ncolour = red\n")
    settings, error = load_settings(path)
    assert settings is None
    assert "unknown setting 'colour'" in error


def test_missing_file(tmp_path):
    settings, error = load_settings(str(tmp_path / "none.ini"))
    assert settings is None
    assert "cannot read settings file" in error


def test_parse_setting():
    assert parse_setting("decimals", " 2 ") == (2, None)
    value, error = parse_setting("decimals", "two")
    assert value is None and "whole number" in error
    value, error = parse_setting("decimals", "-1")
    assert value is None and "negative" in error
