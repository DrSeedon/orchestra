import logging
from datetime import datetime

from stationlog.qc import apply_qc, check_reading, out_of_range
from stationlog.readings import Reading

T0 = datetime(2026, 5, 1, 10, 0)


def test_out_of_range():
    assert out_of_range("temp_c", 61.0)
    assert not out_of_range("temp_c", 20.0)
    assert not out_of_range("humidity", None)


def test_check_reading_blanks_bad_values(caplog):
    reading = Reading("A1", T0, 99.0, 50.0, 700.0)
    with caplog.at_level(logging.WARNING):
        fixed = check_reading(reading)
    assert fixed.temp_c is None
    assert fixed.humidity == 50.0
    assert fixed.pressure_hpa is None
    assert "temp_c=99.0" in caplog.text


def test_good_reading_is_unchanged():
    reading = Reading("A1", T0, 20.0, 50.0, 1010.0)
    assert check_reading(reading) is reading
    assert apply_qc([reading]) == [reading]
