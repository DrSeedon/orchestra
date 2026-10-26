import pytest

from meterread.cli import main


@pytest.fixture
def readings_file(tmp_path):
    path = tmp_path / "readings.csv"
    path.write_text("meter,date,kwh\nM1,2026-03-01,1000\nM1,2026-03-31,1300\nM2,2026-03-01,40\n",
                    encoding="utf-8")
    return str(path)


def test_usage(readings_file, capsys):
    assert main(["usage", readings_file]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "M1: 300 kWh in 30 days (10.0 kWh/day)",
        "M2: 0 kWh in 0 days (n/a)",
    ]


def test_cost_with_settings(readings_file, tmp_path, capsys):
    conf = tmp_path / "meterread.conf"
    conf.write_text("unit_price = 0.25\nstanding_charge = 0.40\ncurrency = GBP\n", encoding="utf-8")
    assert main(["cost", readings_file, "--settings", str(conf)]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "M1: 300 kWh, 30 days, 87.00 GBP"


def test_missing_readings_exits_2(tmp_path, capsys):
    assert main(["usage", str(tmp_path / "none.csv")]) == 2
    assert capsys.readouterr().err.startswith("error: cannot read")


def test_lower_reading_exits_2(tmp_path, capsys):
    path = tmp_path / "readings.csv"
    path.write_text("meter,date,kwh\nM1,2026-03-01,1000\nM1,2026-03-02,900\n", encoding="utf-8")
    assert main(["cost", str(path)]) == 2
    assert "lower than the one before" in capsys.readouterr().err
